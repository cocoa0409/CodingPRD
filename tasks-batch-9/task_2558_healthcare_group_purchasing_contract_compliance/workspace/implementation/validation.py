"""Request-shape validation helpers (PRD section 2.9 rung 6)."""

from decimal import Decimal, InvalidOperation

from flask import request

import db as dbmod
from errors import ApiError

MISSING = object()


def bad(message):
    return ApiError("ERR_INVALID_REQUEST", message)


def body_json():
    """Parse the JSON body. An absent body is treated as an empty object."""
    payload = request.get_json(silent=True)
    if payload is None:
        raw = request.get_data() or b""
        if raw.strip():
            raise bad("Request body is not valid JSON.")
        return {}
    if not isinstance(payload, dict):
        raise bad("Request body must be a JSON object.")
    return payload


def _present(body, key):
    return isinstance(body, dict) and key in body and body[key] is not None


def field_string(body, key, min_len=1, max_len=None, required=True, default=MISSING):
    if not _present(body, key):
        if required:
            raise bad("Field '%s' is required." % key)
        return None if default is MISSING else default
    value = body[key]
    if not isinstance(value, str):
        raise bad("Field '%s' must be a string." % key)
    if min_len is not None and len(value) < min_len:
        raise bad("Field '%s' must be at least %d characters." % (key, min_len))
    if max_len is not None and len(value) > max_len:
        raise bad("Field '%s' must be at most %d characters." % (key, max_len))
    return value


def field_int(body, key, minimum=None, maximum=None, required=True, default=MISSING):
    if not _present(body, key):
        if required:
            raise bad("Field '%s' is required." % key)
        return None if default is MISSING else default
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad("Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        raise bad("Field '%s' must be at least %d." % (key, minimum))
    if maximum is not None and value > maximum:
        raise bad("Field '%s' must be at most %d." % (key, maximum))
    return value


def field_bool(body, key, required=False, default=MISSING):
    if not _present(body, key):
        if required:
            raise bad("Field '%s' is required." % key)
        return None if default is MISSING else default
    value = body[key]
    if not isinstance(value, bool):
        raise bad("Field '%s' must be a boolean." % key)
    return value


def field_enum(body, key, allowed, required=True, default=MISSING):
    if not _present(body, key):
        if required:
            raise bad("Field '%s' is required." % key)
        return None if default is MISSING else default
    value = body[key]
    if not isinstance(value, str) or value not in allowed:
        raise bad("Field '%s' must be one of %s." % (key, ", ".join(allowed)))
    return value


def to_decimal(value, key):
    if isinstance(value, bool):
        raise bad("Field '%s' must be a number." % key)
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    if isinstance(value, str):
        try:
            return Decimal(value.strip())
        except (InvalidOperation, ValueError):
            raise bad("Field '%s' must be a number." % key)
    raise bad("Field '%s' must be a number." % key)


def field_decimal(
    body, key, minimum=None, maximum=None, scale=2, required=True, default=MISSING
):
    if not _present(body, key):
        if required:
            raise bad("Field '%s' is required." % key)
        return None if default is MISSING else default
    value = to_decimal(body[key], key)
    if not value.is_finite():
        raise bad("Field '%s' must be a finite number." % key)
    exponent = value.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -scale:
        raise bad("Field '%s' carries at most %d decimal places." % (key, scale))
    if minimum is not None and value < minimum:
        raise bad("Field '%s' must be at least %s." % (key, minimum))
    if maximum is not None and value > maximum:
        raise bad("Field '%s' must be at most %s." % (key, maximum))
    return value.quantize(Decimal(1).scaleb(-scale))


def field_date(body, key, required=True, default=MISSING):
    if not _present(body, key):
        if required:
            raise bad("Field '%s' is required." % key)
        return None if default is MISSING else default
    parsed = dbmod.parse_date(body[key])
    if parsed is None:
        raise bad("Field '%s' must be an ISO 8601 calendar date (YYYY-MM-DD)." % key)
    return parsed


def field_timestamp(body, key, required=True):
    if not _present(body, key):
        if required:
            raise bad("Field '%s' is required." % key)
        return None, None
    raw = body[key]
    parsed = dbmod.parse_timestamp(raw)
    if parsed is None:
        raise bad("Field '%s' must be an ISO 8601 UTC timestamp." % key)
    return raw, parsed


def field_list(body, key, min_len=1, max_len=None, required=True):
    if not _present(body, key):
        if required:
            raise bad("Field '%s' is required." % key)
        return None
    value = body[key]
    if not isinstance(value, list):
        raise bad("Field '%s' must be an array." % key)
    if min_len is not None and len(value) < min_len:
        raise bad("Field '%s' must carry at least %d entries." % (key, min_len))
    if max_len is not None and len(value) > max_len:
        raise bad("Field '%s' must carry at most %d entries." % (key, max_len))
    return value


# -- query string ------------------------------------------------------------

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _query_int(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise bad("Query parameter '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        raise bad("Query parameter '%s' must be at least %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise bad("Query parameter '%s' must be at most %d." % (name, maximum))
    return value


def pagination():
    limit = _query_int(
        "limit", PAGINATION_DEFAULT_LIMIT, PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT
    )
    offset = _query_int("offset", PAGINATION_DEFAULT_OFFSET, 0, None)
    return limit, offset


def query_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in allowed:
        raise bad("Query parameter '%s' must be one of %s." % (name, ", ".join(allowed)))
    return raw


def query_string(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def query_date(name, required=True):
    raw = request.args.get(name)
    if raw is None or raw == "":
        if required:
            raise bad("Query parameter '%s' is required." % name)
        return None
    parsed = dbmod.parse_date(raw)
    if parsed is None:
        raise bad("Query parameter '%s' must be an ISO 8601 date (YYYY-MM-DD)." % name)
    return parsed


def paginate(rows, limit, offset):
    return rows[offset : offset + limit], len(rows)
