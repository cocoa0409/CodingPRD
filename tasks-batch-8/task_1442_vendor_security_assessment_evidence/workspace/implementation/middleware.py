"""Auth extraction, role checking, VendorContact scoping, pagination (PRD
§2.1, §2.3, §2.9 priorities 1-3 and 23).

Headers: X-User-ID and X-User-Role. Roles: PlatformAdmin, RiskAnalyst,
SecurityApprover, VendorContact. For VendorContact, X-User-ID is the id of the
acting VendorContact record; reads/writes are scoped to that contact's vendor.
"""
from functools import wraps

from flask import g, request

import db
import errors
from errors import ApiError

ROLES = {"PlatformAdmin", "RiskAnalyst", "SecurityApprover", "VendorContact"}


def authenticate():
    """Priority 1: headers present and role declared -> else 401."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            errors.ERR_UNAUTHENTICATED,
            401,
            "Missing or invalid X-User-ID / X-User-Role headers",
        )
    g.user_id = user_id
    g.role = role


def require_roles(*roles):
    """Priority 2: role permitted on this endpoint -> else 403."""

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            if g.role not in roles:
                raise ApiError(
                    errors.ERR_FORBIDDEN,
                    403,
                    "Role %s is not permitted on this endpoint" % g.role,
                )
            return fn(*args, **kwargs)

        return wrapper

    return deco


def vc_vendor_id():
    """For a VendorContact caller, the vendor their contact record belongs to.
    Returns None for non-VendorContact roles, or when the contact id does not
    resolve to a persisted record (nothing is visible to such a caller)."""
    if g.role != "VendorContact":
        return None
    contact = db.contacts.get(g.user_id)
    if contact is None:
        return "__none__"
    return contact["vendor_id"]


def scope_vendor_or_403(vendor_id):
    """After path existence: a VendorContact may only reach its own vendor."""
    if g.role != "VendorContact":
        return
    if vc_vendor_id() != vendor_id:
        raise ApiError(
            errors.ERR_FORBIDDEN,
            403,
            "VendorContact scope is limited to its own vendor",
        )


def parse_pagination():
    """Priority 23: limit in 1..100 (default 10), offset >= 0 (default 0)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = 10 if raw_limit is None else int(raw_limit, 10)
    except (ValueError, TypeError):
        raise ApiError(
            errors.ERR_PAGINATION_INVALID, 422, "limit must be an integer"
        )
    try:
        offset = 0 if raw_offset is None else int(raw_offset, 10)
    except (ValueError, TypeError):
        raise ApiError(
            errors.ERR_PAGINATION_INVALID, 422, "offset must be an integer"
        )
    if limit < 1 or limit > 100 or offset < 0:
        raise ApiError(
            errors.ERR_PAGINATION_INVALID,
            422,
            "limit must be within 1..100 and offset must be >= 0",
        )
    return limit, offset


def paginate(items):
    """Sort by created_at ascending (insertion order breaks ties), slice."""
    limit, offset = parse_pagination()
    ordered = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    return ordered[offset:offset + limit], limit, offset, total


def body():
    """JSON request body as a dict; malformed/absent bodies become {}."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}
