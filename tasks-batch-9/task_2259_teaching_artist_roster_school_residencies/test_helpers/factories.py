"""Payload factories — one per entity, input fields only."""
from typing import List, Optional

from .constants import TEST_DEFAULTS


def create_school_partner_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["SCHOOL_NAME"],
        "district_name": TEST_DEFAULTS["DISTRICT_NAME"],
        "grade_span": TEST_DEFAULTS["GRADE_SPAN"],
        "concurrent_session_capacity": TEST_DEFAULTS["CONCURRENT_SESSION_CAPACITY"],
        "total_enrollment": TEST_DEFAULTS["TOTAL_ENROLLMENT"],
        "frl_pct": TEST_DEFAULTS["FRL_PCT"],
        "ell_pct": TEST_DEFAULTS["ELL_PCT"],
        "iep_pct": TEST_DEFAULTS["IEP_PCT"],
    }
    payload.update(overrides)
    return payload


def create_calendar_blackout_payload(**overrides) -> dict:
    payload = {
        "blackout_type": "TESTING_WINDOW",
        "start_date": "2026-09-14",
        "end_date": "2026-09-18",
    }
    payload.update(overrides)
    return payload


def create_teaching_artist_payload(**overrides) -> dict:
    payload = {
        "full_name": TEST_DEFAULTS["ARTIST_NAME"],
        "email": TEST_DEFAULTS["ARTIST_EMAIL"],
        "primary_discipline": "DANCE",
        "secondary_disciplines": ["THEATER"],
        "grade_bands": ["G3_5", "G6_8"],
        "languages": ["en", "es"],
        "roster_tier_assigned": "APPRENTICE",
    }
    payload.update(overrides)
    return payload


def create_vetting_payload(to_vetting_status: str, **overrides) -> dict:
    payload = {"to_vetting_status": to_vetting_status}
    payload.update(overrides)
    return payload


def create_roster_status_payload(to_roster_status: str, **overrides) -> dict:
    payload = {"to_roster_status": to_roster_status}
    payload.update(overrides)
    return payload


def create_portfolio_review_payload(reviewer_user_id: str, **overrides) -> dict:
    payload = {
        "reviewer_user_id": reviewer_user_id,
        "artistic_quality_score": 3.5,
        "pedagogical_clarity_score": 4.0,
        "cultural_responsiveness_score": 3.2,
    }
    payload.update(overrides)
    return payload


def create_screening_payload(screening_type: str, **overrides) -> dict:
    payload = {
        "screening_type": screening_type,
        "outcome": "CLEARED",
        "effective_on": TEST_DEFAULTS["CLEARANCE_EFFECTIVE_ON"],
        "expires_on": TEST_DEFAULTS["CLEARANCE_EXPIRES_ON"],
    }
    payload.update(overrides)
    return payload


def create_arts_standard_payload(code: str, strand: str, **overrides) -> dict:
    payload = {
        "code": code,
        "discipline": "DANCE",
        "grade_band": "G3_5",
        "strand": strand,
        "description": f"State arts standard {code} for the {strand} strand.",
    }
    payload.update(overrides)
    return payload


def create_residency_payload(school_partner_id: str, **overrides) -> dict:
    payload = {
        "school_partner_id": school_partner_id,
        "title": TEST_DEFAULTS["RESIDENCY_TITLE"],
        "discipline": "DANCE",
        "grade_band": "G3_5",
        "instruction_language": "es",
        "contracted_session_count": TEST_DEFAULTS["CONTRACTED_SESSION_COUNT"],
        "session_length_minutes": TEST_DEFAULTS["SESSION_LENGTH_MINUTES"],
        "budget_cents": TEST_DEFAULTS["BUDGET_CENTS"],
        "materials_stipend_cents": TEST_DEFAULTS["MATERIALS_STIPEND_CENTS"],
        "collaboration_expectation": "CO_TEACH",
        "co_planning_hours_required": TEST_DEFAULTS["CO_PLANNING_HOURS_REQUIRED"],
        "required_strands": ["CREATING", "RESPONDING"],
        "term_start_date": TEST_DEFAULTS["TERM_START_DATE"],
        "term_end_date": TEST_DEFAULTS["TERM_END_DATE"],
        "enrolled_student_count": TEST_DEFAULTS["ENROLLED_STUDENT_COUNT"],
    }
    payload.update(overrides)
    return payload


def create_lead_artist_payload(teaching_artist_id: str) -> dict:
    return {"teaching_artist_id": teaching_artist_id}


def create_residency_status_payload(to_status: str, **overrides) -> dict:
    payload = {"to_status": to_status}
    payload.update(overrides)
    return payload


def create_lesson_plan_payload(
    residency_id: str,
    standard_codes: List[str],
    session_sequence_no: int = 1,
    **overrides,
) -> dict:
    payload = {
        "residency_id": residency_id,
        "title": "Movement and Meaning",
        "session_sequence_no": session_sequence_no,
        "standard_codes": standard_codes,
    }
    payload.update(overrides)
    return payload


