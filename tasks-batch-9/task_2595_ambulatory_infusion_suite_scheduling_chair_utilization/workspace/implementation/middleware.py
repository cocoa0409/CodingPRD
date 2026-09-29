"""Authentication, role authorization and ownership checks (PRD section 2.1)."""

from flask import g, request

from errors import ApiError

ROLES = (
    "Scheduler",
    "InfusionNurse",
    "Pharmacist",
    "AuthorizationSpecialist",
    "MedicalDirector",
    "Patient",
)


def authenticate(*allowed_roles):
    """Ladder steps 1 and 2: authentication then authorization."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if allowed_roles and role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    g.user_id = user_id
    g.role = role
    return user_id, role


def actor_id():
    return getattr(g, "user_id", None)


def actor_role():
    return getattr(g, "role", None)


def require_nurse_owner(appointment):
    """Ladder step 3 — only applies to the five chair-side actions."""
    if appointment is None:
        return
    if actor_role() == "InfusionNurse" and appointment.get("nurse_id") != actor_id():
        raise ApiError("ERR_NURSE_NOT_ASSIGNED")


def require_patient_owner(patient_id):
    """Ladder step 4."""
    if patient_id is None:
        return
    if actor_role() == "Patient" and patient_id != actor_id():
        raise ApiError("ERR_PATIENT_NOT_OWNER")
