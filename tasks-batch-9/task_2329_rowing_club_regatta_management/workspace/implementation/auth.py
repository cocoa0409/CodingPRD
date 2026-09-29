"""Header authentication and role authorisation (PRD 2.1, ladder rungs 1-2)."""
from functools import wraps

from flask import g, request

import db
from errors import fail

ROLES = ("ClubAdmin", "Member", "Coach", "SafetyOfficer", "EquipmentManager",
         "RaceOfficial", "JuryChair")
ENTITY_BACKED = ("Member", "Coach", "SafetyOfficer", "EquipmentManager",
                 "RaceOfficial", "JuryChair")


def require(*allowed):
    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not role or role not in ROLES:
                fail("ERR_MISSING_AUTH_HEADERS",
                     "X-User-ID and a recognised X-User-Role are required.")
            if role not in allowed:
                fail("ERR_UNAUTHORIZED",
                     "Role %s may not perform this operation." % role)
            actor = None
            if role in ENTITY_BACKED:
                actor = db.members.get(user_id)
                if actor is None:
                    fail("ERR_UNAUTHORIZED",
                         "X-User-ID does not resolve to a member.")
            g.actor_id = user_id
            g.actor_role = role
            g.actor_member = actor
            return view(*args, **kwargs)
        return wrapper
    return decorator


def actor_id():
    return getattr(g, "actor_id", None)


def actor_role():
    return getattr(g, "actor_role", None)
