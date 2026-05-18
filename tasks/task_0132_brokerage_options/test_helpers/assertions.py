"""Entity assertions and domain invariant checkers.

These check the response shape and domain invariants required by the
PRD contract.

PRD §2.4 common-fields split:
- Customer, Account, OptionsApproval, Order, ACATTransfer carry id +
  created_at + updated_at + version.
- KYCSubmission and DayTrade are append-only audit rows: id +
  created_at only. NO updated_at, NO version.
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
        f"id must be a server-minted UUID with no type prefix, "
        f"got {data['id']!r}"
    )
    assert "created_at" in data, "missing created_at"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"created_at must be ISO 8601 UTC with three fractional digits, "
        f"got {data['created_at']!r}"
    )


def _assert_updated_at_and_version(data: Dict[str, Any]) -> None:
    """PRD §2.4: every resource EXCEPT KYCSubmission and DayTrade carries
    updated_at + version. version begins at 1 on creation and increments
    by exactly 1 per mutation.
    """
    assert "updated_at" in data, "missing updated_at"
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"updated_at must be ISO 8601 UTC with three fractional digits, "
        f"got {data['updated_at']!r}"
    )
    assert "version" in data, "missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"version must be a positive integer, got "
        f"{data.get('version')!r}"
    )


def _assert_append_only_shape(data: Dict[str, Any]) -> None:
    """PRD §2.4: KYCSubmission and DayTrade 'carry only id and
    created_at. Both updated_at and version are absent from those two
    resource shapes'."""
    assert "updated_at" not in data, (
        "append-only resource must NOT carry updated_at (PRD §2.4)"
    )
    assert "version" not in data, (
        "append-only resource must NOT carry version (PRD §2.4)"
    )


# ===========================================================================
# Customer — PRD §3.1
# ===========================================================================
def assert_customer(data: Dict[str, Any]) -> None:
    """PRD §3.1 Customer shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("legal_name"), str) and data["legal_name"]
    assert isinstance(data.get("date_of_birth"), str), (
        "date_of_birth must be a YYYY-MM-DD string"
    )
    assert isinstance(data.get("ssn_last4"), str)
    assert len(data["ssn_last4"]) == 4 and data["ssn_last4"].isdigit()
    for k in (
        "annual_income_cents",
        "liquid_net_worth_cents",
        "total_net_worth_cents",
        "years_options_experience",
    ):
        assert isinstance(data.get(k), int), (
            f"{k} must be integer, got {type(data.get(k))}"
        )
        assert data[k] >= 0, f"{k} must be non-negative"
    assert (
        data["total_net_worth_cents"] >= data["liquid_net_worth_cents"]
    ), "total_net_worth_cents must be >= liquid_net_worth_cents (PRD §3.1)"
    assert data.get("kyc_status") in {
        "NOT_STARTED", "PENDING", "VERIFIED", "REJECTED",
    }, f"unexpected kyc_status: {data.get('kyc_status')!r}"
    assert isinstance(data.get("w9_collected"), bool), (
        "w9_collected must be boolean"
    )


# ===========================================================================
# Account — PRD §3.1, §3.4
# ===========================================================================
def assert_account(data: Dict[str, Any]) -> None:
    """PRD §3.1 Account shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("customer_id"), str) and data["customer_id"]
    assert data.get("account_type") in {
        "CASH", "MARGIN_REG_T", "MARGIN_PMA",
    }, f"unexpected account_type: {data.get('account_type')!r}"
    assert data.get("status") in {
        "PENDING_KYC", "KYC_REVIEW", "APPROVED", "REJECTED", "CLOSED",
    }, f"unexpected status: {data.get('status')!r}"
    assert data.get("trading_posture") in {
        "RESTRICTED", "OPEN", "PDT_FROZEN", "TRANSFER_LOCKED",
    }, f"unexpected trading_posture: {data.get('trading_posture')!r}"
    assert isinstance(data.get("options_level"), int)
    assert 0 <= data["options_level"] <= 4, (
        "options_level must be in [0,4] (PRD §3.2)"
    )
    for k in ("cash_balance_cents", "equity_value_cents"):
        assert isinstance(data.get(k), int)
    assert isinstance(data.get("pdt_flag"), bool)
    pfa = data.get("pdt_flagged_at")
    assert pfa is None or (
        isinstance(pfa, str) and is_iso8601_timestamp(pfa)
    ), f"pdt_flagged_at must be null or ISO 8601, got {pfa!r}"


