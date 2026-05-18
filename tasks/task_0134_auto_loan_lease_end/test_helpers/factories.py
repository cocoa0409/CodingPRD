"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact JSON-body schema the PRD declares for the
request body (PRD §3 narrative + §4 endpoint table). Tests pass
overrides for the values they want to control. Only PRD-declared input
fields are produced; computed/system fields are intentionally omitted
so the implementation cannot accidentally accept them as inputs.

PRD §2.8: monetary fields are integer cents.
"""
from __future__ import annotations

import random
import string
from typing import Any, Dict, Optional

from .constants import (
    DAYS_PER_PERIOD,
    TEST_DEFAULTS,
    VIN_LENGTH,
)


# ---------------------------------------------------------------------------
# Random helpers — unique VINs / names across tests
# ---------------------------------------------------------------------------
def random_suffix(length: int = 6) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits,
                                  k=length))


def random_vin() -> str:
    """PRD §3.2: 'a 17-character vehicle identification number that must
    be unique across all vehicles'."""
    suffix = random_suffix(VIN_LENGTH - 3)  # leave room for prefix
    s = f"VIN{suffix}"
    # Pad/truncate to exactly 17 characters.
    if len(s) < VIN_LENGTH:
        s = s + "0" * (VIN_LENGTH - len(s))
    return s[:VIN_LENGTH]


def random_full_name(base: str = "Test Customer") -> str:
    return f"{base} {random_suffix(4)}"


def random_model(prefix: str = "Model") -> str:
    return f"{prefix}-{random_suffix(4)}"


# ---------------------------------------------------------------------------
# Version body — for OCC-aware mutations (PRD §2.6).
# ---------------------------------------------------------------------------
def version_body(version: Optional[int] = None) -> Dict[str, Any]:
    """PRD §2.6: 'Every mutating endpoint that targets an entity with the
    common-fields set accepts an optional version value in the request
    body.'"""
    return {"version": version} if version is not None else {}


