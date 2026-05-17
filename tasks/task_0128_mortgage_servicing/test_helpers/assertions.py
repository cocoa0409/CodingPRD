"""Entity assertions and domain invariant checkers.

These check the response shape and domain invariants required by the
PRD contract.

PRD §2.4 common-fields split:
- All entities EXCEPT EscrowAnalysis carry id + created_at + updated_at
  + version.
- EscrowAnalysis is an immutable snapshot once FINALIZED, exposing only
  id + created_at; it has neither updated_at nor version.
"""
from __future__ import annotations

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common-fields predicates — PRD §2.4
# ---------------------------------------------------------------------------
def _assert_id_and_created_at(data: Dict[str, Any]) -> None:
    """Every resource carries id + created_at — PRD §2.4."""
    assert "id" in data, f"missing id; got keys: {list(data)}"
    assert is_valid_uuid(data["id"]), (
        f"id must be a UUID with no type prefix, got {data['id']!r}"
    )
    assert "created_at" in data, "missing created_at"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"created_at must be ISO 8601 with three fractional digits, "
        f"got {data['created_at']!r}"
    )


def _assert_updated_at_and_version(data: Dict[str, Any]) -> None:
    """PRD §2.4: every resource except EscrowAnalysis carries
    updated_at + version. version begins at 1 on creation and
    increments by exactly 1 per mutation.
    """
    assert "updated_at" in data, "missing updated_at"
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"updated_at must be ISO 8601 with three fractional digits, "
        f"got {data['updated_at']!r}"
    )
    assert "version" in data, "missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"version must be a positive integer, got "
        f"{data.get('version')!r}"
    )


# ===========================================================================
# Top-level resources
# ===========================================================================
def assert_borrower(data: Dict[str, Any]) -> None:
    """PRD §3.1 Borrower shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("email"), str) and data["email"]
    # hardship_attested_at is null until attestation; ISO timestamp after.
    ha = data.get("hardship_attested_at")
    assert ha is None or isinstance(ha, str), (
        f"hardship_attested_at must be null or ISO string, got {ha!r}"
    )


def assert_loan(data: Dict[str, Any]) -> None:
    """PRD §3.1 Loan shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("borrower_id"), str) and data["borrower_id"]
    assert isinstance(data.get("origination_date"), str)
    for k in (
        "original_principal_cents",
        "original_appraised_value_cents",
        "interest_rate_bps",
        "term_months",
        "scheduled_payment_cents",
        "principal_balance_cents",
        "escrow_balance_cents",
        "monthly_escrow_payment_cents",
        "pmi_monthly_cents",
        "delinquency_days",
    ):
        assert isinstance(data.get(k), int), (
            f"{k} must be integer cents/bps/days, got {type(data.get(k))}"
        )
    assert data["original_principal_cents"] >= 100_000
    assert data["original_appraised_value_cents"] > 0
    assert 1 <= data["interest_rate_bps"] <= 5_000
    assert 60 <= data["term_months"] <= 480
    assert data["principal_balance_cents"] >= 0
    assert data["delinquency_days"] >= 0
    assert data.get("pmi_status") in {
        "ACTIVE", "REMOVAL_REQUESTED", "REMOVED", "AUTO_TERMINATED",
    }, f"unexpected pmi_status: {data.get('pmi_status')!r}"
    assert data.get("posture") in {
        "CURRENT", "DELINQUENT", "FORBEARANCE", "DEFAULT",
        "FORECLOSURE", "REINSTATED", "PAID_OFF",
    }, f"unexpected posture: {data.get('posture')!r}"
    assert isinstance(data.get("next_due_date"), str)


