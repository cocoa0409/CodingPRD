"""Authentication / authorisation middleware.

Headers (PRD 2.1): X-User-ID and X-User-Role.
Roles: EngagementPartner, EngagementManager, QualityReviewer, FirmLeadership,
ClientContact, PracticeAdmin.
"""

from flask import g, request

from db import db
from errors import fail

ROLE_PARTNER = "EngagementPartner"
ROLE_MANAGER = "EngagementManager"
ROLE_REVIEWER = "QualityReviewer"
ROLE_LEADERSHIP = "FirmLeadership"
ROLE_CLIENT = "ClientContact"
ROLE_ADMIN = "PracticeAdmin"

ALL_ROLES = (
    ROLE_PARTNER,
    ROLE_MANAGER,
    ROLE_REVIEWER,
    ROLE_LEADERSHIP,
    ROLE_ADMIN,
    ROLE_CLIENT,
)

# Every role that reads master data / rows.
READ_ROLES = ALL_ROLES

# Firm roles resolve X-User-ID against Consultant.id.
CONSULTANT_ROLES = (ROLE_PARTNER, ROLE_MANAGER, ROLE_REVIEWER, ROLE_LEADERSHIP)


def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or not str(uid).strip():
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    if role is None or not str(role).strip():
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is required.")
    uid = str(uid).strip()
    role = str(role).strip()
    if role not in ALL_ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role is not a recognised role.")
    if role in CONSULTANT_ROLES:
        if uid not in db.consultants:
            fail("ERR_UNAUTHENTICATED", "X-User-ID does not resolve to a known consultant.")
    elif role == ROLE_CLIENT:
        if uid not in db.clients:
            fail("ERR_UNAUTHENTICATED", "X-User-ID does not resolve to a known client.")
    # PracticeAdmin: opaque back-office identifier, never compared to an entity id.
    g.user_id = uid
    g.role = role


def require_roles(*roles):
    if g.role not in roles:
        fail("ERR_FORBIDDEN_ROLE", "Role %s may not perform this operation." % g.role)


def is_client():
    return g.role == ROLE_CLIENT


def client_scope(client_id):
    """PRD 2.1 / validation 11: a ClientContact may only touch its own rows."""
    if g.role == ROLE_CLIENT and g.user_id != client_id:
        fail("ERR_CLIENT_SCOPE_VIOLATION", "This row is not reachable from the acting client.")
