"""Rungs 1, 2 and 4 of the request-screening ladder (PRD sections 2.1, 2.9)."""

from flask import g, request

from errors import fail

ROLES = (
    "ProgramAdmin",
    "FireMarshal",
    "Inspector",
    "PropertyOwner",
    "Contractor",
    "CommunityOrganizer",
    "TitleAgent",
)


def authenticate():
    """Rung 1 — both headers present and non-blank, role one of the seven."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        fail("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers are required.")
    if not str(user_id).strip() or not str(role).strip():
        fail("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role must be non-blank.")
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "Unknown role '%s'." % role)
    g.user_id = user_id
    g.role = role


def auth(*roles):
    """Rungs 1 and 2 — authenticate, then check endpoint role membership."""
    authenticate()
    if g.role not in roles:
        fail("ERR_FORBIDDEN_ROLE", "Role %s may not invoke this operation." % g.role)
    return g.role


def own(condition):
    """Rung 4 — ownership for entity-backed roles."""
    if not condition:
        fail("ERR_NOT_RESOURCE_OWNER", "Caller does not own the target resource.")


def owner_must_match(value):
    """Rung 4 for PropertyOwner-shared operations: X-User-ID is the Parcel id."""
    if g.role == "PropertyOwner":
        own(g.user_id == value)
