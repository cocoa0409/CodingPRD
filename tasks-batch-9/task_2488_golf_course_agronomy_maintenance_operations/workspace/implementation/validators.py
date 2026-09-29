"""Transport band: auth (priority 1-2) and request shape (priority 3)."""

import json
from decimal import Decimal, InvalidOperation
from functools import wraps

from flask import g, request

from errors import ApiError
from util import dec, is_uuid, parse_date, parse_dt

ROLES = (
    "Superintendent",
    "Agronomist",
    "Applicator",
    "TournamentOfficial",
    "EquipmentTechnician",
)

_MISSING = object()


# --------------------------------------------------------------------------
# priority 1 / 2 -- authentication and authorization
# --------------------------------------------------------------------------
def endpoint(roles, need_user_id=False):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role = request.headers.get("X-User-Role")
            user_id = request.headers.get("X-User-ID")
            if role is None or role not in ROLES:
                raise ApiError("ERR_UNAUTHENTICATED")
            if need_user_id and not user_id:
                raise ApiError("ERR_UNAUTHENTICATED")
            if role not in roles:
                raise ApiError("ERR_UNAUTHORIZED")
            g.role = role
            g.user_id = user_id
            return fn(*args, **kwargs)

        return wrapper

    return decorator


# --------------------------------------------------------------------------
# priority 3 -- request shape
# --------------------------------------------------------------------------
def bad(message="The request payload is malformed or violates a field constraint."):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    try:
        parsed = json.loads(raw.decode("utf-8"), parse_float=Decimal)
    except Exception:
        bad("Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        bad("Request body must be a JSON object.")
    return parsed


def _present(payload, key):
    return key in payload and payload[key] is not None


def _require(payload, key):
    if key not in payload:
        bad("Missing required field '%s'." % key)
    if payload[key] is None:
        bad("Field '%s' may not be null." % key)
    return payload[key]


def path_uuid(value, error_id):
    """Priority 3 covers well-formedness of every id; existence comes later."""
    if not is_uuid(value):
        raise ApiError("ERR_INVALID_REQUEST", "'%s' is not a well-formed UUID." % value)
    return value


def field_str(payload, key, required=True, default=None, max_len=None, allow_empty=False,
              pattern=None):
    if not _present(payload, key):
        if required:
            _require(payload, key)
        return default
    value = payload[key]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % key)
    if not allow_empty and value.strip() == "":
        bad("Field '%s' may not be empty." % key)
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' exceeds %d characters." % (key, max_len))
    if pattern is not None and not pattern.match(value):
        bad("Field '%s' is malformed." % key)
    return value


def field_uuid(payload, key, required=True, default=None):
    if not _present(payload, key):
        if required:
            _require(payload, key)
        return default
    value = payload[key]
    if not isinstance(value, str) or not is_uuid(value):
        bad("Field '%s' must be a well-formed UUID." % key)
    return value


def field_enum(payload, key, allowed, required=True, default=None):
    if not _present(payload, key):
        if required:
            _require(payload, key)
        return default
    value = payload[key]
    if not isinstance(value, str) or value not in allowed:
        bad("Field '%s' must be one of %s." % (key, ", ".join(allowed)))
    return value


def field_bool(payload, key, required=True, default=None):
    if not _present(payload, key):
        if required:
            _require(payload, key)
        return default
    value = payload[key]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % key)
    return value


def field_int(payload, key, required=True, default=None, minimum=None, maximum=None,
              exclusive_min=None, exclusive_max=None):
    if not _present(payload, key):
        if required:
            _require(payload, key)
        return default
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer." % key)
    _range_check(key, Decimal(value), minimum, maximum, exclusive_min, exclusive_max)
    return value


def field_num(payload, key, required=True, default=None, minimum=None, maximum=None,
              exclusive_min=None, exclusive_max=None):
    if not _present(payload, key):
        if required:
            _require(payload, key)
        return default
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        bad("Field '%s' must be a number." % key)
    try:
        value = dec(value)
    except (InvalidOperation, ValueError):
        bad("Field '%s' must be a number." % key)
    if not value.is_finite():
        bad("Field '%s' must be a finite number." % key)
    _range_check(key, value, minimum, maximum, exclusive_min, exclusive_max)
    return value


def _range_check(key, value, minimum, maximum, exclusive_min, exclusive_max):
    if minimum is not None and value < dec(minimum):
        bad("Field '%s' is below its minimum." % key)
    if maximum is not None and value > dec(maximum):
        bad("Field '%s' is above its maximum." % key)
    if exclusive_min is not None and value <= dec(exclusive_min):
        bad("Field '%s' is below its exclusive minimum." % key)
    if exclusive_max is not None and value >= dec(exclusive_max):
        bad("Field '%s' is above its exclusive maximum." % key)


def field_dt(payload, key, required=True, default=None):
    if not _present(payload, key):
        if required:
            _require(payload, key)
        return default
    parsed = parse_dt(payload[key])
    if parsed is None:
        bad("Field '%s' must be an ISO 8601 instant." % key)
    return parsed


def field_date(payload, key, required=True, default=None):
    if not _present(payload, key):
        if required:
            _require(payload, key)
        return default
    parsed = parse_date(payload[key])
    if parsed is None:
        bad("Field '%s' must be an ISO 8601 calendar date (YYYY-MM-DD)." % key)
    return parsed


def field_uuid_list(payload, key, required=True, default=None):
    if key not in payload or payload[key] is None:
        if required:
            _require(payload, key)
        return default
    value = payload[key]
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % key)
    for item in value:
        if not isinstance(item, str) or not is_uuid(item):
            bad("Field '%s' must contain well-formed UUIDs." % key)
    return value


# --------------------------------------------------------------------------
# pagination + query filters (priority 3)
# --------------------------------------------------------------------------
def pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            bad("'limit' must be an integer.")
        if limit < 1 or limit > 100:
            bad("'limit' must be between 1 and 100.")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            bad("'offset' must be an integer.")
        if offset < 0:
            bad("'offset' must be at least 0.")
    return limit, offset


def query_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in allowed:
        bad("Query parameter '%s' must be one of %s." % (name, ", ".join(allowed)))
    return raw


def query_str(name):
    return request.args.get(name)


def query_uuid(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    if not is_uuid(raw):
        bad("Query parameter '%s' must be a well-formed UUID." % name)
    return raw


def query_int(name, minimum=None, maximum=None):
    raw = request.args.get(name)
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        bad("Query parameter '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        bad("Query parameter '%s' is below its minimum." % name)
    if maximum is not None and value > maximum:
        bad("Query parameter '%s' is above its maximum." % name)
    return value


def query_bool(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    lowered = raw.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    bad("Query parameter '%s' must be a boolean." % name)


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
