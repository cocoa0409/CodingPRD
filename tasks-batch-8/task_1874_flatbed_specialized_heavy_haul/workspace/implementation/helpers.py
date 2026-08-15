"""Response envelope, error type, auth header checks, and body validators.
All structural names (headers, envelope fields, error ids, pagination params)
come straight from SCAFFOLD.yaml / PRD.md — nothing assumed."""
import random
import string
from datetime import datetime, timezone

from flask import request, jsonify

from store import now_iso

ROLES = (
    "PlatformAdmin", "Shipper", "Dispatcher", "PermitClerk",
    "StateAuthority", "SafetyManager", "Driver", "BillingClerk",
)

# Error id constants (SCAFFOLD 1.6 / PRD 5)
ERR_AUTH = "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER"
ERR_FORBIDDEN = "ERR_FORBIDDEN"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_NOT_OWN = "ERR_NOT_OWN_RESOURCE"
ERR_STALE = "ERR_STALE_LOAD_VERSION"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_CUSTOMER_SUSPENDED = "ERR_CUSTOMER_SUSPENDED"
ERR_LOAD_INVALID_STATE = "ERR_LOAD_INVALID_STATE"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_LOAD_NOT_CANCELLABLE = "ERR_LOAD_NOT_CANCELLABLE"
ERR_PERMIT_REQ_UNMET = "ERR_PERMIT_REQUIREMENT_UNMET"
ERR_FINE_NOT_DISPUTABLE = "ERR_FINE_NOT_DISPUTABLE"
ERR_INVOICE_NOT_ISSUED = "ERR_INVOICE_NOT_ISSUED"
ERR_REINSTATE_NOT_ALLOWED = "ERR_REINSTATE_NOT_ALLOWED"
ERR_TRAILER_CAPACITY = "ERR_TRAILER_CAPACITY_EXCEEDED"
ERR_AXLE_COUNT = "ERR_AXLE_COUNT_INSUFFICIENT"
ERR_DRIVER_NOT_ENDORSED = "ERR_DRIVER_NOT_ENDORSED"
ERR_WLL = "ERR_SECUREMENT_WLL_INSUFFICIENT"
ERR_TARP = "ERR_TARPING_REQUIRED"
ERR_ESCORT_UNMET = "ERR_ESCORT_REQUIREMENT_UNMET"
ERR_OUTSIDE_WINDOW = "ERR_OUTSIDE_TRAVEL_WINDOW"
ERR_CURFEW = "ERR_CURFEW_VIOLATION"
ERR_ESCORT_OVERLAP = "ERR_ESCORT_WINDOW_OVERLAP"
ERR_CRANE_OVERLAP = "ERR_CRANE_WINDOW_OVERLAP"
ERR_PERMIT_TYPE = "ERR_PERMIT_TYPE_NOT_REQUIRED"
ERR_DUPLICATE_PERMIT = "ERR_DUPLICATE_PERMIT"
ERR_FINE_KIND = "ERR_FINE_KIND_NOT_MANUAL"
ERR_INVOICE_EXISTS = "ERR_INVOICE_EXISTS"
ERR_CREDIT = "ERR_CREDIT_LIMIT_EXCEEDED"


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def api_error(error_id, http_status, message):
    raise ApiError(error_id, message, http_status)


def new_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=24))


def meta():
    return {"api_request_id": new_request_id(), "api_request_timestamp": now_iso()}


def ok(data, code=200):
    return jsonify({"meta": meta(), "response_type": "object", "data": data}), code


def ok_list(items, limit, offset, total_count):
    m = meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total_count
    m["has_more"] = (offset + len(items)) < total_count
    return jsonify({"meta": m, "response_type": "array", "data": items}), 200


def error_payload(error_id, message):
    return {"meta": meta(), "response_type": "error",
            "data": {"error_id": error_id, "message": message}}


# ---------------------------------------------------------------------------
# Auth (validation priorities 1 and 2)
# ---------------------------------------------------------------------------

