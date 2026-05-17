"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact JSON-body schema PRD declares for the
request body. Only PRD-declared input fields are produced; computed and
system-managed fields are intentionally omitted so the implementation
cannot accidentally accept them as inputs.

PRD §2.4: timestamps are ISO 8601 UTC strings with three fractional
digits. PRD §3.3: cert window dates are ISO 8601 dates.
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
    """Convenience: the clock anchor as a datetime."""
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


def iso_date_anchor_offset(*, days: int = 0) -> str:
    """ISO calendar date offset from the clock anchor's date."""
    return iso_date(parse_anchor().date() + timedelta(days=days))


# ---------------------------------------------------------------------------
# Random utilities.
# ---------------------------------------------------------------------------
_DIGITS = string.digits


def random_suffix(n: int = 6) -> str:
    return "".join(random.choices(string.ascii_uppercase + _DIGITS, k=n))


def random_npi() -> str:
    """PRD §3.1 / §3.2: "10-digit npi"."""
    return "".join(random.choices(_DIGITS, k=10))


def random_mbi() -> str:
    """Medicare Beneficiary Identifier. PRD §3.1 mentions it as the MBI
    used on every Medicare claim; format is not pinned beyond
    non-empty."""
    return "1A" + "".join(random.choices(_DIGITS, k=2)) + \
        "A" + "".join(random.choices(_DIGITS, k=2)) + \
        "B" + "".join(random.choices(_DIGITS, k=2))


def random_va_referral_id() -> str:
    """VA Community Care Network referral id. Not format-pinned."""
    return "VA-" + "".join(random.choices(_DIGITS, k=8))


def random_va_facility_code() -> str:
    """PRD §3.1: "a 3-character referring_va_facility_code"."""
    return "".join(random.choices(string.ascii_uppercase, k=3))


def random_authorization_ref() -> str:
    """A payer authorization reference. Not format-pinned."""
    return "AUTH-" + random_suffix(8)


