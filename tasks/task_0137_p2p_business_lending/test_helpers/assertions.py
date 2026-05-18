"""Entity assertions and domain invariant checkers.

These check the response shape and domain invariants required by the
PRD contract.

PRD §2.4 common-fields split:
- Platform, Borrower, LoanListing, Investor, Investment, Loan,
  Installment, Payment, ComplianceOfficer carry id + created_at +
  updated_at + version.
- PlaidSnapshot and Disclosure are append-only and carry ONLY
  id + created_at; they have neither updated_at nor version.
"""
from __future__ import annotations

from typing import Any, Dict, List

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
    """PRD §2.4: most resources carry updated_at + version. version
    begins at 1 on creation and increments by exactly 1 per mutation.
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
def assert_platform(data: Dict[str, Any]) -> None:
    """PRD §3.1 Platform shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("currency"), str) and data["currency"]
    for k in (
        "clock_day_index",
        "origination_fee_bps",
        "servicing_fee_bps",
        "late_fee_cents",
        "max_borrower_concentration_bps",
    ):
        assert isinstance(data.get(k), int), (
            f"{k} must be integer, got {type(data.get(k))}"
        )
    assert data["clock_day_index"] >= 0, (
        f"clock_day_index must be non-negative, got "
        f"{data['clock_day_index']}"
    )


def assert_borrower(data: Dict[str, Any]) -> None:
    """PRD §3.2 Borrower shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("platform_id"), str) and data["platform_id"]
    assert isinstance(data.get("legal_name"), str) and data["legal_name"]
    assert isinstance(data.get("ein"), str) and data["ein"]
    for k in ("annual_revenue_cents", "requested_amount_cents"):
        assert isinstance(data.get(k), int), (
            f"{k} must be integer cents, got {type(data.get(k))}"
        )
    # plaid_snapshot_id is null until first snapshot attached.
    psid = data.get("plaid_snapshot_id")
    assert psid is None or (isinstance(psid, str) and psid), (
        f"plaid_snapshot_id must be null or non-empty string, "
        f"got {psid!r}"
    )
    assert data.get("provisional_grade") in {
        "A", "B", "C", "D", "E",
    }, f"unexpected provisional_grade: {data.get('provisional_grade')!r}"
    assert data.get("final_grade") in {
        "A", "B", "C", "D", "E", "UNGRADED",
    }, f"unexpected final_grade: {data.get('final_grade')!r}"
    assert data.get("status") in {
        "PENDING_KYC", "APPROVED", "SUSPENDED", "BANNED",
    }, f"unexpected status: {data.get('status')!r}"


def assert_loan_listing(data: Dict[str, Any]) -> None:
    """PRD §3.3 LoanListing shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("borrower_id"), str)
    assert isinstance(data.get("platform_id"), str)
    for k in (
        "principal_cents",
        "term_months",
        "interest_rate_bps",
        "pledged_cents",
        "funding_deadline_day_index",
    ):
        assert isinstance(data.get(k), int), (
            f"{k} must be integer, got {type(data.get(k))}"
        )
    assert data["principal_cents"] > 0
    assert data["term_months"] in {12, 24, 36, 48, 60}
    assert data["pledged_cents"] >= 0
    assert data["pledged_cents"] <= data["principal_cents"], (
        f"pledged_cents ({data['pledged_cents']}) cannot exceed "
        f"principal_cents ({data['principal_cents']})"
    )
    assert data.get("grade_at_listing") in {
        "A", "B", "C", "D", "E",
    }, f"unexpected grade_at_listing: {data.get('grade_at_listing')!r}"
    assert data.get("status") in {
        "OPEN", "FUNDED", "ORIGINATED", "WITHDRAWN", "EXPIRED",
    }, f"unexpected status: {data.get('status')!r}"


def assert_investor(data: Dict[str, Any]) -> None:
    """PRD §3.8 Investor shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("platform_id"), str)
    assert isinstance(data.get("display_name"), str) and data["display_name"]
    assert data.get("accreditation_status") in {
        "ACCREDITED", "NON_ACCREDITED",
    }, (
        f"unexpected accreditation_status: "
        f"{data.get('accreditation_status')!r}"
    )
    for k in (
        "committed_capital_cents",
        "cash_balance_cents",
        "outstanding_principal_cents",
    ):
        assert isinstance(data.get(k), int), (
            f"{k} must be integer cents, got {type(data.get(k))}"
        )
        assert data[k] >= 0, f"{k} must be non-negative, got {data[k]}"
    assert data.get("status") in {
        "ACTIVE", "SUSPENDED", "CLOSED",
    }, f"unexpected status: {data.get('status')!r}"


def assert_investment(data: Dict[str, Any]) -> None:
    """PRD §3.3, §3.4 Investment shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("listing_id"), str)
    assert isinstance(data.get("investor_id"), str)
    assert isinstance(data.get("amount_cents"), int)
    assert data["amount_cents"] > 0
    assert data.get("status") in {
        "COMMITTED", "RELEASED", "CONVERTED", "LOST",
    }, f"unexpected status: {data.get('status')!r}"
    assert isinstance(data.get("share_bps"), int)
    assert data["share_bps"] >= 0


