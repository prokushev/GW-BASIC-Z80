#!/usr/bin/python
# Copyright (c) 2020 Leandro Pereira <leandro@hardinfo.org>
# Licensed under GPLv2.

from collections import deque
from itertools import tee, chain, repeat
import re
import sys
import traceback

class Lexer:
    def __init__(self, fp):
        self.state = self._lexer_asm
        self.start = 0
        self.pos = 0
        self.contents = fp.read()
        self.end = self.pos + len(self.contents)
        self.queue = deque()
        self.line = 1
        self.col = 1
        self.paren_count = 0

    def lex(self):
        def queue():
            last = {'type': None}
            while self.queue:
                token = self.queue.popleft()
                if token['type'] == 'newline' and last['type'] == 'newline':
                    continue
                if token['type'] == 'token' and token['value'] == '':
                    continue
                yield token
                last = token

        while self.state is not None:
            yield from queue()
            self.state = self.state()

        yield from queue()

    def _next(self):
        if self.pos >= self.end:
            return None
        c = self.contents[self.pos]
        self.pos += 1

        if c == '\n':
            self.line += 1
            self.col = 1
        else:
            self.col += 1

        return c

    def _current_token(self):
        return self.contents[self.start : self.pos]

    def _emit(self, typ, extra=None, value=None):
        tok = {
            'type': typ,
            'value': self._current_token() if value is None else value
        }
        if extra is not None:
            tok['extra'] = extra
        if typ == 'token':
            tok['value'] = tok['value'].upper()
        self.queue.append(tok)

    def _emit_token(self, typ, extra=None, value=None):
        self._emit(typ, extra=extra, value=value)
        self.start = self.pos

    def _error(self, typ):
        self._emit_token('error', extra={
            'type': typ,
            'position': (self.line, self.col)
        })
        return None

    def _ignore(self):
        self.start = self.pos

    def _backup(self):
        self.pos -= 1

    def _lexer_single_line_comment(self):
        self._ignore() # Ignore ;

        while True:
            c = self._next()
            if c is None:
                return self._error('EOF')

            if c in '\r\n':
                self._backup()
                self._emit_token('comment')
                return self._lexer_asm

    def _lexer_directive(self):
        while True:
            c = self._next()
            if c is None:
                return self._error('EOF')

            if c.isspace():
                self._backup()
                self._emit_token('directive')
                return self._lexer_asm

            if not c.isalpha():
                return self._error('Expecting alphabetic character')

    def _lexer_number(self):
        while True:
            c = self._next()
            if c is None:
                return self._error('EOF')

            if not c.isdigit():
                self._backup()
                self._emit_token('number')
                return self._lexer_asm

    def _lexer_multiline_comment(self):
        self._ignore() # Ignore COMMENT

        comment_char = None

        while True:
            c = self._next()
            if c is None:
                return self._error('EOF')

            if c.isspace():
                continue

            comment_char = c
            self._ignore()
            break

        while True:
            c = self._next()
            if c is None:
                return self._error('EOF')

            if c == comment_char:
                self._backup()
                self._emit_token('comment')

                self.pos += 1
                self._ignore()

                return self._lexer_asm

    def _lexer_token_until_end_of_line(self, typ, lex_comma=False):
        self._ignore()

        while True:
            c = self._next()
            if c is None or c in ';\r\n':
                self._backup()
                self._emit_token(typ, value=self._current_token().strip())
                return self._lexer_token
            if c == ',':
                self._backup()
                self._emit_token(typ, value=self._current_token().strip())
                self.pos += 1
                self._ignore()

    def _lexer_title(self):
        return self._lexer_token_until_end_of_line('title')

    def _lexer_subtitle(self):
        return self._lexer_token_until_end_of_line('subtitle')

    def _lexer_extern(self):
        return self._lexer_token_until_end_of_line('extern', lex_comma=True)

    def _lexer_db(self):
        return self._lexer_token_until_end_of_line('db', lex_comma=True)

    def _lexer_dw(self):
        return self._lexer_token_until_end_of_line('dw', lex_comma=True)

    def _lexer_assign(self):
        self._backup()
        tok = self._current_token()
        self.pos += 1
        self._ignore()

        while True:
            c = self._next()
            if c is None or c in ';\r\n':
                self._backup()
                self._emit_token('assign', value={
                    'token': tok,
                    'value': self._current_token().strip()
                })
                return None if c is None else self._lexer_asm

    def _lexer_token(self):
        while True:
            c = self._next()
            if c is None:
                return self._error('EOF')

            if c == '=':
                return self._lexer_assign

            if not c.isalnum() and not c in ':.[]?$_&':
                self._backup()

                curtoken = self._current_token().upper()
                if curtoken == 'COMMENT':
                    return self._lexer_multiline_comment
                elif curtoken == 'TITLE':
                    return self._lexer_title
                elif curtoken == 'SUBTTL':
                    return self._lexer_subtitle
                elif curtoken == 'EXTRN':
                    return self._lexer_extern
                elif curtoken == 'DB':
                    return self._lexer_db
                elif curtoken == 'DW':
                    return self._lexer_dw

                self._emit_token('token')
                return self._lexer_asm

    def _lexer_string(self, end_char, token_type='string'):
        while True:
            c = self._next()
            if c is None:
                return self._error('EOF')

            if c == end_char:
                self._emit_token(token_type)
                return self._lexer_asm

    def _lexer_string_double(self):
        return self._lexer_string('"')

    def _lexer_string_single(self):
        return self._lexer_string('\'')

    def _lexer_angle(self):
        return self._lexer_string('>', token_type='token')

    def _lexer_asm(self):
        while True:
            c = self._next()
            if c is None:
                return None

            if c == '\n':
                self._emit_token('newline')
                continue

            if c.isspace():
                self._ignore()
                continue

            if c == ';':
                return self._lexer_single_line_comment

            if c == '.':
                return self._lexer_directive

            if c == ',':
                self._emit_token('comma')
                continue

            if c == '(':
                self._emit_token('open_paren')
                self.paren_count += 1
                continue

            if c == ')':
                if self.paren_count == 0:
                    return self._error('Closing parenthesis without an opening parenthesis')
                self._emit_token('close_paren')
                self.paren_count -= 1
                if self.paren_count == 0:
                    self._ignore()
                    return self._lexer_asm

            if c.isdigit():
                return self._lexer_number

            if c.isalpha() or c == '?':
                return self._lexer_token

            if c == '\'':
                return self._lexer_string_single

            if c == '"':
                return self._lexer_string_double

            if c == '<':
                return self._lexer_angle

