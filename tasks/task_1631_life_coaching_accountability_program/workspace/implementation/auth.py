"""Auth middleware (PRD §2.1, SCAFFOLD validations 1-2, RBAC §1.7).

Headers: X-User-ID, X-User-Role.
Roles: PlatformAdmin / PracticeManager (opaque), Coach / Client (entity-backed:
X-User-ID must reference an existing row of that entity, else ERR_FORBIDDEN).
Validation priority: 1 auth (401) -> 2 role membership + entity-backed caller
existence (403) -> 3 target existence (404) -> ownership (403) -> ...
"""
from flask import request

from db import store
from errors import unauthenticated, forbidden

ROLES = ("PlatformAdmin", "PracticeManager", "Coach", "Client")
ENTITY_BACKED = {"Coach": "coaches", "Client": "clients"}


def authenticate():
    """Priority 1: headers. Returns (role, user_id)."""
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if role is None or role not in ROLES:
        raise unauthenticated()
    if role in ENTITY_BACKED and (uid is None or uid == ""):
        raise unauthenticated("X-User-ID is required for entity-backed role " + role)
    return role, uid


def require_role(role, uid, allowed):
    """Priority 2: role permitted for endpoint; entity-backed caller must exist."""
    if role not in allowed:
        raise forbidden("Role %s is not permitted for this endpoint" % role)
    if role in ENTITY_BACKED:
        table = getattr(store, ENTITY_BACKED[role])
        if uid not in table:
            raise forbidden("X-User-ID does not reference an existing %s" % role)
    return role, uid


def require_ownership(value, uid):
    """Entity-backed ownership: the resource's FK must equal X-User-ID."""
    if value != uid:
        raise forbidden("Caller does not own the target resource")


def body():
    """Parsed JSON body as dict; malformed/absent body -> {} (shape checks fire later)."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


# ---- field shape helpers (priority 20: ERR_INVALID_REQUEST) ----

def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def get_str(b, k):
    v = b.get(k)
    return v if isinstance(v, str) and v != "" else None


def get_int(b, k):
    v = b.get(k)
    return v if is_int(v) else None


def get_bool(b, k):
    v = b.get(k)
    return v if isinstance(v, bool) else None