# ---------------------------------------------------------------------------
# Therapist — PRD §3.1.
# ---------------------------------------------------------------------------
def create_therapist_payload(
    *,
    full_name: str = "Test Therapist",
    npi: Optional[str] = None,
    credential: str = "DPT",
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /therapists — ClinicAdmin only.

    PRD §3.1: "Registering a therapist supplies full_name, a 10-digit
    npi, and the therapist's credential, which is one of PT, PTA, or
    DPT."
    """
    payload: Dict[str, Any] = {
        "full_name": full_name,
        "npi": npi if npi is not None else random_npi(),
        "credential": credential,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Patient — PRD §3.1.
# ---------------------------------------------------------------------------
def create_patient_payload(
    *,
    full_name: str = "Test Patient",
    date_of_birth: str = "1985-06-15",
    insurance_type: str = "COMMERCIAL",
    medicare_beneficiary_id: Optional[str] = None,
    va_referral_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /patients — ClinicAdmin only.

    PRD §3.1: "Registering a patient supplies full_name, date_of_birth,
    and insurance_type, the latter being one of MEDICARE_PART_B, VA,
    COMMERCIAL, or SELF_PAY. Two conditional fields piggy-back on the
    payer: when insurance_type is MEDICARE_PART_B, the patient's
    medicare_beneficiary_id is required ... when insurance_type is VA,
    the patient's va_referral_id is required."
    """
    payload: Dict[str, Any] = {
        "full_name": full_name,
        "date_of_birth": date_of_birth,
        "insurance_type": insurance_type,
    }
    if insurance_type == "MEDICARE_PART_B":
        payload["medicare_beneficiary_id"] = (
            medicare_beneficiary_id
            if medicare_beneficiary_id is not None
            else random_mbi()
        )
    elif medicare_beneficiary_id is not None:
        payload["medicare_beneficiary_id"] = medicare_beneficiary_id
    if insurance_type == "VA":
        payload["va_referral_id"] = (
            va_referral_id
            if va_referral_id is not None
            else random_va_referral_id()
        )
    elif va_referral_id is not None:
        payload["va_referral_id"] = va_referral_id
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# VeteranReferral — PRD §3.1.
# ---------------------------------------------------------------------------
def create_veteran_referral_payload(
    *,
    patient_id: str,
    referring_va_facility_code: Optional[str] = None,
    authorized_units: int = 60,
    valid_from: Optional[str] = None,
    valid_through: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /veteran-referrals — ClinicAdmin only.

    PRD §3.1: "The referral supplies the owning patient_id (whose
    insurance_type must be VA), a 3-character referring_va_facility_code,
    the integer authorized_units granted by the VA, and an inclusive
    validity window from valid_from through valid_through."
    """
    if valid_from is None:
        valid_from = iso_date_anchor_offset(days=-1)
    if valid_through is None:
        valid_through = iso_date_anchor_offset(days=120)
    payload: Dict[str, Any] = {
        "patient_id": patient_id,
        "referring_va_facility_code": (
            referring_va_facility_code
            if referring_va_facility_code is not None
            else random_va_facility_code()
        ),
        "authorized_units": authorized_units,
        "valid_from": valid_from,
        "valid_through": valid_through,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Episode — PRD §3.2.
# ---------------------------------------------------------------------------
def create_episode_payload(
    *,
    patient_id: str,
    referring_provider_npi: Optional[str] = None,
    body_region: str = "LUMBAR",
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /episodes — Therapist only.

    PRD §3.2: "A treating therapist opens a new episode of care by
    submitting a patient_id, the 10-digit referring_provider_npi of
    the physician who referred the patient, and a body_region — one of
    LUMBAR, CERVICAL, KNEE, SHOULDER, HIP, ANKLE, or OTHER."
    """
    payload: Dict[str, Any] = {
        "patient_id": patient_id,
        "referring_provider_npi": (
            referring_provider_npi
            if referring_provider_npi is not None
            else random_npi()
        ),
        "body_region": body_region,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Evaluation — PRD §3.2.
# ---------------------------------------------------------------------------
def create_evaluation_payload(
    *,
    evaluation_type: str = "INITIAL",
    clinician_id: str,
    complexity: str = "MODERATE",
    functional_baseline_score: int = 50,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /episodes/{episode_id}/evaluations — Therapist only.

    PRD §3.2: "Recording an evaluation on the episode means creating
    an Evaluation row that captures evaluation_type (either INITIAL or
    REEVAL), the clinician_id of the performing therapist, the
    APTA-style complexity of LOW, MODERATE, or HIGH ..., and the
    patient's functional_baseline_score on a 0-to-100 scale."
    """
    payload: Dict[str, Any] = {
        "evaluation_type": evaluation_type,
        "clinician_id": clinician_id,
        "complexity": complexity,
        "functional_baseline_score": functional_baseline_score,
    }
    payload.update(overrides)
    return payload


def amend_evaluation_payload(
    *,
    functional_baseline_score: Optional[int] = None,
    complexity: Optional[str] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /evaluations/{id}/amend.

    PRD §3.2: "amend transitions the evaluation to AMENDED and may
    revise functional_baseline_score and complexity."
    """
    payload: Dict[str, Any] = {}
    if functional_baseline_score is not None:
        payload["functional_baseline_score"] = functional_baseline_score
    if complexity is not None:
        payload["complexity"] = complexity
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Plan of Care — PRD §3.3.
# ---------------------------------------------------------------------------
def create_plan_of_care_payload(
    *,
    evaluation_id: str,
    certifying_physician_npi: Optional[str] = None,
    planned_visit_count: int = TEST_DEFAULTS["DEFAULT_PLANNED_VISIT_COUNT"],
    planned_units_per_visit: int = TEST_DEFAULTS[
        "DEFAULT_PLANNED_UNITS_PER_VISIT"],
    cert_period_start: Optional[str] = None,
    cert_period_end: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /episodes/{episode_id}/plan-of-cares — Therapist only.

    PRD §3.3: "Drafting a plan supplies an evaluation_id ..., the
    certifying_physician_npi ..., the integer planned_visit_count
    expected over the certification window, the integer
    planned_units_per_visit ..., and the certification window itself —
    cert_period_start and cert_period_end, both ISO 8601 dates."
    """
    if cert_period_start is None:
        cert_period_start = iso_date_anchor_offset(days=0)
    if cert_period_end is None:
        cert_period_end = iso_date_anchor_offset(days=60)
    payload: Dict[str, Any] = {
        "evaluation_id": evaluation_id,
        "certifying_physician_npi": (
            certifying_physician_npi
            if certifying_physician_npi is not None
            else random_npi()
        ),
        "planned_visit_count": planned_visit_count,
        "planned_units_per_visit": planned_units_per_visit,
        "cert_period_start": cert_period_start,
        "cert_period_end": cert_period_end,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Authorization — PRD §3.4.
# ---------------------------------------------------------------------------
def create_authorization_payload(
    *,
    plan_of_care_id: str,
    source: str = "COMMERCIAL_PAYER",
    external_reference: Optional[str] = None,
    unit_quota: int = TEST_DEFAULTS["DEFAULT_UNIT_QUOTA"],
    valid_from: Optional[str] = None,
    valid_through: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /episodes/{episode_id}/authorizations.

    PRD §3.4: "Creating an authorization on an episode requires a
    plan_of_care_id to bind it to, a source of COMMERCIAL_PAYER,
    MEDICARE_AUTO, or VA_REFERRAL, an external_reference ..., an
    integer unit_quota of 15-minute units, and an inclusive
    [valid_from, valid_through] window."
    """
    if valid_from is None:
        valid_from = iso_date_anchor_offset(days=-1)
    if valid_through is None:
        valid_through = iso_date_anchor_offset(days=120)
    payload: Dict[str, Any] = {
        "plan_of_care_id": plan_of_care_id,
        "source": source,
        "external_reference": (
            external_reference
            if external_reference is not None
            else random_authorization_ref()
        ),
        "unit_quota": unit_quota,
        "valid_from": valid_from,
        "valid_through": valid_through,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Visit — PRD §3.5.
# ---------------------------------------------------------------------------
def create_visit_payload(
    *,
    plan_of_care_id: str,
    authorization_id: str,
    clinician_id: str,
    scheduled_start: Optional[str] = None,
    scheduled_end: Optional[str] = None,
    units_planned: int = 3,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /episodes/{episode_id}/visits — Therapist only.

    PRD §3.5: "Scheduling a visit on an active episode supplies the
    binding plan_of_care_id ..., the binding authorization_id ..., the
    delivering therapist's clinician_id, the visit's scheduled_start
    and scheduled_end timestamps ..., and the integer units_planned."
    """
    if scheduled_start is None:
        scheduled_start = iso_anchor_offset(hours=2)
    if scheduled_end is None:
        scheduled_end = iso_anchor_offset(hours=3)
    payload: Dict[str, Any] = {
        "plan_of_care_id": plan_of_care_id,
        "authorization_id": authorization_id,
        "clinician_id": clinician_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "units_planned": units_planned,
    }
    payload.update(overrides)
    return payload


def sign_visit_payload(
    *,
    timed_minutes: int = 45,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /visits/{id}/sign.

    PRD §3.5: "The signing therapist supplies timed_minutes, the
    direct one-on-one timed minutes that drive the 8-minute rule."
    """
    payload: Dict[str, Any] = {"timed_minutes": timed_minutes}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Home Exercise Program — PRD §3.7.
# ---------------------------------------------------------------------------
def default_exercise_items() -> List[Dict[str, Any]]:
    """PRD §3.7: "a non-empty exercise_items array, where each item
    describes one exercise with its name, set count, repetition count,
    and weekly frequency."""
    return [
        {
            "name": "Quad sets",
            "sets": 3,
            "reps": 10,
            "frequency_per_week": 5,
        },
        {
            "name": "Hamstring stretch",
            "sets": 2,
            "reps": 12,
            "frequency_per_week": 5,
        },
    ]


def create_home_exercise_program_payload(
    *,
    plan_of_care_id: str,
    prescribing_clinician_id: str,
    exercise_items: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /episodes/{episode_id}/home-exercise-programs.

    PRD §3.7: "Drafting a HEP supplies the binding plan_of_care_id ...,
    the prescribing_clinician_id of the therapist who authored it, and
    a non-empty exercise_items array."
    """
    payload: Dict[str, Any] = {
        "plan_of_care_id": plan_of_care_id,
        "prescribing_clinician_id": prescribing_clinician_id,
        "exercise_items": (
            exercise_items
            if exercise_items is not None
            else default_exercise_items()
        ),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# MIPS — PRD §3.8.
# ---------------------------------------------------------------------------
def create_mips_measure_payload(
    *,
    measure_code: str,
    visit_id: str,
    numerator_met: bool = True,
    exception_reason: str = "NONE",
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /episodes/{episode_id}/mips-measures.

    PRD §3.8: "A therapist attests a measure against a specific visit
    by creating a MipsMeasure row that supplies the measure_code, the
    visit_id at which the measure applies, a boolean numerator_met ...,
    and an exception_reason of NONE, MEDICAL, PATIENT, or SYSTEM."
    """
    payload: Dict[str, Any] = {
        "measure_code": measure_code,
        "visit_id": visit_id,
        "numerator_met": numerator_met,
        "exception_reason": exception_reason,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Discharge Assessment — PRD §3.9.
# ---------------------------------------------------------------------------
def create_discharge_assessment_payload(
    *,
    discharging_clinician_id: str,
    discharge_outcome: str = "GOALS_MET",
    final_functional_score: int = 80,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /episodes/{episode_id}/discharge-assessments.

    PRD §3.9: "a therapist opens a DischargeAssessment on the episode,
    supplying discharging_clinician_id, an outcome category
    discharge_outcome of GOALS_MET, PARTIAL, PLATEAU, ADVERSE_EVENT, or
    PATIENT_WITHDREW, and the patient's final functional outcome on
    the same 0–100 scale ..., captured in final_functional_score."
    """
    payload: Dict[str, Any] = {
        "discharging_clinician_id": discharging_clinician_id,
        "discharge_outcome": discharge_outcome,
        "final_functional_score": final_functional_score,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Test-only / OCC — PRD §3.10 / §2.4.
# ---------------------------------------------------------------------------
def clock_advance_payload(*, to: str, **overrides: Any) -> Dict[str, Any]:
    """POST /_clock/advance — test-only.

    PRD §3.10: "an admin operator to advance the logical clock to a
    supplied to instant."
    """
    payload: Dict[str, Any] = {"to": to}
    payload.update(overrides)
    return payload


def occ_payload(version: Optional[int] = None,
                **overrides: Any) -> Dict[str, Any]:
    """Minimal action-payload that carries only an optional version for
    PRD §2.4 OCC checks. Action endpoints that take no other inputs use
    this shape."""
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


__all__ = [
    # time helpers
    "iso_utc",
    "parse_iso",
    "iso_date",
    "parse_anchor",
    "iso_anchor_offset",
    "iso_date_anchor_offset",
    # random helpers
    "random_suffix",
    "random_npi",
    "random_mbi",
    "random_va_referral_id",
    "random_va_facility_code",
    "random_authorization_ref",
    # payload factories
    "create_therapist_payload",
    "create_patient_payload",
    "create_veteran_referral_payload",
    "create_episode_payload",
    "create_evaluation_payload",
    "amend_evaluation_payload",
    "create_plan_of_care_payload",
    "create_authorization_payload",
    "create_visit_payload",
    "sign_visit_payload",
    "default_exercise_items",
    "create_home_exercise_program_payload",
    "create_mips_measure_payload",
    "create_discharge_assessment_payload",
    "clock_advance_payload",
    "occ_payload",
]
