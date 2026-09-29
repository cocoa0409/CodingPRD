"""Auth header extraction and RBAC (PRD 2.1, validation precedence 1-4)."""
from functools import wraps

from flask import g, request

from db import db
from errors import fail

ROLES = (
    "ProgramAdmin",
    "ResearchAnalyst",
    "LegalReviewer",
    "EnablementManager",
    "ProductManager",
    "SalesRep",
)

ANY_ROLE = ROLES


def authenticate(allowed_roles, analyst_identity=False):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        fail("ERR_MISSING_AUTH_HEADERS")
    if role not in ROLES:
        fail("ERR_UNKNOWN_ROLE")
    if role not in allowed_roles:
        fail("ERR_ROLE_NOT_PERMITTED")
    if analyst_identity and role == "ResearchAnalyst":
        analyst = db.analysts.get(user_id)
        if analyst is None or analyst["status"] != "ACTIVE":
            fail("ERR_ANALYST_IDENTITY_INVALID")
    g.user_id = user_id
    g.role = role
    return user_id, role


def endpoint(roles, analyst_identity=False):
    """Decorator enforcing precedence rules 1-4 before the handler body runs."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate(roles, analyst_identity)
            return fn(*args, **kwargs)

        return wrapper

    return decorator
