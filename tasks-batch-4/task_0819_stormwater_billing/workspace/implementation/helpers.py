"""Request/response envelope, error type, auth, pagination, field validation."""
import random
import string

from flask import jsonify, request

import store


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _request_id():
    alnum = string.ascii_letters + string.digits
    return "req_" + "".join(random.choice(alnum) for _ in range(20))


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": store.now_iso(),
    }
    if extra:
        m.update(extra)
    return m


def ok_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    body = {"meta": _meta(meta_extra), "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Auth / RBAC / ownership
# ---------------------------------------------------------------------------
def authenticate(allowed_roles):
    """Validate identity headers and role authorization. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in store.KNOWN_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or invalid identity headers.")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation.")
    return user_id, role


def check_ownership(role, user_id, resource_account_id):
    """PropertyOwner may only act on resources whose owning account is theirs."""
    if role == "PropertyOwner" and user_id != resource_account_id:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP", 403, "You do not own this resource.")


# ---------------------------------------------------------------------------
# Body / field validation
# ---------------------------------------------------------------------------
def get_body():
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        return {}
    return data


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise ApiError("ERR_MISSING_FIELD", 400, f"Missing required field: {f}")


def require_enum(value, allowed, field="value"):
    if value not in allowed:
        raise ApiError("ERR_OUT_OF_RANGE", 422, f"{field} out of allowed set.")


def require_int_ge(value, minimum, field="value"):
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ApiError("ERR_OUT_OF_RANGE", 422, f"{field} must be an integer >= {minimum}.")


def require_int_gt(value, threshold, field="value"):
    if not isinstance(value, int) or isinstance(value, bool) or value <= threshold:
        raise ApiError("ERR_OUT_OF_RANGE", 422, f"{field} must be an integer > {threshold}.")


def require_num_range(value, lo, hi, field="value"):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < lo or value > hi:
        raise ApiError("ERR_OUT_OF_RANGE", 422, f"{field} must be within [{lo}, {hi}].")


# ---------------------------------------------------------------------------
# Existence lookups (raise ERR_NOT_FOUND)
# ---------------------------------------------------------------------------
def must_exist(collection, key):
    ent = collection.get(key)
    if ent is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced resource does not exist.")
    return ent


def exists_if_present(collection, body, field):
    """If an FK field is present (non-null) in the body it must reference an
    existing resource. Absent fields are left for the missing-field check."""
    if field in body and body[field] is not None:
        return must_exist(collection, body[field])
    return None


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def pagination():
    args = request.args
    limit = 10
    offset = 0
    raw_limit = args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            limit = 10
    raw_offset = args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(rows, limit, offset):
    """rows: list of entity dicts. Sort oldest-first, slice, return (page, total)."""
    ordered = sorted(rows, key=lambda e: e["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return [store.public(e) for e in page], total