class Parser:
    def __init__(self, lexer):
        self.tokens = lexer.lex()
        self.token_queue = deque()
        self.queue = deque()
        self.state = self._parse_asm

        self.in_cseg = False
        self.in_dseg = False
        self.forc_counter = 0
        self.rept_counter = 0
        self.macro_args = deque()
        self.radix = 10
        self.externs = {}

    def parse(self):
        def queue():
            while self.queue:
                yield self.queue.popleft()

        while self.state is not None:
            yield from queue()
            self.state = self.state()

        yield from queue()

    def _emit(self, token):
        self.queue.append(token)

    def _error(self, msg):
        self._emit({'type': 'error', 'value': msg})
        return None

    def _next(self):
        if self.token_queue:
            return self.token_queue.popleft()
        return next(self.tokens, None)

    def _peek(self):
        token = self._next()
        self.token_queue.appendleft(token)
        return token

    def _must_next(self, msg):
        token = self._next()
        if token is None:
            raise SyntaxError(msg)
        return token

    def _must_next_type(self, typ, msg):
        token = self._must_next(msg)
        if token['type'] != typ:
            raise SyntaxError("Expecting type %s, got %s: %s" % (typ, token['type'], msg))
        return token

    def _parse_directive_radix(self):
        token = self._must_next_type('number', "Expecting radix number")
        self._emit({'type': 'directive_radix', 'value': token['value']})
        self.radix = int(token['value'])
        return self._parse_asm

    def _parse_directive_xlist(self):
        self._emit({'type': 'xlist'})
        return self._parse_asm

    def _parse_directive_sall(self):
        self._emit({'type': 'sall'})
        return self._parse_asm

    def _parse_directive_list(self):
        self._emit({'type': 'list'})
        return self._parse_asm

    def _parse_directive(self, token):
        typ = token['value'][1:]
        return getattr(self, '_parse_directive_%s' % typ.lower())

    def _parse_seg(self, is_cseg=True):
        token = self._must_next_type('token', "Expecting token")
        if token['value'] == 'SEGMENT':
            if is_cseg:
                if self.in_cseg:
                    return self._error("Already in code segment")
            elif self.in_dseg:
                return self._error("Already in data segment")

            token = self._must_next("Expecting segment information")
            if token == {'type': 'token', 'value': 'PUBLIC'}:
                public = True
                token = self._must_next_type('string', "Expecting segment name")
            elif token['type'] == 'string':
                public = False
            else:
                return self._error("Expecting string or PUBLIC")
            self._emit({'type': 'cseg', 'public': public, 'name': token['value'][1:-1]})

            if is_cseg:
                self.in_cseg = True
            else:
                self.in_dseg = True
            return self._parse_asm
        elif token['value'] == 'ENDS':
            if is_cseg:
                self.in_cseg = False
            else:
                self.in_dseg = False
            return self._parse_asm
        else:
            return self._error("Expecting SEGMENT or ENDS")

    def _parse_cseg(self):
        return self._parse_seg(is_cseg=True)

    def _parse_dseg(self):
        return self._parse_seg(is_cseg=False)

    def _parse_assume(self):
        token = self._must_next_type('token', "Expecting segment to assume")
        if not ':' in token['value']:
            return self._error("Segment seems invalid")
        self._emit({'type': 'assume', 'seg': token['value']})
        return self._parse_asm

    def _parse_include(self):
        token = self._must_next_type('token', "Expecting file name to include")
        self._emit({'type': 'include', 'filename': token['value']})
        return self._parse_asm

    def _parse_org(self):
        token = self._must_next_type('number', "Expecting ORG argument")
        self._emit({'type': 'org', 'value': token['value']})
        return self._parse_asm

    def _parse_public(self):
        while True:
            token = self._next()
            if token is None:
                return None

            if token['type'] == 'token':
                self._emit({'type': 'public', 'identifier': token['value']})
            elif token['type'] == 'comma':
                continue
            elif token['type'] == 'newline':
                break
            elif token['type'] == 'comment':
                self._emit({'type': 'comment', 'value': token['value']})
                break
        return self._parse_asm

    def _parse_extern(self, token):
        identifier = token['value'].split(":")
        if len(identifier) != 2:
            self._error("Don't know what to do")
        self.externs[identifier[0]] = identifier[1]
        self._emit({'type': 'extern', 'identifier': identifier[0], 'attr': identifier[1]})
        return self._parse_asm

    def _parse_assign(self, token):
        token = token['value']
        self._emit({'type': 'assign', 'symbol': token['token'], 'value': token['value']})
        return self._parse_asm

    def _parse_label(self, token):
        self._emit({'type': 'label', 'identifier': token['value'][:-1]})
        return self._parse_asm

    def _is_x86_instruction(self, token):
        return token['value'] in {
            'MOV', 'ADD', 'INC', 'CMP', 'JNZ', 'JMP', 'JZ', 'RET', 'PUSH', 'POP',
            'CALL', 'OR', 'XCHG', 'AND', 'XOR', 'DEC', 'JAE', 'JB', 'SUB', 'PUSHF',
            'POPF', 'JNAE', 'STC', 'JNB', 'LAHF', 'SAHF', 'CMC', 'SBB', 'STOSB',
            'REP', 'JNS', 'JS', 'ROR', 'ROL', 'ADC', 'CLD', 'SHL', 'SHR', 'XLAT',
            'LOOP', 'TEST', 'CBW', 'NEG', 'JLE', 'JO', 'JGE', 'JL', 'MOVS', 'JPO',
            'JNE', 'RCL', 'RCR', 'CLC', 'MOVSW', 'LODS', 'STOSW', 'NOT', 'STD',
            'CMPSW', 'JPE', 'IMUL', 'IDIV', 'MUL', 'SAL', 'JE', 'LODSW', 'LODSB',
            'MOVSB', 'JA', 'DIV', 'JCXZ', 'CLI', 'STI', 'LEA', 'JP', 'IN', 'OUT',
            'INT', 'JG', 'REPE', 'REPZ', 'REPNE', 'REPNZ',
        }

    def _is_macro(self, token):
        return token['value'] in {
            'INS86', 'ACRLF', 'DO_EXT', 'HLFHL', 'HLFDE', 'NEGDE', 'POPR', 'UN_DEF',
            'MOVRI', 'T', 'Q', 'QF', 'DERMAK', '?Z0', 'ADD_EXT', 'DEF_MAC', 'M', 'R',
            'R2', '?&S', 'EXPAND_MAC', 'CALLOS', 'DUMY', 'ADR', 'DC', 'NEGHL',
            'CPMXIO', 'DOSIO', 'NDEV', 'DEV', 'NAMES',

            # FIXME: add_ext macro in BINTRP.H references this, but it's parsed incorrectly
            '?I'
        }

    def _valid_number_for_radix(self, num, radix):
        if radix == 8:
            return all('0' <= c <= '7' for c in num)
        if radix == 10:
            return all('0' <= c <= '9' for c in num)
        if radix == 16:
            hex_digits = "0123456789abcdefABCDEF"
            return all(c in hex_digits for c in num)
        raise SyntaxError("Unknown radix: %d" % radix)

    def _radix_to_num(self, radix):
        return {'O': 8, 'H': 16, 'D': 10}[radix]

    def _parse_x86_operand(self, operand):
        out = []
        skip = False
        for i, op in enumerate(operand):
            if skip:
                skip = False
                continue
            if isinstance(op, str):
                if i < len(operand)-1 and operand[i+1] in ('O', 'H', 'D'):
                    skip = True
                    radix = self._radix_to_num(operand[i+1])
                else:
                    radix = self.radix
                if self._valid_number_for_radix(op, radix):
                    out.append(int(op, radix))
                else:
                    out.append(op)
            elif isinstance(op, list) or isinstance(op, tuple):
                out.append(self._parse_x86_operand(op))
            else:
                out.append(op)
        return out[0] if len(out) == 1 else tuple(out)

    def _get_x86_operand(self, n_paren=0):
        operand = []
        while True:
            peek = self._peek()
            if peek is None:
                break
            elif peek['type'] in ('token', 'number', 'string'):
                self._next()
                operand.append(peek['value'])
            elif peek['type'] == 'open_paren':
                self._next()
                operand.append(self._get_x86_operand(n_paren + 1))
            elif peek['type'] == 'close_paren':
                self._next()
                if n_paren == 0:
                    return self._error("Close parenthesis without open parenthesis")
                break
            elif peek['type'] in ('newline', 'comment', 'comma'):
                break
            else:
                return self._error("Unexpected token: %s" % token)
        return self._parse_x86_operand(operand)

    def _parse_x86_instruction(self, token):
        instruction = token['value']
        operands = []
        comment = None
        while True:
            peek = self._peek()
            if peek is None:
                break
            if peek['type'] in ('token', 'number', 'string', 'open_paren'):
                operands.append(self._get_x86_operand())
            elif peek['type'] == 'close_paren':
                return self._error("Close parenthesis without open parenthesis")
            elif peek['type'] == 'comma':
                self._next()
                continue
            elif peek['type'] == 'comment':
                self._next()
                comment = peek['value']
                break
            elif peek['type'] == 'newline':
                break
            else:
                return self._error("Unexpected token while parsing 8086 instruction operand: %s" % token)
        self._emit({'type': 'instruction', 'op': instruction, 'operands': tuple(operands), 'comment': comment})
        return self._parse_asm

    def _parse_byte_from_db(self, db):
        try:
            return int(db, self.radix)
        except ValueError:
            pass

        try:
            if db[-1] == 'D':
                return int(db[:-1], 10)
            if db[-1] == 'H':
                return int(db[:-1], 16)
            if db[-1] == 'O':
                return int(db[:-1], 8)
        except ValueError:
            pass

        return db

    def _parse_macro_movri(self, arguments, comment):
        if len(arguments) != 4:
            raise NotImplementedError("Don't know how to generate MOVRI with %d arguments" % len(arguments))

        as_number = []
        for arg in arguments:
            if len(arg) == 2:
                assert arg[0]['type'] == 'number'
                assert arg[1]['type'] == 'token' and arg[1]['value'] in 'OHD'

                arg = int(arg[0]['value'], self._radix_to_num(arg[1]['value']))
            elif len(arg) == 1:
                arg = int(arg[0]['value'], self.radix)
            else:
                raise NotImplementedError("Can't parse argument for MOVRI macro: %s" % str(arguments))

            as_number.append(arg)

        cx_val = as_number[1] | as_number[0] << 8
        dx_val = as_number[3] | as_number[2] << 8

        self._emit({'type': 'instruction', 'op': 'mov', 'operands': ('CX', cx_val), 'comment': comment})
        self._emit({'type': 'instruction', 'op': 'mov', 'operands': ('DX', dx_val), 'comment': None})
        return self._parse_asm

    def _parse_macro_ins86(self, arguments, comment):
        operands = []
        for ops in arguments:
            for op in ops:
                if op['type'] == 'number':
                    if op['value'].isdigit(): # Arguments to this macro are always in octal
                        operands.append(int(op['value'], 8))
                    elif op['value'] == '+2':
                        operands[-1] += op['value']
                    else:
                        raise SyntaxError("Unknown radix for INS86 numeric argument")
                elif op['type'] in ('token', 'string'):
                    operands.append(op['value'])
                else:
                    raise SyntaxError("Invalid argument to INS86 macro")

        operands = tuple(operands)

        if operands == (6,):
            self._emit({'type': 'instruction', 'op': 'push', 'operands': ('ES',), 'comment': comment})
            return self._parse_asm

        if operands == (7,):
            self._emit({'type': 'instruction', 'op': 'pop', 'operands': ('ES',), 'comment': comment})
            return self._parse_asm

        if operands == (14,):
            self._emit({'type': 'instruction', 'op': 'push', 'operands': ('CS',), 'comment': comment})
            return self._parse_asm

        if operands == (203,):
            self._emit({'type': 'instruction', 'op': 'retf', 'operands': (), 'comment': comment})
            return self._parse_asm

        if operands == (236,):
            self._emit({'type': 'instruction', 'op': 'in', 'operands': ('AL', 'DX'), 'comment': comment})
            return self._parse_asm

        if operands == (238,):
            self._emit({'type': 'instruction', 'op': 'out', 'operands': ('DX', 'AL'), 'comment': comment})
            return self._parse_asm

        if operands in ((46,), (38,)): # CS:/ES: prefixes, useless for Z80
            if comment:
                self._emit({'type': 'comment', 'value': comment})
            return self._parse_asm

        if operands == (139, 242, 46, 172):
            self._emit({'type': 'instruction', 'op': 'mov', 'operands': ('SI', 'DX'), 'comment': comment})
            self._emit({'type': 'instruction', 'op': 'lodsb', 'operands': ('AL', '[SI]'), 'comment': None})
            return self._parse_asm

        if operands == (50, 228):
            self._emit({'type': 'instruction', 'op': 'xor', 'operands': ('AH', 'AH'), 'comment': comment})
            return self._parse_asm

        if operands == (140, 218):
            self._emit({'type': 'instruction', 'op': 'mov', 'operands': ('DX', 'DS'), 'comment': comment})
            return self._parse_asm

        if operands == (57, 23):
            self._emit({'type': 'instruction', 'op': 'cmp', 'operands': ('[BX]', 'DX'), 'comment': comment})
            return self._parse_asm

        if operands == (209, 235):
            self._emit({'type': 'instruction', 'op': 'shr', 'operands': ('BX', 1), 'comment': comment})
            return self._parse_asm

        if operands == (139, 240):
            self._emit({'type': 'instruction', 'op': 'mov', 'operands': ('SI', 'AX'), 'comment': comment})
            return self._parse_asm

        if operands[:2] == (142, 6) and len(operands) == 3:
            self._emit({'type': 'instruction', 'op': 'mov', 'operands': ('ES', operands[-1]), 'comment': comment})
            return self._parse_asm

        if operands[:2] == (255, 180) and len(operands) == 3:
            self._emit({'type': 'instruction', 'op': 'push', 'operands': (operands[-1],), 'comment': comment})
            return self._parse_asm

        if operands[:2] == (137, 22) and len(operands) == 3:
            self._emit({'type': 'instruction', 'op': 'mov', 'operands': (operands[-1], 'DX'), 'comment': comment})
            return self._parse_asm

        if operands[:2] == (137, 38) and len(operands) == 3:
            self._emit({'type': 'instruction', 'op': 'mov', 'operands': (operands[-1], 'SP'), 'comment': comment})
            return self._parse_asm

        if operands[:2] == (246, 6) and len(operands) == 3:
            if comment:
                self._emit({'type': 'comment', 'value': comment})
                comment = None
            while True:
                peek = self._peek()
                if peek['type'] == 'newline':
                    self._next()
                    continue
                if peek['type'] == 'comment':
                    self._next()
                    comment = peek['value']
                    continue
                if peek['type'] == 'db':
                    self._next()
                    op = peek['value']
                    self._emit({'type': 'instruction', 'op': 'test', 'operands': (operands[-1], op), 'comment': comment})
                    return self._parse_asm
                break

        if operands in ((185,), (186,)):
            if comment:
                self._emit({'type': 'comment', 'value': comment})
                comment = None
            dbs = []
            while len(dbs) != 2:
                peek = self._peek()
                if peek['type'] == 'newline':
                    self._next()
                    continue
                if peek['type'] == 'comment':
                    self._next()
                    comment = peek['value']
                    continue
                if peek['type'] == 'db':
                    self._next()
                    dbs.append(peek['value'])
                    continue
                raise SyntaxError("Unexpected token found while parsing INS86 macro: %s" % peek)
            op1 = 'CX' if operands[0] == 185 else 'DX'
            op2 = dbs[0], dbs[1]
            self._emit({'type': 'instruction', 'op': 'movi', 'operands': (op1, op2), 'comment': comment})
            return self._parse_asm

        if operands == (209, 234):
            self._emit({'type': 'instruction', 'op': 'shr', 'operands': ('DX', 1), 'comment': comment})
            return self._parse_asm

        if operands == (209, 233):
            self._emit({'type': 'instruction', 'op': 'shr', 'operands': ('BX', 1), 'comment': comment})
            return self._parse_asm

        if operands == (247, 218):
            self._emit({'type': 'instruction', 'op': 'neg', 'operands': ('DX',), 'comment': comment})
            return self._parse_asm

        if operands == (247, 219):
            self._emit({'type': 'instruction', 'op': 'neg', 'operands': ('BX',), 'comment': comment})
            return self._parse_asm

        if operands == (247, 226):
            self._emit({'type': 'instruction', 'op': 'mul', 'operands': ('DX',), 'comment': comment})
            return self._parse_asm

        if operands == (138, 242):
            self._emit({'type': 'instruction', 'op': 'mov', 'operands': ('DH', 'DL'), 'comment': comment})
            return self._parse_asm

        if operands == (5,):
            if comment:
                self._emit({'type': 'comment', 'value': comment})
                comment = None
            dbs = []
            while len(dbs) != 2:
                peek = self._peek()
                if peek['type'] == 'newline':
                    self._next()
                    continue
                if peek['type'] == 'comment':
                    self._next()
                    comment = peek['value']
                    continue
                if peek['type'] == 'db':
                    self._next()
                    dbs.append(peek['value'])
                    continue
                raise SyntaxError("Unexpected token found while parsing INS86 macro: %s" % peek)
            op = self._parse_byte_from_db(dbs[1]) << 8 | self._parse_byte_from_db(dbs[0])
            self._emit({'type': 'instruction', 'op': 'add', 'operands': ('AX', op), 'comment': comment})
            return self._parse_asm

        if operands == (131, 250):
            if comment:
                self._emit({'type': 'comment', 'value': comment})
                comment = None
            op = None
            while op is None:
                peek = self._peek()
                if peek['type'] == 'newline':
                    self._next()
                elif peek['type'] == 'comment':
                    self._next()
                    comment = peek['value']
                elif peek['type'] == 'db':
                    self._next()
                    op = self._parse_byte_from_db(peek['value'])
                else:
                    raise SyntaxError("Unexpected token while parsing INS86 macro: %s" % peek)
            self._emit({'type': 'instruction', 'op': 'cmp', 'operands': ('DX', op), 'comment': comment})
            return self._parse_asm

        if operands[0] == 115 and len(operands) == 2:
            self._emit({'type': 'instruction', 'op': 'jae', 'operands': (operands[1],), 'comment': comment})
            return self._parse_asm

        if operands == (254, 198):
            self._emit({'type': 'instruction', 'op': 'inc', 'operands': ('DH',), 'comment': comment})
            return self._parse_asm

        if operands == (138, 212):
            self._emit({'type': 'instruction', 'op': 'mov', 'operands': ('DL', 'AH'), 'comment': comment})
            return self._parse_asm

        if operands[:2] == (57, 30) and len(operands) == 3:
            self._emit({'type': 'instruction', 'op': 'cmp', 'operands': (operands[2], 'BX'), 'comment': comment})
            return self._parse_asm

        if operands[:2] == (255, 54) and len(operands) == 3:
            self._emit({'type': 'instruction', 'op': 'push', 'operands': (operands[2],), 'comment': comment})
            return self._parse_asm

        if operands == (255, 39):
            self._emit({'type': 'instruction', 'op': 'jmp', 'operands': ('[BX]',), 'comment': comment})
            return self._parse_asm

        if operands == (247, 211):
            self._emit({'type': 'instruction', 'op': 'not', 'operands': ('BX',), 'comment': comment})
            return self._parse_asm

        if operands == (11, 218):
            self._emit({'type': 'instruction', 'op': 'or', 'operands': ('BX', 'DX'), 'comment': comment})
            return self._parse_asm

        if operands == (35, 218):
            self._emit({'type': 'instruction', 'op': 'and', 'operands': ('BX', 'DX'), 'comment': comment})
            return self._parse_asm

        if operands == (51, 218):
            self._emit({'type': 'instruction', 'op': 'xor', 'operands': ('BX', 'DX'), 'comment': comment})
            return self._parse_asm

        if len(operands) == 2 and operands[0] == 186:
            self._emit({'type': 'instruction', 'op': 'mov', 'operands': ('DX', operands[1]), 'comment': comment})
            return self._parse_asm

        if len(operands) == 2 and operands[0] == 177:
            self._emit({'type': 'instruction', 'op': 'mov', 'operands': ('CL', operands[1]), 'comment': comment})
            return self._parse_asm

        if operands == (211, 234):
            self._emit({'type': 'instruction', 'op': 'shr', 'operands': ('DX', 'CL'), 'comment': comment})
            return self._parse_asm

        if operands == (139, 243):
            self._emit({'type': 'instruction', 'op': 'mov', 'operands': ('SI', 'BX'), 'comment': comment})
            return self._parse_asm

        debug = []
        for op in operands:
            if isinstance(op, int): debug.append('%02x' % op)
            else: debug.append(' %s ' % op)
        raise SyntaxError("Unknown arguments to INS86 macro: %s    %s" % (''.join(debug), operands))

    def _parse_macro_popr(self, comment):
        self._emit({'type': 'instruction', 'op': 'pop', 'operands': ['CX'], 'comment': comment})
        self._emit({'type': 'instruction', 'op': 'pop', 'operands': ['DX'], 'comment': None})
        return self._parse_asm

    def _parse_macro_call(self, token):
        macro = token['value']
        peek = self._peek()
        if peek['type'] == 'token' and peek['value'] == 'MACRO':
                return self._parse_macro(token)

        operands = []
        comment = None
        cur_operand = []
        while True:
            token = self._must_next("Expecting operands for %s" % macro)
            if token['type'] in ('token', 'number', 'string'):
                cur_operand.append(token)
            elif token['type'] == 'comment':
                comment = token['value']
                break
            elif token['type'] == 'newline':
                break
            elif token['type'] == 'comma':
                operands.append(cur_operand)
                cur_operand = []
                continue
            else:
                return self._error("Unexpected token: %s" % token)
        if cur_operand:
            operands.append(cur_operand)

        if macro == 'INS86':
            return self._parse_macro_ins86(operands, comment)
        if macro == 'MOVRI':
            return self._parse_macro_movri(operands, comment)
        if macro == 'POPR':
            return self._parse_macro_popr(comment)

        self._emit({'type': 'macro_call', 'identifier': macro, 'args': operands, 'comment': comment})
        return self._parse_asm

    def _parse_data(self, typ, token):
        if token['value'].startswith('OFFSET'):
            value = ('offset', self._parse_byte_from_db(token['value'][len("OFFSET"):].strip()))
        else:
            value = self._parse_byte_from_db(token['value'])

        self._emit({'type': typ, 'bytes': (value,)})
        return self._parse_asm

    def _parse_db(self, token):
        return self._parse_data('db', token)

    def _parse_dw(self, token):
        return self._parse_data('dw', token)

    def _parse_label_def(self, token):
        self._next() # Eat LABEL
        identifier = token['value']
        attrs = []
        comment = None
        while True:
            token = self._next()
            if token['type'] == 'token':
                attrs.append(token['value'])
            elif token['type'] == 'comment':
                comment = token['value']
            elif token['type'] == 'newline':
                break
            else:
                return self._error("Unexpected token type %s" % token['type'])
        self._emit({'type': 'label_def', 'identifier': identifier, 'attrs': attrs, 'comment': comment})
        return self._parse_asm

    def _parse_equ(self, token):
        self._next() # Eat EQU
        identifier = token['value']
        attrs = []
        comment = None
        while True:
            token = self._next()
            if token['type'] == 'token':
                attrs.append(token['value'])
            elif token['type'] == 'comment':
                comment = token['value']
                break
            elif token['type'] == 'newline':
                break
            else:
                return self._error("Unexpected token type %s" % token['type'])
        self._emit({'type': 'equ', 'identifier': identifier, 'attrs': attrs, 'comment': comment})
        return self._parse_asm

    def _parse_macro(self, token):
        self._next() # Eat MACRO
        identifier = token['value']
        args = []
        comment = None
        while True:
            token = self._next()
            if token is None:
                break
            if token['type'] == 'newline':
                break
            if token['type'] == 'comment':
                comment = token['value']
                break
            if token['type'] == 'comma':
                continue
            if token['type'] == 'token':
                args.append(token['value'])
            else:
                return self._error("Unexpected token type: %s" % token['type'])
        self.macro_args.append(args)
        self._emit({'type': 'macro', 'identifier': identifier, 'args': args, 'comment': comment})
        return self._parse_asm

    def _parse_if(self, typ):
        cond = []
        comment = None
        while True:
            token = self._next()
            if token['type'] in ('number', 'token'):
                cond.append(token['value'])
            elif token['type'] == 'comment':
                comment = token['value']
                break
            elif token['type'] == 'newline':
                break
            else:
                return self._error("Unexpected token type %s" % token['type'])
        if not cond:
            return self._error("If without condition")
        self._emit({'type': typ.lower(), 'cond': cond, 'comment': comment})
        return self._parse_asm

    def _parse_ifdif(self):
        ops = []
        comment = None
        while True:
            token = self._next()
            if token['type'] in ('number', 'token', 'string'):
                ops.append(token['value'])
            elif token['type'] == 'comment':
                comment = token['value']
                break
            elif token['type'] == 'comma':
                continue
            elif token['type'] == 'newline':
                break
            else:
                return self._error("Unexpected token type %s" % token['type'])
        if len(ops) != 2:
            return self._error("IFDIF requires 2 arguments")
        self._emit({'type': 'ifdif', 'ops': ops, 'comment': comment})
        return self._parse_asm

    def _parse_echo(self):
        msg = []
        while True:
            token = self._next()
            if token['type'] == 'newline':
                break
            msg.append(token)
        self._emit({'type': 'echo', 'msg': msg})
        return self._parse_asm

    def _parse_endm(self, escaping=False):
        if escaping:
            self._emit({'type': 'end_macro_escaped'})
        else:
            if self.rept_counter:
                self.rept_counter -= 1
                self._emit({'type': 'end_rept'})
            elif self.forc_counter:
                self.forc_counter -= 1
                self._emit({'type': 'end_forc'})
            elif self.macro_args:
                self.macro_args.popleft()
                self._emit({'type': 'end_macro'})
            else:
                return self._error("Not in macro, rept, or forc")
        return self._parse_asm

    def _parse_forc(self):
        self.forc_counter += 1
        comment = None
        args = []
        while True:
            token = self._next()
            if token['type'] == 'newline':
                break
            if token['type'] == 'comma':
                continue
            if token['type'] == 'comment':
                comment = token['value']
                break
            if token['type'] != 'token':
                return self._error("Expecting token, got %s" % token['type'])
            args.append(token)
        self._emit({'type': 'forc', 'args': args, 'comment': comment})
        return self._parse_asm

    def _parse_purge(self):
        token = self._must_next_type('token', "Macro identifier")
        self._emit({'type': 'purge', 'identifier': token['value']})
        return self._parse_asm

    def _parse_strip_macro(self):
        macro_token_count = 0
        while True:
            token = self._next()
            if token is None:
                return self._error("Expecting ENDM")
            if token['type'] == 'token' and token['value'] == 'MACRO':
                macro_token_count += 1
                if macro_token_count > 1:
                    return self._error("Nested macros not supported for stripping")
            if token['type'] == 'token' and token['value'] == 'ENDM':
                return self._parse_asm

    def _is_useless_macro(self, name):
        useless_macros = {
            'LDIR', 'LDDR', 'DJNZ', 'FSIGN', 'PUSHM', 'SYNCHK', 'OUTCHR', 'CHRGET',
            'COMPAR', 'PUSHR', 'INST', 'GETYPE', 'INS86', 'POPR', 'MOVRI',
        }
        if name in useless_macros:
            peek = self._peek()
            if peek['type'] == 'token' and peek['value'] == 'MACRO':
                return True
        return False

    def _parse_rept(self):
        count = self._must_next("Expecting argument to rept")
        if count['type'] not in ('token', 'number'):
            return self._error("Don't know how to parse REPT argument")
        self._emit({'type': 'rept', 'count': count})
        self.rept_counter += 1
        return self._parse_asm

    def _parse_asm(self):
        while True:
            token = self._next()
            if token is None:
                return None

            typ = token['type']

            if typ == 'newline':
                continue

            if typ == 'comment':
                self._emit(token)
                return self._parse_asm

            if typ == 'directive':
                return self._parse_directive(token)

            if typ == 'token':
                typ = token['value']
                if typ == 'CSEG':
                    return self._parse_cseg
                if typ == 'DSEG':
                    return self._parse_dseg
                if typ == 'ASSUME':
                    return self._parse_assume
                if typ == 'INCLUDE':
                    return self._parse_include
                if typ == 'PUBLIC':
                    return self._parse_public
                if typ == 'ORG':
                    return self._parse_org
                if typ == 'PAGE':
                    continue
                if typ in ('%OUT', 'ECHO'):
                    return self._parse_echo
                if typ == 'END':
                    break
                if typ == 'ENDM':
                    return self._parse_endm(escaping=False)
                if typ == '&ENDM':
                    return self._parse_endm(escaping=True)
                if typ == 'ENDIF':
                    self._emit({'type': 'end_if'})
                    return self._parse_asm
                if typ in ('IF', 'IFE', 'IFDEF', 'IFNDEF'):
                    return self._parse_if(typ)
                if typ == 'IFDIF':
                    return self._parse_ifdif
                if typ == 'IF1': # Hack!
                    self.token_queue.appendleft({'type': 'number', 'value': '1'})
                    return self._parse_if('IF')
                if typ == 'ELSE':
                    self._emit({'type': 'else'})
                    return self._parse_asm
                if typ == 'PURGE':
                    return self._parse_purge
                if typ in ('FORC', 'IRPC'):
                    return self._parse_forc
                if typ == 'REPT':
                    return self._parse_rept
                if token['value'].endswith(':'):
                    return self._parse_label(token)
                if self._is_x86_instruction(token):
                    return self._parse_x86_instruction(token)
                if self._is_useless_macro(typ):
                    self._emit({'type': 'comment', 'value': 'Stripped useless macro: %s' % typ})
                    return self._parse_strip_macro
                if self._is_macro(token):
                    return self._parse_macro_call(token)
                else:
                    peek = self._peek()
                    if peek['type'] == 'token' and peek['value'] == 'LABEL':
                        return self._parse_label_def(token)
                    if peek['type'] == 'token' and peek['value'] == 'EQU':
                        return self._parse_equ(token)

            if typ in ('title', 'subtitle'):
                self._emit(token)
                return self._parse_asm

            if typ == 'assign':
                return self._parse_assign(token)

            if typ == 'extern':
                return self._parse_extern(token)

            if typ == 'db':
                return self._parse_db(token)

            if typ == 'dw':
                return self._parse_dw(token)

            for args in self.macro_args:
                for arg in args:
                    if arg == token['value']:
                        self._emit({'type': 'macro_arg', 'identifier': arg})
                        return self._parse_asm

            return self._error("Don't know how to parse token %s" % token)


