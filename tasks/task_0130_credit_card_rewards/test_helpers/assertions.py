"""Entity assertions and domain invariant checkers.

These check the response shape and domain invariants required by the
PRD contract. They are intentionally generous about server-minted fields
that PRD prose does not pin specifically; a test that wants to pin a
specific computed value asserts it directly in test code.

PRD §2.4 common-fields contract:
- Cardholder, Account, CashbackCategory, Transaction, TransferPartner
  carry id + created_at + updated_at + version.
- QuarterlyActivation, PointsTransfer, StatementCredit, PointsLedgerEntry
  are append-only: ONLY id + created_at, no updated_at, no version.
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
    assert "id" in data, f"missing id; got keys: {list(data)}"
    assert is_valid_uuid(data["id"]), (
        f"id must be a UUID with no type prefix, got {data['id']!r}"
    )
    assert "created_at" in data, "missing created_at"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"created_at must be ISO 8601, got {data['created_at']!r}"
    )


def _assert_updated_at_and_version(data: Dict[str, Any]) -> None:
    """PRD §2.4: 'an integer version that starts at 1 on creation and
    increments by one with every mutation'."""
    assert "updated_at" in data, "missing updated_at"
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"updated_at must be ISO 8601, got {data['updated_at']!r}"
    )
    assert "version" in data, "missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def _assert_no_updated_at_or_version(data: Dict[str, Any]) -> None:
    """PRD §2.4 lean entities (QuarterlyActivation, PointsTransfer,
    StatementCredit, PointsLedgerEntry) carry only id + created_at —
    'with both updated_at and version absent from their JSON shape'.
    """
    assert "updated_at" not in data, (
        f"append-only entity must not expose updated_at, got "
        f"{data.get('updated_at')!r}"
    )
    assert "version" not in data, (
        f"append-only entity must not expose version, got "
        f"{data.get('version')!r}"
    )


# ===========================================================================
# Cardholder — PRD §3.1
# ===========================================================================
def assert_cardholder(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("email"), str) and data["email"]
    # PRD §3.1: 'email (a lowercase, unique RFC 5322 address used for
    # login lookup)'.
    assert data["email"] == data["email"].lower(), (
        f"email must be lowercase, got {data['email']!r}"
    )
    assert "@" in data["email"], (
        f"email must be RFC 5322 form, got {data['email']!r}"
    )
    assert isinstance(data.get("display_name"), str) and data["display_name"]


# ===========================================================================
# Account — PRD §3.1
# ===========================================================================
def assert_account(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("cardholder_id", "")), (
        f"cardholder_id must be a UUID, got "
        f"{data.get('cardholder_id')!r}"
    )
    assert isinstance(data.get("opened_at"), str)
    assert is_iso8601_timestamp(data["opened_at"]), (
        f"opened_at must be ISO 8601, got {data['opened_at']!r}"
    )
    assert data.get("lifecycle_state") in {
        "ACTIVE", "DELINQUENT", "CLOSED",
    }, (
        f"lifecycle_state must be one of ACTIVE/DELINQUENT/CLOSED, got "
        f"{data.get('lifecycle_state')!r}"
    )
    assert data.get("spending_tier") in {
        "STANDARD", "GOLD", "PLATINUM",
    }, (
        f"spending_tier must be one of STANDARD/GOLD/PLATINUM, got "
        f"{data.get('spending_tier')!r}"
    )
    assert isinstance(data.get("ytd_qualifying_spend_cents"), int)
    assert data["ytd_qualifying_spend_cents"] >= 0
    assert isinstance(data.get("points_balance"), int)
    assert data["points_balance"] >= 0, (
        f"points_balance must be non-negative, got "
        f"{data['points_balance']}"
    )
    assert data.get("signup_bonus_state") in {
        "PENDING", "QUALIFIED", "AWARDED", "EXPIRED", "FORFEITED",
    }, (
        f"signup_bonus_state must be one of PENDING/QUALIFIED/AWARDED/"
        f"EXPIRED/FORFEITED, got {data.get('signup_bonus_state')!r}"
    )
    assert isinstance(
        data.get("signup_bonus_qualifying_spend_cents"), int,
    )
    assert data["signup_bonus_qualifying_spend_cents"] >= 0
    assert is_iso8601_timestamp(
        data.get("signup_bonus_deadline_at", ""),
    ), (
        f"signup_bonus_deadline_at must be ISO 8601, got "
        f"{data.get('signup_bonus_deadline_at')!r}"
    )
    assert is_iso8601_timestamp(
        data.get("last_qualifying_activity_at", ""),
    ), (
        f"last_qualifying_activity_at must be ISO 8601, got "
        f"{data.get('last_qualifying_activity_at')!r}"
    )


