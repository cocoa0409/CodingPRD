"""Request body schema validation (priority 40) -> ERR_VALIDATION / HTTP 400."""

import re

from flask import request

from common import dec, parse_iso
from errors import fail

MISSING = object()


def peek_body():
    """Best-effort body read used by narrow role rules that run at priority 20."""
    try:
        body = request.get_json(silent=True)
    except Exception:
        return {}
    if isinstance(body, dict):
        return body
    return {}


def parse_body():
    """Priority 40 entry point: the body must be a JSON object (or absent)."""
    try:
        body = request.get_json(silent=True)
    except Exception:
        body = None
    if body is None:
        return {}
    if not isinstance(body, dict):
        fail("ERR_VALIDATION", "Request body must be a JSON object.")
    return body


class Field(object):
    def __init__(self, name, kind, required=False, default=MISSING, **opts):
        self.name = name
        self.kind = kind
        self.required = required
        self.default = default
        self.opts = opts


def _bad(name, detail):
    fail("ERR_VALIDATION", "Field '%s' %s." % (name, detail))


def _check_string(field, value):
    if not isinstance(value, str):
        _bad(field.name, "must be a string")
    min_len = field.opts.get("min_len", 1)
    max_len = field.opts.get("max_len")
    if len(value) < min_len:
        _bad(field.name, "must be at least %d characters" % min_len)
    if max_len is not None and len(value) > max_len:
        _bad(field.name, "must be at most %d characters" % max_len)
    pattern = field.opts.get("pattern")
    if pattern is not None and not re.match(pattern, value):
        _bad(field.name, "does not match the required format")
    return value


def _check_number(field, value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(field.name, "must be a number")
    parsed = dec(value)
    _range(field, parsed)
    return parsed


def _check_integer(field, value):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(field.name, "must be an integer")
    _range(field, dec(value))
    return value


def _range(field, parsed):
    gt = field.opts.get("gt")
    gte = field.opts.get("gte")
    lt = field.opts.get("lt")
    lte = field.opts.get("lte")
    if gt is not None and not parsed > dec(gt):
        _bad(field.name, "must be greater than %s" % gt)
    if gte is not None and not parsed >= dec(gte):
        _bad(field.name, "must be greater than or equal to %s" % gte)
    if lt is not None and not parsed < dec(lt):
        _bad(field.name, "must be less than %s" % lt)
    if lte is not None and not parsed <= dec(lte):
        _bad(field.name, "must be less than or equal to %s" % lte)


def _check_enum(field, value):
    if not isinstance(value, str) or value not in field.opts["values"]:
        _bad(field.name, "must be one of %s" % ", ".join(field.opts["values"]))
    return value


def _check_bool(field, value):
    if not isinstance(value, bool):
        _bad(field.name, "must be a boolean")
    return value


def _check_datetime(field, value):
    parsed = parse_iso(value)
    if parsed is None:
        _bad(field.name, "must be an ISO 8601 timestamp")
    return parsed


def _check_num_array(field, value):
    if not isinstance(value, list):
        _bad(field.name, "must be an array")
    min_items = field.opts.get("min_items")
    max_items = field.opts.get("max_items")
    if min_items is not None and len(value) < min_items:
        _bad(field.name, "must hold at least %d entries" % min_items)
    if max_items is not None and len(value) > max_items:
        _bad(field.name, "must hold at most %d entries" % max_items)
    item_gte = field.opts.get("item_gte")
    parsed = []
    for entry in value:
        if isinstance(entry, bool) or not isinstance(entry, (int, float)):
            _bad(field.name, "must hold only numbers")
        entry_dec = dec(entry)
        if item_gte is not None and entry_dec < dec(item_gte):
            _bad(field.name, "entries must be at least %s" % item_gte)
        parsed.append(entry_dec)
    return parsed


_CHECKERS = {
    "string": _check_string,
    "number": _check_number,
    "integer": _check_integer,
    "enum": _check_enum,
    "boolean": _check_bool,
    "datetime": _check_datetime,
    "num_array": _check_num_array,
}


def validate(body, fields):
    """Validate a parsed body against a field list; returns a value dict."""
    result = {}
    for field in fields:
        present = field.name in body
        value = body.get(field.name, MISSING)
        if not present or value is None:
            if field.required:
                if not present:
                    _bad(field.name, "is required")
                _bad(field.name, "may not be null")
            result[field.name] = None if field.default is MISSING else field.default
            continue
        result[field.name] = _CHECKERS[field.kind](field, value)
    return result


# Common patterns
MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"
QUARTER_PATTERN = r"^\d{4}-Q[1-4]$"
STATE_CODE_PATTERN = r"^[A-Z]{2}$"
