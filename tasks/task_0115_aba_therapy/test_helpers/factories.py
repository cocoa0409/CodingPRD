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
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .constants import (
    CLOCK_EPOCH,
    SECONDS_PER_DAY,
    TEST_DEFAULTS,
)


# ---------------------------------------------------------------------------
# Timestamp helpers — PRD §2.4 format with three fractional digits.
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
    """Parse an ISO 8601 UTC timestamp back into a timezone-aware
    datetime."""
    return datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))


def add_seconds(iso_ts: str, *, seconds: int) -> str:
    return iso_utc(parse_iso(iso_ts) + timedelta(seconds=seconds))


def add_days(iso_ts: str, *, days: int) -> str:
    return iso_utc(parse_iso(iso_ts) + timedelta(days=days))


def add_minutes(iso_ts: str, *, minutes: int) -> str:
    return iso_utc(parse_iso(iso_ts) + timedelta(minutes=minutes))


def clock_epoch() -> str:
    """The deterministic epoch for fresh clinics — PRD §2.5."""
    return CLOCK_EPOCH


# ---------------------------------------------------------------------------
# Random utilities.
# ---------------------------------------------------------------------------
_ALPHANUM_UPPER = string.ascii_uppercase + string.digits
_DIGITS = string.digits


def random_suffix(n: int = 8) -> str:
    return "".join(random.choices(_ALPHANUM_UPPER, k=n))


def random_member_id() -> str:
    return f"MEM-{random_suffix(10)}"


def random_license_number() -> str:
    return f"{TEST_DEFAULTS['DEFAULT_LICENSE_NUMBER_PREFIX']}-{random_suffix(8)}"


