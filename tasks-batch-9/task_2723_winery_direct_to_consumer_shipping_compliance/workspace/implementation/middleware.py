"""Auth, RBAC and ownership scoping (PRD 2.1, evaluation order per PRD 2.9)."""
from flask import request

from errors import ApiError

ROLES = ("PlatformAdmin", "ComplianceOfficer", "WineryOperator", "Consumer", "CarrierAgent")


def identity():
    """First check of every request: both headers present and non-empty."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or str(uid).strip() == "" or role is None or str(role).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers are required.")
    return str(uid), str(role)


def require(*allowed_roles):
    """Header presence, then role authorization. Returns (user_id, role)."""
    uid, role = identity()
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHORIZED", "Unknown role '%s'." % role)
    if allowed_roles and role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "Role %s may not call this endpoint." % role)
    return uid, role


def own_winery(uid, role, winery_id):
    """A WineryOperator may only reach rows of its own winery."""
    if role == "WineryOperator" and winery_id is not None and uid != winery_id:
        raise ApiError("ERR_FORBIDDEN_RESOURCE_OWNER", "This resource belongs to another winery.")


def own_consumer(uid, role, consumer_id):
    """A Consumer may only reach its own rows."""
    if role == "Consumer" and consumer_id is not None and uid != consumer_id:
        raise ApiError("ERR_FORBIDDEN_RESOURCE_OWNER", "This resource belongs to another consumer.")


def own_both(uid, role, winery_id=None, consumer_id=None):
    own_winery(uid, role, winery_id)
    own_consumer(uid, role, consumer_id)