def create_lesson_plan_review_payload(decision: str, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def create_lesson_plan_revision_payload(adaptation_summary: str, **overrides) -> dict:
    payload = {"adaptation_summary": adaptation_summary}
    payload.update(overrides)
    return payload


def create_session_payload(
    residency_id: str,
    assigned_artist_id: str,
    expected_residency_version: int,
    session_date: str = "2026-09-15",
    start_time: str = "09:00",
    end_time: str = "10:00",
    **overrides,
) -> dict:
    payload = {
        "residency_id": residency_id,
        "assigned_artist_id": assigned_artist_id,
        "session_date": session_date,
        "start_time": start_time,
        "end_time": end_time,
        "expected_residency_version": expected_residency_version,
    }
    payload.update(overrides)
    return payload


def create_confirm_payload(
    classroom_teacher_name: Optional[str] = None,
    co_planning_completed: bool = True,
    **overrides,
) -> dict:
    payload = {
        "classroom_teacher_name": (
            classroom_teacher_name or TEST_DEFAULTS["CLASSROOM_TEACHER_NAME"]
        ),
        "co_planning_completed": co_planning_completed,
    }
    payload.update(overrides)
    return payload


def create_reassign_payload(
    substitute_artist_id: str, expected_session_version: int, **overrides
) -> dict:
    payload = {
        "substitute_artist_id": substitute_artist_id,
        "expected_session_version": expected_session_version,
    }
    payload.update(overrides)
    return payload


def create_cancel_payload(cancel_reason: str, **overrides) -> dict:
    payload = {"cancel_reason": cancel_reason}
    payload.update(overrides)
    return payload


def create_deliver_payload(
    students_present_count: int = 24,
    minutes_delivered: int = 60,
    travel_miles: float = 0.0,
    materials_spend_cents: int = 0,
    **overrides,
) -> dict:
    payload = {
        "students_present_count": students_present_count,
        "minutes_delivered": minutes_delivered,
        "travel_miles": travel_miles,
        "materials_spend_cents": materials_spend_cents,
    }
    payload.update(overrides)
    return payload


def create_observation_rubric_payload(
    evaluator_user_id: str,
    rubric_engagement_score: int = 4,
    rubric_craft_score: int = 3,
    rubric_standards_evidence_score: int = 4,
    **overrides,
) -> dict:
    payload = {
        "evaluation_type": "OBSERVATION_RUBRIC",
        "evaluator_user_id": evaluator_user_id,
        "rubric_engagement_score": rubric_engagement_score,
        "rubric_craft_score": rubric_craft_score,
        "rubric_standards_evidence_score": rubric_standards_evidence_score,
    }
    payload.update(overrides)
    return payload


def create_teacher_survey_payload(
    evaluator_user_id: str, teacher_survey_score: int = 4, **overrides
) -> dict:
    payload = {
        "evaluation_type": "TEACHER_SURVEY",
        "evaluator_user_id": evaluator_user_id,
        "teacher_survey_score": teacher_survey_score,
    }
    payload.update(overrides)
    return payload


def create_student_work_sample_payload(
    evaluator_user_id: str, student_work_artifact_count: int = 12, **overrides
) -> dict:
    payload = {
        "evaluation_type": "STUDENT_WORK_SAMPLE",
        "evaluator_user_id": evaluator_user_id,
        "student_work_artifact_count": student_work_artifact_count,
    }
    payload.update(overrides)
    return payload


def create_payment_voucher_payload(
    teaching_artist_id: str,
    residency_id: str,
    session_ids: List[str],
    period_start: str = "2026-09-01",
    period_end: str = "2026-09-30",
    **overrides,
) -> dict:
    payload = {
        "teaching_artist_id": teaching_artist_id,
        "residency_id": residency_id,
        "session_ids": session_ids,
        "period_start": period_start,
        "period_end": period_end,
    }
    payload.update(overrides)
    return payload


def create_voucher_review_payload(
    review_track: str,
    decision: str,
    expected_payment_voucher_version: int,
    **overrides,
) -> dict:
    payload = {
        "review_track": review_track,
        "decision": decision,
        "expected_payment_voucher_version": expected_payment_voucher_version,
    }
    payload.update(overrides)
    return payload


def create_void_payload(void_reason: str) -> dict:
    return {"void_reason": void_reason}


def create_funder_report_payload(
    scope_residency_ids: List[str],
    funder_name: str = "Cascade Arts Trust",
    grant_code: str = "CAT-2026-09",
    period_start: str = "2026-09-01",
    period_end: str = "2026-09-30",
    headcount_basis: str = "UNDUPLICATED",
    **overrides,
) -> dict:
    payload = {
        "funder_name": funder_name,
        "grant_code": grant_code,
        "period_start": period_start,
        "period_end": period_end,
        "scope_residency_ids": scope_residency_ids,
        "headcount_basis": headcount_basis,
    }
    payload.update(overrides)
    return payload


def create_certify_payload(
    certifier_user_id: str,
    attestation_text: str = "Figures reviewed and attested.",
) -> dict:
    return {
        "certifier_user_id": certifier_user_id,
        "attestation_text": attestation_text,
    }
