"""Auction lifecycle, open, cancel, system-rollback — PRD §3.5."""
from __future__ import annotations

from typing import Any, Optional

from ..audit import emit_audit, emit_system_audit
from ..clock import add_hours, now_dt, parse_iso
from ..constants import (
    DEFAULT_SOFT_CLOSE_EXTENSION_SECONDS,
    DEFAULT_SOFT_CLOSE_WINDOW_SECONDS,
    MAX_PERCENT_BPS,
    MIN_PERCENT_BPS,
    REFUND_SLA_HOURS,
)
from ..errors import ApiError
from ..store import bump_version, common_fields_create, get_store, now_iso
from .calculations import deposit_amount_fixed, deposit_amount_percent


def create_auction_row(
    *,
    lot_id: str,
    round_number: int,
    starting_price_cents: int,
    bid_cap_cents: Optional[int],
    deposit_mode: str,
    deposit_fixed_cents: Optional[int],
    deposit_percent_bps: Optional[int],
    deposit_deadline_at: str,
    payment_deadline_days: int,
    scheduled_end_at: str,
    soft_close_window_seconds: int,
    soft_close_extension_seconds: int,
    scheduled_start_at: str,
) -> dict[str, Any]:
    """Construct and persist an Auction row in SCHEDULED status."""
    store = get_store()
    cf = common_fields_create()
    auction = {
        **cf,
        "lot_id": lot_id,
        "starting_price_cents": int(starting_price_cents),
        "bid_increment_cents": None,  # recomputed on each bid
        "bid_cap_cents": int(bid_cap_cents) if bid_cap_cents is not None else None,
        "deposit_mode": deposit_mode,
        "deposit_fixed_cents": int(deposit_fixed_cents) if deposit_fixed_cents is not None else None,
        "deposit_percent_bps": int(deposit_percent_bps) if deposit_percent_bps is not None else None,
        "deposit_amount_cents": None,  # pinned at announce
        "deposit_deadline_at": deposit_deadline_at,
        "payment_deadline_days": int(payment_deadline_days),
        "scheduled_start_at": scheduled_start_at,
        "scheduled_end_at": scheduled_end_at,
        "effective_end_at": scheduled_end_at,
        "soft_close_window_seconds": int(soft_close_window_seconds or DEFAULT_SOFT_CLOSE_WINDOW_SECONDS),
        "soft_close_extension_seconds": int(soft_close_extension_seconds or DEFAULT_SOFT_CLOSE_EXTENSION_SECONDS),
        "current_high_cents": None,
        "highest_bid_id": None,
        "second_highest_bid_id": None,
        "status": "SCHEDULED",
        "outcome_winner_account_id": None,
        "round_number": int(round_number),
    }
    store.auctions[auction["id"]] = auction
    return auction


def deposit_amount_calc_for(auction: dict[str, Any]) -> int:
    """Pin Auction.deposit_amount_cents according to deposit_mode (PRD §3.4)."""
    if auction.get("deposit_amount_cents") is not None:
        return int(auction["deposit_amount_cents"])
    mode = auction.get("deposit_mode")
    starting_price = int(auction["starting_price_cents"])
    if mode == "FIXED":
        fixed = auction.get("deposit_fixed_cents")
        if fixed is None:
            raise ApiError("ERR_VALIDATION", "deposit_fixed_cents required when deposit_mode = FIXED.")
        if int(fixed) < 0 or int(fixed) > starting_price:
            raise ApiError(
                "ERR_VALIDATION",
                "deposit_fixed_cents must be in [0, starting_price_cents].",
            )
        amount = deposit_amount_fixed(int(fixed))
    elif mode == "PERCENT":
        bps = auction.get("deposit_percent_bps")
        if bps is None:
            raise ApiError("ERR_VALIDATION", "deposit_percent_bps required when deposit_mode = PERCENT.")
        if int(bps) < MIN_PERCENT_BPS or int(bps) > MAX_PERCENT_BPS:
            raise ApiError(
                "ERR_VALIDATION",
                f"deposit_percent_bps must be in [{MIN_PERCENT_BPS}, {MAX_PERCENT_BPS}].",
            )
        amount = deposit_amount_percent(starting_price, int(bps))
    else:
        raise ApiError("ERR_VALIDATION", "deposit_mode must be FIXED or PERCENT.")
    auction["deposit_amount_cents"] = int(amount)
    return int(amount)


