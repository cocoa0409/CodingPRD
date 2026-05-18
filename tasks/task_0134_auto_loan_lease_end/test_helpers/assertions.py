"""Entity assertions and domain invariant checkers.

PRD §2.4 distinguishes two common-fields shapes:
- Persisted resources carrying id + created_at + updated_at + version:
  Customer, Vehicle, LoanContract, LeaseContract, GapInsuranceRider,
  LeaseEndAssessment.
- Append-only / immutable event records carrying ONLY id + created_at:
  Payment, DelinquencyEvent, ClockEvent.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common-fields predicates — PRD §2.4
# ---------------------------------------------------------------------------
def _assert_id_and_created_at(data: Dict[str, Any]) -> None:
    assert "id" in data, f"missing id; got keys: {list(data)}"
    assert is_valid_uuid(data["id"]), (
        f"id must be a UUID with no type prefix, got {data['id']!r}"
    )
    assert "created_at" in data, "missing created_at"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"created_at must be ISO 8601, got {data['created_at']!r}"
    )


def _assert_updated_at_and_version(data: Dict[str, Any]) -> None:
    """PRD §2.4: 'monotonically increasing integer version that begins at
    1 on creation and increments by one on every mutation'."""
    assert "updated_at" in data, "missing updated_at"
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"updated_at must be ISO 8601, got {data['updated_at']!r}"
    )
    assert "version" in data, "missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"version must be a positive integer, got "
        f"{data.get('version')!r}"
    )


def assert_version_incremented_by_one(
    before: Dict[str, Any], after: Dict[str, Any],
) -> None:
    """PRD §2.4: 'increments by one on every mutation.'"""
    assert after["version"] == before["version"] + 1, (
        f"expected version {before['version'] + 1}, got {after['version']}"
    )


# ---------------------------------------------------------------------------
# Customer — PRD §3.1
# ---------------------------------------------------------------------------
_CUSTOMER_STATUSES = {"ACTIVE", "SUSPENDED"}
_FICO_TIERS = {"TIER_1", "TIER_2", "TIER_3", "TIER_4", "TIER_5_DECLINED"}


