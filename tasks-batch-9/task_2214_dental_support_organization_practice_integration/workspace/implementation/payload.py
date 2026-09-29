"""Request body / query-string validation. Every failure is ERR_INVALID_REQUEST."""

import re

from flask import request

import clock
import config
from errors import invalid

_MISSING = object()
_INT_RE = re.compile(r"^[+-]?\d+$")


def body():
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    parsed = request.get_json(silent=True, force=True)
    if parsed is None:
        raise invalid("Request body must be a JSON object.")
    if not isinstance(parsed, dict):
        raise invalid("Request body must be a JSON object.")
    return parsed


def string(data, key, required=True, default=None, allow_empty=False):
    if key not in data or data.get(key) is None:
        if required:
            raise invalid("'%s' is required." % key)
        return default
    value = data[key]
    if not isinstance(value, str):
        raise invalid("'%s' must be a string." % key)
    if not allow_empty and not value.strip():
        raise invalid("'%s' must be a non-empty string." % key)
    return value


def integer(data, key, required=True, default=None, minimum=None, maximum=None):
    if key not in data or data.get(key) is None:
        if required:
            raise invalid("'%s' is required." % key)
        return default
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid("'%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        raise invalid("'%s' must be greater than or equal to %d." % (key, minimum))
    if maximum is not None and value > maximum:
        raise invalid("'%s' must be less than or equal to %d." % (key, maximum))
    return value


def boolean(data, key, required=False, default=None):
    if key not in data or data.get(key) is None:
        if required:
            raise invalid("'%s' is required." % key)
        return default
    value = data.get(key)
    if not isinstance(value, bool):
        raise invalid("'%s' must be a boolean." % key)
    return value


def enum(data, key, allowed, required=True, default=None):
    if key not in data or data.get(key) is None:
        if required:
            raise invalid("'%s' is required." % key)
        return default
    value = data.get(key)
    if not isinstance(value, str) or value not in allowed:
        raise invalid("'%s' must be one of: %s." % (key, ", ".join(allowed)))
    return value


def timestamp(data, key, required=True, default=None):
    if key not in data or data.get(key) is None:
        if required:
            raise invalid("'%s' is required." % key)
        return default
    return clock.parse_iso(data.get(key), key)


def int_list(data, key, length=None, minimum=None, required=True):
    if key not in data or data.get(key) is None:
        if required:
            raise invalid("'%s' is required." % key)
        return None
    value = data.get(key)
    if not isinstance(value, list):
        raise invalid("'%s' must be an array of integers." % key)
    if length is not None and len(value) != length:
        raise invalid("'%s' must contain exactly %d integers." % (key, length))
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            raise invalid("'%s' must contain only integers." % key)
        if minimum is not None and item < minimum:
            raise invalid("'%s' entries must be >= %d." % (key, minimum))
    return list(value)


def uppercase_code(data, key, size, required=True):
    value = string(data, key, required=required)
    if value is None:
        return None
    if len(value) != size or not value.isalpha() or value != value.upper():
        raise invalid(
            "'%s' must be exactly %d uppercase letters." % (key, size)
        )
    return value


def digits(data, key, size, required=True):
    value = string(data, key, required=required)
    if value is None:
        return None
    if len(value) != size or not value.isdigit():
        raise invalid("'%s' must be exactly %d digits." % (key, size))
    return value


def fk(data, key, required=True):
    """Return a candidate foreign key only when it is a usable string."""
    if key not in data or data.get(key) is None:
        return None
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        return None
    return value


# --------------------------------------------------------------------- queries


def _query_int(name, default, minimum=None, maximum=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    if not _INT_RE.match(raw.strip()):
        raise invalid("'%s' must be an integer." % name)
    value = int(raw.strip())
    if minimum is not None and value < minimum:
        raise invalid("'%s' must be >= %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise invalid("'%s' must be <= %d." % (name, maximum))
    return value


def pagination():
    limit = _query_int(
        "limit", config.PAGE_LIMIT_DEFAULT, config.PAGE_LIMIT_MIN, config.PAGE_LIMIT_MAX
    )
    offset = _query_int("offset", config.PAGE_OFFSET_DEFAULT, 0, None)
    return limit, offset


def paginate(rows):
    limit, offset = pagination()
    total = len(rows)
    page = rows[offset : offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, meta


def filter_value(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw
