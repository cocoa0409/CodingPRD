"""Payload factories.

Every numeric field is emitted as a JSON number (never a string) and every
timestamp as an ISO 8601 UTC instant. Overrides are applied last so a test can
change or delete any single field.
"""

import itertools
from typing import Any, Dict

_counter = itertools.count(1)


def _next() -> int:
    return next(_counter)


def _apply(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in overrides.items():
        if value is _OMIT:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


class _Omit:
    """Sentinel that removes a field from a factory payload."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<OMIT>"


_OMIT = _Omit()
OMIT = _OMIT


# --------------------------------------------------------------- audit program
def audit_program_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "name": f"Communications Center QA Program {_next()}",
        "accreditation_body": "IAED",
    }
    return _apply(payload, overrides)


def full_audit_program_payload(**overrides: Any) -> Dict[str, Any]:
    """Every optional threshold supplied explicitly."""
    payload = {
        "name": f"Communications Center QA Program {_next()}",
        "accreditation_body": "IAED",
        "target_compliance_pct": 90.0,
        "watch_floor_pct": 80.0,
        "high_risk_target_pct": 85.0,
        "review_deadline_days": 30,
        "rebuttal_window_days": 14,
        "max_rebuttal_rounds": 2,
        "escalated_sample_floor": 25,
        "hours_owed_restriction_threshold": 6.0,
    }
    return _apply(payload, overrides)


# ------------------------------------------------------------ protocol version
def protocol_version_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "protocol_family": "MPDS_CARDSET",
        "version_label": f"MPDS-13.{_next()}",
        "effective_from": "2026-07-01T00:00:00Z",
        "case_entry_weight": 0.2000,
        "key_questions_weight": 0.3500,
        "pre_arrival_weight": 0.3000,
        "final_coding_weight": 0.1500,
    }
    return _apply(payload, overrides)


def rollout_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "scheduled_golive_at": "2026-08-01T00:00:00Z",
        "target_dispatcher_count": 1,
        "required_training_hours": 2.0,
    }
    return _apply(payload, overrides)


# ------------------------------------------------------------------ dispatcher
def dispatcher_payload(program_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "program_id": program_id,
        "employee_code": f"EMD-{1000 + _next()}",
        "full_name": f"Dispatcher {_next()}",
    }
    return _apply(payload, overrides)


# ----------------------------------------------------------------- call record
def call_record_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "call_reference": f"C-{100000 + _next()}",
        "call_type": "CHEST_PAIN",
        "received_at": "2026-08-05T09:00:00Z",
        "dispatched_determinant_code": "10-C-4",
    }
    return _apply(payload, overrides)


def cardiac_arrest_call_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "call_reference": f"C-{200000 + _next()}",
        "call_type": "CARDIAC_ARREST",
        "received_at": "2026-08-05T09:00:00Z",
        "dispatched_determinant_code": "9-E-1",
        "cardiac_arrest_confirmed": True,
        "bystander_cpr_in_progress": False,
    }
    return _apply(payload, overrides)


# -------------------------------------------------------------- sampling period
def sampling_period_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "call_type": "CHEST_PAIN",
        "period_start": "2026-08-01T00:00:00Z",
        "period_end": "2026-09-01T00:00:00Z",
        "sampling_mode": "TARGETED",
        "target_sample_count": 1,
    }
    return _apply(payload, overrides)


def target_review_payload(call_record_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {"call_record_id": call_record_id, "selection_reason": "COMPLAINT"}
    return _apply(payload, overrides)


# ------------------------------------------------------------------ score sheet
def score_payload(expected_review_version: int, **overrides: Any) -> Dict[str, Any]:
    """An all-90% sheet with an accurate determinant code."""
    payload = {
        "expected_review_version": expected_review_version,
        "case_entry_points_earned": 18,
        "case_entry_points_possible": 20,
        "key_questions_points_earned": 27,
        "key_questions_points_possible": 30,
        "pre_arrival_points_earned": 9,
        "pre_arrival_points_possible": 10,
        "final_coding_points_earned": 9,
        "final_coding_points_possible": 10,
        "reviewer_determinant_code": "10-C-4",
    }
    return _apply(payload, overrides)


def perfect_score_payload(expected_review_version: int, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "expected_review_version": expected_review_version,
        "case_entry_points_earned": 20,
        "case_entry_points_possible": 20,
        "key_questions_points_earned": 30,
        "key_questions_points_possible": 30,
        "pre_arrival_points_earned": 10,
        "pre_arrival_points_possible": 10,
        "final_coding_points_earned": 10,
        "final_coding_points_possible": 10,
        "reviewer_determinant_code": "10-C-4",
    }
    return _apply(payload, overrides)


def section_score_payload(
    expected_review_version: int,
    sections: Dict[str, Any],
    reviewer_determinant_code: str = "10-C-4",
    **overrides: Any,
) -> Dict[str, Any]:
    """Build a sheet from explicit (earned, possible) pairs per section."""
    payload = {"expected_review_version": expected_review_version}
    for prefix in ("case_entry", "key_questions", "pre_arrival", "final_coding"):
        earned, possible = sections[prefix]
        payload[f"{prefix}_points_earned"] = earned
        payload[f"{prefix}_points_possible"] = possible
    payload["reviewer_determinant_code"] = reviewer_determinant_code
    return _apply(payload, overrides)


# --------------------------------------------------------------------- rebuttal
def rebuttal_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "grounds_category": "SCORING_DISPUTE",
        "narrative": "The key questions section was scored against the wrong card.",
    }
    return _apply(payload, overrides)


def rebuttal_decision_payload(decision: str = "REJECTED", **overrides: Any) -> Dict[str, Any]:
    payload = {"decision": decision, "decision_notes": "Reviewed the audio with the reviewer."}
    return _apply(payload, overrides)


# ------------------------------------------------------------ high-risk review
def high_risk_review_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {"outcome_category": "ROSC_FIELD"}
    return _apply(payload, overrides)


def dacpr_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "cardiac_arrest_recognized": True,
        "recognition_time_sec": 15,
        "time_to_first_compression_sec": 45,
        "dacpr_instructions_delivered": True,
        "compressions_coached": True,
    }
    return _apply(payload, overrides)


def sign_off_payload(classification: str = "COACHING_ONLY", **overrides: Any) -> Dict[str, Any]:
    payload = {"classification": classification, "director_notes": "Case discussed with the reviewer."}
    return _apply(payload, overrides)


# ------------------------------------------------------------------ coaching
def coaching_plan_payload(
    dispatcher_id: str, expected_dispatcher_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload = {
        "dispatcher_id": dispatcher_id,
        "expected_dispatcher_version": expected_dispatcher_version,
        "severity": "STANDARD",
        "focus_area": "KEY_QUESTIONS",
    }
    return _apply(payload, overrides)


def retraining_session_payload(protocol_version_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "protocol_version_id": protocol_version_id,
        "starts_at": "2026-08-15T09:00:00Z",
        "ends_at": "2026-08-15T11:00:00Z",
        "modality": "CLASSROOM",
    }
    return _apply(payload, overrides)


# ------------------------------------------------------- accreditation report
def accreditation_report_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "window_start": "2026-08-01T00:00:00Z",
        "window_end": "2026-09-01T00:00:00Z",
        "variant": "CASE_WEIGHTED",
    }
    return _apply(payload, overrides)


def report_submission_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {"submitted_to": "MEDICAL_DIRECTOR"}
    return _apply(payload, overrides)


# ----------------------------------------------------------------------- clock
def clock_payload(to_iso8601: str, **overrides: Any) -> Dict[str, Any]:
    payload = {"to_iso8601": to_iso8601}
    return _apply(payload, overrides)