# ===========================================================================
# CashbackCategory — PRD §3.2
# ===========================================================================
def assert_cashback_category(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("code"), str) and data["code"]
    assert data.get("category_type") in {
        "BASELINE", "FIXED_BONUS", "ROTATING_QUARTERLY",
    }, (
        f"category_type must be one of BASELINE/FIXED_BONUS/"
        f"ROTATING_QUARTERLY, got {data.get('category_type')!r}"
    )
    assert isinstance(data.get("base_rate_bps"), int)
    # PRD §3.2: 'an integer base_rate_bps between zero and ten thousand
    # inclusive'.
    assert 0 <= data["base_rate_bps"] <= 10_000, (
        f"base_rate_bps must be in [0, 10000], got "
        f"{data['base_rate_bps']}"
    )
    assert isinstance(data.get("requires_activation"), bool)
    # PRD §3.2: "the server sets requires_activation to true if and only
    # if category_type is ROTATING_QUARTERLY".
    expected_requires = (data["category_type"] == "ROTATING_QUARTERLY")
    assert data["requires_activation"] is expected_requires, (
        f"requires_activation must be {expected_requires} for "
        f"category_type {data['category_type']}, got "
        f"{data['requires_activation']}"
    )


# ===========================================================================
# Transaction — PRD §3.4
# ===========================================================================
def assert_transaction(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("account_id", ""))
    assert is_valid_uuid(data.get("category_id", ""))
    assert data.get("txn_type") in {"PURCHASE", "REFUND"}
    assert isinstance(data.get("amount_cents"), int)
    # PRD §3.4: 'an amount_cents of at least one (always non-negative;
    # the sign is encoded in txn_type)'.
    assert data["amount_cents"] >= 1, (
        f"amount_cents must be >= 1, got {data['amount_cents']}"
    )
    assert is_iso8601_timestamp(data.get("posted_at", "")), (
        f"posted_at must be ISO 8601, got {data.get('posted_at')!r}"
    )
    assert data.get("status") in {"POSTED", "REVERSED"}
    assert isinstance(data.get("points_provisional"), int)
    assert isinstance(data.get("points_final"), int)


# ===========================================================================
# TransferPartner — PRD §3.3
# ===========================================================================
def assert_transfer_partner(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("code"), str) and data["code"]
    assert data.get("partner_type") in {"AIRLINE", "HOTEL"}
    assert isinstance(data.get("conversion_ratio_points_per_unit"), int)
    # PRD §3.3: 'integer conversion_ratio_points_per_unit of at least
    # one'.
    assert data["conversion_ratio_points_per_unit"] >= 1, (
        f"conversion_ratio_points_per_unit must be >= 1, got "
        f"{data['conversion_ratio_points_per_unit']}"
    )
    assert isinstance(data.get("min_transfer_increment"), int)
    # PRD §3.3: 'integer min_transfer_increment of at least one'.
    assert data["min_transfer_increment"] >= 1, (
        f"min_transfer_increment must be >= 1, got "
        f"{data['min_transfer_increment']}"
    )
    assert isinstance(data.get("is_active"), bool)


