"""Payload factories — one per create/action endpoint, input fields only (PRD §3)."""
from . import constants


def create_candidate_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Candidate",
        "employee_id": "E0000",
        "department": "CS",
        "college": "ENG",
        "tenure_clock_start": constants.TENURE_CLOCK_START,
    }
    defaults.update(overrides)
    return defaults


def create_case_payload(**overrides) -> dict:
    defaults = {
        "review_cycle": "2026-2027",
        "target_rank": "ASSOCIATE_PROFESSOR",
        "seeking_tenure": True,
        "clock_policy": "ANNIVERSARY",
    }
    defaults.update(overrides)
    return defaults


def create_dossier_item_payload(**overrides) -> dict:
    defaults = {
        "category": "TEACHING",
        "title": "Evidence item",
        "page_count": 10,
    }
    defaults.update(overrides)
    return defaults


def create_reviewer_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Reviewer",
        "institution": "MIT",
        "email": "reviewer@mit.edu",
        "expertise_area": "CS",
    }
    defaults.update(overrides)
    return defaults


def create_invitation_payload(**overrides) -> dict:
    defaults = {
        "review_window_start": constants.REVIEW_WINDOW_START,
        "review_window_end": constants.REVIEW_WINDOW_END,
        "is_arm_length": True,
        "declared_coauthor": False,
    }
    defaults.update(overrides)
    return defaults


def create_committee_payload(**overrides) -> dict:
    defaults = {
        "level": "DEPARTMENT",
        "academic_unit": "CS",
        "term_start": constants.TERM_START,
        "term_end": constants.TERM_END,
        "pass_rule": "STRICT_MAJORITY_OF_CAST",
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Committee Member",
        "email": "member@u.edu",
        "service_start": constants.SERVICE_START,
        "service_end": constants.SERVICE_END,
    }
    defaults.update(overrides)
    return defaults


def create_vote_payload(**overrides) -> dict:
    defaults = {"ballot": "YES"}
    defaults.update(overrides)
    return defaults


def patch_vote_payload(**overrides) -> dict:
    defaults = {"ballot": "NO"}
    defaults.update(overrides)
    return defaults


def certify_round_payload(**overrides) -> dict:
    defaults = {"recommendation": "SUPPORT", "letter_text": "Committee letter."}
    defaults.update(overrides)
    return defaults


def submit_letter_payload(**overrides) -> dict:
    defaults = {"letter_text": "External letter."}
    defaults.update(overrides)
    return defaults


def create_clock_extension_payload(**overrides) -> dict:
    defaults = {
        "reason": "MEDICAL_LEAVE",
        "interval_start": "2023-01-01",
        "interval_end": "2023-04-01",
    }
    defaults.update(overrides)
    return defaults


def create_midterm_review_payload(**overrides) -> dict:
    defaults = {"review_year": 3}
    defaults.update(overrides)
    return defaults


def complete_midterm_payload(**overrides) -> dict:
    defaults = {"outcome": "SATISFACTORY"}
    defaults.update(overrides)
    return defaults


def create_decision_payload(**overrides) -> dict:
    defaults = {"decision": "GRANT_TENURE", "rationale_text": "Decision rationale."}
    defaults.update(overrides)
    return defaults


def create_appeal_payload(**overrides) -> dict:
    defaults = {"grounds": "PROCEDURAL_ERROR"}
    defaults.update(overrides)
    return defaults


def resolve_appeal_payload(**overrides) -> dict:
    defaults = {"resolution": "DENIED", "resolution_text": "Resolution rationale."}
    defaults.update(overrides)
    return defaults


def set_clock_payload(**overrides) -> dict:
    defaults = {"to_iso8601": constants.CLOCK_STARTUP_DEFAULT}
    defaults.update(overrides)
    return defaults
