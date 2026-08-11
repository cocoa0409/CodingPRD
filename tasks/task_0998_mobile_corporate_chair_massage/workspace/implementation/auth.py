"""Auth: X-User-ID / X-User-Role header extraction, RBAC, ownership checks."""
from functools import wraps

from flask import g, request

import errors

VALID_ROLES = {"PlatformAdmin", "Organizer", "Therapist"}

# Bootstrap endpoints exempt from the header-presence requirement (PRD 2.1).
BOOTSTRAP = {
    ("POST", "/chair-massage/therapists"),
    ("POST", "/chair-massage/corporate-accounts"),
    ("POST", "/chair-massage/_clock/set_current_utc"),
}


def gate_request():
    """before_request hook: priority-1 (401) auth check for non-bootstrap routes."""
    if not request.path.startswith("/chair-massage"):
        return None
    key = (request.method, request.path.rstrip("/") or "/")
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if key in BOOTSTRAP:
        # Header presence not required; if a role is supplied it must be PlatformAdmin.
        if role and role != "PlatformAdmin":
            raise errors.forbidden("Only PlatformAdmin may call this endpoint")
        g.user_id = uid
        g.role = role if role else "PlatformAdmin"
        return None
    if not uid or not role:
        raise errors.unauthenticated()
    g.user_id = uid
    g.role = role
    return None


def require_roles(*roles):
    """Priority-2 (403) RBAC check."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if g.role not in roles:
                raise errors.forbidden(f"Role {g.role} may not call this endpoint")
            return fn(*args, **kwargs)
        return wrapper
    return deco


def require_account_owner(account_id):
    """Organizer identity is entity-backed by CorporateAccount: X-User-ID must equal
    the referenced corporate_account_id (PRD 2.1)."""
    if g.role == "Organizer" and g.user_id != account_id:
        raise errors.forbidden("Organizer does not own this corporate account")


def require_therapist_self(therapist_id):
    """Therapist identity is entity-backed by Therapist (PRD 2.1)."""
    if g.role == "Therapist" and g.user_id != therapist_id:
        raise errors.forbidden("Therapist may only act on their own resources")
