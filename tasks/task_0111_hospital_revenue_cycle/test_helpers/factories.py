"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact JSON-body schema PRD declares for the
request body. Only PRD-declared input fields are produced; computed and
system-managed fields are intentionally omitted so the implementation
cannot accidentally accept them as inputs.

PRD §2.5: timestamps are ISO 8601 UTC strings with three fractional
digits. PRD §2.7: monetary fields are integer cents.
"""
from __future__ import annotations

import random
import string
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS


# ---------------------------------------------------------------------------
# Timestamp helpers — PRD §2.5 format with three fractional digits.
# ---------------------------------------------------------------------------
def iso_utc(dt: datetime) -> str:
    """Render a datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def iso_now() -> str:
    return iso_utc(utcnow())


def iso_offset(*, days: int = 0, hours: int = 0, minutes: int = 0,
               seconds: int = 0,
               base: Optional[datetime] = None) -> str:
    base = base or utcnow()
    return iso_utc(base + timedelta(
        days=days, hours=hours, minutes=minutes, seconds=seconds,
    ))


def parse_iso(iso_ts: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp back into a timezone-aware
    datetime."""
    return datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))


def iso_date(d: date) -> str:
    return d.isoformat()


def date_today_utc() -> date:
    return datetime.now(tz=timezone.utc).date()


# ---------------------------------------------------------------------------
# Random utilities.
# ---------------------------------------------------------------------------
_ALPHANUM_UPPER = string.ascii_uppercase + string.digits


def random_suffix(n: int = 8) -> str:
    return "".join(random.choices(_ALPHANUM_UPPER, k=n))


def random_mrn(length: int = 10) -> str:
    """PRD §3.1: MRN is 8–12 alphanumeric characters."""
    if length < 8 or length > 12:
        raise ValueError("mrn length must be between 8 and 12")
    return "MR" + "".join(random.choices(_ALPHANUM_UPPER, k=length - 2))


# ---------------------------------------------------------------------------
# Patient — PRD §3.1 / §4
# ---------------------------------------------------------------------------
def create_patient_payload(
    *,
    mrn: Optional[str] = None,
    full_name: Optional[str] = None,
    date_of_birth: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /patients — RegistrationClerk.

    PRD §3.1: required input fields are mrn (8-12 alphanumeric, unique),
    full_name (legal name), and date_of_birth (ISO 8601 calendar date).
    """
    payload: Dict[str, Any] = {
        "mrn": mrn if mrn is not None else random_mrn(),
        "full_name": (
            full_name if full_name is not None
            else f"Patient {random_suffix(4)}"
        ),
        "date_of_birth": (
            date_of_birth if date_of_birth is not None else "1980-01-15"
        ),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# InsurancePolicy — PRD §3.1 / §4
# ---------------------------------------------------------------------------
def create_policy_payload(
    *,
    payer_name: Optional[str] = None,
    policy_number: Optional[str] = None,
    plan_year: Optional[int] = None,
    deductible_cents: Optional[int] = None,
    coinsurance_rate_bps: Optional[int] = None,
    oop_max_cents: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /patients/{patient_id}/policies — RegistrationClerk.

    PRD §3.1: required input fields are payer_name, policy_number,
    plan_year (integer), deductible_cents (>= 0), coinsurance_rate_bps
    (0-10000), oop_max_cents (>= deductible_cents).
    """
    payload: Dict[str, Any] = {
        "payer_name": (
            payer_name if payer_name is not None
            else f"Payer {random_suffix(3)}"
        ),
        "policy_number": (
            policy_number if policy_number is not None
            else f"POL-{random_suffix(6)}"
        ),
        "plan_year": (
            plan_year if plan_year is not None
            else TEST_DEFAULTS["PLAN_YEAR"]
        ),
        "deductible_cents": (
            deductible_cents if deductible_cents is not None
            else TEST_DEFAULTS["DEDUCTIBLE_CENTS"]
        ),
        "coinsurance_rate_bps": (
            coinsurance_rate_bps if coinsurance_rate_bps is not None
            else TEST_DEFAULTS["COINSURANCE_RATE_BPS"]
        ),
        "oop_max_cents": (
            oop_max_cents if oop_max_cents is not None
            else TEST_DEFAULTS["OOP_MAX_CENTS"]
        ),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Encounter — PRD §3.2 / §4
# ---------------------------------------------------------------------------
def create_encounter_payload(
    *,
    patient_id: str,
    policy_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /encounters — RegistrationClerk.

    PRD §3.2: required input fields are patient_id and policy_id.
    """
    payload: Dict[str, Any] = {
        "patient_id": patient_id,
        "policy_id": policy_id,
    }
    payload.update(overrides)
    return payload


def patch_encounter_payload(
    *,
    policy_id: Optional[str] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PATCH /encounters/{encounter_id} — RegistrationClerk.

    PRD §2.6 + §3.2: payload may carry the current version to opt in to
    optimistic concurrency control (omitting version skips the check),
    and only policy_id is modifiable through this path.
    """
    payload: Dict[str, Any] = {}
    if policy_id is not None:
        payload["policy_id"] = policy_id
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Eligibility verification — PRD §3.3 / §4
# ---------------------------------------------------------------------------
def verify_eligibility_payload(
    *,
    policy_eligible: bool = True,
    denial_code: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /encounters/{encounter_id}/verify-eligibility —
    RegistrationClerk.

    PRD §3.3: required input is policy_eligible (boolean); optional
    denial_code when policy_eligible is false.
    """
    payload: Dict[str, Any] = {"policy_eligible": policy_eligible}
    if denial_code is not None:
        payload["denial_code"] = denial_code
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ChargeItem — PRD §3.4 / §4
# ---------------------------------------------------------------------------
def create_charge_payload(
    *,
    cpt_code: Optional[str] = None,
    description: Optional[str] = None,
    quantity: Optional[int] = None,
    unit_price_cents: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /encounters/{encounter_id}/charges — ChargeCaptureClerk.

    PRD §3.4: required input fields are cpt_code (exactly 5 digits),
    description, quantity (>= 1), unit_price_cents (>= 0).
    """
    payload: Dict[str, Any] = {
        "cpt_code": (
            cpt_code if cpt_code is not None
            else TEST_DEFAULTS["CPT_CODE_PRIMARY"]
        ),
        "description": (
            description if description is not None
            else f"Service {random_suffix(4)}"
        ),
        "quantity": (
            quantity if quantity is not None
            else TEST_DEFAULTS["CHARGE_QUANTITY"]
        ),
        "unit_price_cents": (
            unit_price_cents if unit_price_cents is not None
            else TEST_DEFAULTS["CHARGE_UNIT_PRICE_CENTS"]
        ),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# CodingRecord — PRD §3.6 / §4
# ---------------------------------------------------------------------------
def submit_coding_payload(
    *,
    primary_icd10: Optional[str] = None,
    secondary_icd10: Optional[List[str]] = None,
    cpt_codes: Optional[List[str]] = None,
    coder_id: Optional[str] = None,
    finalize: bool = True,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /encounters/{encounter_id}/coding — Coder.

    PRD §3.6: required input fields are primary_icd10 (ICD-10 pattern),
    cpt_codes (list of 5-digit codes), coder_id, finalize (boolean).
    secondary_icd10 is optional with default empty list.
    """
    payload: Dict[str, Any] = {
        "primary_icd10": (
            primary_icd10 if primary_icd10 is not None
            else TEST_DEFAULTS["PRIMARY_ICD10"]
        ),
        "cpt_codes": (
            cpt_codes if cpt_codes is not None
            else [TEST_DEFAULTS["CPT_CODE_PRIMARY"]]
        ),
        "coder_id": (
            coder_id if coder_id is not None
            else TEST_DEFAULTS["DEFAULT_CODER_ID"]
        ),
        "finalize": finalize,
    }
    if secondary_icd10 is not None:
        payload["secondary_icd10"] = secondary_icd10
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ClearanceDecision — PRD §3.6 / §4
# ---------------------------------------------------------------------------
def submit_clearance_payload(
    *,
    decision: str = "APPROVED",
    allowed_amount_cents: int = 0,
    denial_reason_code: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /encounters/{encounter_id}/clearance — Biller.

    PRD §3.6: required input fields are decision (APPROVED, PARTIAL,
    DENIED), allowed_amount_cents (0..total_charges_cents; 0 when
    DENIED), denial_reason_code (required when DENIED or PARTIAL).
    """
    payload: Dict[str, Any] = {
        "decision": decision,
        "allowed_amount_cents": allowed_amount_cents,
    }
    if denial_reason_code is not None:
        payload["denial_reason_code"] = denial_reason_code
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# PatientPayment — PRD §3.7 / §4
# ---------------------------------------------------------------------------
def post_payment_payload(
    *,
    amount_cents: int = 1,
    method: str = "CASH",
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /encounters/{encounter_id}/payments — Biller.

    PRD §3.7: required input fields are amount_cents (>= 1) and method
    (CASH, CARD, CHECK, REFUND).
    """
    payload: Dict[str, Any] = {
        "amount_cents": amount_cents,
        "method": method,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Clock advance — PRD §2.11 / §4
# ---------------------------------------------------------------------------
def clock_advance_payload(
    *,
    to_timestamp: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /_clock/advance — TestHarness, Biller, RegistrationClerk.

    PRD §2.11: required input is to_timestamp (target ISO 8601 instant).
    """
    payload: Dict[str, Any] = {"to_timestamp": to_timestamp}
    payload.update(overrides)
    return payload


__all__ = [
    # time helpers
    "iso_utc",
    "utcnow",
    "iso_now",
    "iso_offset",
    "parse_iso",
    "iso_date",
    "date_today_utc",
    # random
    "random_suffix",
    "random_mrn",
    # payloads
    "create_patient_payload",
    "create_policy_payload",
    "create_encounter_payload",
    "patch_encounter_payload",
    "verify_eligibility_payload",
    "create_charge_payload",
    "submit_coding_payload",
    "submit_clearance_payload",
    "post_payment_payload",
    "clock_advance_payload",
]
