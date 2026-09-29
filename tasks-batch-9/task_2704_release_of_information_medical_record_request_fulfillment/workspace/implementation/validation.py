"""Body schema validation and pagination parsing (priority 4, ERR_INVALID_REQUEST)."""

from flask import request

import store
from errors import ApiError


def bad():
    raise ApiError("ERR_INVALID_REQUEST")


def body():
    """Parsed JSON object, or {} when the caller sent nothing."""
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        bad()
    if not isinstance(payload, dict):
        bad()
    return payload


def present(b, name):
    return name in b and b[name] is not None


# ------------------------------------------------------------------ scalars
def req_str(b, name, max_len=None, min_len=1):
    if not present(b, name):
        bad()
    return _str(b[name], max_len, min_len)


def opt_str(b, name, max_len=None, min_len=1, default=None):
    if not present(b, name):
        return default
    return _str(b[name], max_len, min_len)


def _str(value, max_len, min_len):
    if not isinstance(value, str):
        bad()
    if len(value) < min_len:
        bad()
    if max_len is not None and len(value) > max_len:
        bad()
    return value


def req_int(b, name, minimum=0, maximum=None):
    if not present(b, name):
        bad()
    return _int(b[name], minimum, maximum)


def opt_int(b, name, minimum=0, maximum=None, default=None):
    if not present(b, name):
        return default
    return _int(b[name], minimum, maximum)


def _int(value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        bad()
    if minimum is not None and value < minimum:
        bad()
    if maximum is not None and value > maximum:
        bad()
    return value


def req_bool(b, name):
    if not present(b, name):
        bad()
    if not isinstance(b[name], bool):
        bad()
    return b[name]


def opt_bool(b, name, default=False):
    if not present(b, name):
        return default
    if not isinstance(b[name], bool):
        bad()
    return b[name]


def req_enum(b, name, allowed):
    value = req_str(b, name)
    if value not in allowed:
        bad()
    return value


def opt_enum(b, name, allowed, default=None):
    if not present(b, name):
        return default
    value = _str(b[name], None, 1)
    if value not in allowed:
        bad()
    return value


def req_id(b, name):
    """A foreign key: a non-empty string.  Existence is checked at priority 7."""
    return req_str(b, name)


def opt_id(b, name):
    if not present(b, name):
        return None
    return _str(b[name], None, 1)


def req_enum_array(b, name, allowed, allow_empty=True):
    if not present(b, name):
        bad()
    return _enum_array(b[name], allowed, allow_empty)


def opt_enum_array(b, name, allowed, default=None, allow_empty=True):
    if not present(b, name):
        return list(default) if default is not None else None
    return _enum_array(b[name], allowed, allow_empty)


def _enum_array(value, allowed, allow_empty):
    if not isinstance(value, list):
        bad()
    if not allow_empty and len(value) == 0:
        bad()
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            bad()
    return list(value)


def req_datetime(b, name):
    """Returns (raw_string, parsed_datetime)."""
    if not present(b, name):
        bad()
    return _datetime(b[name])


def opt_datetime(b, name):
    if not present(b, name):
        return None, None
    return _datetime(b[name])


def _datetime(value):
    parsed = store.parse_dt(value)
    if parsed is None:
        bad()
    return value, parsed


def req_date(b, name):
    if not present(b, name):
        bad()
    parsed = store.parse_date(b[name])
    if parsed is None:
        bad()
    return b[name], parsed


# ------------------------------------------------------------------ paging
def paging():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            bad()
        if str(limit) != str(raw).strip():
            bad()
        if limit < 1 or limit > 100:
            bad()
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            bad()
        if str(offset) != str(raw).strip():
            bad()
        if offset < 0:
            bad()
    return limit, offset


def page(rows, limit, offset):
    return [store.public(r) for r in rows[offset:offset + limit]], len(rows)
