"""Auth header extraction and role admission (PRD 2.1, 2.11 tiers 1-2)."""

from flask import request

from errors import unauthenticated, forbidden

ROLES = (
    "FirmAdmin",
    "IntakeSpecialist",
    "ResponsibleAttorney",
    "ConflictsPartner",
    "BillingClerk",
    "Client",
)

# Entity-backed attorney roles (PRD 2.1): X-User-ID is an Attorney.id.
ATTORNEY_ROLES = ("ResponsibleAttorney", "ConflictsPartner")


def caller():
    """Tier 1: both headers present and non-empty, else ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id == "" or role is None or role == "":
        raise unauthenticated()
    return user_id, role


def admit(role, allowed):
    """Tier 2 (endpoint level): caller role must be in the endpoint's roles."""
    if role not in allowed:
        raise forbidden()
    return True


def admit_action(role, allowed):
    """Tier 2 (per-action on transition endpoints)."""
    if role not in allowed:
        raise forbidden()
    return True


def body():
    """JSON request body; a missing/non-JSON body behaves as empty object so
    that existence/state tiers fire before the shape tier (PRD 2.11)."""
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    return {}