def windowed(seq, n, fillvalue=None, step=1):
    """Return a sliding window of width *n* over the given iterable.
        >>> all_windows = windowed([1, 2, 3, 4, 5], 3)
        >>> list(all_windows)
        [(1, 2, 3), (2, 3, 4), (3, 4, 5)]
    When the window is larger than the iterable, *fillvalue* is used in place
    of missing values:
        >>> list(windowed([1, 2, 3], 4))
        [(1, 2, 3, None)]
    Each window will advance in increments of *step*:
        >>> list(windowed([1, 2, 3, 4, 5, 6], 3, fillvalue='!', step=2))
        [(1, 2, 3), (3, 4, 5), (5, 6, '!')]
    To slide into the iterable's items, use :func:`chain` to add filler items
    to the left:
        >>> iterable = [1, 2, 3, 4]
        >>> n = 3
        >>> padding = [None] * (n - 1)
        >>> list(windowed(chain(padding, iterable), 3))
        [(None, None, 1), (None, 1, 2), (1, 2, 3), (2, 3, 4)]

    Shamelessly stolen from more-itertools.
    """
    if n < 0:
        raise ValueError('n must be >= 0')
    if n == 0:
        yield tuple()
        return
    if step < 1:
        raise ValueError('step must be >= 1')

    window = deque(maxlen=n)
    i = n
    for _ in map(window.append, seq):
        i -= 1
        if not i:
            i = step
            yield tuple(window)

    size = len(window)
    if size < n:
        yield tuple(chain(window, repeat(fillvalue, n - size)))
    elif 0 < i < min(step, n):
        window += (fillvalue,) * i
        yield tuple(window)