def open_auction(auction_id: str) -> dict[str, Any]:
    """POST /auctions/{id}/open — SCHEDULED → LIVE."""
    store = get_store()
    auction = store.auctions.get(auction_id)
    if auction is None:
        raise ApiError("ERR_NOT_FOUND", f"Auction {auction_id} not found.")
    if auction["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", f"Auction status must be SCHEDULED, got {auction['status']}.")

    # Parent Lot must be ANNOUNCED
    lot = store.lots.get(auction["lot_id"])
    if not lot or lot.get("status") != "ANNOUNCED":
        raise ApiError("ERR_INVALID_STATE", "Parent Lot must be ANNOUNCED to open auction.")

    # now >= scheduled_start_at
    try:
        scheduled_start = parse_iso(auction["scheduled_start_at"])
    except ValueError:
        raise ApiError("ERR_VALIDATION", "Auction scheduled_start_at invalid.")
    if now_dt() < scheduled_start:
        raise ApiError("ERR_INVALID_STATE", "now < scheduled_start_at; cannot open auction yet.")

    # starting_price and deposit_amount must be pinned
    if auction.get("starting_price_cents") is None or auction.get("deposit_amount_cents") is None:
        raise ApiError("ERR_INVALID_STATE", "starting_price_cents and deposit_amount_cents must be pinned.")

    auction["status"] = "LIVE"
    auction["effective_end_at"] = auction["scheduled_end_at"]
    bump_version(auction)
    return auction


def cancel_auction(auction_id: str, reason: str) -> dict[str, Any]:
    store = get_store()
    auction = store.auctions.get(auction_id)
    if auction is None:
        raise ApiError("ERR_NOT_FOUND", f"Auction {auction_id} not found.")
    if auction["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", f"Cannot cancel auction in status {auction['status']}.")
    if auction.get("current_high_cents") is not None:
        raise ApiError("ERR_INVALID_STATE", "Cannot cancel an auction that has bids.")

    auction["status"] = "CANCELLED"
    bump_version(auction)

    # Cascade: refund all PAID deposits
    cascade_refund_deposits(auction_id)
    return auction


def cascade_refund_deposits(auction_id: str) -> None:
    """Refund every PAID deposit (except the winner if any) on this auction.

    Sets refund_due_at = now + 72h, status = REFUNDED, refunded_at = now.
    Emits DEPOSIT_REFUNDED per refunded deposit.
    """
    store = get_store()
    auction = store.auctions.get(auction_id)
    if auction is None:
        return
    winner_id = auction.get("outcome_winner_account_id")
    refund_due_dt = add_hours(now_dt(), REFUND_SLA_HOURS)
    from ..clock import format_iso
    refund_due_iso = format_iso(refund_due_dt)

    for dep in list(store.deposits.values()):
        if dep.get("auction_id") != auction_id:
            continue
        if dep.get("status") != "PAID":
            continue
        if winner_id and dep.get("bidder_account_id") == winner_id:
            continue
        dep["status"] = "REFUNDED"
        dep["refunded_at"] = now_iso()
        dep["refund_due_at"] = refund_due_iso
        bump_version(dep)
        emit_system_audit(
            "DEPOSIT_REFUNDED",
            subject_entity="Deposit",
            subject_id=dep["id"],
            payload={"auction_id": auction_id, "bidder_account_id": dep.get("bidder_account_id")},
        )


def stamp_refund_due_for_paid_deposits(auction_id: str) -> None:
    """Pin refund_due_at on all PAID deposits on the auction (called on auction close).

    refund_due_at = now + 72h. Refund finalization happens in cascade or sweep.
    """
    store = get_store()
    refund_due_iso = _now_plus(REFUND_SLA_HOURS)
    for dep in store.deposits.values():
        if dep.get("auction_id") != auction_id and dep.get("status") == "PAID":
            continue
        if dep.get("auction_id") == auction_id and dep.get("status") == "PAID":
            dep["refund_due_at"] = refund_due_iso


def _now_plus(hours: float) -> str:
    from ..clock import add_hours, format_iso, now_dt
    return format_iso(add_hours(now_dt(), hours))


def close_auction_if_expired(auction: dict[str, Any]) -> None:
    """Drive LIVE → {SOLD,UNSOLD} when now >= effective_end_at.

    Called from clock-advance sweep.
    """
    if auction["status"] != "LIVE":
        return
    try:
        eff_end = parse_iso(auction["effective_end_at"])
    except ValueError:
        return
    if now_dt() < eff_end:
        return

    if auction.get("current_high_cents") is not None:
        _transition_to_sold(auction)
    else:
        _transition_to_unsold(auction)


