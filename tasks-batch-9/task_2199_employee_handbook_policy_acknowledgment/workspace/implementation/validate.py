"""Body / query screening helpers."""
from flask import request

import clock
import db
from errors import fail

MISSING = object()


def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        fail("ERR_VALIDATION", "Request body must be a JSON object")
    return data


def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        limit = _as_int(raw)
        if limit is None or limit < 1 or limit > 100:
            fail("ERR_INVALID_PAGINATION", "limit must be an integer in [1, 100]")
    if "offset" in args:
        raw = args.get("offset")
        offset = _as_int(raw)
        if offset is None or offset < 0:
            fail("ERR_INVALID_PAGINATION", "offset must be an integer >= 0")
    return limit, offset


def _as_int(raw):
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    try:
        if s.lstrip("+-").isdigit():
            return int(s)
    except ValueError:
        return None
    return None


def req_str(data, key, min_len=1, max_len=None):
    if key not in data:
        fail("ERR_VALIDATION", "%s is required" % key)
    value = data[key]
    if not isinstance(value, str):
        fail("ERR_VALIDATION", "%s must be a string" % key)
    if len(value) < min_len:
        fail("ERR_VALIDATION", "%s must be at least %d characters" % (key, min_len))
    if max_len is not None and len(value) > max_len:
        fail("ERR_VALIDATION", "%s must be at most %d characters" % (key, max_len))
    return value


def opt_str(data, key, default=None, min_len=1, max_len=None):
    if key not in data or data[key] is None:
        return default
    return req_str(data, key, min_len=min_len, max_len=max_len)


def req_int(data, key, minimum=None, maximum=None):
    if key not in data:
        fail("ERR_VALIDATION", "%s is required" % key)
    return _check_int(data[key], key, minimum, maximum)


def opt_int(data, key, default=None, minimum=None, maximum=None):
    if key not in data or data[key] is None:
        return default
    return _check_int(data[key], key, minimum, maximum)


def _check_int(value, key, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_VALIDATION", "%s must be an integer" % key)
    if minimum is not None and value < minimum:
        fail("ERR_VALIDATION", "%s must be >= %s" % (key, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_VALIDATION", "%s must be <= %s" % (key, maximum))
    return value


def req_bool(data, key):
    if key not in data:
        fail("ERR_VALIDATION", "%s is required" % key)
    if not isinstance(data[key], bool):
        fail("ERR_VALIDATION", "%s must be a boolean" % key)
    return data[key]


def opt_bool(data, key, default=None):
    if key not in data or data[key] is None:
        return default
    return req_bool(data, key)


def req_enum(data, key, allowed):
    value = req_str(data, key)
    if value not in allowed:
        fail("ERR_VALIDATION", "%s must be one of %s" % (key, ", ".join(allowed)))
    return value


def opt_enum(data, key, allowed, default=None):
    if key not in data or data[key] is None:
        return default
    return req_enum(data, key, allowed)


def req_datetime(data, key):
    value = req_str(data, key)
    parsed = clock.parse(value)
    if parsed is None:
        fail("ERR_VALIDATION", "%s must be an ISO 8601 instant" % key)
    return parsed


def req_lang(data, key):
    value = req_str(data, key)
    if len(value) != 2 or not value.islower() or not value.isalpha():
        fail("ERR_VALIDATION", "%s must be exactly two lowercase characters" % key)
    return value


def opt_lang(data, key, default=None):
    if key not in data or data[key] is None:
        return default
    return req_lang(data, key)


def req_id_array(data, key):
    if key not in data:
        fail("ERR_VALIDATION", "%s is required" % key)
    value = data[key]
    if not isinstance(value, list) or len(value) == 0:
        fail("ERR_VALIDATION", "%s must be a non-empty array" % key)
    for item in value:
        if not isinstance(item, str) or not item:
            fail("ERR_VALIDATION", "%s must contain identifier strings" % key)
    return value


def fk(table, value, ):
    """Resolve a body foreign key; 404 when unresolvable."""
    row = db.get(table, value) if isinstance(value, str) else None
    if row is None:
        fail("ERR_REFERENCED_ENTITY_NOT_FOUND", "Referenced entity %s not found" % value)
    return row


def path_row(table, value):
    row = db.get(table, value)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND", "Resource %s not found" % value)
    return row


def query_filter(rows, key, field=None, cast=None):
    if key not in request.args:
        return rows
    raw = request.args.get(key)
    field = field or key
    if cast == "bool":
        want = str(raw).strip().lower()
        if want in ("true", "1"):
            value = True
        elif want in ("false", "0"):
            value = False
        else:
            return []
        return [r for r in rows if bool(r.get(field)) is value]
    if cast == "int":
        parsed = _as_int(raw)
        if parsed is None:
            return []
        return [r for r in rows if r.get(field) == parsed]
    return [r for r in rows if r.get(field) == raw]
