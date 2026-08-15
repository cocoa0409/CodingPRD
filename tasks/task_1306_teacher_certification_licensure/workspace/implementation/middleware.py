"""Auth middleware: header extraction, role validation, RBAC, ownership checks."""
from functools import wraps

from flask import request

import errors
from db import db

ROLES = {
    "Anonymous",
    "Applicant",
    "IntakeOfficer",
    "CredentialEvaluator",
    "BackgroundInvestigator",
    "LegalOfficer",
    "ProgramApprovalOfficer",
    "AgencyAdmin",
}

STAFF_ROLES = {
    "IntakeOfficer",
    "CredentialEvaluator",
    "BackgroundInvestigator",
    "LegalOfficer",
    "ProgramApprovalOfficer",
    "AgencyAdmin",
}


class Actor:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def get_actor():
    """Validate auth headers (priority 1). Returns Actor or raises."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise errors.err_unauthenticated()
    return Actor(user_id, role)


def require_roles(*allowed):
    """Decorator factory: validates auth headers then role membership (priorities 1-2).

    Applicant ownership is checked separately per-resource via check_ownership.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            actor = get_actor()
            if actor.role not in allowed:
                raise errors.err_forbidden()
            return fn(actor, *args, **kwargs)
        return wrapper
    return decorator


def applicant_id_of_resource(kind, entity):
    """Resolve the applicant_id a resource chains back to, or None."""
    if entity is None:
        return None
    if kind == "applicant":
        return entity.get("id")
    if kind == "application":
        return entity.get("applicant_id")
    if kind in ("transcript", "test_score", "background_check", "reciprocity_evaluation",
                "deficiency_plan", "emergency_permit"):
        app = db.applications.get(entity.get("application_id"))
        return app.get("applicant_id") if app else None
    if kind == "license":
        return entity.get("applicant_id")
    if kind in ("endorsement", "ce_credit", "ce_audit", "misconduct_case"):
        lic = db.licenses.get(entity.get("license_id"))
        return lic.get("applicant_id") if lic else None
    if kind == "disciplinary_action":
        lic = db.licenses.get(entity.get("license_id"))
        return lic.get("applicant_id") if lic else None
    return None


def check_applicant_ownership(actor, kind, entity):
    """For Applicant actors reading/acting on an entity-backed resource, enforce ownership."""
    if actor.role != "Applicant":
        return
    if applicant_id_of_resource(kind, entity) != actor.user_id:
        raise errors.err_forbidden()
