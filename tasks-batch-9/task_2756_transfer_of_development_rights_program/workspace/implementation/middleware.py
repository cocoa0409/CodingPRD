"""Auth header extraction and RBAC (PRD 2.1, ladder rungs 1-2 and 6)."""

from flask import request

from core import db
from errors import fail

ADMIN = "ProgramAdministrator"
REVIEWER = "SeveranceReviewer"
BOARD = "DesignReviewBoard"
MONITOR = "EasementMonitor"
LANDOWNER = "Landowner"
DEVELOPER = "Developer"

ROLES = (ADMIN, REVIEWER, BOARD, MONITOR, LANDOWNER, DEVELOPER)
ALL_ROLES = ROLES
STAFF_ROLES = (ADMIN, REVIEWER, BOARD, MONITOR)
ENTITY_BACKED = (LANDOWNER, DEVELOPER)


def authenticate():
    """Rung 1: both headers present and the role is one of the six."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or str(user_id).strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-ID header missing or empty")
    if role is None or str(role).strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-Role header missing or empty")
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "unknown role %s" % role)
    return user_id, role


def require_roles(*allowed):
    """Rung 1 then rung 2."""
    user_id, role = authenticate()
    if role not in allowed:
        fail("ERR_ROLE_NOT_PERMITTED", "role %s may not call this endpoint" % role)
    return user_id, role


def is_entity_backed(role):
    return role in ENTITY_BACKED


def require_owner(user_id, role, owner_party_id):
    """Rung 6. Staff identities are opaque; the administrator is exempt where declared."""
    if role in ENTITY_BACKED and user_id != owner_party_id:
        fail("ERR_NOT_RESOURCE_OWNER", "acting party is not the owner of this resource")


def require_suspension_clear(*party_ids):
    """Rung 10: any party involved in the request must not be SUSPENDED."""
    seen = set()
    for pid in party_ids:
        if pid is None or pid in seen:
            continue
        seen.add(pid)
        party = db.parties.get(pid)
        if party is not None and party["status"] == "SUSPENDED":
            fail("ERR_PARTY_SUSPENDED", "party %s is SUSPENDED" % pid)
