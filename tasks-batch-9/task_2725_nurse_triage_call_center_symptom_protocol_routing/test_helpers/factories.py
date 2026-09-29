"""Request-payload builders with PRD-valid defaults.

Every default here satisfies the input constraints stated in PRD §3, so a test
only ever names the fields it actually cares about. Money stays integral
(PRD §2.8: "All money in this system is carried in integers").
"""

from typing import Any, Dict, Optional

from .constants import (
    DEFAULT_OFFICE_CLOSE_HHMM,
    DEFAULT_OFFICE_OPEN_HHMM,
    DEFAULT_PER_MINUTE_RATE_MILLICENTS,
    VALID_OVERRIDE_NARRATIVE,
)


def _clean(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop keys explicitly set to the sentinel so callers can omit fields."""
    return {k: v for k, v in payload.items() if v is not OMIT}


class _Omit:
    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<OMIT>"


OMIT = _Omit()


# ── Reference data ─────────────────────────────────────────────────────────
def practice_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "name": "Northside Family Health",
        "office_open_utc_hhmm": DEFAULT_OFFICE_OPEN_HHMM,
        "office_close_utc_hhmm": DEFAULT_OFFICE_CLOSE_HHMM,
        "per_minute_rate_millicents": DEFAULT_PER_MINUTE_RATE_MILLICENTS,
        "weekend_is_after_hours": True,
        "consent_recording_required": False,
        "variance_review_threshold": 1,
        "audit_period_start_utc": "2026-08-01T00:00:00Z",
    }
    payload.update(overrides)
    return _clean(payload)


def practice_status_payload(status: str = "SUSPENDED", **overrides: Any):
    payload = {"status": status}
    payload.update(overrides)
    return _clean(payload)


def patient_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "full_name": "Dana Reyes",
        "dob": "1990-03-15",
        "sex": "FEMALE",
        "pregnancy_status": "NOT_PREGNANT",
        "phone": "+14155550100",
        "mrn": "MRN-0001",
    }
    payload.update(overrides)
    return _clean(payload)


def protocol_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        # PRD §3.1: a `code` matching "three to twenty uppercase letters,
        # digits or underscores".
        "code": "CHEST_PAIN",
        "title": "Chest Pain In Adults",
        "base_severity": 62,
        "min_age_years": 0,
        "max_age_years": 120,
        "pregnancy_sensitive": False,
        "emergency_override": False,
        "min_disposition_level": "HOME_CARE",
        "infant_modifier_points": 22,
    }
    payload.update(overrides)
    return _clean(payload)


# ── Nurses, licences, shifts, coverage ─────────────────────────────────────
def nurse_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "full_name": "Nora Vance",
        "seniority_level": 3,
        "max_concurrent_calls": 2,
        "high_risk_cap": 2,
    }
    payload.update(overrides)
    return _clean(payload)


def license_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "state_code": "CA",
        "license_number": "CA-11111",
        "expires_on": "2027-01-31",
    }
    payload.update(overrides)
    return _clean(payload)


def shift_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "start_utc": "2026-08-03T12:00:00Z",
        "end_utc": "2026-08-03T20:00:00Z",
    }
    payload.update(overrides)
    return _clean(payload)


def coverage_window_payload(practice_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "practice_id": practice_id,
        "start_utc": "2026-08-01T00:00:00Z",
        "end_utc": "2026-08-08T00:00:00Z",
        "coverage_kind": "WEEKEND",
    }
    payload.update(overrides)
    return _clean(payload)


# ── The call ───────────────────────────────────────────────────────────────
def triage_call_payload(practice_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "practice_id": practice_id,
        "caller_name": "Dana Reyes",
        "caller_phone": "+14155550100",
        "caller_relationship": "SELF",
        "caller_state_code": "CA",
        "reason_text": "chest discomfort",
    }
    payload.update(overrides)
    return _clean(payload)


def match_patient_payload(patient_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {"patient_id": patient_id, "match_method": "MRN"}
    payload.update(overrides)
    return _clean(payload)


def consent_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {"consent_type": "PATIENT_SELF", "consent_given_by": "Dana Reyes"}
    payload.update(overrides)
    return _clean(payload)


def assign_nurse_payload(
    preferred_nurse_id: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if preferred_nurse_id is not None:
        payload["preferred_nurse_id"] = preferred_nurse_id
    payload.update(overrides)
    return _clean(payload)


def abandon_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {"abandon_reason": "Caller disconnected before triage could begin."}
    payload.update(overrides)
    return _clean(payload)


def complete_payload(handle_minutes: int = 13, **overrides: Any) -> Dict[str, Any]:
    payload = {"handle_minutes": handle_minutes}
    payload.update(overrides)
    return _clean(payload)


def reopen_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {"reopen_reason": "Caller rang back within the hour to add symptoms."}
    payload.update(overrides)
    return _clean(payload)


# ── Assessment and disposition ─────────────────────────────────────────────
def assessment_payload(protocol_id: str, **overrides: Any) -> Dict[str, Any]:
    """Confirmed-mode default: PRD §3.5 requires `confirmed_pregnancy_status`
    in `CONFIRMED` mode and `stated_age_years` in `PROVISIONAL` mode."""
    payload = {
        "protocol_id": protocol_id,
        "confirmation_mode": "CONFIRMED",
        "red_flag_count": 1,
        "confirmed_pregnancy_status": "NOT_PREGNANT",
    }
    payload.update(overrides)
    return _clean(payload)


def provisional_assessment_payload(
    protocol_id: str, stated_age_years: int = 36, **overrides: Any
) -> Dict[str, Any]:
    payload = {
        "protocol_id": protocol_id,
        "confirmation_mode": "PROVISIONAL",
        "red_flag_count": 1,
        "stated_age_years": stated_age_years,
    }
    payload.update(overrides)
    return _clean(payload)


def disposition_payload(
    call_id: str,
    assessment_id: str,
    final_level: str,
    expected_call_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "call_id": call_id,
        "assessment_id": assessment_id,
        "final_level": final_level,
        "expected_call_version": expected_call_version,
    }
    payload.update(overrides)
    return _clean(payload)


def override_payload(final_level: str, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "final_level": final_level,
        "override_reason_code": "CALLER_REFUSED_ED",
        "override_narrative": VALID_OVERRIDE_NARRATIVE,
    }
    payload.update(overrides)
    return _clean(payload)


# ── Warm transfer ──────────────────────────────────────────────────────────
def warm_transfer_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "psap_center_code": "SF-PSAP-01",
        "location_source": "CALLER_STATED",
        "location_address_line": "1200 Market Street Apartment 4B",
        "location_state_code": "CA",
        "location_lat": 37.7793,
        "location_lng": -122.4193,
        "callback_number": "+14155550100",
    }
    payload.update(overrides)
    return _clean(payload)


def confirm_location_payload(
    location_confidence_pct: int = 90, **overrides: Any
) -> Dict[str, Any]:
    payload = {"location_confidence_pct": location_confidence_pct}
    payload.update(overrides)
    return _clean(payload)


def psap_response_payload(
    accepted: bool = True,
    psap_incident_number: Optional[str] = "SFFD-2026-0001",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"accepted": accepted}
    if accepted and psap_incident_number is not None:
        payload["psap_incident_number"] = psap_incident_number
    payload.update(overrides)
    return _clean(payload)


# ── Callback task ──────────────────────────────────────────────────────────
def attempt_payload(outcome: str = "REACHED", **overrides: Any) -> Dict[str, Any]:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return _clean(payload)


def verify_payload(
    patient_condition: str = "IMPROVED",
    advice_followed: bool = True,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "patient_condition": patient_condition,
        "advice_followed": advice_followed,
        "verifier_attestation": (
            "Caller followed the advice given and reports their current condition."
        ),
    }
    payload.update(overrides)
    return _clean(payload)


# ── Outcome audit ──────────────────────────────────────────────────────────
def audit_record_payload(
    reported_outcome: str = "ED_ADMITTED",
    outcome_observed_at: str = "2026-08-03T18:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "reported_outcome": reported_outcome,
        "outcome_source": "ED_FEED",
        "outcome_observed_at": outcome_observed_at,
    }
    payload.update(overrides)
    return _clean(payload)


# ── Staffing readout query (PRD §3.10 — all three params mandatory) ────────
def staffing_query(
    state_code: str = "CA",
    window_start_utc: str = "2026-08-03T14:00:00Z",
    window_end_utc: str = "2026-08-03T15:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "state_code": state_code,
        "window_start_utc": window_start_utc,
        "window_end_utc": window_end_utc,
    }
    payload.update(overrides)
    return _clean(payload)
