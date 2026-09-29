"""Request-shape helpers — rejection band 3 (PRD section 2.6)."""

from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError

_MISSING = object()


def body_json():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", "request body must be a JSON object")
    return data


def present(body, field):
    return field in body and body[field] is not None


def require(body, *fields):
    for field in fields:
        if not present(body, field):
            raise ApiError("ERR_VALIDATION", "%s is required" % field)


def get_str(body, field, required=True, min_len=1, max_len=None, default=None):
    if not present(body, field):
        if required:
            raise ApiError("ERR_VALIDATION", "%s is required" % field)
        return default
    value = body[field]
    if not isinstance(value, str):
        raise ApiError("ERR_VALIDATION", "%s must be a string" % field)
    if len(value) < min_len:
        raise ApiError("ERR_VALIDATION", "%s must be at least %d characters" % (field, min_len))
    if max_len is not None and len(value) > max_len:
        raise ApiError("ERR_VALIDATION", "%s must be at most %d characters" % (field, max_len))
    return value


def get_int(body, field, required=True, minimum=None, maximum=None, default=None):
    if not present(body, field):
        if required:
            raise ApiError("ERR_VALIDATION", "%s is required" % field)
        return default
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_VALIDATION", "%s must be an integer" % field)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_VALIDATION", "%s must be >= %s" % (field, minimum))
    if maximum is not None and value > maximum:
        raise ApiError("ERR_VALIDATION", "%s must be <= %s" % (field, maximum))
    return value


def get_bool(body, field, required=True, default=None):
    if not present(body, field):
        if required:
            raise ApiError("ERR_VALIDATION", "%s is required" % field)
        return default
    value = body[field]
    if not isinstance(value, bool):
        raise ApiError("ERR_VALIDATION", "%s must be a boolean" % field)
    return value


def get_number(body, field, required=True, minimum=None, maximum=None, default=None,
               error_id="ERR_VALIDATION"):
    if not present(body, field):
        if required:
            raise ApiError("ERR_VALIDATION", "%s is required" % field)
        return default
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(error_id, "%s must be a number" % field)
    if minimum is not None and value < minimum:
        raise ApiError(error_id, "%s is out of range" % field)
    if maximum is not None and value > maximum:
        raise ApiError(error_id, "%s is out of range" % field)
    return value


def decimal_places(value):
    try:
        dec = Decimal(str(value))
    except InvalidOperation:
        return None
    exponent = dec.as_tuple().exponent
    if not isinstance(exponent, int):
        return None
    return max(0, -exponent)


def get_enum(body, field, allowed, required=True, default=None):
    if not present(body, field):
        if required:
            raise ApiError("ERR_VALIDATION", "%s is required" % field)
        return default
    value = body[field]
    if not isinstance(value, str) or value not in allowed:
        raise ApiError(
            "ERR_VALIDATION",
            "%s must be one of %s" % (field, ", ".join(allowed)),
        )
    return value


def get_id(body, field, required=True):
    """Foreign-key style string, validated only for shape."""
    if not present(body, field):
        if required:
            return None
        return None
    value = body[field]
    if not isinstance(value, str) or not value:
        return None
    return value


# --------------------------------------------------------------------------
# Pagination (PRD section 2.3)
# --------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def pagination():
    args = request.args
    limit = DEFAULT_LIMIT
    offset = DEFAULT_OFFSET

    raw = args.get("limit")
    if raw is not None and raw != "":
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "limit must be an integer")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise ApiError(
                "ERR_VALIDATION",
                "limit must be between %d and %d" % (MIN_LIMIT, MAX_LIMIT),
            )

    raw = args.get("offset")
    if raw is not None and raw != "":
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", "offset must be non-negative")

    return limit, offset


def query_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def query_bool(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    lowered = raw.lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    # An unresolvable filter value yields an empty page, never a 4xx.
    return "__unresolvable__"
