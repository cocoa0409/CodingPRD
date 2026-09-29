"""Payload factories - one per entity, carrying only client-supplied fields."""
from typing import Any, Dict

from .constants import TEST_DEFAULTS


def create_session_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "name": TEST_DEFAULTS["SESSION_NAME"],
        "introduction_deadline_utc": TEST_DEFAULTS["INTRODUCTION_DEADLINE_UTC"],
        "committee_report_deadline_utc": TEST_DEFAULTS["COMMITTEE_REPORT_DEADLINE_UTC"],
        "sine_die_utc": TEST_DEFAULTS["SINE_DIE_UTC"],
        "constrained_threshold_cents": TEST_DEFAULTS["CONSTRAINED_THRESHOLD_CENTS"],
        "fiscal_cap_cents": TEST_DEFAULTS["FISCAL_CAP_CENTS"],
        "required_fiscal_years": list(TEST_DEFAULTS["REQUIRED_FISCAL_YEARS"]),
        "fiscal_note_default_days": TEST_DEFAULTS["FISCAL_NOTE_DEFAULT_DAYS"],
    }
    payload.update(overrides)
    return payload


def create_committee_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "chamber": "HOUSE",
        "name": "House Appropriations",
        "is_fiscal_committee": True,
        "max_concurrent_referrals": 2,
    }
    payload.update(overrides)
    return payload


def create_member_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "full_name": "Rep Alpha",
        "chamber": "HOUSE",
        "party": "IND",
        "priority_slots_total": 2,
    }
    payload.update(overrides)
    return payload


def create_drafter_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "full_name": "Drafter One",
        "is_senior": False,
        "max_concurrent_engagements": 2,
    }
    payload.update(overrides)
    return payload


def create_agency_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "name": "Dept of Transportation",
        "agency_code": "DOT",
        "status": "ACTIVE",
        "max_open_requests": 3,
    }
    payload.update(overrides)
    return payload


def create_drafting_request_payload(session_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "session_id": session_id,
        "subject": "Bridge rehabilitation program",
        "summary": "Create a bridge rehabilitation program.",
        "requested_sections_count": 3,
        "target_code_chapter": "Title 23",
        "confidentiality": "PUBLIC",
        "priority_flag": False,
        "appropriation_requested_cents": 0,
    }
    payload.update(overrides)
    return payload


def assign_payload(drafter_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "drafter_id": drafter_id,
        "engagement_start_utc": "2026-09-02T00:00:00Z",
        "engagement_end_utc": "2026-09-05T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def complete_research_payload(affected_sections_count: int = 3, **overrides) -> Dict[str, Any]:
    payload = {"affected_sections_count": affected_sections_count}
    payload.update(overrides)
    return payload


def clarify_payload(**overrides) -> Dict[str, Any]:
    payload = {"clarification_note": "Sponsor answered the drafting question."}
    payload.update(overrides)
    return payload


def certify_draft_payload(style_findings_count: int = 0, **overrides) -> Dict[str, Any]:
    payload = {"style_findings_count": style_findings_count}
    payload.update(overrides)
    return payload


def withdraw_payload(**overrides) -> Dict[str, Any]:
    payload = {"withdrawal_reason": "Sponsor withdrew the measure."}
    payload.update(overrides)
    return payload


def create_statutory_conflict_payload(drafting_request_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "drafting_request_id": drafting_request_id,
        "code_citation": "23-1-101",
        "conflict_type": "AMENDS_SAME_SECTION",
        "severity": "ADVISORY",
    }
    payload.update(overrides)
    return payload


def resolve_conflict_payload(resolution_status: str = "RESOLVED", **overrides) -> Dict[str, Any]:
    payload = {
        "resolution_status": resolution_status,
        "resolution_note": "Conflict addressed in the redraft.",
    }
    payload.update(overrides)
    return payload


def create_bill_payload(drafting_request_id: str, **overrides) -> Dict[str, Any]:
    payload = {"drafting_request_id": drafting_request_id}
    payload.update(overrides)
    return payload


def companion_payload(companion_bill_id: str, **overrides) -> Dict[str, Any]:
    payload = {"companion_bill_id": companion_bill_id}
    payload.update(overrides)
    return payload


def create_referral_payload(committee_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "committee_id": committee_id,
        "hearing_window_start_utc": "2026-10-05T14:00:00Z",
        "hearing_window_end_utc": "2026-10-05T16:00:00Z",
    }
    payload.update(overrides)
    return payload


def report_payload(outcome: str = "FAVORABLE", **overrides) -> Dict[str, Any]:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def create_fiscal_note_request_payload(agency_id: str, **overrides) -> Dict[str, Any]:
    payload = {"agency_id": agency_id, "methodology": "INCREMENTAL_COST"}
    payload.update(overrides)
    return payload


def create_cost_estimate_payload(
    expected_fiscal_note_request_version: int,
    fiscal_year: int = 2027,
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "expected_fiscal_note_request_version": expected_fiscal_note_request_version,
        "fiscal_year": fiscal_year,
        "scenario": "BASELINE",
        "personnel_cost_cents": 20_000_000,
        "operating_cost_cents": 3_148_148,
        "one_time_cost_cents": 0,
        "fte_count": 1.0,
        "revenue_impact_cents": 0,
        "assumption_note": "Standard crew and materials.",
    }
    payload.update(overrides)
    return payload


def submit_note_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def return_note_payload(**overrides) -> Dict[str, Any]:
    payload = {"return_reason": "Assumptions need restating."}
    payload.update(overrides)
    return payload


def certify_note_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def create_amendment_payload(
    expected_bill_version: int, bill_id: str, **overrides
) -> Dict[str, Any]:
    payload = {
        "expected_bill_version": expected_bill_version,
        "bill_id": bill_id,
        "stage": "FLOOR",
        "summary": "Add a rural set-aside.",
        "fiscal_impact_delta_cents": 0,
        "drafting_start_utc": "2026-10-06T00:00:00Z",
        "drafting_due_utc": "2026-10-06T00:30:00Z",
    }
    payload.update(overrides)
    return payload


def draft_amendment_payload(**overrides) -> Dict[str, Any]:
    payload = {"draft_text": "On page 2, line 8, strike 'two' and insert 'three'."}
    payload.update(overrides)
    return payload


def reject_amendment_payload(**overrides) -> Dict[str, Any]:
    payload = {"rejection_reason": "Amendment not germane."}
    payload.update(overrides)
    return payload


def rescind_amendment_payload(**overrides) -> Dict[str, Any]:
    payload = {"rescission_reason": "Set-aside withdrawn on the floor."}
    payload.update(overrides)
    return payload


def create_technical_correction_payload(
    expected_enrolled_bill_version: int, **overrides
) -> Dict[str, Any]:
    payload = {
        "expected_enrolled_bill_version": expected_enrolled_bill_version,
        "correction_type": "TYPO",
        "description": "Correct a misspelled defined term.",
        "is_substantive": False,
    }
    payload.update(overrides)
    return payload


def signature_payload(signature_role: str, **overrides) -> Dict[str, Any]:
    payload = {"signature_role": signature_role}
    payload.update(overrides)
    return payload
