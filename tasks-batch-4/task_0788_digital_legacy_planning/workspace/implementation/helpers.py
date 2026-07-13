"""Request-pipeline helpers: envelopes, auth, scope, validation primitives."""
from flask import request, jsonify
import store
from errors import ApiError

ROLES = {"Owner", "Deputy", "PlatformAdmin"}


# --- Response envelopes -------------------------------------------------------
def _meta(pagination=None):
    m = {
        "api_request_id": store.new_request_id(),
        "api_request_timestamp": store.fmt_now_wall(),
    }
    if pagination:
        m.update(pagination)
    return m


def ok(data, status=200, pagination=None, response_type="object"):
    body = {"meta": _meta(pagination), "response_type": response_type, "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(items) < total,
    }
    body = {"meta": _meta(pagination), "response_type": "array", "data": items}
    return jsonify(body), 200


def err_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


# --- Auth / RBAC --------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers")
    return role, uid


def begin(allowed_roles):
    role, uid = authenticate()
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "Role not permitted for this operation")
    return role, uid


def check_scope(ctx, plan_id):
    """Ownership/scope gate (ERR_FORBIDDEN_SCOPE). PlatformAdmin is exempt."""
    role, uid = ctx
    if role == "PlatformAdmin":
        return
    if role == "Owner":
        if uid != plan_id:
            raise ApiError("ERR_FORBIDDEN_SCOPE", "Owner does not own the target plan")
        return
    if role == "Deputy":
        dep = store.DEPUTIES.get(uid)
        if not dep or dep["plan_id"] != plan_id:
            raise ApiError("ERR_FORBIDDEN_SCOPE", "Deputy does not serve the target plan")
        return


# --- Body / query parsing -----------------------------------------------------
def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object")
    return body


def req_str(body, key):
    v = body.get(key)
    if not isinstance(v, str) or v.strip() == "":
        raise ApiError("ERR_VALIDATION", f"Field '{key}' is required and must be a non-empty string")
    return v


def opt_str(body, key, default=None):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", f"Field '{key}' must be a string")
    return v


def req_enum(body, key, allowed):
    v = body.get(key)
    if not isinstance(v, str) or v not in allowed:
        raise ApiError("ERR_VALIDATION", f"Field '{key}' must be one of {sorted(allowed)}")
    return v


def opt_enum(body, key, allowed, default=None):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if not isinstance(v, str) or v not in allowed:
        raise ApiError("ERR_VALIDATION", f"Field '{key}' must be one of {sorted(allowed)}")
    return v


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_int(body, key, min_value=None):
    v = body.get(key)
    if not _is_int(v):
        raise ApiError("ERR_VALIDATION", f"Field '{key}' must be an integer")
    if min_value is not None and v < min_value:
        raise ApiError("ERR_VALIDATION", f"Field '{key}' must be >= {min_value}")
    return v


def opt_int(body, key, default=None, min_value=None, allow_none=False):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if not _is_int(v):
        raise ApiError("ERR_VALIDATION", f"Field '{key}' must be an integer")
    if min_value is not None and v < min_value:
        raise ApiError("ERR_VALIDATION", f"Field '{key}' must be >= {min_value}")
    return v


def opt_number(body, key, default=None, min_value=None, max_value=None):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", f"Field '{key}' must be a number")
    if min_value is not None and v < min_value:
        raise ApiError("ERR_VALIDATION", f"Field '{key}' must be >= {min_value}")
    if max_value is not None and v > max_value:
        raise ApiError("ERR_VALIDATION", f"Field '{key}' must be <= {max_value}")
    return v


def req_dt(body, key):
    v = body.get(key)
    try:
        return store.parse_dt(v)
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", f"Field '{key}' must be an ISO-8601 datetime")


def req_enum_array(body, key, allowed):
    v = body.get(key)
    if not isinstance(v, list):
        raise ApiError("ERR_VALIDATION", f"Field '{key}' must be an array")
    for item in v:
        if not isinstance(item, str) or item not in allowed:
            raise ApiError("ERR_VALIDATION", f"Field '{key}' items must be one of {sorted(allowed)}")
    return list(v)


# --- Pagination ---------------------------------------------------------------
def get_pagination():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    if limit is None:
        limit = 10
    else:
        try:
            limit = int(limit)
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_VALIDATION", "limit must be between 1 and 100")
    if offset is None:
        offset = 0
    else:
        try:
            offset = int(offset)
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", "offset must be >= 0")
    return limit, offset


def sort_created(records):
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
