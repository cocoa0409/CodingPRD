"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact JSON-body schema PRD declares for the
request body. Only PRD-declared input fields are produced; computed
and system-managed fields are intentionally omitted so the
implementation cannot accidentally accept them as inputs.

PRD §2.4: ISO 8601 UTC timestamps carry three fractional digits.
"""
from __future__ import annotations

import random
import string
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Timestamp helpers — PRD §2.4 ISO 8601 UTC format with three fractional
# digits.
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


# ---------------------------------------------------------------------------
# Random utilities.
# ---------------------------------------------------------------------------
_ALPHANUM_UPPER = string.ascii_uppercase + string.digits
_DIGITS = string.digits
_LETTERS_UPPER = string.ascii_uppercase


def random_suffix(n: int = 8) -> str:
    return "".join(random.choices(_ALPHANUM_UPPER, k=n))


def random_npi_number() -> str:
    """PRD §3.1: npi_number is "10-digit npi_number (which must match
    the regular expression for ten consecutive digits and be unique
    across all physicians on the platform)".
    """
    return "".join(random.choices(_DIGITS, k=10))


def random_dea_number() -> str:
    """PRD §3.1: dea_number "matching the pattern of two uppercase
    letters followed by seven digits, unique across physicians when
    present".
    """
    prefix = "".join(random.choices(_LETTERS_UPPER, k=2))
    digits = "".join(random.choices(_DIGITS, k=7))
    return f"{prefix}{digits}"


def random_license_number(prefix: str = "LIC") -> str:
    return f"{prefix}-{random_suffix(8)}"


def random_payer_id() -> str:
    return f"PAYER-{random_suffix(6)}"


def random_member_id() -> str:
    return f"MEM-{random_suffix(10)}"


# ---------------------------------------------------------------------------
# OCC payload — PRD §2.5
# ---------------------------------------------------------------------------
def occ_payload(*, version: Optional[int] = None,
                **extras: Any) -> Dict[str, Any]:
    """A minimal payload that may carry an OCC version field per
    PRD §2.5: "Any endpoint that mutates a resource accepts an optional
    version field in its request body."
    """
    body: Dict[str, Any] = dict(extras)
    if version is not None:
        body["version"] = version
    return body


# ---------------------------------------------------------------------------
# Physician — PRD §3.1
# ---------------------------------------------------------------------------
def create_physician_payload(
    *,
    full_name: Optional[str] = None,
    npi_number: Optional[str] = None,
    imlc_compact_member: Optional[bool] = None,
    imlc_home_state: Optional[str] = None,
    dea_number: Optional[str] = None,
    omit_optional: bool = False,
) -> Dict[str, Any]:
    """POST /telemed/physicians — PRD §3.1.

    Required: full_name, npi_number.
    Optional (with PRD defaults): imlc_compact_member (default false),
    imlc_home_state (default null), dea_number (default null).
    """
    payload: Dict[str, Any] = {
        "full_name": full_name or f"Dr. {random_suffix(6)}",
        "npi_number": npi_number or random_npi_number(),
    }
    if imlc_compact_member is not None:
        payload["imlc_compact_member"] = imlc_compact_member
    if imlc_home_state is not None:
        payload["imlc_home_state"] = imlc_home_state
    if dea_number is not None:
        payload["dea_number"] = dea_number
    return payload


# ---------------------------------------------------------------------------
# StateLicense — PRD §3.1
# ---------------------------------------------------------------------------
def create_state_license_payload(
    *,
    state_code: str = "CA",
    license_number: Optional[str] = None,
    license_type: str = "FULL",
    issued_at: Optional[str] = None,
    expires_at: Optional[str] = None,
) -> Dict[str, Any]:
    """POST /telemed/physicians/{id}/licenses — PRD §3.1.

    Required: state_code, license_number, license_type, issued_at,
    expires_at.
    """
    return {
        "state_code": state_code,
        "license_number": license_number or random_license_number(),
        "license_type": license_type,
        "issued_at": issued_at or "2025-01-01T00:00:00.000Z",
        "expires_at": expires_at or "2030-01-01T00:00:00.000Z",
    }


# ---------------------------------------------------------------------------
# Patient — PRD §3.2
# ---------------------------------------------------------------------------
def create_patient_payload(
    *,
    full_name: Optional[str] = None,
    date_of_birth: Optional[str] = None,
    home_state_code: str = "CA",
    present_state_code: Optional[str] = None,
    insurance_payer_id: Optional[str] = None,
    insurance_member_id: Optional[str] = None,
    insurance_deductible_remaining_cents: Optional[int] = None,
    insurance_copay_cents: Optional[int] = None,
    insurance_coinsurance_bps: Optional[int] = None,
) -> Dict[str, Any]:
    """POST /telemed/patients — PRD §3.2.

    Required: full_name, date_of_birth, home_state_code.
    Optional: present_state_code, insurance_payer_id,
    insurance_member_id, insurance_deductible_remaining_cents,
    insurance_copay_cents, insurance_coinsurance_bps.
    """
    payload: Dict[str, Any] = {
        "full_name": full_name or f"Patient {random_suffix(6)}",
        "date_of_birth": date_of_birth or "1990-01-01T00:00:00.000Z",
        "home_state_code": home_state_code,
    }
    if present_state_code is not None:
        payload["present_state_code"] = present_state_code
    if insurance_payer_id is not None:
        payload["insurance_payer_id"] = insurance_payer_id
    if insurance_member_id is not None:
        payload["insurance_member_id"] = insurance_member_id
    if insurance_deductible_remaining_cents is not None:
        payload["insurance_deductible_remaining_cents"] = (
            insurance_deductible_remaining_cents
        )
    if insurance_copay_cents is not None:
        payload["insurance_copay_cents"] = insurance_copay_cents
    if insurance_coinsurance_bps is not None:
        payload["insurance_coinsurance_bps"] = insurance_coinsurance_bps
    return payload


def patch_patient_payload(
    *,
    present_state_code: Optional[str] = None,
    insurance_deductible_remaining_cents: Optional[int] = None,
    insurance_copay_cents: Optional[int] = None,
    insurance_coinsurance_bps: Optional[int] = None,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    """PATCH /telemed/patients/{id} — PRD §3.2."""
    payload: Dict[str, Any] = {}
    if present_state_code is not None:
        payload["present_state_code"] = present_state_code
    if insurance_deductible_remaining_cents is not None:
        payload["insurance_deductible_remaining_cents"] = (
            insurance_deductible_remaining_cents
        )
    if insurance_copay_cents is not None:
        payload["insurance_copay_cents"] = insurance_copay_cents
    if insurance_coinsurance_bps is not None:
        payload["insurance_coinsurance_bps"] = insurance_coinsurance_bps
    if version is not None:
        payload["version"] = version
    return payload


# ---------------------------------------------------------------------------
# Consult — PRD §3.3
# ---------------------------------------------------------------------------
def create_consult_payload(
    *,
    patient_id: str,
    present_state_code: Optional[str] = None,
    billing_mode: str = "SELF_PAY",
    visit_tier: str = "STANDARD",
    requires_followup: Optional[bool] = None,
) -> Dict[str, Any]:
    """POST /telemed/consults — PRD §3.3."""
    payload: Dict[str, Any] = {
        "patient_id": patient_id,
        "billing_mode": billing_mode,
        "visit_tier": visit_tier,
    }
    if present_state_code is not None:
        payload["present_state_code"] = present_state_code
    if requires_followup is not None:
        payload["requires_followup"] = requires_followup
    return payload


def route_consult_payload(
    *,
    physician_id: str,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    """POST /telemed/consults/{id}/route — PRD §3.3.

    The compliance officer supplies a physician_id and an optional
    version.
    """
    payload: Dict[str, Any] = {"physician_id": physician_id}
    if version is not None:
        payload["version"] = version
    return payload


# ---------------------------------------------------------------------------
# Prescription — PRD §3.4
# ---------------------------------------------------------------------------
def create_prescription_payload(
    *,
    drug_name: Optional[str] = None,
    dea_schedule: str = "NONE",
    days_supply: int = 15,
    refills: Optional[int] = None,
    epcs_two_factor_token: Optional[str] = None,
) -> Dict[str, Any]:
    """POST /telemed/consults/{cid}/prescriptions — PRD §3.4.

    drug_name is required. refills defaults to 0 per PRD §3.4 ("an
    optional refills count defaulting to 0"). epcs_two_factor_token is
    optional at create; required at issue for controlled substances.
    """
    payload: Dict[str, Any] = {
        "drug_name": drug_name or f"Drug-{random_suffix(6)}",
        "dea_schedule": dea_schedule,
        "days_supply": days_supply,
    }
    if refills is not None:
        payload["refills"] = refills
    if epcs_two_factor_token is not None:
        payload["epcs_two_factor_token"] = epcs_two_factor_token
    return payload


def patch_prescription_payload(
    *,
    drug_name: Optional[str] = None,
    dea_schedule: Optional[str] = None,
    days_supply: Optional[int] = None,
    refills: Optional[int] = None,
    epcs_two_factor_token: Optional[str] = None,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    """PATCH /telemed/prescriptions/{id} — PRD §3.4."""
    payload: Dict[str, Any] = {}
    if drug_name is not None:
        payload["drug_name"] = drug_name
    if dea_schedule is not None:
        payload["dea_schedule"] = dea_schedule
    if days_supply is not None:
        payload["days_supply"] = days_supply
    if refills is not None:
        payload["refills"] = refills
    if epcs_two_factor_token is not None:
        payload["epcs_two_factor_token"] = epcs_two_factor_token
    if version is not None:
        payload["version"] = version
    return payload


def void_prescription_payload(
    *,
    void_reason: str,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    """POST /telemed/prescriptions/{id}/void — PRD §3.4 requires
    void_reason."""
    payload: Dict[str, Any] = {"void_reason": void_reason}
    if version is not None:
        payload["version"] = version
    return payload


# ---------------------------------------------------------------------------
# InsuranceClaim — PRD §3.7
# ---------------------------------------------------------------------------
def deny_claim_payload(
    *,
    denial_reason: str,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    """POST /telemed/claims/{id}/deny — PRD §3.7 requires
    denial_reason."""
    payload: Dict[str, Any] = {"denial_reason": denial_reason}
    if version is not None:
        payload["version"] = version
    return payload


# ---------------------------------------------------------------------------
# Clock advance — PRD §2.9 / §3.7
# ---------------------------------------------------------------------------
def clock_advance_payload(*, to: str) -> Dict[str, Any]:
    """POST /telemed/_clock/advance — PRD §2.9 / §3.7 requires a `to`
    target instant."""
    return {"to": to}


__all__ = [
    # Timestamp helpers
    "iso_utc",
    "iso_now",
    "iso_offset",
    "parse_iso",
    "utcnow",
    # Random utilities
    "random_suffix",
    "random_npi_number",
    "random_dea_number",
    "random_license_number",
    "random_payer_id",
    "random_member_id",
    # Payloads
    "occ_payload",
    "create_physician_payload",
    "create_state_license_payload",
    "create_patient_payload",
    "patch_patient_payload",
    "create_consult_payload",
    "route_consult_payload",
    "create_prescription_payload",
    "patch_prescription_payload",
    "void_prescription_payload",
    "deny_claim_payload",
    "clock_advance_payload",
]
