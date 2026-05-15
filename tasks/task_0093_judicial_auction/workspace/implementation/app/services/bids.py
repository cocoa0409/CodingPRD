"""Bid placement, ladder validation, soft-close, anti-collusion scoring — PRD §3.5 / §3.6."""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Optional

from ..audit import emit_audit
from ..clock import format_iso, now_dt, parse_iso
from ..constants import (
    W_ALTERNATING,
    W_IDENTICAL_INC,
    W_SHARED_IP,
    W_YOUNG_ACCOUNT,
    YOUNG_ACCOUNT_DAYS,
)
from ..errors import ApiError
from ..store import bump_version, get_store, new_id, now_iso
from .bidder_accounts import apply_collusion_outcome
from .calculations import bid_increment_for, min_next_bid


def lookup_bid(bid_id: str) -> Optional[dict[str, Any]]:
    return get_store().bids.get(bid_id)


def place_bid(body: dict[str, Any], caller_id: str) -> dict[str, Any]:
    """POST /bids — fully validated bid placement."""
    store = get_store()

    auction_id = body.get("auction_id")
    if not isinstance(auction_id, str) or not auction_id.strip():
        raise ApiError("ERR_VALIDATION", "auction_id must be a non-empty string.")
    amount_cents = body.get("amount_cents")
    if isinstance(amount_cents, bool) or not isinstance(amount_cents, int) or amount_cents < 1:
        raise ApiError("ERR_VALIDATION", "amount_cents must be a positive integer.")
    client_seq_no = body.get("client_seq_no")
    if isinstance(client_seq_no, bool) or not isinstance(client_seq_no, int) or client_seq_no < 0:
        raise ApiError("ERR_VALIDATION", "client_seq_no must be a non-negative integer.")

    auction = store.auctions.get(auction_id)
    if auction is None:
        raise ApiError("ERR_NOT_FOUND", f"Auction {auction_id} not found.")
    if auction["status"] != "LIVE":
        raise ApiError("ERR_INVALID_STATE", f"Auction status must be LIVE, got {auction['status']}.")

    # Bidder identity & status (BidderAccount must exist with caller_id)
    account = store.bidder_accounts.get(caller_id)
    if account is None:
        raise ApiError("ERR_NOT_FOUND", f"BidderAccount {caller_id} not found.")
    if account["status"] != "ACTIVE":
        raise ApiError("ERR_BIDDER_NOT_ACTIVE", "BidderAccount must be ACTIVE.")

    # Must have PAID Deposit on this auction
    has_paid = False
    for dep in store.deposits.values():
        if (
            dep.get("auction_id") == auction_id
            and dep.get("bidder_account_id") == caller_id
            and dep.get("status") == "PAID"
        ):
            has_paid = True
            break
    if not has_paid:
        raise ApiError("ERR_DEPOSIT_NOT_PAID", "Bidder has no PAID deposit on this auction.")

    # Ladder: compute min_next_bid; verify increment
    min_next, applied_inc = min_next_bid(
        auction.get("current_high_cents"), int(auction["starting_price_cents"])
    )
    if amount_cents < min_next:
        # Emit BID_REJECTED audit
        emit_audit(
            "BID_REJECTED",
            subject_entity="Auction",
            subject_id=auction_id,
            payload={
                "reason": "ERR_BID_NOT_ABOVE_HIGH",
                "amount_cents": amount_cents,
                "min_next_bid": min_next,
            },
        )
        raise ApiError(
            "ERR_BID_NOT_ABOVE_HIGH",
            f"Bid {amount_cents} below minimum next bid {min_next}.",
        )

    # Bid cap: strict > cap rejected; equality allowed (closed cap)
    cap = auction.get("bid_cap_cents")
    if cap is not None and amount_cents > int(cap):
        emit_audit(
            "BID_REJECTED",
            subject_entity="Auction",
            subject_id=auction_id,
            payload={
                "reason": "ERR_BID_AT_OR_ABOVE_CAP",
                "amount_cents": amount_cents,
                "bid_cap_cents": cap,
            },
        )
        raise ApiError(
            "ERR_BID_AT_OR_ABOVE_CAP",
            f"Bid {amount_cents} above cap {cap}.",
        )

    # Same-second tie / cap-reached tie: if current_high already at cap and
    # new bid also at cap, reject as cap exhausted (concurrency rule §2.12).
    if (
        cap is not None
        and auction.get("current_high_cents") is not None
        and int(auction["current_high_cents"]) >= int(cap)
        and amount_cents >= int(cap)
    ):
        raise ApiError(
            "ERR_BID_AT_OR_ABOVE_CAP",
            "current_high already at cap; bid at/above cap rejected.",
        )

    # ----- Build the Bid row -----
    bid_id = new_id()
    bid = {
        "id": bid_id,
        "created_at": now_iso(),
        "auction_id": auction_id,
        "bidder_account_id": caller_id,
        "amount_cents": int(amount_cents),
        "client_seq_no": int(client_seq_no),
        "validity": "VALID",
        "masked_handle": _compute_masked_handle(auction_id, caller_id),
    }
    store.bids[bid_id] = bid

    # Update auction current_high / highest_bid / second_highest from all valid bids
    valid_bids = [
        b for b in store.bids.values()
        if b.get("auction_id") == auction_id and b.get("validity") == "VALID"
    ]
    sorted_valid = sorted(
        valid_bids,
        key=lambda b: (
            -int(b["amount_cents"]),
            b.get("created_at") or "",
            int(b.get("client_seq_no") or 0),
        ),
    )
    auction["highest_bid_id"] = sorted_valid[0]["id"]
    auction["current_high_cents"] = int(sorted_valid[0]["amount_cents"])
    auction["second_highest_bid_id"] = sorted_valid[1]["id"] if len(sorted_valid) > 1 else None
    # Recompute bid_increment_cents for next bid
    auction["bid_increment_cents"] = bid_increment_for(int(auction["current_high_cents"]))
    bump_version(auction)

    # Soft-close extension
    _apply_soft_close(auction)

    emit_audit(
        "BID_PLACED",
        subject_entity="Bid",
        subject_id=bid_id,
        payload={
            "auction_id": auction_id,
            "bidder_account_id": caller_id,
            "amount_cents": amount_cents,
        },
    )

    # Anti-collusion: recompute risk score against ACTIVE peers
    score = compute_collusion_score(auction_id, caller_id, applied_inc)
    apply_collusion_outcome(caller_id, score)

    return bid


