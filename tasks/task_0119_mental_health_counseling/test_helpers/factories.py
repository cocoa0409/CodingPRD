"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact JSON-body schema PRD declares for the
request body. Only PRD-declared input fields are produced; computed and
system-managed fields are intentionally omitted so the implementation
cannot accidentally accept them as inputs.

PRD §2.4: timestamps are ISO 8601 UTC strings with three fractional
digits.
"""
from __future__ import annotations

import random
import string
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS


# ---------------------------------------------------------------------------
# Timestamp helpers — PRD §2.4 ISO 8601 UTC, three fractional digits.
# ---------------------------------------------------------------------------
def iso_utc(dt: datetime) -> str:
    """Render a datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def parse_iso(iso_ts: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp into a timezone-aware datetime."""
    s = iso_ts
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def iso_date(d: date) -> str:
    """ISO 8601 calendar date (YYYY-MM-DD)."""
    return d.isoformat()


def parse_anchor() -> datetime:
    """Return the configured clock anchor as a datetime."""
    return parse_iso(TEST_DEFAULTS["CLOCK_ANCHOR"])


def iso_anchor_offset(*, days: int = 0, hours: int = 0,
                      minutes: int = 0, seconds: int = 0) -> str:
    """ISO 8601 UTC, offset from the clock anchor by the supplied
    deltas."""
    return iso_utc(
        parse_anchor() + timedelta(
            days=days, hours=hours, minutes=minutes, seconds=seconds,
        ),
    )


def iso_midnight(year: int, month: int, day: int) -> str:
    """UTC midnight for a calendar date — used by StateLicense
    issued_on / expires_on. PRD §3.1: 'an issued_on date, and an
    expires_on date (both in UTC midnight)'."""
    return iso_utc(datetime(year, month, day, 0, 0, 0, tzinfo=timezone.utc))


# ---------------------------------------------------------------------------
# Random utilities.
# ---------------------------------------------------------------------------
_DIGITS = string.digits


def random_suffix(n: int = 6) -> str:
    return "".join(random.choices(string.ascii_uppercase + _DIGITS, k=n))


def random_npi() -> str:
    """PRD §3.1: 'a ten-digit numeric string that must match the regular
    shape of ten digits and be unique within the practice.'"""
    return "".join(random.choices(_DIGITS, k=10))


def random_plan_code() -> str:
    """A unique-within-practice plan code. PRD §3.5: 'an internal
    plan_code that must be unique within the practice.'"""
    return f"PLAN-{random_suffix(8)}"


def random_license_number() -> str:
    """Free-form license number string. PRD §3.1: 'a license_number'."""
    return "L" + random_suffix(7)


# ---------------------------------------------------------------------------
# Therapist — PRD §3.1.
# ---------------------------------------------------------------------------
def create_therapist_payload(*,
                             full_name: str = "Dr. Test Therapist",
                             npi: Optional[str] = None,
                             supervision_track: str = "LICENSED",
                             psypact_enrolled: Optional[bool] = None,
                             pricing_rack_90791_cents: Optional[int] = None,
                             pricing_rack_90834_cents: Optional[int] = None,
                             ) -> Dict[str, Any]:
    """POST /practice/therapists body — PRD §3.1."""
    payload: Dict[str, Any] = {
        "full_name": full_name,
        "npi": npi if npi is not None else random_npi(),
        "supervision_track": supervision_track,
        "pricing_rack_90791_cents": (
            pricing_rack_90791_cents
            if pricing_rack_90791_cents is not None
            else TEST_DEFAULTS["RACK_90791_CENTS"]
        ),
        "pricing_rack_90834_cents": (
            pricing_rack_90834_cents
            if pricing_rack_90834_cents is not None
            else TEST_DEFAULTS["RACK_90834_CENTS"]
        ),
    }
    if psypact_enrolled is not None:
        payload["psypact_enrolled"] = psypact_enrolled
    return payload


def patch_therapist_payload(*,
                            psypact_enrolled: Optional[bool] = None,
                            pricing_rack_90791_cents: Optional[int] = None,
                            pricing_rack_90834_cents: Optional[int] = None,
                            version: Optional[int] = None,
                            ) -> Dict[str, Any]:
    """PATCH /practice/therapists/{id} body — PRD §3.1."""
    payload: Dict[str, Any] = {}
    if psypact_enrolled is not None:
        payload["psypact_enrolled"] = psypact_enrolled
    if pricing_rack_90791_cents is not None:
        payload["pricing_rack_90791_cents"] = pricing_rack_90791_cents
    if pricing_rack_90834_cents is not None:
        payload["pricing_rack_90834_cents"] = pricing_rack_90834_cents
    if version is not None:
        payload["version"] = version
    return payload


# ---------------------------------------------------------------------------
# StateLicense — PRD §3.1.
# ---------------------------------------------------------------------------
def create_state_license_payload(*,
                                 state_code: str = "NY",
                                 license_number: Optional[str] = None,
                                 issued_on: Optional[str] = None,
                                 expires_on: Optional[str] = None,
                                 ) -> Dict[str, Any]:
    """POST /practice/therapists/{tid}/licenses body — PRD §3.1."""
    return {
        "state_code": state_code,
        "license_number": license_number
        if license_number is not None else random_license_number(),
        "issued_on": issued_on
        if issued_on is not None else iso_midnight(2025, 1, 1),
        "expires_on": expires_on
        if expires_on is not None else iso_midnight(2030, 1, 1),
    }


# ---------------------------------------------------------------------------
# Supervisor — PRD §3.3.
# ---------------------------------------------------------------------------
def create_supervisor_payload(*,
                              full_name: str = "Dr. Test Supervisor",
                              home_state_code: str = "NY",
                              active: Optional[bool] = None,
                              ) -> Dict[str, Any]:
    """POST /practice/supervisors body — PRD §3.3."""
    payload: Dict[str, Any] = {
        "full_name": full_name,
        "home_state_code": home_state_code,
    }
    if active is not None:
        payload["active"] = active
    return payload


def create_supervision_assignment_payload(*,
                                          therapist_id: str,
                                          supervisor_id: str,
                                          started_on: Optional[str] = None,
                                          ) -> Dict[str, Any]:
    """POST /practice/supervision-assignments body — PRD §3.3."""
    return {
        "therapist_id": therapist_id,
        "supervisor_id": supervisor_id,
        "started_on": started_on
        if started_on is not None else iso_midnight(2025, 1, 1),
    }


# ---------------------------------------------------------------------------
# Patient — PRD §3.4.
# ---------------------------------------------------------------------------
def create_patient_payload(*,
                           full_name: str = "Test Patient",
                           state_of_residence: str = "NY",
                           household_income_cents: int = 3_000_000,
                           household_size: int = 2,
                           insurance_plan_id: Optional[str] = None,
                           ) -> Dict[str, Any]:
    """POST /practice/patients body — PRD §3.4."""
    payload: Dict[str, Any] = {
        "full_name": full_name,
        "state_of_residence": state_of_residence,
        "household_income_cents": household_income_cents,
        "household_size": household_size,
    }
    if insurance_plan_id is not None:
        payload["insurance_plan_id"] = insurance_plan_id
    return payload


def patch_patient_payload(*,
                          state_of_residence: Optional[str] = None,
                          household_income_cents: Optional[int] = None,
                          household_size: Optional[int] = None,
                          insurance_plan_id: Optional[str] = None,
                          deductible_remaining_cents: Optional[int] = None,
                          version: Optional[int] = None,
                          ) -> Dict[str, Any]:
    """PATCH /practice/patients/{id} body — PRD §3.4."""
    payload: Dict[str, Any] = {}
    if state_of_residence is not None:
        payload["state_of_residence"] = state_of_residence
    if household_income_cents is not None:
        payload["household_income_cents"] = household_income_cents
    if household_size is not None:
        payload["household_size"] = household_size
    if insurance_plan_id is not None:
        payload["insurance_plan_id"] = insurance_plan_id
    if deductible_remaining_cents is not None:
        payload["deductible_remaining_cents"] = deductible_remaining_cents
    if version is not None:
        payload["version"] = version
    return payload


# ---------------------------------------------------------------------------
# InsurancePlan — PRD §3.5.
# ---------------------------------------------------------------------------
def create_insurance_plan_payload(*,
                                  payer_name: str = "Aetna",
                                  plan_code: Optional[str] = None,
                                  network_status: str = "IN_NETWORK",
                                  contract_mode: str = "DEDUCTIBLE_FIRST",
                                  allowed_amount_90791_cents: Optional[
                                      int] = None,
                                  allowed_amount_90834_cents: Optional[
                                      int] = None,
                                  copay_cents: Optional[int] = None,
                                  ) -> Dict[str, Any]:
    """POST /practice/insurance-plans body — PRD §3.5."""
    return {
        "payer_name": payer_name,
        "plan_code": plan_code if plan_code is not None
        else random_plan_code(),
        "network_status": network_status,
        "contract_mode": contract_mode,
        "allowed_amount_90791_cents": (
            allowed_amount_90791_cents
            if allowed_amount_90791_cents is not None
            else TEST_DEFAULTS["ALLOWED_90791_CENTS"]
        ),
        "allowed_amount_90834_cents": (
            allowed_amount_90834_cents
            if allowed_amount_90834_cents is not None
            else TEST_DEFAULTS["ALLOWED_90834_CENTS"]
        ),
        "copay_cents": copay_cents if copay_cents is not None
        else TEST_DEFAULTS["COPAY_CENTS"],
    }


# ---------------------------------------------------------------------------
# Appointment — PRD §3.6.
# ---------------------------------------------------------------------------
def create_appointment_payload(*,
                               therapist_id: str,
                               patient_id: str,
                               cpt_code: str = "90834",
                               modality: str = "IN_PERSON",
                               patient_state_on_day: str = "NY",
                               scheduled_start: Optional[str] = None,
                               scheduled_end: Optional[str] = None,
                               ) -> Dict[str, Any]:
    """POST /practice/appointments body — PRD §3.6."""
    if scheduled_start is None:
        scheduled_start = iso_anchor_offset(hours=2)
    if scheduled_end is None:
        scheduled_end = iso_anchor_offset(hours=2, minutes=45)
    return {
        "therapist_id": therapist_id,
        "patient_id": patient_id,
        "cpt_code": cpt_code,
        "modality": modality,
        "patient_state_on_day": patient_state_on_day,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }


def patch_appointment_payload(*,
                              scheduled_start: Optional[str] = None,
                              scheduled_end: Optional[str] = None,
                              modality: Optional[str] = None,
                              patient_state_on_day: Optional[str] = None,
                              version: Optional[int] = None,
                              ) -> Dict[str, Any]:
    """PATCH /practice/appointments/{id} body — PRD §3.6."""
    payload: Dict[str, Any] = {}
    if scheduled_start is not None:
        payload["scheduled_start"] = scheduled_start
    if scheduled_end is not None:
        payload["scheduled_end"] = scheduled_end
    if modality is not None:
        payload["modality"] = modality
    if patient_state_on_day is not None:
        payload["patient_state_on_day"] = patient_state_on_day
    if version is not None:
        payload["version"] = version
    return payload


# ---------------------------------------------------------------------------
# Session — PRD §3.7.
# ---------------------------------------------------------------------------
def create_session_payload(*,
                           actual_duration_minutes: int = 45,
                           ) -> Dict[str, Any]:
    """POST /practice/appointments/{id}/sessions body — PRD §3.7."""
    return {"actual_duration_minutes": actual_duration_minutes}


# ---------------------------------------------------------------------------
# CrisisAssessment — PRD §3.9.
# ---------------------------------------------------------------------------
def create_crisis_assessment_payload(*,
                                     therapist_id: str,
                                     si_score: int = 0,
                                     pa_score: int = 0,
                                     su_score: int = 0,
                                     so_score: int = 0,
                                     am_score: int = 0,
                                     ) -> Dict[str, Any]:
    """POST /practice/patients/{pid}/crisis-assessments body — PRD §3.9."""
    return {
        "therapist_id": therapist_id,
        "si_score": si_score,
        "pa_score": pa_score,
        "su_score": su_score,
        "so_score": so_score,
        "am_score": am_score,
    }


# ---------------------------------------------------------------------------
# SafetyPlan — PRD §3.9.
# ---------------------------------------------------------------------------
def create_safety_plan_payload(*,
                               trigger_assessment_id: str,
                               warning_signs: str = "Test warning signs.",
                               coping_strategies: str = (
                                   "Test coping strategies."
                               ),
                               support_contacts: Optional[
                                   List[Dict[str, str]]] = None,
                               crisis_hotline: str = "988",
                               means_restriction_plan: str = (
                                   "Remove access to means."
                               ),
                               ) -> Dict[str, Any]:
    """POST /practice/patients/{pid}/safety-plans body — PRD §3.9."""
    if support_contacts is None:
        support_contacts = [{"name": "Alex Friend", "phone": "555-0100"}]
    return {
        "trigger_assessment_id": trigger_assessment_id,
        "warning_signs": warning_signs,
        "coping_strategies": coping_strategies,
        "support_contacts": list(support_contacts),
        "crisis_hotline": crisis_hotline,
        "means_restriction_plan": means_restriction_plan,
    }


# ---------------------------------------------------------------------------
# Clock — PRD §2.8.
# ---------------------------------------------------------------------------
def clock_advance_payload(*, to: str) -> Dict[str, Any]:
    """POST /practice/_clock/advance body — PRD §2.8."""
    return {"to": to}


# ---------------------------------------------------------------------------
# OCC convenience — PRD §2.4.
# ---------------------------------------------------------------------------
def occ_payload(version: int) -> Dict[str, Any]:
    """Convenience body carrying only `version` for state-transition POSTs
    that accept optimistic concurrency control."""
    return {"version": version}


__all__ = [
    # Time helpers
    "iso_utc",
    "parse_iso",
    "iso_date",
    "parse_anchor",
    "iso_anchor_offset",
    "iso_midnight",
    # Random helpers
    "random_suffix",
    "random_npi",
    "random_plan_code",
    "random_license_number",
    # Body factories
    "create_therapist_payload",
    "patch_therapist_payload",
    "create_state_license_payload",
    "create_supervisor_payload",
    "create_supervision_assignment_payload",
    "create_patient_payload",
    "patch_patient_payload",
    "create_insurance_plan_payload",
    "create_appointment_payload",
    "patch_appointment_payload",
    "create_session_payload",
    "create_crisis_assessment_payload",
    "create_safety_plan_payload",
    "clock_advance_payload",
    "occ_payload",
]
