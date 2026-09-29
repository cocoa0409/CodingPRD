"""Body shape validation (PRD 2.8 step 4 -> ERR_INVALID_REQUEST)."""

from decimal import Decimal, InvalidOperation

from flask import request

from core import parse_dt
from errors import ApiError, invalid

_SENTINEL = object()

# fields a client may never set; a body that carries them has the keys ignored
IGNORED_KEYS = ("id", "created_at", "updated_at", "version")


def body():
    if not request.data:
        return {}
    raw = request.get_json(silent=True)
    if raw is None:
        raise invalid("body must be a JSON object")
    if not isinstance(raw, dict):
        raise invalid("body must be a JSON object")
    return {k: v for k, v in raw.items() if k not in IGNORED_KEYS}


def raw_get(data, name):
    return data.get(name, _SENTINEL)


def present(data, name):
    value = data.get(name, _SENTINEL)
    return value is not _SENTINEL and value is not None


def opt_str_ref(data, name):
    """Read a possible foreign-key string without validating it (for pre-existence checks)."""
    value = data.get(name)
    return value if isinstance(value, str) else None


def req_string(data, name, allow_empty=False):
    value = data.get(name, _SENTINEL)
    if value is _SENTINEL or value is None:
        raise invalid("'%s' is required" % name)
    if not isinstance(value, str):
        raise invalid("'%s' must be a string" % name)
    if not allow_empty and value.strip() == "":
        raise invalid("'%s' may not be empty" % name)
    return value


def opt_string(data, name, default=None, allow_empty=False):
    value = data.get(name, _SENTINEL)
    if value is _SENTINEL or value is None:
        return default
    if not isinstance(value, str):
        raise invalid("'%s' must be a string" % name)
    if not allow_empty and value.strip() == "":
        raise invalid("'%s' may not be empty" % name)
    return value


def _as_int(name, value):
    if isinstance(value, bool):
        raise invalid("'%s' must be an integer" % name)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and float(value).is_integer():
        return int(value)
    raise invalid("'%s' must be an integer" % name)


def req_int(data, name, minimum=None, maximum=None, multiple_of=None):
    value = data.get(name, _SENTINEL)
    if value is _SENTINEL or value is None:
        raise invalid("'%s' is required" % name)
    number = _as_int(name, value)
    _check_int_bounds(name, number, minimum, maximum, multiple_of)
    return number


def opt_int(data, name, default=None, minimum=None, maximum=None, multiple_of=None):
    value = data.get(name, _SENTINEL)
    if value is _SENTINEL or value is None:
        return default
    number = _as_int(name, value)
    _check_int_bounds(name, number, minimum, maximum, multiple_of)
    return number


def _check_int_bounds(name, number, minimum, maximum, multiple_of):
    if minimum is not None and number < minimum:
        raise invalid("'%s' must be >= %s" % (name, minimum))
    if maximum is not None and number > maximum:
        raise invalid("'%s' must be <= %s" % (name, maximum))
    if multiple_of is not None and number % multiple_of != 0:
        raise invalid("'%s' must be a multiple of %s" % (name, multiple_of))


def req_decimal(data, name, minimum=None, exclusive_minimum=None, max_decimals=None):
    value = data.get(name, _SENTINEL)
    if value is _SENTINEL or value is None:
        raise invalid("'%s' is required" % name)
    return _as_decimal(name, value, minimum, exclusive_minimum, max_decimals)


def _as_decimal(name, value, minimum, exclusive_minimum, max_decimals):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise invalid("'%s' must be a number" % name)
    if isinstance(value, str):
        raise invalid("'%s' must be a number" % name)
    try:
        number = Decimal(repr(value)) if isinstance(value, float) else Decimal(value)
    except (InvalidOperation, ValueError):
        raise invalid("'%s' must be a number" % name)
    if minimum is not None and number < minimum:
        raise invalid("'%s' must be >= %s" % (name, minimum))
    if exclusive_minimum is not None and number <= exclusive_minimum:
        raise invalid("'%s' must be > %s" % (name, exclusive_minimum))
    if max_decimals is not None:
        exponent = number.normalize().as_tuple().exponent
        if isinstance(exponent, int) and exponent < -max_decimals:
            raise invalid("'%s' may carry at most %d decimal places" % (name, max_decimals))
    return number


def req_bool(data, name):
    value = data.get(name, _SENTINEL)
    if value is _SENTINEL or value is None:
        raise invalid("'%s' is required" % name)
    if not isinstance(value, bool):
        raise invalid("'%s' must be a boolean" % name)
    return value


def opt_bool(data, name, default=None):
    value = data.get(name, _SENTINEL)
    if value is _SENTINEL or value is None:
        return default
    if not isinstance(value, bool):
        raise invalid("'%s' must be a boolean" % name)
    return value


def req_enum(data, name, members):
    value = req_string(data, name)
    if value not in members:
        raise invalid("'%s' must be one of %s" % (name, ", ".join(members)))
    return value


def opt_enum(data, name, members, default=None):
    value = data.get(name, _SENTINEL)
    if value is _SENTINEL or value is None:
        return default
    if not isinstance(value, str):
        raise invalid("'%s' must be a string" % name)
    if value not in members:
        raise invalid("'%s' must be one of %s" % (name, ", ".join(members)))
    return value


def req_dt(data, name):
    value = data.get(name, _SENTINEL)
    if value is _SENTINEL or value is None:
        raise invalid("'%s' is required" % name)
    parsed = parse_dt(value)
    if parsed is None:
        raise invalid("'%s' must be an ISO 8601 instant" % name)
    return parsed


def opt_dt(data, name, default=None):
    value = data.get(name, _SENTINEL)
    if value is _SENTINEL or value is None:
        return default
    parsed = parse_dt(value)
    if parsed is None:
        raise invalid("'%s' must be an ISO 8601 instant" % name)
    return parsed


def req_enum_array(data, name, members, distinct=True):
    value = data.get(name, _SENTINEL)
    if value is _SENTINEL or value is None:
        raise invalid("'%s' is required" % name)
    if not isinstance(value, list):
        raise invalid("'%s' must be an array" % name)
    if len(value) == 0:
        raise invalid("'%s' may not be empty" % name)
    for member in value:
        if not isinstance(member, str) or member not in members:
            raise invalid("'%s' members must be one of %s" % (name, ", ".join(members)))
    if distinct and len(set(value)) != len(value):
        raise invalid("'%s' may not contain duplicate members" % name)
    return list(value)


def enum_filter(args, name, members):
    """Query-string filter value; unknown members simply match nothing."""
    value = args.get(name)
    if value is None or value == "":
        return None
    return value


def bool_filter(args, name):
    value = args.get(name)
    if value is None or value == "":
        return None
    lowered = str(value).strip().lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    return None
