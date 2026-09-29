"""Payload factories. Each factory emits only the request fields the PRD
declares for that endpoint, with sensible defaults that satisfy every
field-level constraint.
"""

from .constants import CONFERENCE_CALENDAR, TEST_DEFAULTS


def set_clock_payload(current_utc: str) -> dict:
    return {"current_utc": current_utc}


def create_conference_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["CONFERENCE_NAME"],
        "code": TEST_DEFAULTS["CONFERENCE_CODE"],
        "event_start_utc": CONFERENCE_CALENDAR["event_start_utc"],
        "event_end_utc": CONFERENCE_CALENDAR["event_end_utc"],
        "abstract_deadline_utc": CONFERENCE_CALENDAR["abstract_deadline_utc"],
        "review_deadline_utc": CONFERENCE_CALENDAR["review_deadline_utc"],
        "program_freeze_utc": CONFERENCE_CALENDAR["program_freeze_utc"],
        "oral_slot_capacity": 3,
        "poster_slot_capacity": 2,
        "workshop_slot_capacity": 1,
        "cme_minutes_pool_total": TEST_DEFAULTS["CME_MINUTES_POOL_TOTAL"],
    }
    payload.update(overrides)
    return payload


def create_category_payload(conference_id: str, **overrides) -> dict:
    payload = {
        "conference_id": conference_id,
        "code": TEST_DEFAULTS["CATEGORY_CODE"],
        "name": TEST_DEFAULTS["CATEGORY_NAME"],
        "max_word_count": TEST_DEFAULTS["MAX_WORD_COUNT"],
        "allowed_formats": ["ORAL", "POSTER"],
        "requires_structured_body": False,
        "min_reviews_required": 2,
        "discrepancy_threshold": 4.00,
        "cme_eligible": True,
    }
    payload.update(overrides)
    return payload


def create_author_payload(**overrides) -> dict:
    payload = {
        "full_name": "Ada Rivera",
        "email": "ada@lab.example",
        "affiliation": "Northline University",
    }
    payload.update(overrides)
    return payload


def register_author_payload(is_registered: bool = True) -> dict:
    return {"is_registered": is_registered}


def create_abstract_payload(
    conference_id: str, category_id: str, submitting_author_id: str, **overrides
) -> dict:
    payload = {
        "conference_id": conference_id,
        "category_id": category_id,
        "submitting_author_id": submitting_author_id,
        "title": "Immunotherapy response imaging",
        "body_word_count": 280,
        "requested_format": "ORAL",
        "keywords": list(TEST_DEFAULTS["ABSTRACT_KEYWORDS"]),
        "body_structured": True,
        "coauthor_emails": [],
        "is_newsworthy": False,
    }
    payload.update(overrides)
    return payload


def revise_abstract_payload(body_word_count: int, **overrides) -> dict:
    payload = {"body_word_count": body_word_count}
    payload.update(overrides)
    return payload


def status_transition_payload(to_status: str, **overrides) -> dict:
    payload = {"to_status": to_status}
    payload.update(overrides)
    return payload


def decision_payload(decision: str, expected_conference_version: int, **overrides) -> dict:
    payload = {
        "decision": decision,
        "expected_conference_version": expected_conference_version,
    }
    payload.update(overrides)
    return payload


def review_assignment_payload(**overrides) -> dict:
    payload: dict = {}
    payload.update(overrides)
    return payload


def press_action_payload(action: str, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


def create_committee_member_payload(
    conference_id: str, member_role: str = "REVIEWER", **overrides
) -> dict:
    payload = {
        "conference_id": conference_id,
        "full_name": "Rui Alvarez",
        "email": "rui@panel.example",
        "member_role": member_role,
        "expertise_keywords": list(TEST_DEFAULTS["REVIEWER_KEYWORDS"]),
        "max_review_load": 4,
        "calibration_bias": 0.00,
    }
    payload.update(overrides)
    return payload


def create_conflict_declaration_payload(member_id: str, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "conflict_subject_type": "NONE",
        "conflict_type": "NONE",
    }
    payload.update(overrides)
    return payload


def submit_review_payload(
    score_originality: int = 4,
    score_methodology: int = 4,
    score_relevance: int = 4,
    score_clarity: int = 4,
    confidence: str = "HIGH",
    recommended_format: str = "ORAL",
    **overrides,
) -> dict:
    payload = {
        "score_originality": score_originality,
        "score_methodology": score_methodology,
        "score_relevance": score_relevance,
        "score_clarity": score_clarity,
        "confidence": confidence,
        "recommended_format": recommended_format,
    }
    payload.update(overrides)
    return payload


def decline_review_payload(decline_reason: str = "outside my expertise", **overrides) -> dict:
    payload = {"decline_reason": decline_reason}
    payload.update(overrides)
    return payload


def assign_arbiter_payload(arbiter_member_id: str) -> dict:
    return {"arbiter_member_id": arbiter_member_id}


def resolution_payload(resolution_method: str, **overrides) -> dict:
    payload = {"resolution_method": resolution_method}
    payload.update(overrides)
    return payload


def create_session_payload(conference_id: str, chair_member_id: str, **overrides) -> dict:
    payload = {
        "conference_id": conference_id,
        "chair_member_id": chair_member_id,
        "theme_code": "oncology",
        "format": "ORAL",
        "room_code": "HALL-A",
        "start_utc": "2026-09-01T09:00:00Z",
        "end_utc": "2026-09-01T10:00:00Z",
        "capacity_slots": 3,
        "cme_designated": False,
    }
    payload.update(overrides)
    return payload


def create_session_slot_payload(
    abstract_id: str,
    presenter_author_id: str,
    position: int,
    duration_minutes: int,
    expected_session_version: int,
    **overrides,
) -> dict:
    payload = {
        "abstract_id": abstract_id,
        "presenter_author_id": presenter_author_id,
        "position": position,
        "duration_minutes": duration_minutes,
        "expected_session_version": expected_session_version,
    }
    payload.update(overrides)
    return payload


def create_accreditation_payload(abstract_id: str, content_minutes: int, **overrides) -> dict:
    payload = {
        "abstract_id": abstract_id,
        "content_minutes": content_minutes,
        "commercial_support_disclosed": False,
    }
    payload.update(overrides)
    return payload


def accreditation_validation_payload(action: str, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


def create_disclosure_statement_payload(
    abstract_id: str,
    accreditation_id: str,
    author_id: str,
    has_financial_relationship: bool = False,
    **overrides,
) -> dict:
    payload = {
        "abstract_id": abstract_id,
        "accreditation_id": accreditation_id,
        "author_id": author_id,
        "has_financial_relationship": has_financial_relationship,
    }
    payload.update(overrides)
    return payload


def disclosure_adjudication_payload(outcome: str, **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def create_program_change_request_payload(
    session_slot_id: str, change_type: str, **overrides
) -> dict:
    payload = {"session_slot_id": session_slot_id, "change_type": change_type}
    payload.update(overrides)
    return payload


def change_request_adjudication_payload(outcome: str, **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def update_committee_member_payload(**overrides) -> dict:
    payload: dict = {}
    payload.update(overrides)
    return payload
