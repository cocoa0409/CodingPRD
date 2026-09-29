"""Header integrity and role authorisation — PRD §2.1 and rungs 1-2 of §2.9."""
from functools import wraps

from flask import g, request

from errors import ApiError

ROLES = ("ProcurementAnalyst", "ComplianceOfficer", "CategoryManager",
         "ContractAdmin", "CarrierRep")
ALL_ROLES = ROLES


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    g.user_id = user_id
    g.role = role
    return user_id, role


def authorize(roles):
    user_id, role = authenticate()
    if role not in roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")
    return user_id, role


def roles_required(*roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            authorize(roles)
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def actor():
    return g.get("user_id")


def acting_role():
    return g.get("role")


def own_carrier_or_raise(carrier_id):
    """Rung 6: a CarrierRep may only act on rows of its own carrier."""
    if acting_role() == "CarrierRep" and actor() != carrier_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