# ===========================================================================
# QuarterlyActivation — PRD §3.2; PRD §2.4 append-only entity
# ===========================================================================
def assert_quarterly_activation(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_no_updated_at_or_version(data)
    assert is_valid_uuid(data.get("account_id", ""))
    assert is_valid_uuid(data.get("category_id", ""))
    assert isinstance(data.get("quarter_label"), str)
    # PRD §2.12: 'four digits then the letter Q then a digit one through
    # four, for example 2026Q2'.
    assert len(data["quarter_label"]) == 6, (
        f"quarter_label must be YYYYQq (6 chars), got "
        f"{data['quarter_label']!r}"
    )
    assert data["quarter_label"][4] == "Q"
    assert data["quarter_label"][:4].isdigit()
    assert data["quarter_label"][5] in {"1", "2", "3", "4"}
    assert is_iso8601_timestamp(
        data.get("activation_window_start", ""),
    )
    assert is_iso8601_timestamp(data.get("activation_window_end", ""))
    assert is_iso8601_timestamp(data.get("activated_at", ""))
    assert data.get("status") in {"ACTIVATED", "EXPIRED"}


# ===========================================================================
# PointsTransfer — PRD §3.7; PRD §2.4 append-only entity
# ===========================================================================
def assert_points_transfer(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_no_updated_at_or_version(data)
    assert is_valid_uuid(data.get("account_id", ""))
    assert is_valid_uuid(data.get("partner_id", ""))
    assert isinstance(data.get("requested_partner_units"), int)
    assert data["requested_partner_units"] >= 1
    assert isinstance(data.get("points_debited"), int)
    assert data["points_debited"] >= 0
    assert data.get("status") in {"PENDING", "COMPLETED", "REVERSED"}
    assert is_iso8601_timestamp(data.get("initiated_at", ""))
    # completed_at is null until COMPLETED.
    if data.get("completed_at") is not None:
        assert is_iso8601_timestamp(data["completed_at"]), (
            f"completed_at must be ISO 8601, got {data['completed_at']!r}"
        )


# ===========================================================================
# StatementCredit — PRD §3.6; PRD §2.4 append-only entity
# ===========================================================================
def assert_statement_credit(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_no_updated_at_or_version(data)
    assert is_valid_uuid(data.get("account_id", ""))
    assert data.get("redemption_mode") in {
        "POINTS_FIRST", "AMOUNT_FIRST",
    }
    # PRD §3.6: "POINTS_FIRST requires requested_points to be present
    # and requested_amount_cents to be absent; AMOUNT_FIRST requires
    # requested_amount_cents to be present and requested_points to be
    # absent." On read PRD §3.9 says: "both requested_points and
    # requested_amount_cents on credits (the unused field is null per
    # the redemption-mode contract of §3.6)."
    if data["redemption_mode"] == "POINTS_FIRST":
        assert isinstance(data.get("requested_points"), int)
        assert data["requested_points"] >= 1
        assert data.get("requested_amount_cents") in (None, 0) or (
            data.get("requested_amount_cents") is None
        ), (
            f"requested_amount_cents must be null on POINTS_FIRST, got "
            f"{data.get('requested_amount_cents')!r}"
        )
    else:
        assert isinstance(data.get("requested_amount_cents"), int)
        assert data["requested_amount_cents"] >= 1
        assert data.get("requested_points") is None, (
            f"requested_points must be null on AMOUNT_FIRST, got "
            f"{data.get('requested_points')!r}"
        )
    assert isinstance(data.get("points_debited"), int)
    assert data["points_debited"] >= 0
    assert isinstance(data.get("credit_amount_cents"), int)
    assert data["credit_amount_cents"] >= 0
    assert is_iso8601_timestamp(data.get("applied_at", ""))
    assert data.get("status") in {"APPLIED", "REVERSED"}


# ===========================================================================
# PointsLedgerEntry — PRD §2.7; PRD §2.4 append-only entity
# ===========================================================================
def assert_ledger_entry(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_no_updated_at_or_version(data)
    assert is_valid_uuid(data.get("account_id", ""))
    # PRD §2.7: "an entry_type drawn from the enumeration EARN,
    # EARN_ADJUST, SIGNUP_BONUS, TRANSFER_DEBIT, TRANSFER_REVERSE,
    # REDEEM_DEBIT, REDEEM_REVERSE, EXPIRE, and FORFEIT".
    assert data.get("entry_type") in {
        "EARN", "EARN_ADJUST", "SIGNUP_BONUS", "TRANSFER_DEBIT",
        "TRANSFER_REVERSE", "REDEEM_DEBIT", "REDEEM_REVERSE", "EXPIRE",
        "FORFEIT",
    }, (
        f"entry_type must be one of the nine enumeration values, got "
        f"{data.get('entry_type')!r}"
    )
    # PRD §2.7: "a source_entity_type drawn from Transaction,
    # PointsTransfer, StatementCredit, Account, and System".
    assert data.get("source_entity_type") in {
        "Transaction", "PointsTransfer", "StatementCredit", "Account",
        "System",
    }
    # PRD §2.7: "a source_entity_id linking back to the originating row
    # (or null when source_entity_type is System)".
    if data["source_entity_type"] == "System":
        assert data.get("source_entity_id") is None, (
            f"source_entity_id must be null when source_entity_type is "
            f"System, got {data.get('source_entity_id')!r}"
        )
    else:
        assert is_valid_uuid(data.get("source_entity_id", "")), (
            f"source_entity_id must be a UUID, got "
            f"{data.get('source_entity_id')!r}"
        )
    assert isinstance(data.get("delta_points"), int)
    assert is_iso8601_timestamp(data.get("occurred_at", ""))


# ===========================================================================
# Domain invariants
# ===========================================================================
def assert_balance_equals_ledger_sum(account: Dict[str, Any],
                                     ledger: List[Dict[str, Any]]) -> None:
    """PRD §2.7: 'Every change to it is materialised by appending
    exactly one row to the PointsLedgerEntry ledger and then recomputing
    points_balance as the signed sum of delta_points over all entries
    for the account.'
    """
    total = sum(
        e["delta_points"] for e in ledger
        if e.get("account_id") == account.get("id")
    )
    assert account["points_balance"] == total, (
        f"points_balance ({account['points_balance']}) must equal the "
        f"signed sum of delta_points over the ledger ({total})"
    )


def assert_version_incremented_by_one(after: Dict[str, Any],
                                      before_version: int) -> None:
    """PRD §2.4: 'an integer version that starts at 1 on creation and
    increments by one with every mutation'.
    """
    assert after["version"] == before_version + 1, (
        f"expected version {before_version + 1}, got {after['version']}"
    )


def find_ledger_entries(ledger: List[Dict[str, Any]],
                        *,
                        entry_type: str = None,
                        source_entity_id: str = None,
                        source_entity_type: str = None
                        ) -> List[Dict[str, Any]]:
    """Filter helper for assertions over the ledger."""
    out = list(ledger)
    if entry_type is not None:
        out = [e for e in out if e.get("entry_type") == entry_type]
    if source_entity_id is not None:
        out = [e for e in out
               if e.get("source_entity_id") == source_entity_id]
    if source_entity_type is not None:
        out = [e for e in out
               if e.get("source_entity_type") == source_entity_type]
    return out


__all__ = [
    "assert_cardholder",
    "assert_account",
    "assert_cashback_category",
    "assert_transaction",
    "assert_transfer_partner",
    "assert_quarterly_activation",
    "assert_points_transfer",
    "assert_statement_credit",
    "assert_ledger_entry",
    "assert_balance_equals_ledger_sum",
    "assert_version_incremented_by_one",
    "find_ledger_entries",
]