# ===========================================================================
# KYCSubmission — PRD §3.1 (append-only)
# ===========================================================================
def assert_kyc_submission(data: Dict[str, Any]) -> None:
    """PRD §3.1 KYCSubmission shape; PRD §2.4 says append-only."""
    _assert_id_and_created_at(data)
    _assert_append_only_shape(data)
    assert isinstance(data.get("customer_id"), str)
    assert data.get("government_id_type") in {
        "PASSPORT", "DRIVERS_LICENSE", "STATE_ID",
    }, f"unexpected government_id_type: {data.get('government_id_type')!r}"
    assert isinstance(data.get("government_id_number"), str)
    assert isinstance(data.get("address_line1"), str)
    assert isinstance(data.get("address_country"), str)
    assert len(data["address_country"]) == 2 and (
        data["address_country"].isupper()
    ), "address_country must be exactly 2 uppercase letters (PRD §3.1)"
    assert isinstance(data.get("w9_signed_name"), str)
    assert data.get("status") in {"PENDING", "VERIFIED", "REJECTED"}, (
        f"unexpected status: {data.get('status')!r}"
    )
    rr = data.get("rejection_reason")
    assert rr is None or isinstance(rr, str), (
        f"rejection_reason must be null or string, got {rr!r}"
    )


# ===========================================================================
# OptionsApproval — PRD §3.2
# ===========================================================================
def assert_options_approval(data: Dict[str, Any]) -> None:
    """PRD §3.2 OptionsApproval shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("account_id"), str)
    rl = data.get("requested_level")
    assert isinstance(rl, int) and 1 <= rl <= 4, (
        f"requested_level must be int in [1,4], got {rl!r}"
    )
    assert data.get("status") in {
        "SUBMITTED", "UNDER_REVIEW", "APPROVED", "REJECTED",
        "REVISION_REQUESTED",
    }, f"unexpected status: {data.get('status')!r}"
    al = data.get("approved_level")
    assert al is None or (isinstance(al, int) and 0 <= al <= 4), (
        f"approved_level must be null or int in [0,4], got {al!r}"
    )
    rc = data.get("revision_count")
    assert isinstance(rc, int) and rc >= 0, (
        f"revision_count must be non-negative int, got {rc!r}"
    )


# ===========================================================================
# Order — PRD §3.3
# ===========================================================================
def assert_order(data: Dict[str, Any]) -> None:
    """PRD §3.3 Order shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("account_id"), str)
    assert isinstance(data.get("symbol"), str)
    s = data["symbol"]
    assert 1 <= len(s) <= 5 and s.isupper() and s.isalpha(), (
        f"symbol must be 1..5 uppercase A-Z, got {s!r} (PRD §3.3)"
    )
    assert data.get("instrument_type") in {"EQUITY", "OPTION"}, (
        f"unexpected instrument_type: {data.get('instrument_type')!r}"
    )
    os_field = data.get("option_strategy")
    if data["instrument_type"] == "OPTION":
        assert os_field in {
            "COVERED_CALL", "CASH_SECURED_PUT", "LONG_CALL", "LONG_PUT",
            "SPREAD", "NAKED_CALL", "NAKED_PUT",
        }, f"option_strategy required for OPTION; got {os_field!r}"
    else:
        # PRD §3.3: option_strategy required iff instrument_type==OPTION.
        # For EQUITY orders option_strategy should be absent or null.
        assert os_field is None, (
            f"option_strategy must be null for EQUITY orders, got "
            f"{os_field!r}"
        )
    assert data.get("side") in {"BUY", "SELL"}
    assert data.get("order_type") in {
        "MARKET", "LIMIT", "STOP", "STOP_LIMIT", "TAKE_PROFIT",
    }
    assert isinstance(data.get("quantity"), int) and data["quantity"] >= 1
    assert data.get("status") in {
        "ACCEPTED", "WORKING", "FILLED", "CANCELLED", "REJECTED",
    }, f"unexpected status: {data.get('status')!r}"
    assert isinstance(data.get("opened_for_day_trade"), bool)
    assert isinstance(data.get("margin_requirement_cents"), int)
    assert data["margin_requirement_cents"] >= 0


