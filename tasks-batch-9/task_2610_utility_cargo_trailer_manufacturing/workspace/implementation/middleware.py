"""Authentication and RBAC — PRD 2.1 (ladder steps 1 and 2)."""
import functools

from flask import g, request

import errors

ROLES = ("PlantEngineer", "CertificationOfficer", "WeldSupervisor", "AssemblyTech",
         "QualityInspector", "SalesAdmin", "Dealer")

ALL_ROLES = list(ROLES)


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id == "" or role is None or role == "":
        raise errors.unauthenticated()
    if role not in ROLES:
        raise errors.unauthenticated()
    g.user_id = user_id
    g.role = role
    return user_id, role


def endpoint(roles):
    """Decorator running ladder step 1 (auth) then step 2 (role permission)."""
    allowed = tuple(roles)

    def decorate(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = authenticate()
            if role not in allowed:
                raise errors.role_not_permitted(role, request.method, request.path)
            return fn(*args, **kwargs)
        return wrapper
    return decorate


def actor():
    return g.user_id


def role():
    return g.role


def is_dealer():
    return g.role == "Dealer"
