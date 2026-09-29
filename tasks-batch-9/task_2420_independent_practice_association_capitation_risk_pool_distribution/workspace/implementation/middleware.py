"""Authentication, endpoint authorisation and ownership (PRD 2.1, 2.10 #1/#2/#6)."""

from flask import request

from errors import fail

ROLES = (
    "IpaAdmin",
    "NetworkManager",
    "ClaimsExaminer",
    "ReinsuranceUnderwriter",
    "PhysicianUser",
    "PayerRepresentative",
)


def authenticate():
    """Check 1 — X-User-ID / X-User-Role present, non-empty, role declared."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        fail("ERR_UNAUTHENTICATED")
    if not str(user_id).strip() or not str(role).strip():
        fail("ERR_UNAUTHENTICATED")
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED")
    return user_id, role


def require(*allowed_roles):
    """Checks 1 then 2 — endpoint-level authorised-role list."""
    user_id, role = authenticate()
    if role not in allowed_roles:
        fail("ERR_UNAUTHORIZED")
    return user_id, role


def require_transition_role(role, allowed_roles):
    """Transition-level authorisation (a refinement of check 2)."""
    if role not in allowed_roles:
        fail("ERR_UNAUTHORIZED")


def check_ownership(role, user_id, physician_ids=None, agreement=None):
    """Check 6 — resource ownership.

    PhysicianUser: X-User-ID must equal the PhysicianMember id the operation
    acts on.  PayerRepresentative: X-User-ID must equal the DelegationAgreement
    id the operation acts under.
    """
    if role == "PhysicianUser":
        candidates = [pid for pid in (physician_ids or []) if pid]
        if user_id not in candidates:
            fail("ERR_NOT_RESOURCE_OWNER")
    elif role == "PayerRepresentative":
        agreement_id = agreement["id"] if isinstance(agreement, dict) else agreement
        if not agreement_id or user_id != agreement_id:
            fail("ERR_NOT_RESOURCE_OWNER")