def _compute_masked_handle(auction_id: str, bidder_account_id: str) -> str:
    """Assign a stable masked_handle for this (auction, bidder) tuple.

    Serial: first distinct bidder = #001, second = #002, etc.
    """
    store = get_store()
    serial_by_bidder: dict[str, int] = {}
    counter = 0
    # Iterate existing bids by created_at to preserve order
    for b in sorted(store.bids.values(), key=lambda x: x.get("created_at") or ""):
        if b.get("auction_id") != auction_id:
            continue
        bid_acct = b.get("bidder_account_id")
        if bid_acct and bid_acct not in serial_by_bidder:
            counter += 1
            serial_by_bidder[bid_acct] = counter
    if bidder_account_id in serial_by_bidder:
        n = serial_by_bidder[bidder_account_id]
    else:
        n = counter + 1
    return f"Bidder #{n:03d}"


def _apply_soft_close(auction: dict[str, Any]) -> None:
    """Soft-close extension: if remaining < window, set effective_end = now + extension."""
    try:
        eff_end = parse_iso(auction["effective_end_at"])
    except (KeyError, ValueError):
        return
    now = now_dt()
    remaining = (eff_end - now).total_seconds()
    window = int(auction.get("soft_close_window_seconds") or 0)
    if remaining < window:
        ext = int(auction.get("soft_close_extension_seconds") or 0)
        new_eff = now + timedelta(seconds=ext)
        auction["effective_end_at"] = format_iso(new_eff)
        bump_version(auction)
        from ..audit import emit_audit as _emit
        _emit(
            "SOFT_CLOSE_EXTENSION",
            subject_entity="Auction",
            subject_id=auction["id"],
            payload={
                "prior_effective_end_at": format_iso(eff_end),
                "new_effective_end_at": auction["effective_end_at"],
            },
        )


