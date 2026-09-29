"""Request body / query parsing and rank-5 body-schema validation (PRD 2.5)."""

from decimal import Decimal

from flask import request

from db import parse_iso
from errors import ApiError
from response import (
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_DEFAULT_OFFSET,
    PAGINATION_MAX_LIMIT,
    PAGINATION_MIN_LIMIT,
)

MISSING = object()


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    """Parsed JSON object body; a missing body is treated as {}."""
    if not request.data:
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        bad("Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        bad("Request body must be a JSON object.")
    return parsed


def _present(payload, key):
    return key in payload and payload[key] is not None


def opt_string(payload, key, max_length=None, allow_empty=True):
    if not _present(payload, key):
        return None
    value = payload[key]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % key)
    if not allow_empty and value.strip() == "":
        bad("Field '%s' must be non-empty." % key)
    if max_length is not None and len(value) > max_length:
        bad("Field '%s' exceeds %d characters." % (key, max_length))
    return value


def req_string(payload, key, max_length=None, allow_empty=False):
    if not _present(payload, key):
        bad("Field '%s' is required." % key)
    return opt_string(payload, key, max_length=max_length, allow_empty=allow_empty)


def _check_int(key, value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be <= %s." % (key, maximum))
    return value


def opt_int(payload, key, minimum=None, maximum=None):
    if not _present(payload, key):
        return None
    return _check_int(key, payload[key], minimum, maximum)


def req_int(payload, key, minimum=None, maximum=None):
    if not _present(payload, key):
        bad("Field '%s' is required." % key)
    return _check_int(key, payload[key], minimum, maximum)


def _check_number(key, value, minimum, maximum, places):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("Field '%s' must be a number." % key)
    dec = Decimal(str(value))
    if minimum is not None and dec < Decimal(str(minimum)):
        bad("Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and dec > Decimal(str(maximum)):
        bad("Field '%s' must be <= %s." % (key, maximum))
    if places is not None:
        from calc import round_half_up

        dec = round_half_up(dec, places)
    return dec


def opt_number(payload, key, minimum=None, maximum=None, places=None):
    if not _present(payload, key):
        return None
    return _check_number(key, payload[key], minimum, maximum, places)


def req_number(payload, key, minimum=None, maximum=None, places=None):
    if not _present(payload, key):
        bad("Field '%s' is required." % key)
    return _check_number(key, payload[key], minimum, maximum, places)


def opt_enum(payload, key, allowed):
    if not _present(payload, key):
        return None
    value = payload[key]
    if not isinstance(value, str) or value not in allowed:
        bad("Field '%s' must be one of %s." % (key, ", ".join(sorted(allowed))))
    return value


def req_enum(payload, key, allowed):
    if not _present(payload, key):
        bad("Field '%s' is required." % key)
    return opt_enum(payload, key, allowed)


def opt_bool(payload, key, default=None):
    if not _present(payload, key):
        return default
    value = payload[key]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % key)
    return value


def opt_datetime(payload, key):
    if not _present(payload, key):
        return None
    raw = payload[key]
    if not isinstance(raw, str):
        bad("Field '%s' must be an ISO 8601 timestamp string." % key)
    parsed = parse_iso(raw)
    if parsed is None:
        bad("Field '%s' must be an ISO 8601 timestamp string." % key)
    return raw, parsed


def req_datetime(payload, key):
    if not _present(payload, key):
        bad("Field '%s' is required." % key)
    return opt_datetime(payload, key)


def pagination():
    args = request.args
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            bad("Query parameter 'limit' must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            bad(
                "Query parameter 'limit' must be between %d and %d."
                % (PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT)
            )
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            bad("Query parameter 'offset' must be an integer.")
        if offset < 0:
            bad("Query parameter 'offset' must be >= 0.")
    return limit, offset


def query_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in allowed:
        bad("Query parameter '%s' must be one of %s." % (name, ", ".join(sorted(allowed))))
    return raw


def query_string(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def query_bool(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    lowered = raw.lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    bad("Query parameter '%s' must be a boolean." % name)
