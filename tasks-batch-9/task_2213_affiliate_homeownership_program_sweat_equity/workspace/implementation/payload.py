"""Request body / query parsing and ERR_VALIDATION shape checks."""
from decimal import Decimal

from flask import request

from errors import fail
from util import D2, dec, iso_date, parse_date, parse_dt

MISSING = object()


def body():
    """The JSON object sent with the request ({} when no body was sent)."""
    raw = request.get_data()
    if raw is None or len(raw.strip()) == 0:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        fail("ERR_VALIDATION", "Request body must be a JSON object.")
    if not isinstance(data, dict):
        fail("ERR_VALIDATION", "Request body must be a JSON object.")
    return data


def pick(data, *names):
    """First present alias among names -> (name, value); (None, MISSING) if absent."""
    for name in names:
        if name in data:
            return name, data[name]
    return None, MISSING


def _bad(field, detail):
    fail("ERR_VALIDATION", "%s %s" % (field, detail))


def _fetch(data, field, aliases):
    names = (field,) + tuple(aliases or ())
    return pick(data, *names)


def vstring(data, field, min_len=1, max_len=None, required=False,
            default=None, aliases=(), nullable=False):
    name, value = _fetch(data, field, aliases)
    if value is MISSING:
        if required:
            _bad(field, "is required.")
        return default
    if value is None:
        if nullable:
            return None
        if required:
            _bad(field, "is required.")
        return default
    if not isinstance(value, str):
        _bad(field, "must be a string.")
    if min_len is not None and len(value) < min_len:
        _bad(field, "must be at least %d characters." % min_len)
    if max_len is not None and len(value) > max_len:
        _bad(field, "must be at most %d characters." % max_len)
    return value


def vint(data, field, minimum=None, maximum=None, required=False,
         default=None, aliases=(), nullable=False, choices=None):
    name, value = _fetch(data, field, aliases)
    if value is MISSING:
        if required:
            _bad(field, "is required.")
        return default
    if value is None:
        if nullable:
            return None
        if required:
            _bad(field, "is required.")
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(field, "must be an integer.")
    if minimum is not None and value < minimum:
        _bad(field, "must be at least %d." % minimum)
    if maximum is not None and value > maximum:
        _bad(field, "must be at most %d." % maximum)
    if choices is not None and value not in choices:
        _bad(field, "must be one of %s." % (", ".join(str(c) for c in choices),))
    return value


def vdecimal(data, field, minimum=None, maximum=None, required=False,
             default=None, aliases=(), nullable=False, places=2):
    name, value = _fetch(data, field, aliases)
    if value is MISSING:
        if required:
            _bad(field, "is required.")
        return default
    if value is None:
        if nullable:
            return None
        if required:
            _bad(field, "is required.")
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        _bad(field, "must be a number.")
    amount = dec(value)
    quantum = Decimal(1).scaleb(-places)
    if amount != amount.quantize(quantum):
        _bad(field, "must have at most %d decimal places." % places)
    amount = amount.quantize(quantum)
    if minimum is not None and amount < dec(minimum):
        _bad(field, "must be at least %s." % minimum)
    if maximum is not None and amount > dec(maximum):
        _bad(field, "must be at most %s." % maximum)
    return amount


def vbool(data, field, required=False, default=None, aliases=(), nullable=False):
    name, value = _fetch(data, field, aliases)
    if value is MISSING:
        if required:
            _bad(field, "is required.")
        return default
    if value is None:
        if nullable:
            return None
        if required:
            _bad(field, "is required.")
        return default
    if not isinstance(value, bool):
        _bad(field, "must be a boolean.")
    return value


def venum(data, field, choices, required=False, default=None,
          aliases=(), nullable=False, alias_map=None):
    name, value = _fetch(data, field, aliases)
    if value is MISSING:
        if required:
            _bad(field, "is required.")
        return default
    if value is None:
        if nullable:
            return None
        if required:
            _bad(field, "is required.")
        return default
    if not isinstance(value, str):
        _bad(field, "must be a string.")
    if alias_map and value in alias_map:
        value = alias_map[value]
    if value not in choices:
        _bad(field, "must be one of %s." % ", ".join(choices))
    return value


def vdate(data, field, required=False, default=None, aliases=(), nullable=False):
    name, value = _fetch(data, field, aliases)
    if value is MISSING:
        if required:
            _bad(field, "is required.")
        return default
    if value is None:
        if nullable:
            return None
        if required:
            _bad(field, "is required.")
        return default
    if not isinstance(value, str):
        _bad(field, "must be a date string.")
    parsed = parse_date(value)
    if parsed is None:
        _bad(field, "must be an ISO 8601 date.")
    return iso_date(parsed)


def vdatetime(data, field, required=False, default=None, aliases=(), nullable=False):
    name, value = _fetch(data, field, aliases)
    if value is MISSING:
        if required:
            _bad(field, "is required.")
        return default
    if value is None:
        if nullable:
            return None
        if required:
            _bad(field, "is required.")
        return default
    if not isinstance(value, str):
        _bad(field, "must be an ISO 8601 timestamp.")
    parsed = parse_dt(value)
    if parsed is None:
        _bad(field, "must be an ISO 8601 timestamp.")
    return parsed


def vid(data, field, required=False, default=None, aliases=(), nullable=False):
    return vstring(data, field, min_len=1, max_len=None, required=required,
                   default=default, aliases=aliases, nullable=nullable)


def vlist(data, field, required=False, default=None, aliases=(), nullable=False):
    name, value = _fetch(data, field, aliases)
    if value is MISSING:
        if required:
            _bad(field, "is required.")
        return default
    if value is None:
        if nullable:
            return None
        if required:
            _bad(field, "is required.")
        return default
    if not isinstance(value, list):
        _bad(field, "must be an array.")
    return value


# --------------------------------------------------------------------------- #
# query string
# --------------------------------------------------------------------------- #
def _query_int(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        _bad(name, "must be an integer.")
    value = int(text)
    if minimum is not None and value < minimum:
        _bad(name, "must be at least %d." % minimum)
    if maximum is not None and value > maximum:
        _bad(name, "must be at most %d." % maximum)
    return value


def pagination():
    limit = _query_int("limit", 10, 1, 100)
    offset = _query_int("offset", 0, 0, None)
    return limit, offset


def qenum(name, choices):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in choices:
        _bad(name, "must be one of %s." % ", ".join(choices))
    return raw


def qstring(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def qbool(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw in ("true", "True", "1"):
        return True
    if raw in ("false", "False", "0"):
        return False
    _bad(name, "must be a boolean.")


def qid(name):
    return qstring(name)


def qdatetime(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    parsed = parse_dt(raw)
    if parsed is None:
        _bad(name, "must be an ISO 8601 timestamp.")
    return parsed


def qdate(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    parsed = parse_date(raw)
    if parsed is None:
        _bad(name, "must be an ISO 8601 date.")
    return iso_date(parsed)
