"""Payload factories - one per entity, carrying only caller-supplied fields."""

from typing import Any, Dict

DEFAULT_CONDITION_CODE = "CP_MILD_ASD"
DEFAULT_PRECAUTION_CODE = "CP_SPASTIC"
DEFAULT_ACTIVITY_TYPE = "THERAPEUTIC_RIDING"


def condition_policy_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "condition_code": DEFAULT_CONDITION_CODE,
        "activity_type": DEFAULT_ACTIVITY_TYPE,
        "tier": "CLEAR",
        "min_instructor_tier": "REGISTERED",
    }
    payload.update(overrides)
    return payload


def rider_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "full_name": "Rae Rider",
        "date_of_birth": "2012-03-04",
        "weight_lb": 150,
        "household_income_band": "BAND_D",
        "demographic_group": "ADULT",
        "program_code": "THERAPEUTIC_RIDING",
        "condition_codes": [DEFAULT_CONDITION_CODE],
        "funding_mode": "PRIVATE_PAY_ALLOWED",
        "payer_rate_cents": 0,
    }
    payload.update(overrides)
    return payload


def medical_release_payload(expected_rider_version: int, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "signed_on": "2026-04-01",
        "physician_name": "Dr Oak",
        "cleared_condition_codes": [],
        "expected_rider_version": expected_rider_version,
    }
    payload.update(overrides)
    return payload


def assessment_payload(expected_rider_version: int, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "assessment_type": "INTAKE",
        "performed_on": "2026-04-01",
        "balance_score": 9,
        "trunk_control_score": 9,
        "rider_weight_lb": 150,
        "backriding_required": False,
        "expected_rider_version": expected_rider_version,
    }
    payload.update(overrides)
    return payload


def horse_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {"name": "Comet", "body_weight_lb": 1100, "tack_weight_lb": 30}
    payload.update(overrides)
    return payload


def volunteer_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "full_name": "Sam Sidewalker",
        "date_of_birth": "2000-02-02",
        "last_retraining_on": "2026-04-01",
    }
    payload.update(overrides)
    return payload


def qualification_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {"crew_role": "SIDEWALKER", "training_hours": 6}
    payload.update(overrides)
    return payload


def instructor_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "full_name": "Ada Reins",
        "certification_level": "MASTER",
        "certification_expires_at": "2028-04-30T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def session_payload(rider_id: str, horse_id: str, instructor_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "rider_id": rider_id,
        "horse_id": horse_id,
        "instructor_id": instructor_id,
        "activity_type": DEFAULT_ACTIVITY_TYPE,
        "scheduled_start": "2026-05-11T10:00:00Z",
        "duration_minutes": 60,
    }
    payload.update(overrides)
    return payload


def crew_assignment_payload(
    volunteer_id: str, crew_role: str, expected_session_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload = {
        "volunteer_id": volunteer_id,
        "crew_role": crew_role,
        "expected_session_version": expected_session_version,
    }
    payload.update(overrides)
    return payload


def goal_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "domain": "PHYSICAL",
        "objective": "Maintain independent posture for 10 minutes",
        "baseline_rating": 2,
        "target_rating": 4,
    }
    payload.update(overrides)
    return payload


def progress_note_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {"narrative": "Steady posture", "goal_ratings": []}
    payload.update(overrides)
    return payload


def grant_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "grant_name": "Hooves Fund",
        "funder_name": "County",
        "awarded_amount_cents": 3000,
        "period_start": "2026-01-01",
        "period_end": "2026-12-31",
    }
    payload.update(overrides)
    return payload


def scholarship_award_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "cap_pct": 0.5,
        "period_cap_cents": 5000,
        "period_start": "2026-01-01",
        "period_end": "2026-12-31",
    }
    payload.update(overrides)
    return payload


def incident_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "incident_type": "FALL",
        "injury_reported": True,
        "occurred_at": "2026-05-11T10:30:00Z",
        "narrative": "Rider dismounted unexpectedly and reported pain",
    }
    payload.update(overrides)
    return payload


def period_report_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {"period_start": "2026-05-01", "period_end": "2026-05-31"}
    payload.update(overrides)
    return payload
