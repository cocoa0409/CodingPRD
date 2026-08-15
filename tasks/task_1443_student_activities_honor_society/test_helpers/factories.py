"""Payload factories — one per creatable entity, input fields only."""
import uuid

from .constants import (
    ACADEMIC_YEAR,
    CYCLE_CLOSE_ISO,
    CYCLE_INDUCTION_ISO,
    CYCLE_LABEL,
    CYCLE_OPEN_ISO,
    DEFAULT_GPA_THRESHOLD_UNWEIGHTED,
    DEFAULT_GPA_THRESHOLD_WEIGHTED,
    DEFAULT_NATIONAL_DUES_CENTS,
    DEFAULT_SERVICE_HOURS_ANNUAL,
    DEFAULT_SERVICE_HOURS_PER_SEMESTER,
)


def _tag() -> str:
    return uuid.uuid4().hex[:8]


def create_chapter_payload(**overrides) -> dict:
    defaults = {
        "school_name": f"Test High {_tag()}",
        "charter_number": f"NHS-{_tag()}",
        "advisor_user_id": "adv-1",
        "gpa_threshold_weighted": DEFAULT_GPA_THRESHOLD_WEIGHTED,
        "gpa_threshold_unweighted": DEFAULT_GPA_THRESHOLD_UNWEIGHTED,
        "service_hours_annual_required": DEFAULT_SERVICE_HOURS_ANNUAL,
        "service_hours_per_semester_required": DEFAULT_SERVICE_HOURS_PER_SEMESTER,
        "national_dues_cents_per_member": DEFAULT_NATIONAL_DUES_CENTS,
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(**overrides) -> dict:
    tag = _tag()
    defaults = {
        "student_id": f"S-{tag}",
        "full_name": f"Student {tag}",
        "email": f"{tag}@example.com",
        "grade_level": 11,
        "weighted_gpa": 4.50,
        "unweighted_gpa": 3.90,
    }
    defaults.update(overrides)
    return defaults


def create_cycle_payload(**overrides) -> dict:
    defaults = {
        "cycle_label": CYCLE_LABEL,
        "academic_year": ACADEMIC_YEAR,
        "semester": "FALL",
        "nomination_open_date": CYCLE_OPEN_ISO,
        "nomination_close_date": CYCLE_CLOSE_ISO,
        "induction_date": CYCLE_INDUCTION_ISO,
    }
    defaults.update(overrides)
    return defaults


def create_service_entry_payload(**overrides) -> dict:
    defaults = {
        "activity_name": "Community service",
        "service_date": "2026-08-02T00:00:00Z",
        "hours": 2.0,
        "organization": "City Food Bank",
        "supervisor_email": "sup@example.org",
    }
    defaults.update(overrides)
    return defaults


def create_election_payload(cycle_id, office, **overrides) -> dict:
    defaults = {"cycle_id": cycle_id, "office": office}
    defaults.update(overrides)
    return defaults


def create_vote_payload(voter_member_id, candidate_member_id) -> dict:
    return {
        "voter_member_id": voter_member_id,
        "candidate_member_id": candidate_member_id,
    }


def create_minutes_payload(called_by_officer_id, attendees_member_ids,
                           **overrides) -> dict:
    defaults = {
        "meeting_date": "2026-09-10T18:00:00Z",
        "called_by_officer_id": called_by_officer_id,
        "attendees_member_ids": attendees_member_ids,
        "agenda": "Chapter agenda",
        "notes": "Minutes body v1",
    }
    defaults.update(overrides)
    return defaults


def create_fundraiser_payload(requested_by_officer_id, **overrides) -> dict:
    defaults = {
        "title": f"Fundraiser {_tag()}",
        "description": "Chapter fundraiser",
        "goal_amount_cents": 50000,
        "upfront_cost_cents": 0,
        "requested_by_officer_id": requested_by_officer_id,
        "scheduled_date": "2026-09-20T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_dues_payment_payload(**overrides) -> dict:
    defaults = {
        "academic_year": ACADEMIC_YEAR,
        "amount_cents": DEFAULT_NATIONAL_DUES_CENTS,
        "paid_at": "2026-09-06T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_probation_case_payload(opened_by_user_id, **overrides) -> dict:
    defaults = {
        "opened_by_user_id": opened_by_user_id,
        "reason_code": "CONDUCT_VIOLATION",
        "evidence_text": "Documented standards concern",
    }
    defaults.update(overrides)
    return defaults


def create_athletics_block_payload(member_id, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "block_start": "2026-08-30T00:00:00Z",
        "block_end": "2026-09-05T00:00:00Z",
        "sport": "Soccer",
        "priority": "GAME",
    }
    defaults.update(overrides)
    return defaults