def assert_payment(data: Dict[str, Any]) -> None:
    """PRD §3.2 Payment shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("loan_id"), str)
    assert isinstance(data.get("received_date"), str)
    for k in (
        "amount_cents",
        "allocation_principal_cents",
        "allocation_interest_cents",
        "allocation_escrow_cents",
        "allocation_late_fee_cents",
        "allocation_suspense_cents",
    ):
        assert isinstance(data.get(k), int) and data[k] >= 0, (
            f"{k} must be non-negative integer, got {data.get(k)!r}"
        )
    assert data.get("status") in {"POSTED", "REVERSED"}, (
        f"unexpected status: {data.get('status')!r}"
    )
    # reversed_at is null while POSTED, ISO timestamp when REVERSED.
    rev = data.get("reversed_at")
    assert rev is None or isinstance(rev, str), (
        f"reversed_at must be null or string, got {rev!r}"
    )


def assert_disbursement(data: Dict[str, Any]) -> None:
    """PRD §3.3 Disbursement shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("loan_id"), str)
    assert data.get("type") in {
        "PROPERTY_TAX", "HAZARD_INSURANCE", "SURPLUS_REFUND",
    }, f"unexpected type: {data.get('type')!r}"
    assert isinstance(data.get("scheduled_date"), str)
    assert isinstance(data.get("amount_cents"), int)
    assert data["amount_cents"] > 0, (
        f"amount_cents must be strictly positive, got {data['amount_cents']}"
    )
    assert data.get("status") in {
        "SCHEDULED", "PAID", "FAILED", "CANCELED",
    }, f"unexpected status: {data.get('status')!r}"
    fr = data.get("failure_reason")
    assert fr is None or fr == "INSUFFICIENT_ESCROW", (
        f"unexpected failure_reason: {fr!r}"
    )


def assert_forbearance_plan(data: Dict[str, Any]) -> None:
    """PRD §3.4 ForbearancePlan shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("loan_id"), str)
    assert isinstance(data.get("start_date"), str)
    assert isinstance(data.get("end_date"), str)
    assert isinstance(data.get("months"), int)
    assert 1 <= data["months"] <= 12, (
        f"months must be 1..12, got {data['months']}"
    )
    assert data.get("repayment_method") in {
        "LUMP_SUM", "REPAYMENT_PLAN_12M", "DEFERRAL",
    }, f"unexpected repayment_method: {data.get('repayment_method')!r}"
    assert data.get("status") in {
        "ACTIVE", "COMPLETED", "BREACHED", "CANCELED",
    }, f"unexpected status: {data.get('status')!r}"
    assert isinstance(data.get("total_paused_cents"), int)
    assert data["total_paused_cents"] >= 0


def assert_pmi_removal_request(data: Dict[str, Any]) -> None:
    """PRD §3.5 PmiRemovalRequest shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("loan_id"), str)
    assert data.get("trigger") in {
        "BORROWER_REQUEST", "AUTO_TERMINATION",
    }, f"unexpected trigger: {data.get('trigger')!r}"
    assert isinstance(data.get("evaluated_ltv_bps"), int)
    assert data["evaluated_ltv_bps"] >= 0
    assert data.get("decision") in {
        "PENDING", "APPROVED", "DENIED",
    }, f"unexpected decision: {data.get('decision')!r}"
    dr = data.get("denial_reason")
    assert dr is None or dr in {
        "LTV_TOO_HIGH",
        "PAYMENT_HISTORY_INSUFFICIENT",
        "LOAN_NOT_CURRENT",
    }, f"unexpected denial_reason: {dr!r}"


def assert_foreclosure_case(data: Dict[str, Any]) -> None:
    """PRD §3.6 ForeclosureCase shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("loan_id"), str)
    assert data.get("status") in {
        "NOI_ISSUED", "MEDIATION_OPEN", "FILED", "AUCTION_SCHEDULED",
        "CLOSED_REINSTATED", "CLOSED_MODIFIED", "CLOSED_SOLD",
    }, f"unexpected status: {data.get('status')!r}"
    assert isinstance(data.get("noi_sent_at"), str)
    fa = data.get("filed_at")
    assert fa is None or isinstance(fa, str)
    ad = data.get("auction_date")
    assert ad is None or isinstance(ad, str)
    assert isinstance(data.get("foreclosure_costs_cents"), int)
    assert data["foreclosure_costs_cents"] >= 0


def assert_mediation_case(data: Dict[str, Any]) -> None:
    """PRD §3.7 MediationCase shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("foreclosure_case_id"), str)
    assert data.get("status") in {
        "REQUESTED", "OPEN", "OFFER_EXTENDED", "OFFER_ACCEPTED",
        "OFFER_REJECTED", "FAILED", "COMPLETED",
    }, f"unexpected status: {data.get('status')!r}"
    rr = data.get("rejection_reason")
    assert rr is None or rr in {
        "DTI_TOO_HIGH", "AFFORDABILITY_FLOOR", "BORROWER_REFUSED",
    }, f"unexpected rejection_reason: {rr!r}"


