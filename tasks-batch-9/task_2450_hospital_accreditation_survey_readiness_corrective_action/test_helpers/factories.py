"""Payload factories — one per write operation, input fields only."""

from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS


def chapter_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "code": TEST_DEFAULTS["CHAPTER_CODE"],
        "name": TEST_DEFAULTS["CHAPTER_NAME"],
        "weight_pct": TEST_DEFAULTS["CHAPTER_WEIGHT_PCT"],
    }
    payload.update(overrides)
    return payload


def standard_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "standard_code": TEST_DEFAULTS["STANDARD_CODE"],
        "title": TEST_DEFAULTS["STANDARD_TITLE"],
        "risk_tier": "DIRECT_IMPACT",
    }
    payload.update(overrides)
    return payload


def owner_assignment_payload(**overrides) -> Dict[str, Any]:
    payload = {"owner_user_id": "owner-1", "designation": "PRIMARY"}
    payload.update(overrides)
    return payload


def evidence_item_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "title": "Fire drill log",
        "doc_type": "LOG",
        "effective_date": "2026-07-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def evidence_transition_payload(action: str, review_note: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    if review_note is not None:
        payload["review_note"] = review_note
    return payload


def unit_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "name": TEST_DEFAULTS["UNIT_NAME"],
        "unit_type": TEST_DEFAULTS["UNIT_TYPE"],
        "bed_count": TEST_DEFAULTS["BED_COUNT"],
    }
    payload.update(overrides)
    return payload


def mock_tracer_payload(unit_id: str, chapter_id: str, expected_unit_version: int, **overrides):
    payload = {
        "unit_id": unit_id,
        "chapter_id": chapter_id,
        "tracer_type": "PATIENT",
        "window_start": "2026-08-10T08:00:00Z",
        "window_end": "2026-08-10T12:00:00Z",
        "expected_unit_version": expected_unit_version,
    }
    payload.update(overrides)
    return payload


def observation_payload(standard_id: str, result: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"standard_id": standard_id, "result": result}
    payload.update(overrides)
    return payload


def tracer_transition_payload(action: str, abort_reason: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    if abort_reason is not None:
        payload["abort_reason"] = abort_reason
    return payload


def rounding_session_payload(unit_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "unit_id": unit_id,
        "round_type": "ENVIRONMENT_OF_CARE",
        "window_start": "2026-08-01T08:00:00Z",
        "window_end": "2026-08-01T12:00:00Z",
    }
    payload.update(overrides)
    return payload


def deficiency_payload(standard_id: str, severity: str, **overrides) -> Dict[str, Any]:
    payload = {
        "standard_id": standard_id,
        "description": "Blocked egress corridor",
        "severity": severity,
    }
    payload.update(overrides)
    return payload


def ticket_transition_payload(action: str, note: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    if note is not None:
        payload["note"] = note
    return payload


def survey_window_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "cycle_label": TEST_DEFAULTS["CYCLE_LABEL"],
        "prior_survey_end_date": "2025-03-15T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def window_transition_payload(action: str, note: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    if note is not None:
        payload["note"] = note
    return payload


def finding_payload(
    standard_id: str,
    unit_id: str,
    sampled_count: int,
    observed_noncompliance_count: int,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "standard_id": standard_id,
        "unit_id": unit_id,
        "sampled_count": sampled_count,
        "observed_noncompliance_count": observed_noncompliance_count,
    }
    payload.update(overrides)
    return payload


def esc_submission_payload(expected_finding_version: int, **overrides) -> Dict[str, Any]:
    payload = {
        "corrective_action_summary": "Retrained staff and revised the oversight policy",
        "measure_of_success": "Ninety percent compliance across three monthly audits",
        "leadership_signoff": True,
        "expected_finding_version": expected_finding_version,
    }
    payload.update(overrides)
    return payload


def esc_review_payload(decision: str, decision_note: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if decision_note is not None:
        payload["decision_note"] = decision_note
    return payload


def ppr_payload(period_label: str, self_ratings: List[Dict[str, str]]) -> Dict[str, Any]:
    return {"period_label": period_label, "self_ratings": self_ratings}


def self_rating(standard_id: str, rating: str) -> Dict[str, str]:
    return {"standard_id": standard_id, "rating": rating}
