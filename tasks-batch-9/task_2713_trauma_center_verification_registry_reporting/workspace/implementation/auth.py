"""Band A checks: identity, role authorisation, center scope, deciding authority
(PRD 2.1 and 2.11)."""
from flask import request

from errors import ApiError

ROLES = (
    "SystemAdmin",
    "TraumaProgramManager",
    "RegistryAbstractor",
    "RegistryValidator",
    "TraumaMedicalDirector",
    "VerificationReviewer",
    "StateDesignationOfficer",
)

ALL_ROLES = list(ROLES)

AUTHORITY_FOR_CYCLE_TYPE = {
    "NATIONAL_VERIFICATION": "VerificationReviewer",
    "STATE_DESIGNATION": "StateDesignationOfficer",
}


def identity():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    return user_id, role


def require_roles(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")


def require_scope(user_id, role, center_id):
    """TraumaProgramManager identity is the id of its own TraumaCenter."""
    if role != "TraumaProgramManager":
        return
    if center_id is None:
        return
    if user_id != center_id:
        raise ApiError("ERR_CENTER_SCOPE_VIOLATION")


def require_scope_any(user_id, role, center_ids):
    if role != "TraumaProgramManager":
        return
    candidates = [c for c in center_ids if c is not None]
    if not candidates:
        return
    if user_id not in candidates:
        raise ApiError("ERR_CENTER_SCOPE_VIOLATION")


def require_authority(role, cycle):
    """The deciding authority must match the cycle_type."""
    if cycle is None:
        return
    expected = AUTHORITY_FOR_CYCLE_TYPE.get(cycle["cycle_type"])
    if expected is None:
        return
    if role in ("VerificationReviewer", "StateDesignationOfficer") and role != expected:
        raise ApiError("ERR_DESIGNATION_AUTHORITY_MISMATCH")
