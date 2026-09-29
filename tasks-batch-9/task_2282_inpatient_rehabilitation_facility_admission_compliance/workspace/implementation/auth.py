"""Authentication / RBAC gates — PRD §2.1 and validation ladder ranks 1-4."""

from flask import request

from db import store
from errors import ApiError

ROLES = ("ComplianceOfficer", "NurseCaseManager", "RehabPhysician", "TherapyLead", "HimCoder")
ALL_ROLES = ROLES

# Clinician-backed roles and the credentials that satisfy them (PRD §2.1).
ROLE_CREDENTIALS = {
    "NurseCaseManager": ("NURSE",),
    "RehabPhysician": ("REHAB_PHYSICIAN",),
    "TherapyLead": ("THERAPIST_PT", "THERAPIST_OT", "THERAPIST_SLP"),
    "HimCoder": ("CODER",),
}


def authenticate(allowed_roles):
    """Ladder ranks 1-4.  Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")

    # 1 — header presence and role recognition
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")

    # 2 — role authorisation for the endpoint
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")

    # 3 / 4 — clinician-backed identity gates.  ComplianceOfficer identity is
    # opaque and is never resolved against any persisted entity.
    if role in ROLE_CREDENTIALS:
        clinician = store.clinicians.get(user_id)
        if clinician is None or clinician["credential"] not in ROLE_CREDENTIALS[role]:
            raise ApiError("ERR_ROLE_CREDENTIAL_MISMATCH")
        if clinician["status"] != "ACTIVE":
            raise ApiError("ERR_ACTING_CLINICIAN_INACTIVE")

    return user_id, role