def assert_loan(data: Dict[str, Any]) -> None:
    """PRD §3.4 Loan shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    for k in ("listing_id", "borrower_id", "platform_id"):
        assert isinstance(data.get(k), str) and data[k], (
            f"{k} must be non-empty string, got {data.get(k)!r}"
        )
    for k in (
        "principal_cents",
        "interest_rate_bps",
        "term_months",
        "monthly_payment_cents",
        "principal_outstanding_cents",
        "accrued_late_fees_cents",
        "charged_off_loss_cents",
        "consecutive_missed_installments",
        "origination_day_index",
    ):
        assert isinstance(data.get(k), int), (
            f"{k} must be integer, got {type(data.get(k))}"
        )
    assert data["principal_cents"] > 0
    assert data["term_months"] in {12, 24, 36, 48, 60}
    assert data["principal_outstanding_cents"] >= 0
    assert data["accrued_late_fees_cents"] >= 0
    assert data["charged_off_loss_cents"] >= 0
    assert data["consecutive_missed_installments"] >= 0
    assert data.get("status") in {
        "ACTIVE", "DELINQUENT", "DEFAULT", "CHARGED_OFF", "PAID_OFF",
    }, f"unexpected status: {data.get('status')!r}"


def assert_installment(data: Dict[str, Any]) -> None:
    """PRD §3.4 Installment shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("loan_id"), str)
    for k in (
        "sequence_number",
        "due_day_index",
        "scheduled_principal_cents",
        "scheduled_interest_cents",
        "paid_principal_cents",
        "paid_interest_cents",
        "paid_fees_cents",
    ):
        assert isinstance(data.get(k), int), (
            f"{k} must be integer, got {type(data.get(k))}"
        )
    assert data["sequence_number"] >= 1
    assert data["scheduled_principal_cents"] >= 0
    assert data["scheduled_interest_cents"] >= 0
    assert data["paid_principal_cents"] >= 0
    assert data["paid_interest_cents"] >= 0
    assert data["paid_fees_cents"] >= 0
    assert data.get("status") in {
        "SCHEDULED", "DUE", "PAID", "LATE", "WAIVED",
    }, f"unexpected status: {data.get('status')!r}"


def assert_payment(data: Dict[str, Any]) -> None:
    """PRD §3.5 Payment shape — includes allocation breakdown."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    for k in ("loan_id", "borrower_id"):
        assert isinstance(data.get(k), str) and data[k], (
            f"{k} must be non-empty string, got {data.get(k)!r}"
        )
    assert isinstance(data.get("amount_cents"), int)
    assert data["amount_cents"] > 0
    assert isinstance(data.get("received_on_day_index"), int)
    assert data.get("status") in {"POSTED", "REVERSED"}, (
        f"unexpected status: {data.get('status')!r}"
    )
    # PRD §3.5: "The allocation object exposes five integer cent
    # fields: fees_cents for servicing fees, interest_cents for
    # scheduled interest, principal_cents for scheduled and prepayment
    # principal, late_fees_cents for accrued late fees, and
    # unallocated_cents for any cent amount that exceeds total
    # liability."
    alloc = data.get("allocation")
    assert isinstance(alloc, dict), (
        f"allocation must be a dict, got {type(alloc).__name__}"
    )
    for k in (
        "fees_cents",
        "interest_cents",
        "principal_cents",
        "late_fees_cents",
        "unallocated_cents",
    ):
        assert isinstance(alloc.get(k), int), (
            f"allocation.{k} must be integer cents, got "
            f"{type(alloc.get(k))}"
        )
        assert alloc[k] >= 0, (
            f"allocation.{k} must be non-negative, got {alloc[k]}"
        )


def assert_compliance_officer(data: Dict[str, Any]) -> None:
    """PRD §3.9 ComplianceOfficer shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("platform_id"), str)
    assert isinstance(data.get("display_name"), str) and data["display_name"]
    assert data.get("status") in {
        "ACTIVE", "INACTIVE",
    }, f"unexpected status: {data.get('status')!r}"


