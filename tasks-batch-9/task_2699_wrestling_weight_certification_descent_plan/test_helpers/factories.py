"""
Request-body builders.

Every weight, allowance, body-fat percentage and specific-gravity reading is
emitted as a JSON number — a Python ``int`` or ``float`` — never as a string,
because the specification declares them as numeric fields with numeric ranges.
Optional fields are omitted entirely unless a caller supplies them, so the
server's declared defaults are exercised rather than shadowed; a caller that
genuinely wants to send an explicit ``null`` passes the field with ``None`` and
the builder keeps it, which is what the ``_include`` sentinel distinguishes.
"""

from typing import Any, Dict, List, Optional, Sequence

from .constants import (
    ASSESSED_AT,
    CANON_BODY_FAT_PCT,
    CANON_MEASURED_WEIGHT_LBS,
    CANON_USG_PASS,
    DEFAULT_ASSESSOR_NAME,
    DEFAULT_CREDENTIAL_EXPIRY,
    DEFAULT_CREDENTIAL_NUMBER,
    DEFAULT_TRAINING_CODE,
    DEFAULT_WRESTLER_GRADE,
    DEFAULT_WRESTLER_NAME,
    EVENT_TYPE_TOURNAMENT,
    METHOD_BIA,
    METHOD_SKINFOLD,
    SEASON_NAME,
    SEASON_START_DATE,
    SEX_MALE,
    VARIANT_WEEKLY_STEP,
)

# A sentinel that means "the caller said nothing about this field".
_OMITTED = object()


def _put(payload: Dict[str, Any], key: str, value: Any) -> None:
    """Add ``key`` to the payload unless the caller omitted it."""
    if value is not _OMITTED:
        payload[key] = value


# ── The logical clock ────────────────────────────────────────────────

def clock_payload(to_iso8601: str) -> Dict[str, Any]:
    """The body that moves the logical clock to a UTC instant."""
    return {"to_iso8601": to_iso8601}


# ── Season ───────────────────────────────────────────────────────────

def season_payload(
    name: str = SEASON_NAME,
    start_date: str = SEASON_START_DATE,
    weight_classes: Any = _OMITTED,
    min_body_fat_pct_male: Any = _OMITTED,
    min_body_fat_pct_female: Any = _OMITTED,
    hydration_max_specific_gravity: Any = _OMITTED,
    max_weekly_descent_pct: Any = _OMITTED,
    assessor_min_training_hours: Any = _OMITTED,
    audit_fail_threshold_pct: Any = _OMITTED,
    audit_min_sample_count: Any = _OMITTED,
    max_consecutive_day_allowance_lbs: Any = _OMITTED,
    appeal_filing_window_days: Any = _OMITTED,
    max_appeal_retest_rounds: Any = _OMITTED,
    assessor_daily_assessment_capacity: Any = _OMITTED,
    plan_breach_limit: Any = _OMITTED,
) -> Dict[str, Any]:
    """A season creation body; every constant is left to its default unless set."""
    payload: Dict[str, Any] = {"name": name, "start_date": start_date}
    _put(payload, "weight_classes", weight_classes)
    _put(payload, "min_body_fat_pct_male", min_body_fat_pct_male)
    _put(payload, "min_body_fat_pct_female", min_body_fat_pct_female)
    _put(payload, "hydration_max_specific_gravity", hydration_max_specific_gravity)
    _put(payload, "max_weekly_descent_pct", max_weekly_descent_pct)
    _put(payload, "assessor_min_training_hours", assessor_min_training_hours)
    _put(payload, "audit_fail_threshold_pct", audit_fail_threshold_pct)
    _put(payload, "audit_min_sample_count", audit_min_sample_count)
    _put(payload, "max_consecutive_day_allowance_lbs", max_consecutive_day_allowance_lbs)
    _put(payload, "appeal_filing_window_days", appeal_filing_window_days)
    _put(payload, "max_appeal_retest_rounds", max_appeal_retest_rounds)
    _put(payload, "assessor_daily_assessment_capacity", assessor_daily_assessment_capacity)
    _put(payload, "plan_breach_limit", plan_breach_limit)
    return payload


def season_status_payload(status: str) -> Dict[str, Any]:
    return {"status": status}