# ===========================================================================
# Immutable snapshot — PRD §2.4: EscrowAnalysis has only id + created_at
# ===========================================================================
def assert_escrow_analysis(data: Dict[str, Any]) -> None:
    """PRD §3.3 EscrowAnalysis shape — immutable snapshot, carries
    ONLY id + created_at. PRD §2.4: 'EscrowAnalysis is an immutable
    snapshot once it has been finalised, and therefore exposes only id
    and created_at; it has neither updated_at nor version.'"""
    _assert_id_and_created_at(data)
    # Do NOT assert updated_at / version — PRD says they are absent.
    assert isinstance(data.get("loan_id"), str)
    assert isinstance(data.get("analysis_date"), str)
    assert data.get("status") in {
        "PROVISIONAL", "FINALIZED", "SUPERSEDED",
    }, f"unexpected status: {data.get('status')!r}"
    for k in (
        "projected_disbursements_cents",
        "required_cushion_cents",
        "starting_balance_cents",
        "shortage_cents",
        "surplus_cents",
        "new_monthly_escrow_cents",
    ):
        assert isinstance(data.get(k), int), (
            f"{k} must be integer cents, got {type(data.get(k))}"
        )
        assert data[k] >= 0, f"{k} must be non-negative, got {data[k]}"
    fa = data.get("finalized_at")
    assert fa is None or isinstance(fa, str)


# ===========================================================================
# Domain invariants
# ===========================================================================
def assert_principal_invariant(loan: Dict[str, Any],
                               posted_payments: list,
                               modification_principal_forbearance: int = 0,
                               ) -> None:
    """PRD §3.2: 'The fundamental invariant preserved across posting
    and reversal is that the current principal_balance_cents plus the
    sum of allocation_principal_cents across all POSTED payments equals
    original_principal_cents minus any principal forbearance granted by
    an accepted loan modification.'"""
    posted_sum = sum(
        int(p.get("allocation_principal_cents", 0))
        for p in posted_payments
        if p.get("status") == "POSTED"
    )
    expected = (
        int(loan["original_principal_cents"])
        - int(modification_principal_forbearance)
    )
    actual = int(loan["principal_balance_cents"]) + posted_sum
    assert actual == expected, (
        f"principal invariant violated: principal_balance_cents "
        f"({loan['principal_balance_cents']}) + "
        f"sum(POSTED allocation_principal_cents) ({posted_sum}) = "
        f"{actual} != original_principal_cents ({expected})"
    )


def assert_waterfall_sum_equals_amount(payment: Dict[str, Any]) -> None:
    """PRD §3.2: the five allocation buckets together exhaust amount_cents
    when no foreclosure-cost line is involved. PRD §3.2 names the five
    allocation_*_cents fields as the totality of the standard waterfall
    output.
    """
    total = sum(
        int(payment.get(k, 0))
        for k in (
            "allocation_late_fee_cents",
            "allocation_interest_cents",
            "allocation_principal_cents",
            "allocation_escrow_cents",
            "allocation_suspense_cents",
        )
    )
    assert total == int(payment["amount_cents"]), (
        f"sum of allocations ({total}) != amount_cents "
        f"({payment['amount_cents']})"
    )


def assert_version_incremented_by_one(prev: Dict[str, Any],
                                      curr: Dict[str, Any]) -> None:
    """PRD §2.4: 'version is an integer that starts at 1 on creation
    and increases by exactly 1 on each mutation.'"""
    assert "version" in prev and "version" in curr, (
        "both records must carry version"
    )
    assert curr["version"] == prev["version"] + 1, (
        f"version expected to increment by exactly 1: "
        f"prev={prev['version']} curr={curr['version']}"
    )


__all__ = [
    "assert_borrower",
    "assert_loan",
    "assert_payment",
    "assert_disbursement",
    "assert_forbearance_plan",
    "assert_pmi_removal_request",
    "assert_foreclosure_case",
    "assert_mediation_case",
    "assert_escrow_analysis",
    "assert_principal_invariant",
    "assert_waterfall_sum_equals_amount",
    "assert_version_incremented_by_one",
]