class Transformer:
    def __init__(self, parser):
        self.parser = parser
        self.inverted_jumps = {
            'JZ': 'JNZ',
            'JAE': 'JNAE',
            'JB': 'JNB',
            'JS': 'JNS',
            'JNZ': 'JZ',
            'JNAE': 'JAE',
            'JNB': 'JB',
            'JNS': 'JS',
        }
        self.autogenlabel_re = re.compile('^\\?\\?L\\d+$')

    def extern(self, identifier):
        return self.parser.externs.get(identifier)

    def _match(self, window, *match):
        def _match_op_tuple(code_oper, pattern_oper):
            for pattern, code in zip(pattern_oper, code_oper):
                if pattern is None:
                    continue
                if isinstance(pattern, set):
                    if not code in pattern:
                        return False
                elif isinstance(pattern, str):
                    if code != pattern:
                        return False
                elif isinstance(pattern, tuple):
                    if type(code) != type(pattern):
                        return False
                    if not _match_op_tuple(code, pattern):
                        return False
                else:
                    raise NotImplementedError("Pattern of type %s not supported" % type(pattern))
            return True

        def _match_op(code, pattern):
            if code is None:
                return False

            if code['type'] == 'label':
                return pattern == ('??L:', None) and self.autogenlabel_re.fullmatch(code['identifier'])

            code_op, code_oper = code['op'], code['operands']
            pattern_op, pattern_oper = pattern

            code_op = code_op.upper()

            if isinstance(pattern_op, str):
                op_match = code_op == pattern_op
            elif isinstance(pattern_op, set):
                op_match = code_op in pattern_op
            elif pattern_op is None:
                op_match = True
            else:
                raise NotImplementedError("Operation of type %s not supported" % type(pattern_op))

            if isinstance(pattern_oper, tuple):
                oper_match = _match_op_tuple(code_oper, pattern_oper)
            elif pattern_oper is None:
                oper_match = True
            else:
                raise NotImplementedError("Operand of type %s not supported" % type(pattern_oper))

            return op_match and oper_match

        return window if all(_match_op(wop, mop) for wop, mop in zip(window, match)) else ()

    def _calculate_transform_dict(self, tokens):
        trans_dict = {}

        def fill_dict(window, *new_tokens):
            if len(new_tokens) > len(window):
                raise NotImplementedError("Can't insert more instructions than the window size")
            if not any(token['id'] in trans_dict for token in window):
                for token in window:
                    trans_dict[token['id']] = None
                for window_token, new_token in zip(window, new_tokens):
                    trans_dict[window_token['id']] = new_token

        tokens = list(token for token in tokens if token['type'] in {'label', 'instruction'})

        for window in windowed(tokens, 5):
            if window[0] is None:
                break
            matched = self._match(window, ('LAHF', ()), ('ADD', None), ('RCR', ('SI', None)), ('SAHF', ()), ('RCL', ('SI', None)))
            if matched and matched[2]['operands'] == matched[4]['operands']:
                fill_dict(matched,
                    {'op': 'savepsw', 'operands': ('reg',)},
                    {'op': matched[1]['op'], 'operands': matched[1]['operands']},
                    {'op': 'restorepsw', 'operands': ('reg',)})
                continue

        for window in windowed(tokens, 3):
            matched = self._match(window, ({'JZ', 'JAE', 'JB', 'JS', 'JNZ', 'JNAE', 'JNB', 'JNS'}, (('SHORT', None),)), ({'JMP', 'CALL'}, None), ('??L:', None))
            if matched and self.autogenlabel_re.fullmatch(matched[0]['operands'][0][1]):
                fill_dict(matched, {'op': matched[1]['op'] + '_' + self.inverted_jumps[matched[0]['op']][1:], 'operands': matched[1]['operands']})
                continue

            matched = self._match(window, ('POP', ('AX',)), ('XCHG', ('AL', 'AH')), ('SAHF', ()))
            if matched:
                fill_dict(matched, {'op': 'restorepsw', 'operands': ('stack',)})
                continue

            matched = self._match(window, ('POP', ('SI',)), ('XCHG', ('SI', 'BX')), ('PUSH', ('SI',)))
            if matched:
                fill_dict(matched, {'op': 'xthl', 'operands': ()})
                continue

            matched = self._match(window, ('XOR', ('AH', 'AH')), ('CMP', ('AL', None)), ('JZ', None))
            if matched:
                fill_dict(matched, {'op': 'cmp', 'operands': matched[1]['operands']}, {'op': 'jz', 'operands': matched[2]['operands']})
                continue

            matched = self._match(window, ('POP', ('AX',)), ('OR', ('AH', 'AH')), ('JZ', None))
            if matched:
                fill_dict(matched, {'op': 'jz', 'operands': matched[2]['operands']})
                continue

            matched = self._match(window, ('LAHF', ()), ({'INC', 'DEC'}, ({'BX', 'CX', 'DX', 'SP'},)), ('SAHF', ()))
            if matched:
                fill_dict(matched, {'op': matched[1]['op'], 'operands': matched[1]['operands']})
                continue

            matched = self._match(window, ('XOR', ('AH', 'AH')), ('MUL', ('DX',)), ('MOV', ('DH', 'DL')))
            if matched:
                fill_dict(matched, {'op': 'mul16by8', 'operands': ('AL', 'DX', 'DL')})
                continue

        for window in windowed(tokens, 4):
            matched = self._match(window, ('LAHF', ()), ('XCHG', ('AL', 'AH')), ('PUSH', ('AX',)), ('XCHG', ('AL', 'AH')))
            if matched:
                fill_dict(matched, {'op': 'savepsw', 'operands': ('stack',)})
                continue

        for window in windowed(tokens, 2):
            matched = self._match(window, ({'DEC', 'DECB'}, ('CH',)), ('JNZ', (('SHORT', None),)))
            if matched:
                fill_dict(matched, {'op': 'djnz', 'operands': matched[1]['operands']})
                continue

            matched = self._match(window, ({'JZ', 'JAE', 'JB', 'JS', 'JNZ', 'JNAE', 'JNB', 'JNS'}, (('SHORT', '$+3'),)), ('RET', ()))
            if matched:
                fill_dict(matched, {'op': 'ret_' + self.inverted_jumps[matched[0]['op']], 'operands': ()})
                continue

            matched = self._match(window, ('POP', ('AX',)), ('SAHF', ()))
            if matched:
                fill_dict(matched, {'op': 'POP', 'operands': ('AX',)})
                continue

            matched = self._match(window, ('LAHF', ()), ('PUSH', ('AX',)))
            if matched:
                fill_dict(matched, {'op': 'PUSH', 'operands': ('AX',)})
                continue

        for window in windowed(tokens, 1):
            matched = self._match(window, ({'REP', 'REPE', 'REPZ', 'REPNZ', 'REPNE'}, ({'LODSB', 'LODSW', 'STOSB', 'STOSW', 'MOVSB', 'MOVSW', 'SCASB', 'SCASW', 'CMPSB'},)))
            if matched:
                fill_dict(matched, {'op': matched[0]['op'] + '_' + matched[0]['operands'][0], 'operands': ()})
                continue

        return trans_dict

    def transform(self):
        def annotate_with_id():
            for id, token in enumerate(self.parser.parse()):
                token['id'] = id
                yield token

        left, right = tee(annotate_with_id())
        trans_dict = self._calculate_transform_dict(left)
        for token in right:
            if token['id'] in trans_dict:
                trans = trans_dict[token['id']]
                if trans is None:
                    comment = token.get('comment', None)
                    if comment is not None:
                        yield {'type': 'comment', 'value': comment}
                    continue

                token.update(trans)

            yield token