# ===========================================================================
# ACATTransfer — PRD §3.5
# ===========================================================================
def assert_acat_transfer(data: Dict[str, Any]) -> None:
    """PRD §3.5 ACATTransfer shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("account_id"), str)
    assert data.get("direction") in {"INBOUND", "OUTBOUND"}
    assert isinstance(data.get("counterparty_brokerage"), str)
    assert isinstance(data.get("counterparty_account_number"), str)
    rv = data.get("requested_value_cents")
    assert isinstance(rv, int) and rv >= 100, (
        f"requested_value_cents must be >= 100 (PRD §3.5), got {rv!r}"
    )
    assert data.get("status") in {
        "INITIATED", "VALIDATED", "IN_TRANSIT", "COMPLETED",
        "REJECTED", "CANCELLED",
    }, f"unexpected status: {data.get('status')!r}"
    assert isinstance(data.get("initiated_at"), str)
    assert is_iso8601_timestamp(data["initiated_at"])
    eca = data.get("expected_completion_at")
    assert eca is None or (
        isinstance(eca, str) and is_iso8601_timestamp(eca)
    ), f"expected_completion_at must be null or ISO 8601, got {eca!r}"
    ca = data.get("completed_at")
    assert ca is None or (
        isinstance(ca, str) and is_iso8601_timestamp(ca)
    )
    bde = data.get("business_days_elapsed")
    assert isinstance(bde, int) and bde >= 0


# ===========================================================================
# DayTrade — append-only
# ===========================================================================
def assert_day_trade(data: Dict[str, Any]) -> None:
    """PRD §3.4 DayTrade shape (append-only)."""
    _assert_id_and_created_at(data)
    _assert_append_only_shape(data)
    assert isinstance(data.get("account_id"), str)
    assert isinstance(data.get("symbol"), str)
    assert isinstance(data.get("opening_order_id"), str)
    assert isinstance(data.get("closing_order_id"), str)
    assert isinstance(data.get("trade_date"), str)


# ===========================================================================
# Domain invariants
# ===========================================================================
def assert_version_incremented_by_one(after: int, before: int) -> None:
    """PRD §2.4: 'version that begins at 1 and increases by exactly 1
    on every successful mutation.'"""
    assert after == before + 1, (
        f"version must increment by exactly 1, got {before} -> {after}"
    )


def assert_account_invariants(data: Dict[str, Any]) -> None:
    """Cross-field invariants on Account that must hold after any
    operation.

    PRD §3.2: 'options_level (default 0)' and approved levels are 0..4.
    PRD §3.4: 'while Account.pdt_flag is true and
    Account.equity_value_cents is strictly less than 2,500,000 ...'.
    """
    assert 0 <= data["options_level"] <= 4
    if data["pdt_flag"]:
        assert data.get("pdt_flagged_at") is not None, (
            "pdt_flagged_at must be populated when pdt_flag is true "
            "(PRD §3.4)"
        )


__all__ = [
    "assert_customer",
    "assert_account",
    "assert_kyc_submission",
    "assert_options_approval",
    "assert_order",
    "assert_acat_transfer",
    "assert_day_trade",
    "assert_version_incremented_by_one",
    "assert_account_invariants",
]