def _transition_to_sold(auction: dict[str, Any]) -> None:
    from .bids import lookup_bid

    store = get_store()
    auction["status"] = "SOLD"
    winner_bid_id = auction.get("highest_bid_id")
    if winner_bid_id:
        bid = lookup_bid(winner_bid_id)
        if bid:
            auction["outcome_winner_account_id"] = bid.get("bidder_account_id")
    bump_version(auction)
    emit_system_audit(
        "AUCTION_CLOSED",
        subject_entity="Auction",
        subject_id=auction["id"],
        payload={"outcome": "SOLD", "winner_account_id": auction.get("outcome_winner_account_id")},
    )
    # Bubble parent Lot.status to AUCTIONED
    from .lots import bubble_lot_to_auctioned
    bubble_lot_to_auctioned(auction["lot_id"])
    # Cascade-refund non-winners
    cascade_refund_deposits(auction["id"])


def _transition_to_unsold(auction: dict[str, Any]) -> None:
    auction["status"] = "UNSOLD"
    bump_version(auction)
    emit_system_audit(
        "AUCTION_CLOSED",
        subject_entity="Auction",
        subject_id=auction["id"],
        payload={"outcome": "UNSOLD"},
    )
    from .lots import bubble_lot_to_auctioned, trigger_reauction
    bubble_lot_to_auctioned(auction["lot_id"])
    # Cascade refund all PAID deposits
    cascade_refund_deposits(auction["id"])
    # Schedule re-auction subject to round cap
    try:
        trigger_reauction(auction["lot_id"], reason="AUCTION_UNSOLD")
    except ApiError:
        # ERR_REAUCTION_LIMIT_REACHED — lot stays AUCTIONED (closed unsold)
        pass


def recompute_high_from_bids(auction_id: str) -> None:
    """Recompute current_high_cents, highest_bid_id, second_highest_bid_id from
    remaining VALID bids on this auction. Used by BLOCK and SYSTEM_FAULT_ROLLBACK."""
    store = get_store()
    auction = store.auctions.get(auction_id)
    if auction is None:
        return
    valid_bids = [
        b for b in store.bids.values()
        if b.get("auction_id") == auction_id and b.get("validity") == "VALID"
    ]
    if not valid_bids:
        auction["current_high_cents"] = None
        auction["highest_bid_id"] = None
        auction["second_highest_bid_id"] = None
        bump_version(auction)
        return
    # sort by amount desc, then by created_at asc, then by client_seq_no asc
    sorted_bids = sorted(
        valid_bids,
        key=lambda b: (
            -int(b["amount_cents"]),
            b.get("created_at") or "",
            int(b.get("client_seq_no") or 0),
        ),
    )
    auction["current_high_cents"] = int(sorted_bids[0]["amount_cents"])
    auction["highest_bid_id"] = sorted_bids[0]["id"]
    auction["second_highest_bid_id"] = sorted_bids[1]["id"] if len(sorted_bids) > 1 else None
    bump_version(auction)


def system_rollback(auction_id: str, last_n_bids: int, fault_reason: str) -> dict[str, Any]:
    """AuctionAdmin: mark most-recent N bids as ROLLED_BACK, recompute current_high.

    Does NOT re-apply soft_close_extension.
    """
    store = get_store()
    auction = store.auctions.get(auction_id)
    if auction is None:
        raise ApiError("ERR_NOT_FOUND", f"Auction {auction_id} not found.")
    if not isinstance(last_n_bids, int) or last_n_bids < 1:
        raise ApiError("ERR_VALIDATION", "last_n_bids must be a positive integer.")
    if not fault_reason or not isinstance(fault_reason, str):
        raise ApiError("ERR_VALIDATION", "fault_reason must be a non-empty string.")

    # Pick the N most-recent bids (any validity? PRD says "the most recent N bids")
    auction_bids = [b for b in store.bids.values() if b.get("auction_id") == auction_id]
    sorted_bids = sorted(auction_bids, key=lambda b: b.get("created_at") or "", reverse=True)
    targets = sorted_bids[:last_n_bids]
    rolled_ids = []
    for bid in targets:
        if bid.get("validity") == "VALID":
            bid["validity"] = "ROLLED_BACK"
            rolled_ids.append(bid["id"])
            emit_audit(
                "BID_ROLLED_BACK",
                subject_entity="Bid",
                subject_id=bid["id"],
                payload={"auction_id": auction_id, "fault_reason": fault_reason},
            )

    recompute_high_from_bids(auction_id)
    emit_audit(
        "SYSTEM_FAULT_ROLLBACK",
        subject_entity="Auction",
        subject_id=auction_id,
        payload={
            "fault_reason": fault_reason,
            "last_n_bids": last_n_bids,
            "rolled_back_bid_ids": rolled_ids,
        },
    )
    return auction
