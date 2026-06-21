"""Entity lookup + ownership helpers (PRD §2.6, §2.1)."""
from __future__ import annotations

from db import db
from errors import (
    APIError,
    ERR_NOT_FOUND,
    ERR_NOT_RESOURCE_OWNER,
)


def _get_or_404(table: dict, rec_id: str, label: str) -> dict:
    rec = table.get(rec_id)
    if rec is None:
        raise APIError(ERR_NOT_FOUND, 404, f"{label} not found")
    return rec


def get_guardian(rec_id: str) -> dict:
    return _get_or_404(db.guardians, rec_id, "Guardian")


def get_child(rec_id: str) -> dict:
    return _get_or_404(db.children, rec_id, "Child")


def get_emergency_contact(rec_id: str) -> dict:
    return _get_or_404(db.emergency_contacts, rec_id, "EmergencyContact")


def get_authorization_form(rec_id: str) -> dict:
    return _get_or_404(db.authorization_forms, rec_id, "AuthorizationForm")


def get_program(rec_id: str) -> dict:
    return _get_or_404(db.programs, rec_id, "Program")


def get_session(rec_id: str) -> dict:
    return _get_or_404(db.sessions, rec_id, "Session")


def get_weekly_offering(rec_id: str) -> dict:
    return _get_or_404(db.weekly_offerings, rec_id, "WeeklyOffering")


def get_scholarship_award(rec_id: str) -> dict:
    return _get_or_404(db.scholarship_awards, rec_id, "ScholarshipAward")


def get_enrollment(rec_id: str) -> dict:
    return _get_or_404(db.enrollments, rec_id, "Enrollment")


def get_invoice(rec_id: str) -> dict:
    return _get_or_404(db.invoices, rec_id, "Invoice")


# ---------------------------------------------------------------------------
# Ownership: a Guardian owns a Child whose guardian_id == X-User-ID, and any
# resource hanging off that child (PRD §2.1, validation priority 4).
# ---------------------------------------------------------------------------
def require_child_owner(child: dict, user_id: str) -> None:
    if child["guardian_id"] != user_id:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Acting guardian does not own this child")
