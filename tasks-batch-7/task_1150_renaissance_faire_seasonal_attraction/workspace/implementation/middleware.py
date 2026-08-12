"""Auth header extraction, role gating, ownership checks, body access,
404 loading and pagination parsing — the shared request pipeline.

Validation layering (PRD section 2.9):
  1. header presence  -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400)
  2. role / ownership -> ERR_UNAUTHORIZED_ROLE / ERR_NOT_RESOURCE_OWNER (403)
  3. existence        -> ERR_*_NOT_FOUND (404), path ids left to right, then body FKs
  4. shape            -> ERR_INVALID_REQUEST (400)
  5. state gates      -> 409 family; OCC version checks last within this layer (412)
  6-9. business layers as wired in the route handlers.
"""
from flask import request

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_UNAUTHORIZED_ROLE,
    ERR_NOT_RESOURCE_OWNER,
    ERR_INVALID_REQUEST,
    not_found,
)


def auth_context():
    """Layer 1: both headers present and non-empty."""
    uid = request.headers.get("X-User-ID") or ""
    role = request.headers.get("X-User-Role") or ""
    if not uid.strip() or not role.strip():
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-ID and X-User-Role headers must be present and non-empty",
        )
    return uid, role


def require_roles(*roles):
    """Layers 1+2: headers, then role membership. No roles => any authenticated caller."""
    uid, role = auth_context()
    if roles and role not in roles:
        raise ApiError(
            ERR_UNAUTHORIZED_ROLE,
            403,
            "role %s is not permitted for this endpoint" % role,
        )
    return uid, role


def require_owner(ok):
    if not ok:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, 403, "caller does not own this resource")


def get_body():
    """JSON object body; absent body means {}. Non-object JSON is a shape error."""
    data = request.get_json(force=True, silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "request body must be a JSON object")
    return data


def load(coll, rid, err_id, what):
    rec = coll.get(rid)
    if rec is None:
        raise not_found(err_id, what)
    return rec


def parse_pagination():
    """limit (default 10, 1..100) and offset (default 0, >=0)."""
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be an integer")
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be >= 0")
    return limit, offset


def apply_filters(items, filters):
    """filters: list of (query_param, record_key)."""
    for param, key in filters:
        value = request.args.get(param)
        if value is not None:
            items = [r for r in items if str(r.get(key)) == value]
    return items


def sorted_by_creation(coll):
    return sorted(coll.values(), key=lambda r: r["_seq"])
