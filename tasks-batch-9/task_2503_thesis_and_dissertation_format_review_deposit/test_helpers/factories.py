"""Payload factories — one per entity, client-supplied input fields only."""

from typing import Any, Dict, List, Optional

DEFAULTS: Dict[str, Any] = {
    "TERM_CODE": "2026FA",
    "DEFENSE_DEADLINE": "2026-11-13T23:59:59Z",
    "FORMAT_REVIEW_DEPOSIT_DEADLINE": "2026-12-04T17:00:00Z",
    "DEGREE_CONFERRAL_DATE": "2026-12-18T00:00:00Z",
    "ANNOUNCEMENT_LEAD_BUSINESS_DAYS": 10,
    "STUDENT_NAME": "Ada Stone",
    "STUDENT_EMAIL": "ada@u.edu",
    "PROGRAM_CODE": "CS",
    "FACULTY_NAME": "Cara Cho",
    "FACULTY_EMAIL": "cho@u.edu",
    "ROOM_CODE": "R101",
    "ROOM_BUILDING": "Graduate Hall",
    "ROOM_SEAT_CAPACITY": 40,
    "ROOM_TURNOVER_BUFFER_MINUTES": 30,
    "THESIS_TITLE": "A Study of Formatting",
    "THESIS_PAGE_COUNT": 101,
    "SCHEDULED_START": "2026-09-25T14:00:00Z",
    "SCHEDULED_END": "2026-09-25T16:00:00Z",
    "ABSTRACT_WORD_COUNT": 150,
    "SUBJECT_KEYWORDS": ["a", "b", "c"],
}


def create_term_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "code": DEFAULTS["TERM_CODE"],
        "defense_deadline": DEFAULTS["DEFENSE_DEADLINE"],
        "format_review_deposit_deadline": DEFAULTS["FORMAT_REVIEW_DEPOSIT_DEADLINE"],
        "degree_conferral_date": DEFAULTS["DEGREE_CONFERRAL_DATE"],
        "announcement_lead_business_days": DEFAULTS["ANNOUNCEMENT_LEAD_BUSINESS_DAYS"],
    }
    payload.update(overrides)
    return payload


def create_student_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "full_name": DEFAULTS["STUDENT_NAME"],
        "email": DEFAULTS["STUDENT_EMAIL"],
        "degree_level": "MASTERS",
        "program_code": DEFAULTS["PROGRAM_CODE"],
    }
    payload.update(overrides)
    return payload


def create_faculty_member_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "full_name": DEFAULTS["FACULTY_NAME"],
        "email": DEFAULTS["FACULTY_EMAIL"],
        "appointment_type": "TENURED",
        "graduate_faculty_certified": True,
    }
    payload.update(overrides)
    return payload


def create_defense_room_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "code": DEFAULTS["ROOM_CODE"],
        "building": DEFAULTS["ROOM_BUILDING"],
        "seat_capacity": DEFAULTS["ROOM_SEAT_CAPACITY"],
        "turnover_buffer_minutes": DEFAULTS["ROOM_TURNOVER_BUFFER_MINUTES"],
    }
    payload.update(overrides)
    return payload


def create_thesis_payload(student_id: str, term_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "student_id": student_id,
        "term_id": term_id,
        "title": DEFAULTS["THESIS_TITLE"],
        "document_type": "THESIS",
        "page_count": DEFAULTS["THESIS_PAGE_COUNT"],
        "third_party_item_count": 0,
    }
    payload.update(overrides)
    return payload


def create_committee_payload(thesis_id: str, **overrides) -> Dict[str, Any]:
    payload = {"thesis_id": thesis_id}
    payload.update(overrides)
    return payload


def create_committee_member_payload(
    faculty_id: str, role: str = "MEMBER", **overrides
) -> Dict[str, Any]:
    payload = {"faculty_id": faculty_id, "role": role}
    payload.update(overrides)
    return payload


def create_defense_event_payload(
    thesis_id: str, room_id: str, **overrides
) -> Dict[str, Any]:
    payload = {
        "thesis_id": thesis_id,
        "room_id": room_id,
        "scheduled_start": DEFAULTS["SCHEDULED_START"],
        "scheduled_end": DEFAULTS["SCHEDULED_END"],
    }
    payload.update(overrides)
    return payload


def format_review_decision_payload(
    decision: str = "ACCEPT",
    critical_defect_count: int = 0,
    major_defect_count: int = 0,
    minor_defect_count: int = 0,
    **overrides
) -> Dict[str, Any]:
    payload = {
        "decision": decision,
        "critical_defect_count": critical_defect_count,
        "major_defect_count": major_defect_count,
        "minor_defect_count": minor_defect_count,
    }
    payload.update(overrides)
    return payload


def create_permission_record_payload(
    thesis_id: str,
    expected_thesis_version: int,
    material_type: str = "FIGURE",
    rights_basis: str = "WRITTEN_PERMISSION",
    page_reference: str = "p. 42",
    **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "thesis_id": thesis_id,
        "material_type": material_type,
        "rights_basis": rights_basis,
        "page_reference": page_reference,
        "expected_thesis_version": expected_thesis_version,
    }
    payload.update(overrides)
    return payload


def create_embargo_request_payload(
    thesis_id: str,
    expected_thesis_version: int,
    reason_code: str = "PUBLISHER_AGREEMENT",
    requested_months: int = 6,
    justification: str = "Publisher requires a six-month hold.",
    **overrides
) -> Dict[str, Any]:
    payload = {
        "thesis_id": thesis_id,
        "reason_code": reason_code,
        "requested_months": requested_months,
        "justification": justification,
        "expected_thesis_version": expected_thesis_version,
    }
    payload.update(overrides)
    return payload


def create_integrity_screening_payload(
    thesis_id: str, similarity_pct: float, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "thesis_id": thesis_id,
        "similarity_pct": similarity_pct,
    }
    payload.update(overrides)
    return payload


def create_repository_deposit_payload(
    thesis_id: str,
    abstract_word_count: int = DEFAULTS["ABSTRACT_WORD_COUNT"],
    subject_keywords: Optional[List[str]] = None,
    late_fee_paid_cents: int = 0,
    **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "thesis_id": thesis_id,
        "abstract_word_count": abstract_word_count,
        "subject_keywords": list(subject_keywords or DEFAULTS["SUBJECT_KEYWORDS"]),
        "late_fee_paid_cents": late_fee_paid_cents,
    }
    payload.update(overrides)
    return payload
