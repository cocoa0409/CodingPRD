"""Header-based authentication, RBAC and request-input validation helpers."""
from flask import request

import store
from errors import ApiError

ROLES = {
    "AftermarketPlanner",
    "InventoryController",
    "DealerUser",
    "PricingAnalyst",
    "PlatformAdmin",
}

ALL_ROLES = sorted(ROLES)


def authenticate():
    """Validation priority 1 — both headers present, role spelled exactly."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    if not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    return user_id, role


def require(*allowed_roles):
    """Validation priorities 1 then 2. Returns (user_id, role)."""
    user_id, role = authenticate()
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return user_id, role


def dealer_scope(role, user_id, dealer_id):
    """Validation priority 3 — a DealerUser may act only on its own resources."""
    if role == "DealerUser" and dealer_id is not None and dealer_id != user_id:
        raise ApiError("ERR_DEALER_SCOPE_VIOLATION")


# ------------------------------------------------------------- body input --
def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def _bad(field, why):
    raise ApiError("ERR_INVALID_REQUEST", "%s %s" % (field, why))


def req_int(data, field, minimum=None, maximum=None):
    if field not in data or data[field] is None:
        _bad(field, "is required.")
    return _as_int(data[field], field, minimum, maximum)


def opt_int(data, field, default=None, minimum=None, maximum=None):
    if field not in data or data[field] is None:
        return default
    return _as_int(data[field], field, minimum, maximum)


def _as_int(value, field, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(field, "must be an integer.")
    if minimum is not None and value < minimum:
        _bad(field, "must be >= %s." % minimum)
    if maximum is not None and value > maximum:
        _bad(field, "must be <= %s." % maximum)
    return value


def req_number(data, field, minimum=None, maximum=None, exclusive_min=None, exclusive_max=None):
    if field not in data or data[field] is None:
        _bad(field, "is required.")
    return _as_number(data[field], field, minimum, maximum, exclusive_min, exclusive_max)


def opt_number(data, field, default=None, minimum=None, maximum=None,
               exclusive_min=None, exclusive_max=None):
    if field not in data or data[field] is None:
        return default
    return _as_number(data[field], field, minimum, maximum, exclusive_min, exclusive_max)


def _as_number(value, field, minimum, maximum, exclusive_min, exclusive_max):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(field, "must be a number.")
    if minimum is not None and value < minimum:
        _bad(field, "must be >= %s." % minimum)
    if maximum is not None and value > maximum:
        _bad(field, "must be <= %s." % maximum)
    if exclusive_min is not None and value <= exclusive_min:
        _bad(field, "must be > %s." % exclusive_min)
    if exclusive_max is not None and value >= exclusive_max:
        _bad(field, "must be < %s." % exclusive_max)
    return value


def req_str(data, field):
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        _bad(field, "is required and must be a non-empty string.")
    return value


def opt_str(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    value = data[field]
    if not isinstance(value, str):
        _bad(field, "must be a string.")
    return value


def req_enum(data, field, members):
    value = data.get(field)
    if not isinstance(value, str) or value not in members:
        _bad(field, "must be one of %s." % ", ".join(sorted(members)))
    return value


def opt_enum(data, field, members, default=None):
    if field not in data or data[field] is None:
        return default
    return req_enum(data, field, members)


def req_bool(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    value = data[field]
    if not isinstance(value, bool):
        _bad(field, "must be a boolean.")
    return value


def req_datetime(data, field):
    value = data.get(field)
    parsed = store.parse_iso(value) if isinstance(value, str) else None
    if parsed is None:
        _bad(field, "must be an ISO 8601 UTC instant.")
    return parsed


def req_id(data, field):
    value = data.get(field)
    if value is None:
        _bad(field, "is required.")
    if not isinstance(value, str) or not value.strip():
        _bad(field, "must be a string identifier.")
    return value


# ----------------------------------------------------------- query params --
def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            _bad("limit", "must be an integer between 1 and 100.")
        if limit < 1 or limit > 100:
            _bad("limit", "must be between 1 and 100.")
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            _bad("offset", "must be a non-negative integer.")
        if offset < 0:
            _bad("offset", "must not be negative.")
    return limit, offset


def query_enum(field, members):
    value = request.args.get(field)
    if value is None or value == "":
        return None
    if value not in members:
        _bad(field, "must be one of %s." % ", ".join(sorted(members)))
    return value


def query_str(field):
    value = request.args.get(field)
    if value is None or value == "":
        return None
    return value


def query_int(field):
    value = request.args.get(field)
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        _bad(field, "must be an integer.")


def query_bool(field):
    value = request.args.get(field)
    if value is None or value == "":
        return None
    low = value.lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    _bad(field, "must be a boolean.")


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total
