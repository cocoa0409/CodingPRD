"""Auth header extraction, role checking, and the endpoint wrapper."""
from functools import wraps

from flask import request

from db import store
from errors import ApiError, fail
from response import error_response

ROLES = {
    "ZoneOperator",
    "Resident",
    "Driver",
    "PartnerManager",
    "Inspector",
    "SponsorManager",
    "CharityAdmin",
    "SensorGateway",
}


def authenticate():
    """Priority 1: both headers present and role declared -> else 401."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers")
    return user_id, role


def endpoint(roles):
    """Decorator: auth (p1) + role membership (p2) + uniform error envelope.

    Handlers receive (user_id, role, *path_params). All work happens under the
    store lock so concurrent requests cannot interleave mutations.
    """
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            with store.lock:
                try:
                    user_id, role = authenticate()
                    if roles is not None and role not in roles:
                        fail("ERR_UNAUTHORIZED", "Role %s may not call this endpoint" % role)
                    return fn(user_id, role, *args, **kwargs)
                except ApiError as e:
                    return error_response(e)
        return wrapper
    return deco