def growth_allowance_payload(
    effective_date: str, allowance_lbs: float, note: Any = _OMITTED
) -> Dict[str, Any]:
    """A published growth-allowance date; ``allowance_lbs`` is a JSON number."""
    payload: Dict[str, Any] = {
        "effective_date": effective_date,
        "allowance_lbs": allowance_lbs,
    }
    _put(payload, "note", note)
    return payload


# ── Team ─────────────────────────────────────────────────────────────

def team_payload(season_id: str, school_name: str) -> Dict[str, Any]:
    return {"season_id": season_id, "school_name": school_name}


# ── Assessor ─────────────────────────────────────────────────────────

def assessor_payload(
    full_name: str = DEFAULT_ASSESSOR_NAME,
    credential_number: str = DEFAULT_CREDENTIAL_NUMBER,
    certified_methods: Optional[Sequence[str]] = None,
    certification_expires_on: str = DEFAULT_CREDENTIAL_EXPIRY,
) -> Dict[str, Any]:
    return {
        "full_name": full_name,
        "credential_number": credential_number,
        "certified_methods": list(
            certified_methods if certified_methods is not None
            else [METHOD_SKINFOLD, METHOD_BIA]
        ),
        "certification_expires_on": certification_expires_on,
    }


def training_record_payload(
    hours: float, credential_code: str = DEFAULT_TRAINING_CODE
) -> Dict[str, Any]:
    """A logged training record; ``hours`` is a JSON number."""
    return {"credential_code": credential_code, "hours": hours}


def suspension_payload(reason: str) -> Dict[str, Any]:
    return {"reason": reason}


# ── Wrestler ─────────────────────────────────────────────────────────

def wrestler_payload(
    full_name: str = DEFAULT_WRESTLER_NAME,
    sex: str = SEX_MALE,
    grade: int = DEFAULT_WRESTLER_GRADE,
) -> Dict[str, Any]:
    return {"full_name": full_name, "sex": sex, "grade": grade}


def disqualification_payload(health_flag_id: str, reason: str) -> Dict[str, Any]:
    return {"health_flag_id": health_flag_id, "reason": reason}


# ── Assessment ───────────────────────────────────────────────────────

def assessment_payload(
    assessor_id: str,
    method: str = METHOD_SKINFOLD,
    assessed_at: str = ASSESSED_AT,
    measured_weight_lbs: float = CANON_MEASURED_WEIGHT_LBS,
    body_fat_pct: float = CANON_BODY_FAT_PCT,
    urine_specific_gravity: float = CANON_USG_PASS,
    retest_of_assessment_id: Any = _OMITTED,
    appeal_id: Any = _OMITTED,
) -> Dict[str, Any]:
    """A draft assessment body; the three readings are all JSON numbers."""
    payload: Dict[str, Any] = {
        "assessor_id": assessor_id,
        "method": method,
        "assessed_at": assessed_at,
        "measured_weight_lbs": measured_weight_lbs,
        "body_fat_pct": body_fat_pct,
        "urine_specific_gravity": urine_specific_gravity,
    }
    _put(payload, "retest_of_assessment_id", retest_of_assessment_id)
    _put(payload, "appeal_id", appeal_id)
    return payload


# ── Appeal ───────────────────────────────────────────────────────────

def appeal_payload(team_id: str, reason: str = "Skinfold caliper reading disputed.") -> Dict[str, Any]:
    return {"team_id": team_id, "reason": reason}


def assign_reviewer_payload(reviewing_assessor_id: str) -> Dict[str, Any]:
    return {"reviewing_assessor_id": reviewing_assessor_id}


def appeal_decision_payload(outcome: str, decision_note: str) -> Dict[str, Any]:
    return {"outcome": outcome, "decision_note": decision_note}


# ── Descent plan ─────────────────────────────────────────────────────

def descent_plan_payload(
    source_assessment_id: str,
    target_class_lbs: int,
    plan_start_date: str,
    expected_wrestler_version: int,
    plan_variant: str = VARIANT_WEEKLY_STEP,
    requested_weeks: Any = _OMITTED,
) -> Dict[str, Any]:
    """A plan creation body; ``expected_wrestler_version`` is non-optional."""
    payload: Dict[str, Any] = {
        "source_assessment_id": source_assessment_id,
        "plan_variant": plan_variant,
        "target_class_lbs": target_class_lbs,
        "plan_start_date": plan_start_date,
        "expected_wrestler_version": expected_wrestler_version,
    }
    _put(payload, "requested_weeks", requested_weeks)
    return payload


