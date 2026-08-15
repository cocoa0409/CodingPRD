from functools import wraps
from flask import request
from errors import ApiError

ALL_ROLES = {"APClerk", "TaxSpecialist", "TaxTransmitter", "TaxAdmin", "IRSSystem", "VendorPortal"}


def guard(roles, portal_vendor_param=None):
    """Auth ladder rungs 1-2: header presence, role membership, VendorPortal ownership."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if uid is None or not uid.strip() or role is None or not role.strip():
                raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                               "X-User-ID and X-User-Role headers must be present and non-empty")
            if role not in roles:
                raise ApiError("ERR_FORBIDDEN_FOR_ROLE", 403,
                               "Role %s is not permitted for this endpoint" % role)
            if role == "VendorPortal" and portal_vendor_param is not None:
                if uid != kwargs.get(portal_vendor_param):
                    raise ApiError("ERR_FORBIDDEN_FOR_ROLE", 403,
                                   "VendorPortal caller may only access its own vendor record")
            return fn(*args, **kwargs)
        return wrapper
    return deco


def caller_id():
    return request.headers.get("X-User-ID")


def caller_role():
    return request.headers.get("X-User-Role")