def compute_collusion_score(auction_id: str, acting_account_id: str, applied_inc: int) -> int:
    """Implements PRD §3.6: per-peer signal scoring, MAX across peers."""
    store = get_store()
    acting = store.bidder_accounts.get(acting_account_id)
    if acting is None:
        return 0

    valid_bids = [
        b for b in store.bids.values()
        if b.get("auction_id") == auction_id and b.get("validity") == "VALID"
    ]
    # Sorted ascending by created_at for sequence analysis
    valid_sorted = sorted(valid_bids, key=lambda b: b.get("created_at") or "")

    # Find peers — ACTIVE BidderAccounts other than self that have VALID bids here
    peer_ids: set[str] = set()
    for b in valid_sorted:
        ba_id = b.get("bidder_account_id")
        if not ba_id or ba_id == acting_account_id:
            continue
        acct = store.bidder_accounts.get(ba_id)
        if acct and acct.get("status") == "ACTIVE":
            peer_ids.add(ba_id)

    if not peer_ids:
        return 0

    # Young-account flag — same for all peers
    age_days = int(acting.get("account_age_days") or 0)
    young = 1 if age_days < YOUNG_ACCOUNT_DAYS else 0

    acting_ip = acting.get("ip_fingerprint") or ""

    max_score = 0
    for peer_id in peer_ids:
        peer = store.bidder_accounts.get(peer_id)
        if peer is None:
            continue

        shared_ip = 1 if acting_ip and peer.get("ip_fingerprint") == acting_ip else 0

        # Alternating: last 4 VALID bids by either self or peer must strictly alternate
        last4 = [b for b in valid_sorted if b.get("bidder_account_id") in {acting_account_id, peer_id}][-4:]
        if len(last4) == 4 and (
            (
                last4[0]["bidder_account_id"] == acting_account_id
                and last4[1]["bidder_account_id"] == peer_id
                and last4[2]["bidder_account_id"] == acting_account_id
                and last4[3]["bidder_account_id"] == peer_id
            )
            or (
                last4[0]["bidder_account_id"] == peer_id
                and last4[1]["bidder_account_id"] == acting_account_id
                and last4[2]["bidder_account_id"] == peer_id
                and last4[3]["bidder_account_id"] == acting_account_id
            )
        ):
            alternating = 1
        else:
            alternating = 0

        # Identical increment: last 3 VALID bid deltas by self AND peer are all equal
        # to applied_inc. Compute deltas in chronological order, per bidder.
        self_deltas = _bid_deltas(valid_sorted, acting_account_id)
        peer_deltas = _bid_deltas(valid_sorted, peer_id)
        if (
            len(self_deltas) >= 3
            and len(peer_deltas) >= 3
            and all(d == applied_inc for d in self_deltas[-3:])
            and all(d == applied_inc for d in peer_deltas[-3:])
        ):
            identical_inc = 1
        else:
            identical_inc = 0

        peer_score = (
            W_SHARED_IP * shared_ip
            + W_ALTERNATING * alternating
            + W_IDENTICAL_INC * identical_inc
            + W_YOUNG_ACCOUNT * young
        )
        if peer_score > max_score:
            max_score = peer_score

    return int(max_score)


def _bid_deltas(valid_sorted: list[dict[str, Any]], account_id: str) -> list[int]:
    """Compute the deltas between consecutive bids placed by this account, relative
    to the prior bid by ANYONE on the auction."""
    deltas: list[int] = []
    prior_high = None
    for b in valid_sorted:
        if prior_high is None:
            prior_high = int(b["amount_cents"])
            if b["bidder_account_id"] == account_id:
                # First bid by anyone — no prior high; skip delta
                pass
            continue
        if b["bidder_account_id"] == account_id:
            deltas.append(int(b["amount_cents"]) - int(prior_high))
        prior_high = int(b["amount_cents"])
    return deltas


def list_bids_for_auction(
    auction_id: str, validity: Optional[str], viewer_role: str, viewer_id: str
) -> list[dict[str, Any]]:
    store = get_store()
    auction = store.auctions.get(auction_id)
    if auction is None:
        raise ApiError("ERR_NOT_FOUND", f"Auction {auction_id} not found.")
    bids = [b for b in store.bids.values() if b.get("auction_id") == auction_id]
    if validity is not None:
        if validity not in {"VALID", "REJECTED", "ROLLED_BACK"}:
            raise ApiError("ERR_VALIDATION", "validity filter must be VALID/REJECTED/ROLLED_BACK.")
        bids = [b for b in bids if b.get("validity") == validity]
    bids = sorted(bids, key=lambda b: b.get("created_at") or "")
    return bids