def plan_revision_payload(
    plan_start_date: str,
    target_class_lbs: Any = _OMITTED,
    plan_variant: Any = _OMITTED,
    requested_weeks: Any = _OMITTED,
) -> Dict[str, Any]:
    """A revision body; only the new start date is required."""
    payload: Dict[str, Any] = {"plan_start_date": plan_start_date}
    _put(payload, "target_class_lbs", target_class_lbs)
    _put(payload, "plan_variant", plan_variant)
    _put(payload, "requested_weeks", requested_weeks)
    return payload


# ── Event ────────────────────────────────────────────────────────────

def event_payload(
    name: str,
    event_date: str,
    event_type: str = EVENT_TYPE_TOURNAMENT,
    competition_days: Any = _OMITTED,
    weigh_in_days: Any = _OMITTED,
    consecutive_day_allowance_lbs: Any = _OMITTED,
) -> Dict[str, Any]:
    """An event body; the three shape parameters are left to their defaults."""
    payload: Dict[str, Any] = {
        "name": name,
        "event_type": event_type,
        "event_date": event_date,
    }
    _put(payload, "competition_days", competition_days)
    _put(payload, "weigh_in_days", weigh_in_days)
    _put(payload, "consecutive_day_allowance_lbs", consecutive_day_allowance_lbs)
    return payload


def event_status_payload(status: str) -> Dict[str, Any]:
    return {"status": status}


# ── Tournament entry ─────────────────────────────────────────────────

def entry_payload(
    wrestler_id: str, weight_class_lbs: int, season_win_count: Any = _OMITTED
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "wrestler_id": wrestler_id,
        "weight_class_lbs": weight_class_lbs,
    }
    _put(payload, "season_win_count", season_win_count)
    return payload


def weight_class_change_payload(
    weight_class_lbs: int, expected_entry_version: int
) -> Dict[str, Any]:
    return {
        "weight_class_lbs": weight_class_lbs,
        "expected_entry_version": expected_entry_version,
    }


# ── Weigh-in ─────────────────────────────────────────────────────────

def weigh_in_payload(
    entry_id: str, day_index: int, recorded_weight_lbs: float
) -> Dict[str, Any]:
    """A weigh-in body; the scale reading is a JSON number."""
    return {
        "entry_id": entry_id,
        "day_index": day_index,
        "recorded_weight_lbs": recorded_weight_lbs,
    }


# ── Eligibility check ────────────────────────────────────────────────

def eligibility_check_payload(event_id: str, requested_class_lbs: int) -> Dict[str, Any]:
    return {"event_id": event_id, "requested_class_lbs": requested_class_lbs}


# ── Health flag review ───────────────────────────────────────────────

def flag_review_payload(outcome: str, review_note: str) -> Dict[str, Any]:
    return {"outcome": outcome, "review_note": review_note}


# ── Program audit ────────────────────────────────────────────────────

def audit_sample(assessment_id: str, remeasured_body_fat_pct: float) -> Dict[str, Any]:
    """One audit sample; the remeasured percentage is a JSON number."""
    return {
        "assessment_id": assessment_id,
        "remeasured_body_fat_pct": remeasured_body_fat_pct,
    }


def audit_payload(
    audit_type: str,
    scoring_variant: str,
    sample_window_start: str,
    assessor_id: Any = _OMITTED,
    samples: Any = _OMITTED,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "audit_type": audit_type,
        "scoring_variant": scoring_variant,
        "sample_window_start": sample_window_start,
    }
    _put(payload, "assessor_id", assessor_id)
    _put(payload, "samples", samples)
    return payload


def audit_samples(pairs: Sequence[Sequence[Any]]) -> List[Dict[str, Any]]:
    """Build a samples array from ``(assessment_id, remeasured_body_fat_pct)`` pairs."""
    return [audit_sample(assessment_id, pct) for assessment_id, pct in pairs]