# ===========================================================================
# Append-only resources — PRD §2.4: NO updated_at, NO version.
# ===========================================================================
def assert_plaid_snapshot(data: Dict[str, Any]) -> None:
    """PRD §3.2 PlaidSnapshot shape — append-only, carries ONLY
    id + created_at. PRD §2.4: 'A PlaidSnapshot carries only id and
    created_at and has neither updated_at nor version.'"""
    _assert_id_and_created_at(data)
    # Do NOT assert updated_at / version — PRD says they are absent.
    assert isinstance(data.get("borrower_id"), str)
    for k in (
        "pulled_on_day_index",
        "deposits_last_90d_cents",
        "avg_daily_balance_cents",
        "nsf_count_last_90d",
        "existing_debt_service_cents",
    ):
        assert isinstance(data.get(k), int), (
            f"{k} must be integer, got {type(data.get(k))}"
        )
        assert data[k] >= 0, f"{k} must be non-negative, got {data[k]}"


def assert_disclosure(data: Dict[str, Any]) -> None:
    """PRD §3.7 Disclosure shape — append-only, carries ONLY
    id + created_at. PRD §2.4: 'A Disclosure likewise carries only id
    and created_at among the common fields ... neither updated_at nor
    version is exposed.'"""
    _assert_id_and_created_at(data)
    # Do NOT assert updated_at / version — PRD says they are absent.
    assert isinstance(data.get("platform_id"), str)
    assert data.get("subject_type") in {
        "BORROWER", "LISTING", "LOAN", "INVESTMENT",
    }, f"unexpected subject_type: {data.get('subject_type')!r}"
    assert isinstance(data.get("subject_id"), str) and data["subject_id"]
    assert data.get("kind") in {
        "LISTING_OPENED", "LISTING_FUNDED", "LOAN_ORIGINATED",
        "DELINQUENCY_NOTICE", "DEFAULT_NOTICE", "CHARGE_OFF_NOTICE",
        "MATERIAL_AMENDMENT",
    }, f"unexpected kind: {data.get('kind')!r}"
    assert isinstance(data.get("payload"), dict), (
        f"payload must be a dict, got {type(data.get('payload'))}"
    )
    assert isinstance(data.get("published"), bool), (
        f"published must be a bool, got {type(data.get('published'))}"
    )
    # published_on_day_index is null until publish, integer after.
    pdi = data.get("published_on_day_index")
    assert pdi is None or (isinstance(pdi, int) and pdi >= 0), (
        f"published_on_day_index must be null or non-negative int, "
        f"got {pdi!r}"
    )


# ===========================================================================
# Domain invariants — PRD prose
# ===========================================================================
def assert_amortization_principal_invariant(
    monthly_payment_cents: int,
    installments: List[Dict[str, Any]],
    loan_principal_cents: int,
) -> None:
    """PRD §3.4: 'The final installment absorbs the residual cents so
    that the sum of scheduled_principal_cents across all installments
    equals principal_cents exactly.'"""
    total = sum(int(it["scheduled_principal_cents"]) for it in installments)
    assert total == loan_principal_cents, (
        f"sum(scheduled_principal_cents)={total} != principal_cents="
        f"{loan_principal_cents}"
    )


def assert_charge_off_loss_distribution_invariant(
    investments_deltas: List[int],
    total_loss_cents: int,
) -> None:
    """PRD §3.6: 'the total distributed equals total_loss exactly.'
    The per-investor decrements of outstanding_principal_cents MUST
    sum exactly to Loan.charged_off_loss_cents."""
    total = sum(int(d) for d in investments_deltas)
    assert total == total_loss_cents, (
        f"sum(per-investor loss deltas)={total} != "
        f"total_loss_cents={total_loss_cents}"
    )


def assert_version_incremented_by_one(prev: Dict[str, Any],
                                      curr: Dict[str, Any]) -> None:
    """PRD §2.4: 'The version is a non-negative integer that begins at
    1 on creation and increments by 1 on every successful mutation.'"""
    assert "version" in prev and "version" in curr, (
        "both records must carry version"
    )
    assert curr["version"] == prev["version"] + 1, (
        f"version expected to increment by exactly 1: "
        f"prev={prev['version']} curr={curr['version']}"
    )


__all__ = [
    "assert_platform",
    "assert_borrower",
    "assert_loan_listing",
    "assert_investor",
    "assert_investment",
    "assert_loan",
    "assert_installment",
    "assert_payment",
    "assert_compliance_officer",
    "assert_plaid_snapshot",
    "assert_disclosure",
    "assert_amortization_principal_invariant",
    "assert_charge_off_loss_distribution_invariant",
    "assert_version_incremented_by_one",
]
