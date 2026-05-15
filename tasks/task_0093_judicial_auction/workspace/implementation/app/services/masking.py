"""Bidder identity masking and audit-aware projections — PRD §2.11."""
from __future__ import annotations

from typing import Any

from ..store import get_store


def _masked_handle_for(bid: dict[str, Any]) -> str:
    return bid.get("masked_handle") or "Bidder #000"


def project_bid(bid: dict[str, Any], viewer_role: str, viewer_id: str) -> dict[str, Any]:
    """Return a Bid payload with bidder_account_id masked for non-CourtClerk callers.

    Bidder sees their own bid un-masked; everyone else's bid is masked unless caller
    is CourtClerk.
    """
    out = dict(bid)
    if viewer_role == "CourtClerk":
        return out
    if viewer_role == "Bidder" and bid.get("bidder_account_id") == viewer_id:
        return out
    # Mask
    out.pop("bidder_account_id", None)
    out["masked_handle"] = _masked_handle_for(bid)
    return out


def project_auction(auction: dict[str, Any], viewer_role: str) -> dict[str, Any]:
    """Return Auction record. PRD §2.11 specifically masks
    `Bid.bidder_account_id` for non-CourtClerk callers; the Auction's
    `outcome_winner_account_id` is a separate field of the auction
    record itself and is not covered by that masking rule, so it
    surfaces for every role that can read the auction.
    """
    return dict(auction)


def make_masked_handle(serial_number: int) -> str:
    return f"Bidder #{serial_number:03d}"


def next_bidder_serial_for_auction(auction_id: str) -> int:
    """Assign a monotonic per-auction serial to a fresh bidder participating in this
    auction. Used to build masked_handle."""
    store = get_store()
    seen: dict[str, int] = {}
    serial = 0
    # Iterate bids in created_at order so the same bidder gets the same handle.
    for bid in sorted(store.bids.values(), key=lambda b: b.get("created_at") or ""):
        if bid.get("auction_id") != auction_id:
            continue
        ba_id = bid.get("bidder_account_id")
        if ba_id is None:
            continue
        if ba_id not in seen:
            serial += 1
            seen[ba_id] = serial
    return serial + 1, seen


def assign_masked_handle(auction_id: str, bidder_account_id: str) -> str:
    """Compute a masked_handle for the (auction_id, bidder_account_id) tuple based on
    bidder participation order."""
    next_serial, existing = next_bidder_serial_for_auction(auction_id)
    if bidder_account_id in existing:
        return make_masked_handle(existing[bidder_account_id])
    return make_masked_handle(next_serial)
