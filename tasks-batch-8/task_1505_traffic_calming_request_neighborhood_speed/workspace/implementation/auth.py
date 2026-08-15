"""Auth middleware (PRD §2.1, §2.10 tiers 1-3).

Headers: X-User-ID and X-User-Role, both mandatory and non-empty.
Roles: Resident, TrafficEngineer, CityEngineer, EmergencyReviewer, CityAdmin.
Resident calls are entity-backed: an X-User-ID with no matching resident
record is rejected with ERR_RESIDENT_NOT_FOUND (404). Other roles are opaque.
"""
from functools import wraps

from flask import g, request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN, ERR_RESIDENT_NOT_FOUND
from store import store

ALL_ROLES = ("Resident", "TrafficEngineer", "CityEngineer", "EmergencyReviewer", "CityAdmin")


def require_roles(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            # Tier 1: authentication
            if uid is None or role is None or not uid.strip() or not role.strip():
                raise ApiError(401, ERR_UNAUTHENTICATED,
                               "X-User-Role and X-User-ID headers must be present and non-empty")
            # Tier 2: authorization (an unrecognized role matches no endpoint)
            if role not in roles:
                raise ApiError(403, ERR_FORBIDDEN,
                               "Role %s is not permitted on this endpoint" % role)
            g.user_id = uid
            g.role = role
            # Tier 3 (identity resolution): resident calls are entity-backed
            if role == "Resident":
                resident = store.residents.get(uid)
                if resident is None:
                    raise ApiError(404, ERR_RESIDENT_NOT_FOUND,
                                   "Acting resident %s is not registered" % uid)
                g.resident = resident
            return fn(*args, **kwargs)
        return wrapper
    return deco