# ---------------------------------------------------------------------------
# Customer — PRD §3.1
# ---------------------------------------------------------------------------
def create_customer_payload(
    *,
    full_name: Optional[str] = None,
    fico_score: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /customers — PRD §3.1.
    Inputs: full_name (str), fico_score (int, 300..850 inclusive)."""
    payload: Dict[str, Any] = {
        "full_name": full_name or random_full_name(),
        "fico_score": (
            fico_score if fico_score is not None
            else TEST_DEFAULTS["FICO_TIER_1"]
        ),
    }
    payload.update(overrides)
    return payload


def update_customer_payload(
    *,
    full_name: Optional[str] = None,
    fico_score: Optional[int] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PUT /customers/{id} — PRD §4 input: full_name?, fico_score?,
    version?."""
    payload: Dict[str, Any] = {}
    if full_name is not None:
        payload["full_name"] = full_name
    if fico_score is not None:
        payload["fico_score"] = fico_score
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Vehicle — PRD §3.2
# ---------------------------------------------------------------------------
def create_vehicle_payload(
    *,
    vin: Optional[str] = None,
    model: Optional[str] = None,
    msrp_cents: Optional[int] = None,
    residual_factor_bps: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /vehicles — PRD §3.2.
    Inputs: vin (17 chars unique), model (str), msrp_cents (>0),
    residual_factor_bps (1000..8000)."""
    payload: Dict[str, Any] = {
        "vin": vin or random_vin(),
        "model": model or random_model(),
        "msrp_cents": (
            msrp_cents if msrp_cents is not None
            else TEST_DEFAULTS["MSRP_CENTS"]
        ),
        "residual_factor_bps": (
            residual_factor_bps if residual_factor_bps is not None
            else TEST_DEFAULTS["RESIDUAL_FACTOR_BPS"]
        ),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Loan contract — PRD §3.3
# ---------------------------------------------------------------------------
def create_loan_contract_payload(
    *,
    vehicle_id: str,
    down_payment_cents: Optional[int] = None,
    term_months: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /customers/{customerId}/loan-contracts — PRD §3.3.
    Inputs: vehicle_id, down_payment_cents, term_months (one of
    {36,48,60,72})."""
    payload: Dict[str, Any] = {
        "vehicle_id": vehicle_id,
        "down_payment_cents": (
            down_payment_cents if down_payment_cents is not None
            else TEST_DEFAULTS["LOAN_DOWN_PAYMENT_CENTS"]
        ),
        "term_months": (
            term_months if term_months is not None
            else TEST_DEFAULTS["LOAN_TERM_MONTHS"]
        ),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Lease contract — PRD §3.4
# ---------------------------------------------------------------------------
def create_lease_contract_payload(
    *,
    vehicle_id: str,
    down_payment_cents: Optional[int] = None,
    term_months: Optional[int] = None,
    mileage_allowance: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /customers/{customerId}/lease-contracts — PRD §3.4.
    Inputs: vehicle_id, down_payment_cents, term_months (one of
    {24,36,48}), mileage_allowance (10000..75000)."""
    payload: Dict[str, Any] = {
        "vehicle_id": vehicle_id,
        "down_payment_cents": (
            down_payment_cents if down_payment_cents is not None
            else TEST_DEFAULTS["LEASE_DOWN_PAYMENT_CENTS"]
        ),
        "term_months": (
            term_months if term_months is not None
            else TEST_DEFAULTS["LEASE_TERM_MONTHS"]
        ),
        "mileage_allowance": (
            mileage_allowance if mileage_allowance is not None
            else TEST_DEFAULTS["MILEAGE_ALLOWANCE"]
        ),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Lease end election — PRD §3.9
# ---------------------------------------------------------------------------
def lease_end_payload(election: str, **overrides: Any) -> Dict[str, Any]:
    """POST .../lease-end — PRD §3.9.
    Input: election ∈ {PURCHASE, RENEW, RETURN}."""
    payload: Dict[str, Any] = {"election": election}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Assessment — PRD §3.9
# ---------------------------------------------------------------------------
def patch_assessment_payload(
    *, odometer_reading: int, **overrides: Any,
) -> Dict[str, Any]:
    """PATCH .../assessment — PRD §3.9.
    Input: odometer_reading (non-negative integer)."""
    payload: Dict[str, Any] = {"odometer_reading": odometer_reading}
    payload.update(overrides)
    return payload


def resolve_assessment_payload(
    *, revised_odometer_reading: int, **overrides: Any,
) -> Dict[str, Any]:
    """POST .../assessment/resolve — PRD §3.9.
    Input: revised_odometer_reading (non-negative integer)."""
    payload: Dict[str, Any] = {
        "revised_odometer_reading": revised_odometer_reading,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Gap rider — PRD §3.7
# ---------------------------------------------------------------------------
def create_gap_rider_payload(
    *,
    contract_id: str,
    contract_type: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /customers/{customerId}/gap-riders — PRD §3.7.
    Inputs: contract_id, contract_type ∈ {LOAN, LEASE}."""
    payload: Dict[str, Any] = {
        "contract_id": contract_id,
        "contract_type": contract_type,
    }
    payload.update(overrides)
    return payload


def claim_gap_rider_payload(
    *, payout_cents: int, **overrides: Any,
) -> Dict[str, Any]:
    """POST .../gap-riders/{id}/claim — PRD §3.7. Input: payout_cents."""
    payload: Dict[str, Any] = {"payout_cents": payout_cents}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Clock advance — PRD §3.11
# ---------------------------------------------------------------------------
def clock_advance_payload(
    *, days_advanced: int, **overrides: Any,
) -> Dict[str, Any]:
    """POST /customers/{customerId}/clock/advance — PRD §3.11.
    Input: days_advanced (1..365 inclusive)."""
    payload: Dict[str, Any] = {"days_advanced": days_advanced}
    payload.update(overrides)
    return payload


__all__ = [
    "random_suffix",
    "random_vin",
    "random_full_name",
    "random_model",
    "version_body",
    "DAYS_PER_PERIOD",
    "create_customer_payload",
    "update_customer_payload",
    "create_vehicle_payload",
    "create_loan_contract_payload",
    "create_lease_contract_payload",
    "lease_end_payload",
    "patch_assessment_payload",
    "resolve_assessment_payload",
    "create_gap_rider_payload",
    "claim_gap_rider_payload",
    "clock_advance_payload",
]