# ---------------------------------------------------------------------------
# Clock — PRD §2.5
# ---------------------------------------------------------------------------
def clock_advance_payload(
    *,
    clinic_id: str,
    seconds: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /_clock/advance — ClinicAdmin only.

    PRD §2.5: "The clock-advance body carries the clinic_id and the
    seconds field; seconds must be a strictly positive integer."
    """
    payload: Dict[str, Any] = {
        "clinic_id": clinic_id,
        "seconds": seconds,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Clinic — PRD §3.1
# ---------------------------------------------------------------------------
def create_clinic_payload(
    *,
    name: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /clinics — ClinicAdmin only.

    PRD §3.1: "the clinic creation request that carries a single field
    — the clinic's display name."
    """
    payload: Dict[str, Any] = {
        "name": name if name is not None else f"Clinic {random_suffix(4)}",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Patient — PRD §3.1
# ---------------------------------------------------------------------------
def create_patient_payload(
    *,
    clinic_id: str,
    legal_name: Optional[str] = None,
    date_of_birth: Optional[str] = None,
    insurance_member_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /patients — ClinicAdmin or BCBA.

    PRD §3.1: "A patient carries the owning clinic_id, the patient's
    legal_name, their date_of_birth, and the payer-issued
    insurance_member_id."
    """
    payload: Dict[str, Any] = {
        "clinic_id": clinic_id,
        "legal_name": (
            legal_name if legal_name is not None
            else f"Patient {random_suffix(4)}"
        ),
        "date_of_birth": (
            date_of_birth if date_of_birth is not None
            else TEST_DEFAULTS["DEFAULT_DOB"]
        ),
        "insurance_member_id": (
            insurance_member_id if insurance_member_id is not None
            else random_member_id()
        ),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Therapist — PRD §3.1
# ---------------------------------------------------------------------------
def create_therapist_payload(
    *,
    clinic_id: str,
    legal_name: Optional[str] = None,
    credential: str = "BCBA",
    license_number: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /therapists — ClinicAdmin only.

    PRD §3.1: "A therapist row carries the owning clinic_id, the
    therapist's legal_name, their credential (one of BCBA or RBT), and
    their license_number."
    """
    payload: Dict[str, Any] = {
        "clinic_id": clinic_id,
        "legal_name": (
            legal_name if legal_name is not None
            else f"Therapist {random_suffix(4)}"
        ),
        "credential": credential,
        "license_number": (
            license_number if license_number is not None
            else random_license_number()
        ),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# DiagnosticEvaluation — PRD §3.2
# ---------------------------------------------------------------------------
def create_evaluation_payload(
    *,
    evaluator_therapist_id: str,
    scheduled_at: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /patients/{patient_id}/evaluations — BCBA or ClinicAdmin.

    PRD §3.2: "the request body carries the evaluator_therapist_id
    (which must resolve to a BCBA-credentialled therapist of the same
    clinic) and the scheduled_at instant."
    """
    payload: Dict[str, Any] = {
        "evaluator_therapist_id": evaluator_therapist_id,
        "scheduled_at": scheduled_at,
    }
    payload.update(overrides)
    return payload


def complete_evaluation_payload(
    *,
    diagnosis_code: Optional[str] = None,
    severity_level: str = "LEVEL_2",
    recommended_weekly_hours: int = 20,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /evaluations/{id}/complete — BCBA.

    PRD §3.2: "Finishing the evaluation requires a body containing the
    diagnosis_code (the ICD-10 code, for example F84.0), the
    severity_level (one of LEVEL_1, LEVEL_2, LEVEL_3), and the
    recommended_weekly_hours."
    """
    payload: Dict[str, Any] = {
        "diagnosis_code": (
            diagnosis_code if diagnosis_code is not None
            else TEST_DEFAULTS["DEFAULT_DIAGNOSIS_CODE"]
        ),
        "severity_level": severity_level,
        "recommended_weekly_hours": recommended_weekly_hours,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# TreatmentPlan — PRD §3.3
# ---------------------------------------------------------------------------
def create_treatment_plan_payload(
    *,
    source_evaluation_id: str,
    weekly_direct_hours_target: int,
    weekly_supervision_hours_target: float,
    weekly_parent_training_hours_target: float,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /patients/{patient_id}/treatment-plans — BCBA.

    PRD §3.3: "The draft body carries the source_evaluation_id (the id
    of the completed evaluation it derives from), the
    weekly_direct_hours_target, the weekly_supervision_hours_target, and
    the weekly_parent_training_hours_target."
    """
    payload: Dict[str, Any] = {
        "source_evaluation_id": source_evaluation_id,
        "weekly_direct_hours_target": weekly_direct_hours_target,
        "weekly_supervision_hours_target": weekly_supervision_hours_target,
        "weekly_parent_training_hours_target": (
            weekly_parent_training_hours_target
        ),
    }
    payload.update(overrides)
    return payload


def supersede_treatment_plan_payload(
    *,
    previous_plan_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /treatment-plans/{plan_id}/supersede — BCBA.

    PRD §3.3: "the supersede capability on the new plan, supplying the
    body field previous_plan_id that names the older ACTIVE plan."
    """
    payload: Dict[str, Any] = {"previous_plan_id": previous_plan_id}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Authorization — PRD §3.4
# ---------------------------------------------------------------------------
def create_authorization_payload(
    *,
    treatment_plan_id: str,
    payer_name: Optional[str] = None,
    cpt_code: str = "97153",
    approved_units: int = 240,
    effective_start: str,
    effective_end: str,
    renewed_from_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /patients/{patient_id}/authorizations — ClinicAdmin.

    PRD §3.4: "A ClinicAdmin submits the authorization request, carrying
    a treatment_plan_id (which must be ACTIVE), a payer_name, a cpt_code
    …, the integer approved_units …, the effective_start, the
    effective_end, and optionally a renewed_from_id".
    """
    payload: Dict[str, Any] = {
        "treatment_plan_id": treatment_plan_id,
        "payer_name": (
            payer_name if payer_name is not None
            else TEST_DEFAULTS["DEFAULT_PAYER_NAME"]
        ),
        "cpt_code": cpt_code,
        "approved_units": approved_units,
        "effective_start": effective_start,
        "effective_end": effective_end,
    }
    if renewed_from_id is not None:
        payload["renewed_from_id"] = renewed_from_id
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# TherapySession — PRD §3.5
# ---------------------------------------------------------------------------
def create_session_payload(
    *,
    authorization_id: str,
    therapist_id: str,
    session_type: str,
    planned_start: str,
    planned_end: str,
    supervising_therapist_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /patients/{patient_id}/sessions — ClinicAdmin or BCBA.

    PRD §3.5: "The request body carries the authorization_id …, the
    therapist_id …, the session_type …, the planned_start, the
    planned_end, and, only when the session is a supervision session,
    the supervising_therapist_id".
    """
    payload: Dict[str, Any] = {
        "authorization_id": authorization_id,
        "therapist_id": therapist_id,
        "session_type": session_type,
        "planned_start": planned_start,
        "planned_end": planned_end,
    }
    if supervising_therapist_id is not None:
        payload["supervising_therapist_id"] = supervising_therapist_id
    payload.update(overrides)
    return payload


def complete_session_payload(
    *,
    progress_rating: int = 4,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /sessions/{id}/complete — BCBA or RBT.

    PRD §3.5: "The body must carry the progress_rating, an integer in
    the inclusive range from 1 to 5."
    """
    payload: Dict[str, Any] = {"progress_rating": progress_rating}
    payload.update(overrides)
    return payload


def dispute_session_payload(
    *,
    dispute_reason: str = "review_pending",
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /sessions/{id}/dispute — BCBA.

    PRD §3.5: "A completed session can be disputed by a BCBA, who
    supplies a free-text dispute_reason in the body."
    """
    payload: Dict[str, Any] = {"dispute_reason": dispute_reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# InsuranceClaim — PRD §3.6
# ---------------------------------------------------------------------------
def create_claim_payload(
    *,
    authorization_id: str,
    session_ids: List[str],
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /patients/{patient_id}/claims — ClinicAdmin.

    PRD §3.6: "A ClinicAdmin drafts the claim under a patient, supplying
    the body field authorization_id and the array session_ids."
    """
    payload: Dict[str, Any] = {
        "authorization_id": authorization_id,
        "session_ids": list(session_ids),
    }
    payload.update(overrides)
    return payload


def adjudicate_claim_payload(
    *,
    denial_reason: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /claims/{id}/adjudicate — PayerAdmin.

    PRD §3.6: "A PayerAdmin adjudicates the claim by posting the
    adjudicate capability with an optional body field denial_reason."
    """
    payload: Dict[str, Any] = {}
    if denial_reason is not None:
        payload["denial_reason"] = denial_reason
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Round-half-up — PRD §2.12.
# ---------------------------------------------------------------------------
def round_half_up(value: float) -> int:
    """PRD §2.12: "Whenever a dollar amount must be converted to cents,
    the conversion uses round half up to the nearest cent."

    Python's banker's-rounding default would corrupt this; emulate
    arithmetic round-half-up to the nearest whole integer.
    """
    if value >= 0:
        return int(value + 0.5)
    return -int(-value + 0.5)


__all__ = [
    "iso_utc",
    "parse_iso",
    "add_seconds",
    "add_days",
    "add_minutes",
    "clock_epoch",
    "random_suffix",
    "random_member_id",
    "random_license_number",
    "clock_advance_payload",
    "create_clinic_payload",
    "create_patient_payload",
    "create_therapist_payload",
    "create_evaluation_payload",
    "complete_evaluation_payload",
    "create_treatment_plan_payload",
    "supersede_treatment_plan_payload",
    "create_authorization_payload",
    "create_session_payload",
    "complete_session_payload",
    "dispute_session_payload",
    "create_claim_payload",
    "adjudicate_claim_payload",
    "round_half_up",
]
