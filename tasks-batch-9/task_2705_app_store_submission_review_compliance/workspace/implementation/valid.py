"""Schema validation primitives (rung 28: ERR_VALIDATION / 422)."""
from decimal import Decimal

from common import fail, parse_iso

_MISSING = object()


def check_unknown(body, allowed):
    for key in body.keys():
        if key not in allowed:
            fail("ERR_VALIDATION", "unknown field %r" % key)


def present(body, name):
    return name in body and body[name] is not None


def req_str(body, name, min_len=1, max_len=None, enum=None):
    value = body.get(name, _MISSING)
    if value is _MISSING or value is None:
        fail("ERR_VALIDATION", "%s is required" % name)
    return _str(name, value, min_len, max_len, enum)


def opt_str(body, name, min_len=0, max_len=None, enum=None, default=None,
            nullable=True):
    value = body.get(name, _MISSING)
    if value is _MISSING:
        return default
    if value is None:
        if not nullable:
            fail("ERR_VALIDATION", "%s may not be null" % name)
        return None
    return _str(name, value, min_len, max_len, enum)


def _str(name, value, min_len, max_len, enum):
    if not isinstance(value, str):
        fail("ERR_VALIDATION", "%s must be a string" % name)
    if enum is not None and value not in enum:
        fail("ERR_VALIDATION", "%s must be one of %s" % (name, sorted(enum)))
    if min_len is not None and len(value) < min_len:
        fail("ERR_VALIDATION", "%s is shorter than %d characters" % (name, min_len))
    if max_len is not None and len(value) > max_len:
        fail("ERR_VALIDATION", "%s is longer than %d characters" % (name, max_len))
    return value


def req_int(body, name, minimum=None, maximum=None):
    value = body.get(name, _MISSING)
    if value is _MISSING or value is None:
        fail("ERR_VALIDATION", "%s is required" % name)
    return _int(name, value, minimum, maximum)


def opt_int(body, name, minimum=None, maximum=None, default=None, nullable=True):
    value = body.get(name, _MISSING)
    if value is _MISSING:
        return default
    if value is None:
        if not nullable:
            fail("ERR_VALIDATION", "%s may not be null" % name)
        return None
    return _int(name, value, minimum, maximum)


def _int(name, value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_VALIDATION", "%s must be an integer" % name)
    if minimum is not None and value < minimum:
        fail("ERR_VALIDATION", "%s must be >= %s" % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_VALIDATION", "%s must be <= %s" % (name, maximum))
    return value


def req_num(body, name, minimum=None, maximum=None):
    value = body.get(name, _MISSING)
    if value is _MISSING or value is None:
        fail("ERR_VALIDATION", "%s is required" % name)
    return _num(name, value, minimum, maximum)


def opt_num(body, name, minimum=None, maximum=None, default=None):
    value = body.get(name, _MISSING)
    if value is _MISSING:
        return default
    if value is None:
        return None
    return _num(name, value, minimum, maximum)


def _num(name, value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_VALIDATION", "%s must be a number" % name)
    dec = Decimal(str(value))
    if minimum is not None and dec < Decimal(str(minimum)):
        fail("ERR_VALIDATION", "%s must be >= %s" % (name, minimum))
    if maximum is not None and dec > Decimal(str(maximum)):
        fail("ERR_VALIDATION", "%s must be <= %s" % (name, maximum))
    return dec


def req_bool(body, name):
    value = body.get(name, _MISSING)
    if value is _MISSING or value is None:
        fail("ERR_VALIDATION", "%s is required" % name)
    if not isinstance(value, bool):
        fail("ERR_VALIDATION", "%s must be a boolean" % name)
    return value


def opt_bool(body, name, default=None):
    value = body.get(name, _MISSING)
    if value is _MISSING:
        return default
    if value is None:
        return default
    if not isinstance(value, bool):
        fail("ERR_VALIDATION", "%s must be a boolean" % name)
    return value


def req_iso(body, name):
    value = body.get(name, _MISSING)
    if value is _MISSING or value is None:
        fail("ERR_VALIDATION", "%s is required" % name)
    return _iso(name, value)


def opt_iso(body, name, default=None):
    value = body.get(name, _MISSING)
    if value is _MISSING:
        return default
    if value is None:
        return None
    return _iso(name, value)


def _iso(name, value):
    if not isinstance(value, str):
        fail("ERR_VALIDATION", "%s must be an ISO 8601 UTC instant" % name)
    parsed = parse_iso(value)
    if parsed is None:
        fail("ERR_VALIDATION", "%s is not a valid ISO 8601 UTC instant" % name)
    return parsed


def req_id(body, name):
    """An entity reference: must be a non-empty string."""
    return req_str(body, name, min_len=1)


def opt_id(body, name, default=None):
    return opt_str(body, name, min_len=1, default=default)


def raw_id(body, name):
    """Reference value straight from the body, unvalidated (for resolve())."""
    value = body.get(name)
    return value if isinstance(value, str) else None


def req_array(body, name, min_items=None, max_items=None, member_enum=None,
              member_type=str, unique=False):
    value = body.get(name, _MISSING)
    if value is _MISSING or value is None:
        fail("ERR_VALIDATION", "%s is required" % name)
    return _array(name, value, min_items, max_items, member_enum, member_type,
                  unique)


def opt_array(body, name, min_items=None, max_items=None, member_enum=None,
              member_type=str, default=None, unique=False):
    value = body.get(name, _MISSING)
    if value is _MISSING:
        return list(default) if isinstance(default, list) else default
    if value is None:
        return list(default) if isinstance(default, list) else default
    return _array(name, value, min_items, max_items, member_enum, member_type,
                  unique)


def _array(name, value, min_items, max_items, member_enum, member_type, unique):
    if not isinstance(value, list):
        fail("ERR_VALIDATION", "%s must be an array" % name)
    if min_items is not None and len(value) < min_items:
        fail("ERR_VALIDATION", "%s must have at least %d items" % (name, min_items))
    if max_items is not None and len(value) > max_items:
        fail("ERR_VALIDATION", "%s must have at most %d items" % (name, max_items))
    for item in value:
        if member_type is str and not isinstance(item, str):
            fail("ERR_VALIDATION", "%s members must be strings" % name)
        if member_enum is not None and item not in member_enum:
            fail("ERR_VALIDATION", "%s members must be one of %s"
                 % (name, sorted(member_enum)))
    if unique and len(set(value)) != len(value):
        fail("ERR_VALIDATION", "%s members must be unique" % name)
    return list(value)


def req_object(body, name):
    value = body.get(name, _MISSING)
    if value is _MISSING or value is None:
        fail("ERR_VALIDATION", "%s is required" % name)
    if not isinstance(value, dict):
        fail("ERR_VALIDATION", "%s must be an object" % name)
    return value