def assert_customer(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    fico = data.get("fico_score")
    assert isinstance(fico, int) and 300 <= fico <= 850, (
        f"fico_score must be int in [300,850]; got {fico!r}"
    )
    assert data.get("fico_tier") in _FICO_TIERS, (
        f"fico_tier must be one of {_FICO_TIERS}, got "
        f"{data.get('fico_tier')!r}"
    )
    assert data.get("status") in _CUSTOMER_STATUSES, (
        f"status must be one of {_CUSTOMER_STATUSES}, got "
        f"{data.get('status')!r}"
    )
    assert isinstance(data.get("default_count"), int)
    assert isinstance(data.get("lifetime_payment_count"), int)
    # default_rate is a number with 6 decimal places per PRD §2.8.
    dr = data.get("default_rate")
    assert isinstance(dr, (int, float))
    assert isinstance(data.get("clock_day_index"), int)


# ---------------------------------------------------------------------------
# Vehicle — PRD §3.2
# ---------------------------------------------------------------------------
_VEHICLE_STATUSES = {"AVAILABLE", "RESERVED", "SOLD", "LEASED"}


def assert_vehicle(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("vin"), str) and len(data["vin"]) == 17
    assert isinstance(data.get("model"), str)
    msrp = data.get("msrp_cents")
    assert isinstance(msrp, int) and msrp > 0
    rf = data.get("residual_factor_bps")
    assert isinstance(rf, int) and 1000 <= rf <= 8000
    assert data.get("status") in _VEHICLE_STATUSES


# ---------------------------------------------------------------------------
# Loan contract — PRD §3.3
# ---------------------------------------------------------------------------
_LOAN_STATUSES = {
    "PENDING_APPROVAL", "APPROVED", "ACTIVE",
    "PAID_OFF", "DEFAULTED", "CHARGED_OFF",
}


def assert_loan_contract(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert is_valid_uuid(data.get("vehicle_id", ""))
    assert isinstance(data.get("principal_cents"), int)
    assert isinstance(data.get("down_payment_cents"), int)
    assert data.get("term_months") in {36, 48, 60, 72}
    assert data.get("status") in _LOAN_STATUSES


# ---------------------------------------------------------------------------
# Lease contract — PRD §3.4
# ---------------------------------------------------------------------------
_LEASE_STATUSES = {
    "PENDING_APPROVAL", "APPROVED", "ACTIVE", "MATURED",
    "PURCHASED", "RENEWED", "RETURNED", "CLOSED", "DEFAULTED",
}


def assert_lease_contract(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert is_valid_uuid(data.get("vehicle_id", ""))
    assert isinstance(data.get("capitalized_cost_cents"), int)
    assert isinstance(data.get("down_payment_cents"), int)
    assert data.get("term_months") in {24, 36, 48}
    assert isinstance(data.get("mileage_allowance"), int)
    assert data.get("status") in _LEASE_STATUSES


# ---------------------------------------------------------------------------
# Payment — PRD §2.4 (immutable, id + created_at only)
# ---------------------------------------------------------------------------
_PAYMENT_STATUSES = {"SCHEDULED", "PAID", "LATE", "DEFAULTED"}
_PAYMENT_CONTRACT_TYPES = {"LOAN", "LEASE"}


def assert_payment(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    # PRD §2.4: Payment carries ONLY id + created_at on the common-fields
    # axis; updated_at / version are NOT on the row.
    assert is_valid_uuid(data.get("customer_id", ""))
    assert is_valid_uuid(data.get("contract_id", ""))
    assert data.get("contract_type") in _PAYMENT_CONTRACT_TYPES
    assert isinstance(data.get("period_index"), int)
    assert data["period_index"] >= 1
    assert isinstance(data.get("due_day_index"), int)
    assert isinstance(data.get("amount_due_cents"), int)
    assert data.get("status") in _PAYMENT_STATUSES


# ---------------------------------------------------------------------------
# Gap insurance rider — PRD §3.7
# ---------------------------------------------------------------------------
_GAP_RIDER_STATUSES = {"ACTIVE", "CANCELLED", "CLAIMED"}


def assert_gap_rider(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("contract_id", ""))
    assert data.get("contract_type") in {"LOAN", "LEASE"}
    assert isinstance(data.get("monthly_premium_cents"), int)
    assert data.get("status") in _GAP_RIDER_STATUSES


# ---------------------------------------------------------------------------
# Lease end assessment — PRD §3.9
# ---------------------------------------------------------------------------
_ASSESSMENT_STATUSES = {
    "DRAFT", "ISSUED", "SETTLED", "DISPUTED", "RESOLVED",
}


def assert_lease_end_assessment(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("lease_contract_id", ""))
    assert data.get("status") in _ASSESSMENT_STATUSES


def assert_assessment_total_invariant(data: Dict[str, Any]) -> None:
    """PRD §3.9: 'The total_due_cents aggregation is the unconditional
    sum of the three component fields on the same assessment row:
    mileage_penalty_cents plus disposition_fee_cents plus
    purchase_option_cents.'"""
    mp = data.get("mileage_penalty_cents", 0) or 0
    df = data.get("disposition_fee_cents", 0) or 0
    po = data.get("purchase_option_cents", 0) or 0
    td = data.get("total_due_cents", 0) or 0
    assert td == mp + df + po, (
        f"total_due_cents invariant violated: "
        f"{td} != {mp} (mileage) + {df} (disposition) + {po} (purchase)"
    )


# ---------------------------------------------------------------------------
# Delinquency event — PRD §3.5 (append-only)
# ---------------------------------------------------------------------------
def assert_delinquency_event(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert is_valid_uuid(data.get("payment_id", ""))
    assert isinstance(data.get("default_count_after"), int)
    assert isinstance(data.get("apr_uplift_bps_applied"), int)
    assert isinstance(data.get("affected_contract_ids"), list)


# ---------------------------------------------------------------------------
# Clock event — PRD §3.11 (append-only)
# ---------------------------------------------------------------------------
def assert_clock_event(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert isinstance(data.get("days_advanced"), int)
    assert 1 <= data["days_advanced"] <= 365
    assert isinstance(data.get("new_clock_day_index"), int)
    assert isinstance(data.get("payments_due_now"), int)
    assert isinstance(data.get("payments_defaulted_now"), int)


# ---------------------------------------------------------------------------
# Loan principal-conservation invariant — Difficulty Rule 9 / PRD §3.5+§3.7
# ---------------------------------------------------------------------------
def assert_loan_principal_conservation(
    loan: Dict[str, Any], gap_claims_sum_cents: int = 0,
) -> None:
    """PRD §3.5: 'remaining_principal_cents is then decremented by the
    principal portion ... total_principal_paid_cents is incremented by
    it'.  PRD §3.7: 'For a loan, the contract's remaining_principal_cents
    is decremented by payout_cents'.

    Invariant: total_principal_paid_cents + remaining_principal_cents
               + sum(gap_claim_payout_cents on this loan)
               == principal_cents (origination)."""
    p = loan["principal_cents"]
    tpp = loan["total_principal_paid_cents"]
    rp = loan["remaining_principal_cents"]
    assert tpp + rp + gap_claims_sum_cents == p, (
        f"principal conservation violated: "
        f"total_paid {tpp} + remaining {rp} + gap_claims "
        f"{gap_claims_sum_cents} != principal {p}"
    )


__all__ = [
    "assert_version_incremented_by_one",
    "assert_customer",
    "assert_vehicle",
    "assert_loan_contract",
    "assert_lease_contract",
    "assert_payment",
    "assert_gap_rider",
    "assert_lease_end_assessment",
    "assert_assessment_total_invariant",
    "assert_delinquency_event",
    "assert_clock_event",
    "assert_loan_principal_conservation",
]