def current_auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        api_error(ERR_AUTH, 400,
                  "X-User-ID / X-User-Role headers missing or role not recognized")
    return uid, role


def require_roles(*roles):
    uid, role = current_auth()
    if role not in roles:
        api_error(ERR_FORBIDDEN, 403, "Role is not permitted on this endpoint")
    return uid, role


# ---------------------------------------------------------------------------
# Body parsing and field validators (validation priority 6)
# ---------------------------------------------------------------------------

def json_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        api_error(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return data


def parse_dt(value):
    """Parse an ISO 8601 datetime; returns an aware UTC datetime or None."""
    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip()
    if s[-1] in ("Z", "z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def v_str(data, name, required=True, default=None):
    if name not in data or data[name] is None:
        if required:
            api_error(ERR_INVALID_REQUEST, 400, f"Missing required field: {name}")
        return default
    v = data[name]
    if not isinstance(v, str) or len(v) == 0:
        api_error(ERR_INVALID_REQUEST, 400, f"Field {name} must be a non-empty string")
    return v


def v_int(data, name, required=True, min_value=None, default=None):
    if name not in data or data[name] is None:
        if required:
            api_error(ERR_INVALID_REQUEST, 400, f"Missing required field: {name}")
        return default
    v = data[name]
    if isinstance(v, bool) or not isinstance(v, int):
        api_error(ERR_INVALID_REQUEST, 400, f"Field {name} must be an integer")
    if min_value is not None and v < min_value:
        api_error(ERR_INVALID_REQUEST, 400,
                  f"Field {name} must be >= {min_value}")
    return v


def v_bool(data, name, required=True, default=None):
    if name not in data or data[name] is None:
        if required:
            api_error(ERR_INVALID_REQUEST, 400, f"Missing required field: {name}")
        return default
    v = data[name]
    if not isinstance(v, bool):
        api_error(ERR_INVALID_REQUEST, 400, f"Field {name} must be a boolean")
    return v


def v_enum(data, name, allowed, required=True):
    v = v_str(data, name, required=required)
    if v is None:
        return None
    if v not in allowed:
        api_error(ERR_INVALID_REQUEST, 400,
                  f"Field {name} must be one of {sorted(allowed)}")
    return v


def v_dt(data, name, required=True):
    """Returns (raw_string, parsed_datetime)."""
    raw = v_str(data, name, required=required)
    if raw is None:
        return None, None
    dt = parse_dt(raw)
    if dt is None:
        api_error(ERR_INVALID_REQUEST, 400,
                  f"Field {name} must be a valid ISO 8601 datetime")
    return raw, dt


def v_state_list(data, name, allowed):
    v = data.get(name)
    if not isinstance(v, list) or len(v) == 0:
        api_error(ERR_INVALID_REQUEST, 400,
                  f"Field {name} must be a non-empty list")
    for item in v:
        if not isinstance(item, str) or item not in allowed:
            api_error(ERR_INVALID_REQUEST, 400,
                      f"Field {name} entries must be drawn from {sorted(allowed)}")
    return list(v)


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3): limit/offset, defaults 10/0, limit in [1, 100]
# ---------------------------------------------------------------------------

def pagination_params():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            api_error(ERR_INVALID_REQUEST, 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            api_error(ERR_INVALID_REQUEST, 400, "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            api_error(ERR_INVALID_REQUEST, 400, "offset must be an integer")
        if offset < 0:
            api_error(ERR_INVALID_REQUEST, 400, "offset must be >= 0")
    return limit, offset


def pub(rec):
    """Public view of a stored record: strip internal underscore keys."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def paginate(records, limit, offset):
    """Sort by creation ascending, slice, and strip internal keys."""
    ordered = sorted(records, key=lambda r: r["_seq"])
    total = len(ordered)
    page = [pub(r) for r in ordered[offset:offset + limit]]
    return page, total
