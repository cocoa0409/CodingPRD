"""Payload factories — one per entity, input fields only (PRD §3)."""
from .constants import (
    DEFAULT_AGREEMENT_EXPIRES_AT,
    DEFAULT_AGREEMENT_SIGNED_AT,
    DEFAULT_COMPLETED_AT,
    DEFAULT_REVIEW_AT,
)

DEFAULTS = {
    "PROGRAM_NAME": "Test Program",
    "FOCUS_AREA": "GRIEF",
    "ROOM_NAME": "Room A",
    "ROOM_CAPACITY": 10,
    "GROUP_NAME": "Group A",
    "MODALITY": "VIRTUAL",
    "BASE_CAPACITY": 5,
    "REQUIRED_FACILITATOR_LEVEL": 1,
    "FACILITATOR_NAME": "Facilitator One",
    "COURSE_CODE": "T100",
    "COURSE_TITLE": "Foundations",
    "CREDIT_HOURS": 4,
    "LEVEL_WEIGHT": 2,
    "SCORE": 90,
    "RATING": 4,
    "PARTICIPANT_NAME": "Participant One",
    "HOUSEHOLD_SIZE": 1,
    "SESSION_START": "2026-08-02T10:00:00Z",
    "SESSION_END": "2026-08-02T11:00:00Z",
    "SEVERITY": "STANDARD",
    "CATEGORY": "OTHER",
    "OVERALL_RATING": 5,
    "FACILITATOR_RATING": 4,
    "MODALITY_RATING": 5,
}

_email_counter = {"n": 0}
_course_code_counter = {"n": 0}


def _unique_email(prefix: str = "user") -> str:
    _email_counter["n"] += 1
    return f"{prefix}{_email_counter['n']}@example.com"


def unique_course_code(prefix: str = "FAC") -> str:
    """PRD §3.2 requires course codes to be unique system-wide; factories that
    auto-create a course per facilitator must not collide within one test."""
    _course_code_counter["n"] += 1
    return f"{prefix}-{_course_code_counter['n']:03d}"


def create_program_payload(**overrides) -> dict:
    defaults = {"name": DEFAULTS["PROGRAM_NAME"], "focus_area": DEFAULTS["FOCUS_AREA"]}
    defaults.update(overrides)
    return defaults


def create_room_payload(**overrides) -> dict:
    defaults = {"name": DEFAULTS["ROOM_NAME"], "physical_capacity": DEFAULTS["ROOM_CAPACITY"]}
    defaults.update(overrides)
    return defaults


def create_group_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["GROUP_NAME"],
        "modality": DEFAULTS["MODALITY"],
        "base_capacity": DEFAULTS["BASE_CAPACITY"],
        "required_facilitator_level": DEFAULTS["REQUIRED_FACILITATOR_LEVEL"],
    }
    defaults.update(overrides)
    return defaults


def create_facilitator_payload(**overrides) -> dict:
    defaults = {"full_name": DEFAULTS["FACILITATOR_NAME"], "email": _unique_email("fac")}
    defaults.update(overrides)
    return defaults


def create_training_course_payload(**overrides) -> dict:
    defaults = {
        "code": DEFAULTS["COURSE_CODE"],
        "title": DEFAULTS["COURSE_TITLE"],
        "credit_hours": DEFAULTS["CREDIT_HOURS"],
        "level_weight": DEFAULTS["LEVEL_WEIGHT"],
    }
    defaults.update(overrides)
    return defaults


def create_training_completion_payload(course_id, **overrides) -> dict:
    defaults = {
        "course_id": course_id,
        "completed_at": DEFAULT_COMPLETED_AT,
        "score": DEFAULTS["SCORE"],
    }
    defaults.update(overrides)
    return defaults


def create_supervision_review_payload(reviewer_id, **overrides) -> dict:
    defaults = {
        "reviewer_id": reviewer_id,
        "occurred_at": DEFAULT_REVIEW_AT,
        "rating": DEFAULTS["RATING"],
    }
    defaults.update(overrides)
    return defaults


def create_participant_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["PARTICIPANT_NAME"],
        "email": _unique_email("par"),
        "household_size": DEFAULTS["HOUSEHOLD_SIZE"],
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(**overrides) -> dict:
    defaults = {
        "signed_at": DEFAULT_AGREEMENT_SIGNED_AT,
        "expires_at": DEFAULT_AGREEMENT_EXPIRES_AT,
        "agreement_version": 1,
    }
    defaults.update(overrides)
    return defaults


def create_session_payload(primary_facilitator_id, **overrides) -> dict:
    defaults = {
        "start_at": DEFAULTS["SESSION_START"],
        "end_at": DEFAULTS["SESSION_END"],
        "primary_facilitator_id": primary_facilitator_id,
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(participant_id, **overrides) -> dict:
    defaults = {"participant_id": participant_id}
    defaults.update(overrides)
    return defaults


def create_attendance_payload(participant_id, **overrides) -> dict:
    defaults = {"participant_id": participant_id, "access_modality": "IN_PERSON"}
    defaults.update(overrides)
    return defaults


def create_incident_payload(raised_by_facilitator_id, **overrides) -> dict:
    defaults = {
        "raised_by_facilitator_id": raised_by_facilitator_id,
        "severity": DEFAULTS["SEVERITY"],
        "category": DEFAULTS["CATEGORY"],
        "description": "incident narrative",
    }
    defaults.update(overrides)
    return defaults


def create_survey_payload(participant_id, **overrides) -> dict:
    defaults = {
        "participant_id": participant_id,
        "overall_rating": DEFAULTS["OVERALL_RATING"],
        "facilitator_rating": DEFAULTS["FACILITATOR_RATING"],
        "modality_rating": DEFAULTS["MODALITY_RATING"],
    }
    defaults.update(overrides)
    return defaults
