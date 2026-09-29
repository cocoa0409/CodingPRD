"""Authentication, role gating and the ownership / segregation-of-duties rules.

Implements validation rules 1-9 of PRD 2.9 in priority order.
"""

from flask import request

from errors import ApiError
from store import db

PATIENT = "Patient"
HEARING_PROFESSIONAL = "HearingProfessional"
LICENSED_AUDIOLOGIST = "LicensedAudiologist"
CARE_OPS = "CareOpsAgent"
REIMBURSEMENT = "ReimbursementSpecialist"
REPAIR_TECH = "RepairTechnician"
FIRMWARE_ENG = "FirmwareEngineer"
COMPLIANCE = "ComplianceOfficer"
ADMIN = "PlatformAdmin"

ROLES = (
    PATIENT,
    HEARING_PROFESSIONAL,
    LICENSED_AUDIOLOGIST,
    CARE_OPS,
    REIMBURSEMENT,
    REPAIR_TECH,
    FIRMWARE_ENG,
    COMPLIANCE,
    ADMIN,
)

PROVIDER_ROLES = (HEARING_PROFESSIONAL, LICENSED_AUDIOLOGIST)


class Actor(object):
    __slots__ = ("role", "user_id", "patient", "provider")

    def __init__(self, role, user_id):
        self.role = role
        self.user_id = user_id
        self.patient = None
        self.provider = None

    @property
    def is_patient(self):
        return self.role == PATIENT

    @property
    def is_provider(self):
        return self.role in PROVIDER_ROLES


def authorize(*allowed):
    """Rules 1-4: headers, known role, entity-backed identity, role permitted."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or not str(user_id).strip() or not str(role).strip():
        raise ApiError("ERR_MISSING_AUTH_HEADERS")
    user_id = str(user_id).strip()
    role = str(role).strip()
    if role not in ROLES:
        raise ApiError("ERR_UNKNOWN_ROLE")
    actor = Actor(role, user_id)
    if role == PATIENT:
        row = db.patients.get(user_id)
        if row is None or row.get("status") == "DEACTIVATED":
            raise ApiError("ERR_IDENTITY_NOT_FOUND")
        actor.patient = row
    elif role in PROVIDER_ROLES:
        row = db.providers.get(user_id)
        if row is None or row.get("status") == "OFFBOARDED":
            raise ApiError("ERR_IDENTITY_NOT_FOUND")
        actor.provider = row
    if allowed and role not in allowed:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    return actor


# ------------------------------------------------------------------ rules 5-9
def require_owner(actor, patient_id):
    """Rule 5: an acting Patient may only touch its own resources."""
    if actor.is_patient and patient_id != actor.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def require_assigned_provider(actor, provider_id):
    """Rule 6: the acting provider must be the assigned provider."""
    if actor.is_provider and provider_id != actor.user_id:
        raise ApiError("ERR_NOT_ASSIGNED_PROVIDER")


def require_audiologist(actor):
    """Rule 7: clearance determinations and invalidations need a licensed audiologist."""
    provider = actor.provider
    if provider is not None and provider.get("provider_type") != "LICENSED_AUDIOLOGIST":
        raise ApiError("ERR_PROVIDER_TYPE_NOT_PERMITTED")


def require_distinct_user(actor, other_user_id):
    """Rule 8: segregation of duties on approve / decide actions."""
    if other_user_id is not None and other_user_id == actor.user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")


def require_no_conflict(provider_id, screening_session_id):
    """Rule 9: the provider who invalidated the triggering screening is excluded."""
    if provider_id is None or screening_session_id is None:
        return
    session = db.screening_sessions.get(screening_session_id)
    if session is None:
        return
    if session.get("_invalidated_by_provider_id") == provider_id:
        raise ApiError("ERR_PROVIDER_CONFLICT_OF_INTEREST")
