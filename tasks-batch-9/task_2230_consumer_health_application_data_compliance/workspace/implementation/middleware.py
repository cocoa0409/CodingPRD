"""Authentication and role authorisation (PRD 2.1, precedence checks 1 and 2)."""

from flask import request

from errors import fail

ROLES = (
    "PlatformAdmin",
    "PrivacyOfficer",
    "ComplianceApprover",
    "DataSteward",
    "SecurityEngineer",
    "Consumer",
)

STAFF = (
    "PlatformAdmin",
    "PrivacyOfficer",
    "ComplianceApprover",
    "DataSteward",
    "SecurityEngineer",
)

STAFF_AND_CONSUMER = STAFF + ("Consumer",)


def actor():
    """Check 1: both headers present and the role recognised."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not str(user_id).strip():
        fail("ERR_UNAUTHENTICATED")
    if not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED")
    return str(user_id), role


def require(*allowed):
    """Checks 1 then 2. Returns (user_id, role)."""
    if len(allowed) == 1 and isinstance(allowed[0], (list, tuple)):
        allowed = tuple(allowed[0])
    user_id, role = actor()
    if role not in allowed:
        fail("ERR_UNAUTHORIZED")
    return user_id, role
