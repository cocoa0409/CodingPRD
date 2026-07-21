"""HTTP glue: response envelope, auth, pagination, body-validation helpers."""
from flask import request, jsonify

from errors import ApiError
from store import new_request_id, now_iso

VALID_ROLES = {"OpsManager", "SalesAgent", "Finance", "Auditor"}


def _meta():
    return {"api_request_id": new_request_id(), "api_request_timestamp": now_iso()}


def ok(data, status=200, response_type="object"):
    return jsonify({"meta": _meta(), "response_type": response_type, "data": data}), status


def created(data):
    return ok(data, status=201, response_type="object")


def ok_list(items, total, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = offset + len(items) < total
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error_response(err):
    return (
        jsonify(
            {
                "meta": _meta(),
                "response_type": "error",
                "data": {"error_id": err.error_id, "message": err.message},
            }
        ),
        err.http_status,
    )


def authenticate(allowed_roles):
    """Priority 1-2: auth then RBAC. allowed_roles == 'ALL' for read endpoints."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in VALID_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if allowed_roles != "ALL" and role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return role


def get_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object")
    return body


def parse_pagination():
    args = request.args
    try:
        limit = int(args.get("limit", 10))
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", "limit/offset must be integers")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


# ----- body field validators (priority 3: ERR_VALIDATION) -----

def require(body, field):
    if field not in body or body[field] is None:
        raise ApiError("ERR_VALIDATION", f"Missing required field: {field}")
    return body[field]


def req_str(body, field):
    v = require(body, field)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", f"Field {field} must be a non-empty string")
    return v


def req_int(body, field, min_val=None):
    v = require(body, field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", f"Field {field} must be an integer")
    if min_val is not None and v < min_val:
        raise ApiError("ERR_VALIDATION", f"Field {field} must be >= {min_val}")
    return v


def opt_int(body, field, default, min_val=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", f"Field {field} must be an integer")
    if min_val is not None and v < min_val:
        raise ApiError("ERR_VALIDATION", f"Field {field} must be >= {min_val}")
    return v


def opt_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", f"Field {field} must be a boolean")
    return v


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", f"Field {field} must be a string")
    return v
