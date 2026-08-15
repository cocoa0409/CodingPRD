"""Auth header extraction + role gating, per scaffold validations priority 1-2."""
from functools import wraps
from flask import request, g
from db import store
from errors import missing_headers, insufficient_permissions

ALL_ROLES = ("FederationAdmin", "ClubCoach", "Proctor", "Treasurer", "Auditor")


def require_roles(*roles):
    """Decorator: check X-User-ID / X-User-Role presence, then role membership."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = (request.headers.get("X-User-ID") or "").strip()
            role = (request.headers.get("X-User-Role") or "").strip()
            if not uid or not role:
                raise missing_headers()
            if role not in roles:
                raise insufficient_permissions()
            g.user_id = uid
            g.user_role = role
            return fn(*args, **kwargs)
        return wrapper
    return deco


def acting_coach():
    """When the role is entity-backed (ClubCoach/Proctor), resolve X-User-ID to a Coach."""
    if g.user_role in ("ClubCoach", "Proctor"):
        return store.coaches.get(g.user_id)
    return None
