"""Shared plumbing: errors, response envelope, auth, validation, datetimes."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify, request

from store import now

ALL_ROLES = ["FleetAdmin", "LoadPlanner", "Dispatcher", "SafetyOfficer",
             "PayrollClerk", "Driver"]

ERR_AUTH = "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER"
ERR_PERMS = "ERR_INSUFFICIENT_PERMISSIONS"
ERR_INVALID = "ERR_INVALID_REQUEST"
ERR_DRIVER_MISMATCH = "ERR_DRIVER_MISMATCH"
ERR_STALE = "ERR_STALE_VERSION"


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def iso(d):
    """ISO 8601 UTC with exactly three fractional digits."""
    d = d.astimezone(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def parse_dt(value, field):
    if not isinstance(value, str):
        raise ApiError(ERR_INVALID, 400, f"Field '{field}' must be an ISO 8601 datetime string")
    t = value.strip()
    if t.endswith(("Z", "z")):
        t = t[:-1] + "+00:00"
    try:
        d = datetime.fromisoformat(t)
    except ValueError:
        raise ApiError(ERR_INVALID, 400, f"Field '{field}' is not a valid ISO 8601 datetime")
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def serialize(obj):
    if isinstance(obj, dict):
        return {k: serialize(v) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, list):
        return [serialize(v) for v in obj]
    if isinstance(obj, datetime):
        return iso(obj)
    return obj


def meta():
    rid = "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=24))
    return {"api_request_id": rid, "api_request_timestamp": iso(now())}


def ok(data, status=200):
    return jsonify({"meta": meta(), "response_type": "object",
                    "data": serialize(data)}), status


def ok_list(items, limit, offset, total):
    m = meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total
    m["has_more"] = offset + len(items) < total
    return jsonify({"meta": m, "response_type": "array",
                    "data": [serialize(i) for i in items]}), 200


def ok_array_raw(items):
    """List response without pagination params (e.g. GET /loads/{id}/invoice)."""
    return jsonify({"meta": meta(), "response_type": "array",
                    "data": [serialize(i) for i in items]}), 200


def error_response(e):
    return jsonify({"meta": meta(), "response_type": "error",
                    "data": {"error_id": e.error_id, "message": e.message}}), e.status


def require_role(allowed):
    """Validation pipeline stages 1-2: identity headers then role authorization."""
    uid = request.headers.get("X-User-ID") or ""
    role = request.headers.get("X-User-Role") or ""
    if not uid or role not in ALL_ROLES:
        raise ApiError(ERR_AUTH, 400,
                       "X-User-ID and X-User-Role headers must be present and role recognized")
    if role not in allowed:
        raise ApiError(ERR_PERMS, 403, f"Role {role} is not permitted for this endpoint")
    return uid, role


def get_body(required=True):
    raw = request.get_data()
    if not raw or not raw.strip():
        if required:
            raise ApiError(ERR_INVALID, 400, "Request body must be a JSON object")
        return {}
    try:
        b = request.get_json(force=True)
    except Exception:
        raise ApiError(ERR_INVALID, 400, "Request body is not valid JSON")
    if not isinstance(b, dict):
        raise ApiError(ERR_INVALID, 400, "Request body must be a JSON object")
    return b


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(b, name):
    v = b.get(name)
    if not isinstance(v, str) or v == "":
        raise ApiError(ERR_INVALID, 400, f"Field '{name}' is required and must be a string")
    return v


def opt_str(b, name):
    v = b.get(name)
    if v is None:
        return None
    if not isinstance(v, str) or v == "":
        raise ApiError(ERR_INVALID, 400, f"Field '{name}' must be a string")
    return v


def req_int(b, name, min_v=None, max_v=None):
    v = b.get(name)
    if not _is_int(v):
        raise ApiError(ERR_INVALID, 400, f"Field '{name}' is required and must be an integer")
    if min_v is not None and v < min_v:
        raise ApiError(ERR_INVALID, 400, f"Field '{name}' must be >= {min_v}")
    if max_v is not None and v > max_v:
        raise ApiError(ERR_INVALID, 400, f"Field '{name}' must be <= {max_v}")
    return v


def opt_int(b, name, min_v=None, max_v=None):
    v = b.get(name)
    if v is None:
        return None
    return req_int(b, name, min_v, max_v)


def req_enum(b, name, values):
    v = b.get(name)
    if v not in values:
        raise ApiError(ERR_INVALID, 400,
                       f"Field '{name}' must be one of {', '.join(values)}")
    return v


def req_dt(b, name):
    return parse_dt(b.get(name), name)


def opt_dt(b, name):
    v = b.get(name)
    if v is None:
        return None
    return parse_dt(v, name)


def opt_bool(b, name, default=False):
    v = b.get(name)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise ApiError(ERR_INVALID, 400, f"Field '{name}' must be a boolean")
    return v


def pagination():
    """limit (default 10, 1..100) and offset (default 0, >= 0) query params."""
    limit_s = request.args.get("limit")
    offset_s = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_s is not None:
        try:
            limit = int(limit_s)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID, 400, "Query parameter 'limit' must be an integer")
        if str(limit_s).strip().lstrip("+-").isdigit() is False:
            raise ApiError(ERR_INVALID, 400, "Query parameter 'limit' must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError(ERR_INVALID, 400, "Query parameter 'limit' must be between 1 and 100")
    if offset_s is not None:
        try:
            offset = int(offset_s)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID, 400, "Query parameter 'offset' must be an integer")
        if str(offset_s).strip().lstrip("+-").isdigit() is False:
            raise ApiError(ERR_INVALID, 400, "Query parameter 'offset' must be an integer")
        if offset < 0:
            raise ApiError(ERR_INVALID, 400, "Query parameter 'offset' must be >= 0")
    return limit, offset


def created_order(items):
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


def paged(items, limit, offset):
    total = len(items)
    return items[offset:offset + limit], total
