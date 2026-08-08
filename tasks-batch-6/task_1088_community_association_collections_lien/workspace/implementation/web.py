"""HTTP helpers: error type, response envelope, auth, pagination, validation."""
import uuid

from flask import jsonify, request

import store as S


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def _meta(extra=None):
    m = {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": S.now_iso(),
    }
    if extra:
        m.update(extra)
    return m


def success(data, code=200, response_type="object", meta_extra=None):
    body = {
        "meta": _meta(meta_extra),
        "response_type": response_type,
        "data": data if data is not None else {},
    }
    return jsonify(body), code


def list_response(items, total_count, limit, offset):
    has_more = (offset + len(items)) < total_count
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    return success(items, 200, "array", meta_extra)


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# --------------------------------------------------------------------------
# auth
# --------------------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in S.ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or invalid authentication headers")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")


def require_own_association(role, uid, association_id):
    """AssociationManager may only act within its own association."""
    if role == "AssociationManager" and association_id != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "AssociationManager scope violation")


# --------------------------------------------------------------------------
# body / query parsing
# --------------------------------------------------------------------------
def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", 422, "Request body must be a JSON object")
    return data


def parse_pagination():
    args = request.args
    limit = args.get("limit")
    offset = args.get("offset")
    if limit is None:
        limit = 10
    else:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 422, "limit must be an integer")
        if limit < 1:
            limit = 1
        elif limit > 100:
            limit = 100
    if offset is None:
        offset = 0
    else:
        try:
            offset = int(offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 422, "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(items, limit, offset):
    items = sorted(items, key=lambda e: (e["_cdt"], e["_cseq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


# --------------------------------------------------------------------------
# generic field validators
# --------------------------------------------------------------------------
def require_present(data, fields):
    for f in fields:
        if data.get(f) is None:
            raise ApiError("ERR_VALIDATION", 422, f"Missing required field: {f}")


def require_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", 422, f"Field {field} must be a non-empty string")
    return v


def require_int(data, field):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 422, f"Field {field} must be an integer")
    return v


def require_datetime(data, field):
    v = data.get(field)
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", 422, f"Field {field} must be an ISO8601 string")
    try:
        S.parse_iso(v)
    except Exception:
        raise ApiError("ERR_VALIDATION", 422, f"Field {field} must be a valid ISO8601 datetime")
    return v


def require_enum(data, field, members):
    v = data.get(field)
    if v not in members:
        raise ApiError("ERR_INVALID_ENUM", 422, f"Field {field} has an invalid value")
    return v