class PasmoWriter:
    regmap = {
        'BX': 'HL', 'BH': 'H', 'BL': 'L',
        'DX': 'DE', 'DH': 'D', 'DL': 'E',
        'CX': 'BC', 'CH': 'B', 'CL': 'C',
        'SI': 'IY', 'DI': 'IX',
        'SP': 'SP',
        'AL': 'A',
        # FIXME: will need to spill/fill AX, AH, and AL using the Z80 prime
        # registers because the code uses AX as a 16-bit register extensively
    }

    def __init__(self, transformer):
        self.transformer = transformer

    def lines(self):
        for token in self.transformer.transform():
            generator = '_gen_' + token['type']
            if not hasattr(self, generator):
                raise SyntaxError("Don't know how to generate token of type %s (%s)" % (token['type'], token))

            line = getattr(self, generator)(token)
            if line is not None:
                yield line

    def _gen_comment(self, token):
        return '\n'.join('; %s' % line for line in token['value'].split('\n'))

    def _gen_directive_radix(self, token):
        return '\t.radix %s' % token['value']

    def _gen_assign(self, token):
        return '\t%s=%s' % (token['symbol'], token['value'])

    def _gen_cseg(self, token):
        return '; CSEG %s (%s)' % (token['name'], 'public' if token['public'] else 'local')

    def _gen_assume(self, token):
        return '; Assuming segment %s' % token['seg']

    def _gen_xlist(self, token):
        return None

    def _gen_list(self, token):
        return None

    def _gen_extern(self, token):
        extern = '\tEXTERN %s:%s' % (token['identifier'], token['attr'])
        return '%s ; %s' % (extern, token['comment']) if 'comment' in token and token['comment'] else extern

    def _gen_public(self, token):
        return '\tPUBLIC %s' % token['identifier']

    def _gen_sall(self, token):
        return None

    def _gen_include(self, token):
        return '\tinclude %s' % token['filename']

    def _gen_title(self, token):
        header = ';' * (len(token['value']) + 6)
        return '\n%s\n;; %s ;;\n%s\n' % (header, token['value'], header)

    def _gen_subtitle(self, token):
        return '\n;;; %s ;;;\n' % token['value']

    def _gen_label(self, token):
        return '%s:' % token['identifier']

    def _is_16bit_reg(self, reg):
        return isinstance(reg, str) and len(reg) == 2 and reg[1] == 'X' or reg == 'SI' or reg == 'DI' or reg == 'ES'

    def _gen_instruction_clc(self, token):
        return 'SCF\n\tCCF'

    def _gen_instruction_mov(self, token):
        # FIXME: not all operations are possible here; for instance, it's not
        # possible to perform LD DE, (HL), which is generated by this function
        # in some cases.  This would need to be a sereies of instructions to
        # load D and E separately as there's no LD DE, r16 instruction.
        operands = []
        for op in token['operands']:
            if op in self.regmap:
                operands.append(self.regmap[op])
            elif self._is_ptr_access_through_extern(op):
                if isinstance(op, str):
                    operands.append('(%s)' % op)
                elif len(op) == 3 and op[:2] == ('BYTE', 'PTR'):
                    operands.append('(%s)' % op[2])
                elif len(op) >= 2 and op[0] == 'OFFSET':
                    operands.append('(%s)' % ''.join(op[1:]))
                else:
                    operands.append('(%s)' % ''.join(op))
            elif self._is_ptr_read(op):
                op = op[2]
                if op[0] == '[' and op[1:-1] in self.regmap:
                    operands.append('(%s)' % self.regmap[op[1:-1]])
                elif op not in self.regmap:
                    operands.append('(%s)' % op)
            elif isinstance(op, str) and op[0] == '[':
                if op[1:-1] in self.regmap:
                    operands.append('(%s)' % self.regmap[op[1:-1]])
                else:
                    raise SyntaxError("Don't know how to generate this MOV op: %s" % op)
            elif isinstance(op, tuple):
                operands.append(' '.join(str(op) for op in op))
            else:
                operands.append(op)

        assert len(operands) == 2

        op0_is_index = operands[0] in {'IX', 'IY'}
        op1_is_index = operands[1] in {'IX', 'IY'}
        if op0_is_index != op1_is_index:
            z1, z2 = operands

            # Have to use undocumented instructions here.
            if op0_is_index:
                return 'LD %sH, %s\n\tLD %sL, %s' % (z1, z2[0], z1, z2[1])
            return 'LD %s, %sH\n\tLD %sL, %s' % (z1[0], z2, z1[1], z2)

        if all(self._is_16bit_reg(op) for op in token['operands']):
            return ('PUSH %s\n\t' +
                    'POP %s\n\t') % (operands[0], operands[1])

        return 'LD %s' % ', '.join(str(op) for op in operands)

    def _gen_instruction_add(self, token, z80='ADD'):
        assert len(token['operands']) == 2
        op1, op2 = token['operands']
        if op1 == 'AL' and self._is_ptr_read_through_bx(op2):
            return '%s A, (HL)' % z80
        if (op1, op2) == ('AL', 'AL'):
            return 'RLA'
        if op1 in self.regmap:
            if op2 in self.regmap:
                return '%s %s, %s' % (z80, self.regmap[op1], self.regmap[op2])
            return '%s %s, %s' % (z80, self.regmap[op1], ' '.join(str(op) for op in op2))
        if op1 == 'AX' and isinstance(op2, int):
            # FIXME: figure out what to do with usage of AX...
            return '; ADD AX, %dD' % op2
        raise SyntaxError("Don't know how to generate %s: %s, %s" % (z80, op1, op2))

    def _gen_instruction_adc(self, token):
        return self._gen_instruction_add(token, 'ADC')

    def _gen_instruction_inc(self, token):
        assert len(token['operands']) == 1
        op = token['operands'][0]
        if self._is_ptr_read_through_bx(op):
            return 'INC (HL)'
        if op == ('WORD', 'PTR', 0, '[BX]'):
            return ('PUSH IY\n\t' +
                    'PUSH BC\n\t' +
                    'LD IY, HL\n\t' +
                    'LD B, (IY+0)\n\t' +
                    'LD C, (IY+1)\n\t' +
                    'INC BC\n\t' +
                    'LD (IY+0), B\n\t' +
                    'LD (IY+1), C\n\t' +
                    'POP BC\n\t' +
                    'POP IY')
        if op in self.regmap:
            return 'INC %s' % self.regmap[op]
        raise SyntaxError("Could not generate INC %s" % str(op))

    def _is_low_imm8(self, op):
        return isinstance(op, tuple) and len(op) == 2 and op[0] == 'LOW' and isinstance(op[1], int)

    def _gen_instruction_cmp(self, token):
        assert len(token['operands']) == 2
        op1, op2 = token['operands']
        if op1 == 'AH':
            # FIXME: still don't know what to do about AH
            if isinstance(op2, tuple) and len(op2) == 2 and op2[0] == 'LOW' and isinstance(op2[1], int):
                return '; CMP AH, %dD' % op2[1]
        if token['operands'] == (('BYTE', 'PTR', 0, '[DI]'), 'AL'):
            # FIXME: implement this
            return '; CMP 0[DI], AL'
        if isinstance(op1, tuple) and len(op1) == 3 and op1[:2] == ('BYTE', 'PTR') and op1[2].endswith('[SI]'):
            if isinstance(op2, tuple) and len(op2) == 2 and op2[0] == 'LOW' and isinstance(op2[1], int):
                op2 = op2[1]
            elif not isinstance(op2, int):
                raise SyntaxError("Don't know how to generate CMP %s" % str(token))
            offset = op1[2][:-4]
            return ('PUSH BC\n\t' +
                    'LD B, A\n\t' +
                    'LD A, %dD\n\t' +
                    'CP (IY+%s)\n\t' +
                    'POP BC') % (op2, offset)
        if op1 == 'CH':
            if self._is_low_imm8(op2):
                op2 = op2[1]
            elif not isinstance(op2, int):
                raise SyntaxError("Can't generate CMP %s" % token)
            if 0 <= op2 <= 255 or -128 <= op2 <= 127:
                return ('PUSH BC\n\t' +
                        'PUSH HL\n\t' +
                        'LD H, A\n\t' +
                        'LD A, B\n\t' +
                        'CP %dD\n\t' +
                        'LD A, H\n\t' +
                        'POP HL\n\t' +
                        'POP BC') % op2
        if self._is_ptr_read_through_bx(op1):
            if self._is_low_imm8(op2):
                op2 = op2[1]
            elif not isinstance(op2, int):
                raise SyntaxError("Can't generate CMP %s" % token)
            return ('PUSH BC\n\t' +
                    'LD B, A\n\t' +
                    'LD A, %dD\n\t' +
                    'CP (HL)\n\t' +
                    'LD A, B\n\t' +
                    'POP BC') % op2
        if op1 == 'AL' and op2 in self.regmap:
            return 'CP %s' % self.regmap[op2]
        if op1 == 'AL':
            if isinstance(op2, tuple):
                if len(op2) >= 3 and op2[:2] == ('LOW', 'OFFSET'):
                    op2 = ''.join(str(op) for op in op2[2:])
                elif len(op2) >= 2 and op2[:1] == ('LOW',):
                    op2 = ''.join(str(op) for op in op2[1:])
                elif self._is_ptr_read_through_bx(op2):
                    op2 = '(HL)'
                elif len(op2) == 4 and op2[:2] == ('BYTE', 'PTR') and op2[3] in ('[DI]', '[SI]') and isinstance(op2[2], int):
                    op2 = '(%s+%d)' % (self.regmap[op2[3][1:-1]], op2[2])
                else:
                    raise SyntaxError("Don't know how to generate CMP AL, %s" % op2)
            return 'CP %s' % op2
        if op1 == 'DX' and isinstance(op2, int):
            return ('PUSH HL\n\t' +
                    'PUSH DE\n\t' +
                    'LD HL, %dD\n\t' +
                    'OR A\n\t' +
                    'SBC DE, HL\n\t' +
                    'ADD DE, HL\n\t' +
                    'POP DE\n\t' +
                    'POP HL') % op2
        if (op1, op2) == ('BX', 'DX'):
            return ('LD A, H\n\t' +
                    'SUB D\n\t' +
                    'RET NZ\n\t' +
                    'LD A, L\n\t' +
                    'SUB E')
        if op2 in self.regmap:
            reg = self.regmap[op2]
            if op1 == 'BX':
                return ('OR A\n\t' + \
                        'SBC HL, %s\n\t' + \
                        'ADD HL, %s') % (reg, reg)
            if op1 == '[BX]':
                return ('PUSH HL\n\t' + \
                        'LD HL, (HL)\n\t' + \
                        'OR A\n\t' + \
                        'SBC HL, %s\n\t' + \
                        'ADD HL, %s\n\t' + \
                        'POP HL') % (reg, reg)
        raise SyntaxError("Don't know how to generate CMP: %s" % token)

    def _gen_instruction_ja(self, token):
        assert len(token['operands']) == 1
        return ('JR NC, $+2\n\t' +
                'JP Z %s') % token['operands'][0]

    def _gen_instruction_jg(self, token):
        assert len(token['operands']) == 1
        return ('JR NZ, $+2\n\t' +
                'JP PE, %s') % token['operands'][0]

    def _gen_instruction_jmp(self, token):
        assert len(token['operands']) == 1
        op = token['operands'][0]
        if op == '[BX]':
            return 'JP (HL)'
        if isinstance(op, str):
            return 'JP %s' % op
        if len(op) == 2 and op[0] == 'SHORT':
            return 'JR %s' % op[1]
        raise SyntaxError("Unsupported JMP to %s" % op)

    def _gen_instruction_jne(self, token):
        return self._gen_instruction_jnz(token)

    def _gen_instruction_je(self, token):
        return self._gen_instruction_jz(token)

    def _gen_instruction_ret(self, token):
        assert len(token['operands']) == 0
        # FIXME: maybe look at the code to generate other RET variants?
        return 'RET'

    def _gen_instruction_retf(self, token):
        return self._gen_instruction_ret(token)

    def _gen_instruction_push(self, token):
        assert len(token['operands']) == 1
        op = token['operands'][0]
        if op == 'ES':
            return None
        if self._is_16bit_reg(op):
            if op != 'AX':
                return 'PUSH %s' % self.regmap[op]
            return 'PUSH AF'
        # FIXME: check if op is a dword label first!
        return 'PUSH HL\n\tLD HL, (%s)\n\tEX (SP), HL' % op

    def _gen_instruction_pop(self, token):
        assert len(token['operands']) == 1
        op = token['operands'][0]
        if op == 'ES':
            return None
        if self._is_16bit_reg(op):
            if op != 'AX':
                return 'POP %s' % self.regmap[op]
            return 'POP AF'
        raise SyntaxError("Only 16-bit registers can be popped (trying %s)" % op)

    def _gen_instruction_pushf(self, token):
        assert len(token['operands']) == 0
        return 'PUSH AF' # FIXME: Not really interested in saving A here... maybe store in a prime?

    def _gen_instruction_popf(self, token):
        assert len(token['operands']) == 0
        return 'POP AF' # FIXME: Not really interested in restoring A here... maybe store in a prime?

    def _gen_instruction_or(self, token):
        assert len(token['operands']) == 2
        op1, op2 = token['operands']
        if op1 == 'AL':
            if not self._is_16bit_reg(op2) and op2 in self.regmap:
                return 'OR %s' % self.regmap[op2]
            if self._is_ptr_read_through_bx(op2):
                return 'OR (HL)'
            if len(op2) == 2 and op2[0] == 'LOW':
                if isinstance(op2[1], int):
                    return 'OR %dD' % op2[1]
                return 'OR %s' % op2[1]
        if op1 == op2:
            return 'OR A' # NOP, but clear C/N/P/V flags
        if {op1, op2} == {'BX', 'DX'}:
            return ('PUSH A\n\t' +
                    'LD A, H\n\t' +
                    'OR D\n\t' +
                    'LD H, A\n\t' +
                    'LD A, L\n\t' +
                    'OR E\n\t' +
                    'LD L, A\n\t' +
                    'POP A')
        raise SyntaxError("Don't know how to generate an OR with these yet: %s, %s" % (op1, op2))

    def _gen_instruction_dec(self, token):
        assert len(token['operands']) == 1
        op = token['operands'][0]
        if self._is_ptr_read_through_bx(op):
            return 'DEC (HL)'
        if op in self.regmap:
            return 'DEC %s' % self.regmap[op]
        raise SyntaxError("Don't know how to generate DEC with arg %s" % op)

    def _gen_instruction_call(self, token):
        assert len(token['operands']) == 1
        op = token['operands'][0]
        if op.isalnum() or (op[0] == '$' and op[1:].isalnum()):
            return 'CALL %s' % op
        raise SyntaxError("Don't know how to generate CALL with arg %s" % op)

    def _gen_instruction_cond_jmp(self, cond, op, has_jr=False):
        is_short = isinstance(op, tuple) and len(op) == 2 and op[0] == 'SHORT'

        target = None
        if isinstance(op, str):
            target = op
        elif isinstance(op, tuple):
            if len(op) == 1:
                target = op[0]
            elif len(op) == 2:
                target = op[1]
        elif isinstance(op, int):
            if not(-128 <= op < 127 or 0 <= op <= 255):
                is_short = False
            target = op

        if target is None:
            raise NotImplementedError("Can't perform a conditional jump with target %s" % str(op))

        instruction = "JR" if has_jr and is_short else "JP"
        return "%s %s, %s" % (instruction, cond, target)

    def _gen_instruction_jz(self, token):
        assert len(token['operands']) == 1
        return self._gen_instruction_cond_jmp('Z', token['operands'][0], has_jr=True)

    def _gen_instruction_jnz(self, token):
        assert len(token['operands']) == 1
        return self._gen_instruction_cond_jmp('NZ', token['operands'][0], has_jr=True)

    def _gen_instruction_jae(self, token):
        assert len(token['operands']) == 1
        return self._gen_instruction_cond_jmp('NC', token['operands'][0], has_jr=True)

    def _gen_instruction_js(self, token):
        assert len(token['operands']) == 1
        return self._gen_instruction_cond_jmp('M', token['operands'][0])

    def _gen_instruction_jns(self, token):
        assert len(token['operands']) == 1
        return self._gen_instruction_cond_jmp('P', token['operands'][0])

    def _gen_instruction_jp(self, token):
        return self._gen_instruction_jns(token)

    def _gen_instruction_jb(self, token):
        assert len(token['operands']) == 1
        return self._gen_instruction_cond_jmp('C', token['operands'][0], has_jr=True)

    def _gen_instruction_jnae(self, token):
        return self._gen_instruction_jb(token)

    def _gen_instruction_jnb(self, token):
        return self._gen_instruction_jae(token)

    def _gen_instruction_stc(self, token):
        assert len(token['operands']) == 0
        return 'SCF'

    def _gen_instruction_lahf(self, token):
        raise NotImplementedError("This use of LAHF is not supported")

    def _gen_instruction_sahf(self, token):
        raise NotImplementedError("This use of SAHF is not supported")

    def _gen_instruction_cmc(self, token):
        assert len(token['operands']) == 0
        return 'CCF'

    def _gen_instruction_xchg(self, token):
        assert len(token['operands']) == 2
        op1, op2 = token['operands']
        if {op1, op2} == {'DX', 'BX'}:
            return 'EX DE, HL'
        if {op1, op2} == {'AL', 'AH'}:
            return '; FIXME: This is invalid Z80\n\tLD C\', A\n\tLD A, B\'\n\tLD B\', C\''
        if self._is_16bit_reg(op1) and self._is_16bit_reg(op2):
            push_pop_regs = {'AF', 'BC', 'DE', 'HL', 'IX', 'IY'}
            z1 = self.regmap[op1]
            z2 = self.regmap[op2]
            if z1 in push_pop_regs and z2 in push_pop_regs:
                return 'PUSH %s\n\tPUSH %s\n\tPOP %s\n\tPOP %s' % (z1, z2, z1, z2)
        raise SyntaxError("Don't know how to generate XCHG %s, %s" % (op1, op2))

    def _is_ptr_read_through_bx(self, op):
        return op[:2] == ('BYTE', 'PTR') and op[2:] in (('[BX]',), (0, '[BX]'))

    def _is_ptr_read(self, op):
        return isinstance(op, tuple) and len(op) == 3 and op[:2] == ('BYTE', 'PTR')

    def _is_ptr_access_through_extern(self, op):
        if isinstance(op, str):
            return self.transformer.extern(op) in ('WORD', 'BYTE')
        if isinstance(op, tuple):
            return any(self._is_ptr_access_through_extern(op) for op in op)
        return False

    def _gen_instruction_and(self, token):
        assert len(token['operands']) == 2
        op1, op2 = token['operands']
        if op1 == 'AL':
            if op2 in self.regmap:
                return 'AND %s' % self.regmap[op2]
            if self._is_ptr_read_through_bx(op2):
                return 'AND (HL)'
            return 'AND %s' % ' '.join(str(op) for op in op2)
        if {op1, op2} == {'BX', 'DX'}:
            return ('PUSH A\n\t' +
                    'LD A, H\n\t' +
                    'AND D\n\t' +
                    'LD H, A\n\t' +
                    'LD A, L\n\t' +
                    'AND E\n\t' +
                    'LD L, A\n\t' +
                    'POP A')
        raise SyntaxError("Don't know how to generate AND with ops %s, %s" % (op1, op2))

    def _gen_instruction_sub(self, token, z80='SUB'):
        assert len(token['operands']) == 2
        op1, op2 = token['operands']
        if op1 == 'AL':
            if op2 in self.regmap:
                return '%s %s' % (z80, self.regmap[op2])
            if self._is_ptr_read_through_bx(op2):
                return '%s (HL)' % z80
            if isinstance(op2, tuple) and len(op2) >= 2 and op2[0] == 'LOW':
                return '%s %s' % (z80, ' '.join(str(op) for op in op2[1:]))
        if op1 == 'CX':
            # FIXME: Implement this.
            return '; SUB CX, %s' % str(op2)
        if op1 == 'BX' and op2 == 'DX':
            # FIXME: Is SBC always the right choice here?
            return 'SBC HL, DE'
        if op1 == 'DL' and self._is_ptr_read(op2):
            return ('PUSH HL\n\t' +
                    'EX AF, AF\'\n\t' +
                    'LD A, E\n\t' +
                    'LD HL, %s\n\t' +
                    'SUB (HL)\n\t' +
                    'EX AF, AF\'\n\t' +
                    'POP HL') % op2[2]
        raise SyntaxError("Don't know how to generate %s with ops %s, %s" % (z80, op1, op2))

    def _gen_instruction_sbb(self, token):
        return self._gen_instruction_sub(token, 'SBC')

    def _gen_instruction_xor(self, token):
        assert len(token['operands']) == 2
        op1, op2 = token['operands']
        if op1 == 'AL':
            if op2 in self.regmap:
                return 'XOR %s' % self.regmap[op2]
            if isinstance(op2, tuple) and op2[0] == 'LOW' and isinstance(op2[1], int):
                op2 = op2[1]
            if isinstance(op2, int) and 0 <= op2 <= 255:
                return 'XOR %dD' % op2
        if (op1, op2) == ('AH', 'AH'):
            return '; FIXME: This is invalid Z80 code\n\tPUSH AF\n\tXOR A\n\tLD B\', 0\n\tPOP AF'
        if op1 == op2:
            # FIXME: what about the flags?
            if op1 in self.regmap:
                return 'LD %s, 0' % self.regmap[op1]
            elif op1 == 'AX':
                return '; FIXME: Invalid Z80 code\n\tLD AF, 0'
        if {op1, op2} == {'BX', 'DX'}:
            return ('EX AF, AF\'\n\t' +
                    'LD A, H\n\t' +
                    'XOR D\n\t' +
                    'LD H, A\n\t' +
                    'LD A, L\n\t' +
                    'XOR E\n\t' +
                    'LD L, A\n\t' +
                    'EX AF, AF\'')
        raise SyntaxError("Don't know how to generate XOR with ops %s, %s" % (op1, op2))

    def _gen_instruction_stosb(self, token):
        assert len(token['operands']) == 0
        return 'LD (IX), A'

    def _gen_instruction_xthl(self, token):
        assert len(token['operands']) == 0
        return 'EX (SP), HL'

    def _gen_instruction_ror(self, token):
        assert len(token['operands']) == 2
        op1, op2 = token['operands']
        if op2 == 1:
            if op1 == 'AL':
                return 'RRA'
            if not self._is_16bit_reg(op1) and op1 in self.regmap:
                return 'RR %s' % self.regmap[op]
            if op1 == '[BX]':
                return 'RR (HL)'
        raise SyntaxError("Don't know how to generate ROR with op %s, %s" % (op1, op2))

    def _gen_instruction_rcr(self, token):
        assert len(token['operands']) == 2
        op1, op2 = token['operands']
        if op2 == 1:
            if op1 == 'AL':
                return 'RRCA'
            if op1 in self.regmap:
                if self._is_16bit_reg(op1):
                    return 'PUSH HL\n\tADC HL, %s\n\tLD %s, HL\n\tPOP HL' % (self.regmap[op1], self.regmap[op1])
                else:
                    return 'RRC %s' % self.regmap[op]
            if op1 == '[BX]':
                return 'RRC (HL)'

        raise SyntaxError("Don't know how to generate RCR with op %s, %s" % (op1, op2))

    def _gen_instruction_rcl(self, token):
        assert len(token['operands']) == 2
        op1, op2 = token['operands']
        if op2 == 1:
            if op1 == 'AL':
                return 'RLCA'
            if op1 in self.regmap:
                if self._is_16bit_reg(op1):
                    return 'PUSH HL\n\tSBC HL, %s\n\tLD %s, HL\n\tPOP HL' % (self.regmap[op1], self.regmap[op1])
                else:
                    return 'RLC %s' % self.regmap[op]
            if op1 == '[BX]':
                return 'RLC (HL)'

        raise SyntaxError("Don't know how to generate RCL with op %s, %s" % (op1, op2))

    def _gen_instruction_rol(self, token):
        assert len(token['operands']) == 2
        op1, op2 = token['operands']
        if op2 == 1:
            if op1 == 'AL':
                return 'RLA'
            if not self._is_16bit_reg(op1) and op1 in self.regmap:
                return 'RL %s' % self.regmap[op]
            if op1 == '[BX]':
                return 'RL (HL)'
        raise SyntaxError("Don't know how to generate ROL with op %s, %s" % (op1, op2))

    def _gen_instruction_lodsb(self, token):
        return '; LODSB %s' % token

    def _gen_instruction_test(self, token):
        return '; TEST %s' % token

    def _gen_instruction_movi(self, token):
        return self._gen_instruction_mov(token)

    def _gen_instruction_neg(self, token):
        assert len(token['operands']) == 1
        op = token['operands'][0]
        if op == 'AL':
            return 'NEG'
        if self._is_16bit_reg(op):
            high, low = self.regmap[op]
            return ('EX AF, AF\'\n\t' +
                    'XOR A\n\t' +
                    'SUB %s\n\t' +
                    'LD %s, A\n\t' +
                    'SBC A, A\n\t' +
                    'SUB %s\n\t' +
                    'LD %s, A\n\t' +
                    'EX AF, AF\'') % (low, low, high, high)
        raise SyntaxError("Don't know how to generate NEG with op %s" % op)

    def _gen_instruction_shr(self, token):
        assert len(token['operands']) == 2
        op1, op2 = token['operands']
        if op2 == 1 and self._is_16bit_reg(op1):
            op1 = self.regmap[op1]
            return 'SRL %s\n\tRR %s' % (op1[0], op1[1])
        raise SyntaxError("Don't know how to generate SHR %s, %s" % (op1, op2))

    def _gen_instruction_not(self, token):
        assert len(token['operands']) == 1
        op = token['operands'][0]
        if op == 'AL':
            return 'CPL'
        if op == 'BX':
            return ('EX AF, AF\'\n\t' +
                    'LD A, H\n\t' +
                    'CPL\n\t' +
                    'LD H, A\n\t' +
                    'LD A, L\n\t' +
                    'CPL\n\t' +
                    'LD L, A\n\t' +
                    'EX AF, AF\'')
        raise SyntaxError("Don't know how to generate NOT %s" % op)

    def _gen_instruction_mul(self, token):
        assert len(token['operands']) == 1
        op = token['operands'][0]
        # http://cpctech.cpc-live.com/docs/mult.html has a nice algorithm
        # for 16-bit multiplication
        if op == 'DX':
            return '; MUL DX'
        raise SyntaxError("Don't know how to generate MUL %s" % op)

    def _gen_instruction_in(self, token):
        assert len(token['operands']) == 2
        op1, op2 = token['operands']
        if op1 == 'AL' and op2 == 'DX':
            # This is not exactly equivalent, because ports in Z80 are 8-bit and in 8086
            # they're 16-bit... so we just take the lower byte.
            return ('PUSH BC\n\t' +
                    'LD BC, DE\n\t' +
                    'IN A, (C)\n\t' +
                    'POP BC')
        raise SyntaxError("Don't know how to generate IN %s, %s" % (op1, op2))

    def _gen_instruction_out(self, token):
        assert len(token['operands']) == 2
        op1, op2 = token['operands']
        if op1 == 'DX' and op2 == 'AL':
            # This is not exactly equivalent, because ports in Z80 are 8-bit and in 8086
            # they're 16-bit... so we just take the lower byte.
            return ('PUSH BC\n\t' +
                    'LD BC, DE\n\t' +
                    'OUT (C), A\n\t' +
                    'POP BC')
        raise SyntaxError("Don't know how to generate IN %s, %s" % (op1, op2))

    def _gen_instruction_int(self, token):
        assert len(token['operands']) == 1
        op = token['operands'][0]
        # FIXME: what to do here?
        return '; INT %dD' % op

    def _gen_instruction_ret_jz(self, token):
        return 'RET Z'

    def _gen_instruction_ret_jnz(self, token):
        return 'RET NZ'

    def _gen_instruction_ret_jnb(self, token):
        return 'RET NC'

    def _gen_instruction_ret_js(self, token):
        return 'RET M'

    def _gen_instruction_ret_jb(self, token):
        return 'RET C'

    def _gen_instruction_ret_jae(self, token):
        return self._gen_instruction_ret_jnb(token)

    def _gen_instruction_ret_jnae(self, token):
        return self._gen_instruction_ret_jb(token)

    def _gen_instruction_ret_jns(self, token):
        return self._gen_instruction_ret_js(token)

    def _gen_instruction_ret_jnae(self, token):
        return self._gen_instruction_ret_jb(token)

    def _gen_instruction_jmp_ae(self, token):
        return self._gen_instruction_jae(token)

    def _gen_instruction_jmp_s(self, token):
        return self._gen_instruction_js(token)

    def _gen_instruction_jmp_nae(self, token):
        return self._gen_instruction_jnae(token)

    def _gen_instruction_jmp_z(self, token):
        return self._gen_instruction_jz(token)

    def _gen_instruction_jmp_nz(self, token):
        return self._gen_instruction_jnz(token)

    def _gen_instruction_jmp_ns(self, token):
        return self._gen_instruction_jns(token)

    def _gen_instruction_std(self, token):
        # FIXME: what to do here?
        return '; STD'

    def _gen_instruction_cld(self, token):
        # FIXME: what to do here?
        return '; CLD'

    def _gen_instruction_cli(self, token):
        return 'DI'

    def _gen_instruction_sti(self, token):
        return 'EI'

    def _gen_instruction_repe_scasb(self, token):
        # FIXME: what to do here?
        return '; REPE SCASB'

    def _gen_instruction_savepsw(self, token):
        if token['operands'] == ('stack',):
            return 'PUSH AF'
        if token['operands'] == ('reg',):
            return 'EX AF, AF\''
        raise SyntaxError("Internal error: operands for savepsw are invalid: %s" % str(token))

    def _gen_instruction_restorepsw(self, token):
        if token['operands'] == ('stack',):
            return 'POP AF'
        if token['operands'] == ('reg',):
            return 'EX AF, AF\''
        raise SyntaxError("Internal error: operands for savepsw are invalid: %s" % str(token))

    def _gen_instruction_djnz(self, token):
        return 'DJNZ %s' % token['operands'][0][-1]

    def _gen_instruction_mul16by8(self, token):
        return '; MUL 16-by-8 %s' % str(token['operands'])

    def _gen_instruction_call_z(self, token):
        return 'CALL Z, %s' % token['operands'][0]

    def _gen_instruction_call_nz(self, token):
        return 'CALL NZ, %s' % token['operands'][0]

    def _gen_instruction_call_b(self, token):
        return 'CALL C, %s' % token['operands'][0]

    def _gen_instruction_call_nc(self, token):
        return 'CALL NC, %s' % token['operands'][0]

    def _gen_instruction_call_ae(self, token):
        return self._gen_instruction_call_nc(token)

    def _gen_instruction(self, token):
        op = token['op']
        instr = getattr(self, '_gen_instruction_' + op.lower())(token)
        return '\t%s\t\t; %s' % (instr, token['comment']) if token['comment'] else '\t' + instr

    def _gen_macro_call(self, token):
        args = []
        for arg_tuple in token['args']:
            for arg in arg_tuple:
                if arg['type'] in ('token', 'number'):
                    args.append(arg['value'])
                else:
                    raise SyntaxError("Unexpected type for macro argument: %s" % arg['type'])
        line = '\t%s %s' % (token['identifier'], ', '.join(args))
        return '%s ; %s' % (line, token['comment']) if token['comment'] else line

    def _gen_org(self, token):
        return '\torg %s' % token['value']

    def _gen_db(self, token):
        bytes = token['bytes'][0]
        if isinstance(bytes, tuple):
            if bytes[0] == 'offset':
                if isinstance(bytes[1], int):
                    return "\tDB %dD" % bytes[1]
                return "\tDB %s" % bytes[1]
        if isinstance(bytes, int):
            return "\tDB %dD" % bytes
        return '\tDB %s' % bytes

    def _gen_dw(self, token):
        return '\tdw %s' % ', '.join(str(b) for b in token['bytes'])

    def _gen_label_def(self, token):
        return '%s: ; %s' % (token['identifier'], ' '.join(token['attrs']))

    def _gen_equ(self, token):
        equ = '\t%s equ %s' % (token['identifier'], ' '.join(token['attrs']))
        return '%s ; %s' % (equ, token['comment']) if token['comment'] else equ

    def _gen_if(self, token):
        return 'IF %s' % ' '.join(token['cond'])

    def _gen_ifdef(self, token):
        return 'IFDEF %s' % ' '.join(token['cond'])

    def _gen_end_if(self, token):
        return 'ENDIF'

    def _gen_macro(self, token):
        macro = '%s MACRO %s' % (token['identifier'], ', '.join(token['args']))
        return '%s ; %s' % (macro, token['comment']) if token['comment'] else macro

    def _gen_end_macro(self, token):
        return 'ENDM'

    def _gen_end_forc(self, token):
        return 'ENDM'

    def _gen_echo(self, token):
        return '\t.WARNING %s' % ' '.join(token['value'] for token in token['msg'])

    def _gen_forc(self, token):
        assert len(token['args']) == 2
        op1, op2 = token['args']
        return '\tIRP %s, %s' % (op1['value'], op2['value'])

    def _gen_ifdif(self, token):
        assert len(token['ops']) == 2
        op1, op2 = token['ops']
        return '\tIF %s != %s' % (op1, op2)

    def _gen_ife(self, token):
        return '\tIF (%s) = 0' % ''.join(str(cond) for cond in token['cond'])

    def _gen_else(self, token):
        return '\tELSE'

    def _gen_rept(self, token):
        return 'REPT %s' % token['count']['value']

    def _gen_end_rept(self, token):
        return 'ENDM'

if __name__ == '__main__':
    lexer = Lexer(sys.stdin)
    parser = Parser(lexer)
    transformer = Transformer(parser)
    writer = PasmoWriter(transformer)

    try:
        for line in writer.lines():
            print(line)
    except SyntaxError as e:
        print("Exception: %s" % e)
        traceback.print_exc(file=sys.stdout)

