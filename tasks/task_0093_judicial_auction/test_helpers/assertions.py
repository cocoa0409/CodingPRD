"""Entity assertions and domain invariant checkers.

Each `assert_<entity>` validates the structural envelope of an entity
returned by the API — required fields, types, and PRD-enumerated
states. Domain invariants (deposit conservation, round_number ↔
Auction count) live alongside.

Per PRD §2.4: Lot, BidderAccount, Auction, Deposit, Confirmation,
Payment, TransferOrder carry id/created_at/updated_at/version. Bid
and AuditEvent are append-only with only id/created_at — they MUST
NOT carry updated_at or version.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Lookup helpers (used by tests that need to fish a specific row out of a
# paginated list).
# ---------------------------------------------------------------------------
def find_row(rows: List[Dict[str, Any]], **predicates: Any) -> Dict[str, Any]:
    """Return the first row whose fields match every predicate kwarg.

    Raises AssertionError when no row matches — keeps failure messages
    informative inside tests.
    """
    for row in rows:
        if all(row.get(k) == v for k, v in predicates.items()):
            return row
    raise AssertionError(
        f"No row matching {predicates}. Saw: "
        f"{[dict((k, r.get(k)) for k in predicates) for r in rows]}"
    )


def select_rows(rows: List[Dict[str, Any]],
                **predicates: Any) -> List[Dict[str, Any]]:
    return [
        r for r in rows
        if all(r.get(k) == v for k, v in predicates.items())
    ]


# ---------------------------------------------------------------------------
# Common-field assertion — PRD §2.4
# ---------------------------------------------------------------------------
def _assert_common_fields(data: Dict[str, Any]) -> None:
    assert is_valid_uuid(data.get("id", "")), \
        f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    version = data.get("version")
    assert isinstance(version, int) and version >= 1, \
        f"version must be a positive integer, got {version!r}"


def _assert_append_only_fields(data: Dict[str, Any]) -> None:
    """For append-only entities (PRD §2.4 — Bid and AuditEvent only).

    These rows expose only id and created_at — never updated_at or
    version. The skill spec mandates this distinction.
    """
    assert is_valid_uuid(data.get("id", "")), \
        f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"


# ---------------------------------------------------------------------------
# Lot — PRD §3.1
# ---------------------------------------------------------------------------
_LOT_STATUSES = {
    "DRAFT", "REGISTERED", "ANNOUNCED", "AUCTIONED", "WITHDRAWN", "TRANSFERRED",
}
_ASSET_PROFILES = {"REAL_ESTATE", "VEHICLE", "EQUITY", "MOVABLE_ASSET"}


def assert_lot(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["court_order_no"], str) \
        and len(data["court_order_no"]) > 0, "court_order_no must be non-empty"
    assert data["asset_profile"] in _ASSET_PROFILES, \
        f"asset_profile {data['asset_profile']!r} not in {_ASSET_PROFILES}"
    assert isinstance(data["assessment_value_cents"], int) \
        and data["assessment_value_cents"] >= 1, \
        "assessment_value_cents must be positive integer"
    assert isinstance(data["assessment_report_uri"], str) \
        and len(data["assessment_report_uri"]) > 0
    assert data["status"] in _LOT_STATUSES, \
        f"Lot.status {data['status']!r} not in {_LOT_STATUSES}"
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    # auction_scheduled_start_at + inspection windows are ISO 8601
    for key in (
        "auction_scheduled_start_at",
        "inspection_window_start_at",
        "inspection_window_end_at",
    ):
        if key in data and data[key] is not None:
            assert is_iso8601_timestamp(data[key]), \
                f"{key} must be ISO 8601, got {data[key]!r}"


# ---------------------------------------------------------------------------
# BidderAccount — PRD §3.2
# ---------------------------------------------------------------------------
_BIDDER_STATUSES = {"ACTIVE", "SUSPENDED", "BLOCKED"}


def assert_bidder_account(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["real_name"], str) and len(data["real_name"]) > 0
    assert isinstance(data["id_document_no"], str) \
        and len(data["id_document_no"]) > 0
    assert data["status"] in _BIDDER_STATUSES, \
        f"BidderAccount.status {data['status']!r} not in {_BIDDER_STATUSES}"
    risk = data.get("collusion_risk_score", 0)
    assert isinstance(risk, int) and 0 <= risk <= 100, \
        f"collusion_risk_score must be int in [0,100], got {risk!r}"


# ---------------------------------------------------------------------------
# Auction — PRD §3.3–§3.5
# ---------------------------------------------------------------------------
_AUCTION_STATUSES = {"SCHEDULED", "LIVE", "SOLD", "UNSOLD", "CANCELLED"}
_DEPOSIT_MODES = {"FIXED", "PERCENT"}


def assert_auction(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["lot_id"]), \
        f"lot_id must be UUID, got {data['lot_id']!r}"
    assert data["status"] in _AUCTION_STATUSES, \
        f"Auction.status {data['status']!r} not in {_AUCTION_STATUSES}"
    assert data["deposit_mode"] in _DEPOSIT_MODES, \
        f"deposit_mode {data['deposit_mode']!r} not in {_DEPOSIT_MODES}"
    assert isinstance(data["starting_price_cents"], int) \
        and data["starting_price_cents"] >= 1, \
        "starting_price_cents must be positive integer"
    if "bid_cap_cents" in data and data["bid_cap_cents"] is not None:
        assert isinstance(data["bid_cap_cents"], int)
    # current_high_cents may be null (auction has no valid bids yet)
    if data.get("current_high_cents") is not None:
        assert isinstance(data["current_high_cents"], int) \
            and data["current_high_cents"] >= 0


# ---------------------------------------------------------------------------
# Deposit — PRD §3.4, §3.10
# ---------------------------------------------------------------------------
_DEPOSIT_STATUSES = {"PENDING", "PAID", "REFUNDED", "FORFEITED", "DISPUTED"}


def assert_deposit(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["auction_id"])
    assert is_valid_uuid(data["bidder_account_id"])
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["status"] in _DEPOSIT_STATUSES, \
        f"Deposit.status {data['status']!r} not in {_DEPOSIT_STATUSES}"


# ---------------------------------------------------------------------------
# Bid — PRD §3.5 (append-only)
# ---------------------------------------------------------------------------
_BID_VALIDITIES = {"VALID", "REJECTED", "ROLLED_BACK"}


def assert_bid(data: Dict[str, Any], *, is_clerk_view: bool = False) -> None:
    """Validate a Bid envelope.

    PRD §2.4 declares Bid append-only: only id and created_at are
    exposed; updated_at and version MUST NOT be present.

    PRD §2.11 masks bidder_account_id for non-CourtClerk callers; the
    `is_clerk_view` flag toggles whether the un-masked bidder_account_id
    is required to be present.
    """
    _assert_append_only_fields(data)
    assert "updated_at" not in data, \
        "Bid is append-only — must not carry updated_at (PRD §2.4)"
    assert "version" not in data, \
        "Bid is append-only — must not carry version (PRD §2.4)"
    assert is_valid_uuid(data["auction_id"])
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["validity"] in _BID_VALIDITIES, \
        f"Bid.validity {data['validity']!r} not in {_BID_VALIDITIES}"
    assert isinstance(data["masked_handle"], str) \
        and len(data["masked_handle"]) > 0, \
        "masked_handle must be a non-empty string (PRD §2.11)"
    assert isinstance(data["client_seq_no"], int)
    if is_clerk_view:
        assert is_valid_uuid(data.get("bidder_account_id", "")), \
            "CourtClerk view of a Bid must include un-masked bidder_account_id"


# ---------------------------------------------------------------------------
# Confirmation — PRD §3.8
# ---------------------------------------------------------------------------
_CONFIRMATION_STATUSES = {"DRAFT", "ISSUED", "SEALED", "FAILED"}
_FAILURE_REASONS = {"COLLUSION_FOUND", "BIDDER_DISQUALIFIED", "COURT_OVERRIDE"}


def assert_confirmation(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["auction_id"])
    assert isinstance(data["ruling_document_uri"], str) \
        and len(data["ruling_document_uri"]) > 0
    assert data["status"] in _CONFIRMATION_STATUSES, \
        f"Confirmation.status {data['status']!r} not in {_CONFIRMATION_STATUSES}"
    if data["status"] == "FAILED":
        assert data.get("failure_reason") in _FAILURE_REASONS, \
            "FAILED Confirmation must carry a failure_reason"
    else:
        # PRD §3.8: "Confirmation.failure_reason is null on any
        # confirmation whose status is not FAILED."
        assert data.get("failure_reason") is None, \
            "Non-FAILED Confirmation must have failure_reason == null"


# ---------------------------------------------------------------------------
# Payment — PRD §3.9
# ---------------------------------------------------------------------------
_PAYMENT_STATUSES = {"PENDING", "OVERDUE", "PAID", "FORFEITED"}


def assert_payment(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["confirmation_id"])
    assert isinstance(data["balance_due_cents"], int) \
        and data["balance_due_cents"] >= 0, \
        "balance_due_cents must be non-negative integer (PRD §3.9)"
    assert isinstance(data["penalty_accrued_cents"], int) \
        and data["penalty_accrued_cents"] >= 0
    assert isinstance(data["amount_paid_cents"], int) \
        and data["amount_paid_cents"] >= 0
    assert data["status"] in _PAYMENT_STATUSES, \
        f"Payment.status {data['status']!r} not in {_PAYMENT_STATUSES}"


# ---------------------------------------------------------------------------
# TransferOrder — PRD §3.11
# ---------------------------------------------------------------------------
_TRANSFER_STATUSES = {
    "INITIATED", "AGENCY_NOTIFIED", "HANDOVER_DONE", "COMPLETED", "BLOCKED",
}
_AGENCIES = {
    "REAL_ESTATE_REGISTRY",
    "VEHICLE_AUTHORITY",
    "EQUITY_REGISTRY",
    "COURT_BAILIFF",
}


def assert_transfer_order(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["confirmation_id"])
    assert data["counterpart_agency"] in _AGENCIES, \
        f"counterpart_agency {data['counterpart_agency']!r} not in {_AGENCIES}"
    assert data["status"] in _TRANSFER_STATUSES, \
        f"TransferOrder.status {data['status']!r} not in {_TRANSFER_STATUSES}"


# ---------------------------------------------------------------------------
# AuditEvent — PRD §2.10 (append-only)
# ---------------------------------------------------------------------------
_AUDIT_KINDS = {
    "BID_PLACED", "BID_REJECTED", "BID_ROLLED_BACK",
    "SOFT_CLOSE_EXTENSION", "AUCTION_CLOSED",
    "DEPOSIT_PAID", "DEPOSIT_REFUNDED", "DEPOSIT_FORFEITED",
    "CONFIRMATION_ISSUED", "CONFIRMATION_SEALED", "CONFIRMATION_FAILED",
    "PAYMENT_RECEIVED", "PAYMENT_OVERDUE",
    "TRANSFER_NOTIFIED", "TRANSFER_COMPLETED",
    "COLLUSION_FLAGGED", "REAUCTION_TRIGGERED", "SYSTEM_FAULT_ROLLBACK",
}


def assert_audit_event(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data)
    assert "updated_at" not in data, \
        "AuditEvent is append-only — must not carry updated_at (PRD §2.4)"
    assert "version" not in data, \
        "AuditEvent is append-only — must not carry version (PRD §2.4)"
    assert data["kind"] in _AUDIT_KINDS, \
        f"AuditEvent.kind {data['kind']!r} not in {_AUDIT_KINDS}"
    assert isinstance(data.get("actor_role"), str)
    assert isinstance(data.get("actor_id"), str)
    assert isinstance(data.get("subject_entity"), str)
    assert isinstance(data.get("subject_id"), str)


# ---------------------------------------------------------------------------
# Domain invariants used by difficulty-design tests.
# ---------------------------------------------------------------------------
def assert_deposit_total_conservation(
    deposits: List[Dict[str, Any]], expected_total: int,
) -> None:
    """PRD §2.7: auction-close cascade preserves total escrow.

    Sums amount_cents across deposits in {PAID, REFUNDED, FORFEITED}
    and compares against `expected_total`.
    """
    counted = sum(
        d["amount_cents"] for d in deposits
        if d["status"] in {"PAID", "REFUNDED", "FORFEITED"}
    )
    assert counted == expected_total, (
        f"Deposit conservation broken: "
        f"sum(PAID + REFUNDED + FORFEITED amount_cents) = {counted}, "
        f"expected {expected_total}"
    )


def assert_round_number_matches_auction_count(
    round_number: int, auction_rows: List[Dict[str, Any]], lot_id: str,
) -> None:
    """PRD §3.3 invariant: Lot.round_number == count of Auction rows
    for that lot.
    """
    count = len([a for a in auction_rows if a.get("lot_id") == lot_id])
    assert round_number == count, (
        f"Round-count invariant broken: Lot.round_number = {round_number} "
        f"but Auction rows for this lot = {count}"
    )


def assert_round_half_up_cents(actual: int, balance_due: int, bps: int,
                              days: int) -> None:
    """PRD §3.9: penalty = round_half_up(balance_due * bps * days / 10000).

    Multiplication first, division by 10000, then round-half-up.
    """
    from decimal import Decimal, ROUND_HALF_UP
    num = Decimal(balance_due) * Decimal(bps) * Decimal(days)
    quotient = num / Decimal(10000)
    expected = int(quotient.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    assert actual == expected, (
        f"round_half_up mismatch: balance_due={balance_due}, bps={bps}, "
        f"days={days} → expected {expected}, got {actual}"
    )


__all__ = [
    "find_row",
    "select_rows",
    "assert_lot",
    "assert_bidder_account",
    "assert_auction",
    "assert_deposit",
    "assert_bid",
    "assert_confirmation",
    "assert_payment",
    "assert_transfer_order",
    "assert_audit_event",
    "assert_deposit_total_conservation",
    "assert_round_number_matches_auction_count",
    "assert_round_half_up_cents",
]
