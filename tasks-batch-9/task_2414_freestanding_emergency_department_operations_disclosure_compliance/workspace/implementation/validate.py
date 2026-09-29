"""Authentication / authorisation (ladder steps 1-2) and request-shape
validation (ladder step 3). Everything here raises ApiError."""

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_HALF_UP

from flask import request

from constants import (
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_DEFAULT_OFFSET,
    PAGINATION_MAX_LIMIT,
    PAGINATION_MIN_LIMIT,
    ROLES,
)
from errors import ApiError

UTC = timezone.utc

_ONE = Decimal(1)
_CENT = Decimal("0.01")


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


# --- rounding ------------------------------------------------------------


def rh(value):
    """round_half_up to whole cents -> int."""
    return int(Decimal(value).quantize(_ONE, rounding=ROUND_HALF_UP))


def rh2(value):
    """round_half_up to two decimals -> Decimal."""
    return Decimal(value).quantize(_CENT, rounding=ROUND_HALF_UP)


def quarter_ceiling(value):
    """Raise to the next whole quarter unit."""
    scaled = Decimal(value) * 4
    return scaled.to_integral_value(rounding=ROUND_CEILING) / Decimal(4)


def num(value):
    """Serialise a Decimal hour/rate figure for JSON."""
    if value is None:
        return None
    return float(value)


# --- auth ----------------------------------------------------------------


def auth(*allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if allowed_roles and role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return user_id, role


# --- body ----------------------------------------------------------------


def body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        bad("Request body must be a JSON object")
    if not isinstance(payload, dict):
        bad("Request body must be a JSON object")
    return payload


def present(data, field):
    return field in data and data[field] is not None


def req_str(data, field, min_len=1, max_len=None, required=True, default=None):
    if not present(data, field):
        if required:
            bad("Field '%s' is required" % field)
        return default
    value = data[field]
    if not isinstance(value, str):
        bad("Field '%s' must be a string" % field)
    if min_len is not None and len(value.strip()) < min_len:
        bad("Field '%s' must be at least %d characters" % (field, min_len))
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' must be at most %d characters" % (field, max_len))
    return value


def req_int(data, field, minimum=None, maximum=None, required=True, default=None):
    if not present(data, field):
        if required:
            bad("Field '%s' is required" % field)
        return default
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer" % field)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be >= %s" % (field, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be <= %s" % (field, maximum))
    return value


def req_bool(data, field, required=True, default=None):
    if not present(data, field):
        if required:
            bad("Field '%s' is required" % field)
        return default
    value = data[field]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean" % field)
    return value


def req_enum(data, field, allowed, required=True, default=None):
    if not present(data, field):
        if required:
            bad("Field '%s' is required" % field)
        return default
    value = data[field]
    if not isinstance(value, str) or value not in allowed:
        bad("Field '%s' must be one of %s" % (field, ", ".join(allowed)))
    return value


def req_enum_array(data, field, allowed, required=True, default=None):
    if not present(data, field):
        if required:
            bad("Field '%s' is required" % field)
        return list(default) if default is not None else default
    value = data[field]
    if not isinstance(value, list):
        bad("Field '%s' must be an array" % field)
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            bad("Field '%s' may only contain %s" % (field, ", ".join(allowed)))
    return value


def req_int_array(data, field, minimum=0, max_items=None, required=True):
    if not present(data, field):
        if required:
            bad("Field '%s' is required" % field)
        return []
    value = data[field]
    if not isinstance(value, list):
        bad("Field '%s' must be an array" % field)
    if max_items is not None and len(value) > max_items:
        bad("Field '%s' may hold at most %d elements" % (field, max_items))
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            bad("Every element of '%s' must be an integer" % field)
        if minimum is not None and item < minimum:
            bad("Every element of '%s' must be >= %s" % (field, minimum))
    return value


def req_rate(data, field, required=True):
    if not present(data, field):
        if required:
            bad("Field '%s' is required" % field)
        return None
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("Field '%s' must be a number" % field)
    try:
        dec = Decimal(str(value))
    except InvalidOperation:
        bad("Field '%s' must be a number" % field)
    if dec < 0 or dec > 1:
        bad("Field '%s' must lie between 0 and 1 inclusive" % field)
    if -dec.as_tuple().exponent > 4:
        bad("Field '%s' may carry at most four decimal places" % field)
    return dec


def parse_date_str(value, field):
    if not isinstance(value, str):
        bad("Field '%s' must be a YYYY-MM-DD date string" % field)
    try:
        parsed = datetime.strptime(value.strip(), "%Y-%m-%d")
    except ValueError:
        bad("Field '%s' must be a YYYY-MM-DD date string" % field)
    return date(parsed.year, parsed.month, parsed.day)


def req_date(data, field, required=True):
    if not present(data, field):
        if required:
            bad("Field '%s' is required" % field)
        return None
    parse_date_str(data[field], field)
    return data[field].strip()


def parse_dt_str(value, field):
    if not isinstance(value, str):
        bad("Field '%s' must be an ISO 8601 datetime" % field)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        bad("Field '%s' must be an ISO 8601 datetime" % field)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def req_datetime(data, field, required=True):
    if not present(data, field):
        if required:
            bad("Field '%s' is required" % field)
        return None
    return parse_dt_str(data[field], field)


# --- query parameters ----------------------------------------------------


def query_int(name, default, minimum=None, maximum=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw.strip())
    except (TypeError, ValueError):
        bad("Query parameter '%s' must be an integer" % name)
    if minimum is not None and value < minimum:
        bad("Query parameter '%s' must be >= %s" % (name, minimum))
    if maximum is not None and value > maximum:
        bad("Query parameter '%s' must be <= %s" % (name, maximum))
    return value


def pagination():
    limit = query_int(
        "limit", PAGINATION_DEFAULT_LIMIT, PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT
    )
    offset = query_int("offset", PAGINATION_DEFAULT_OFFSET, 0, None)
    return limit, offset


def query_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in allowed:
        bad("Query parameter '%s' must be one of %s" % (name, ", ".join(allowed)))
    return raw


def query_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw
