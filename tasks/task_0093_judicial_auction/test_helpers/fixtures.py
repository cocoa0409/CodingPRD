"""Composite setup helpers — multi-step preambles tests can reuse.

The judicial-auction pipeline is long: lot intake → announce → auction
open → deposit posting → deposit pay → bidding → close (clock-advance)
→ confirmation draft/issue → payment → transfer-order → handover →
confirm completion. Most interesting test claims need the system in
some specific late-pipeline state; these helpers reach it.

IDENTITY THREADING — PRD §2.1: Bidder is ENTITY-BACKED. X-User-ID is
the acting BidderAccount.id. Every ownership-gated Bidder call (POST
/deposits/{id}/pay, POST /bids, POST /deposits/{id}/raise-dispute,
POST /payments/{id}/settle, GET /bidder-accounts/{id}, GET
/payments/{id}) in this file MUST mint headers via
make_bidder_headers(account["id"]) — never with the shared
BIDDER_FALLBACK_ID constant. CourtClerk, AuctionAdmin, and Observer
are opaque; their shared constants are canonical.

Setup calls use get_success_data (a lenient 2xx validator), so a
failed setup surfaces as "Setup failed" rather than a confusing
test assertion failure.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    GRACE_FORFEITURE_DAYS,
    HANDOVER_BUFFER_HOURS,
    REFUND_SLA_HOURS,
    STATUTORY_NOTICE_DAYS,
    TEST_DEFAULTS,
)
from .factories import (
    add_inspection_window_payload,
    cancel_auction_payload,
    clear_bidder_account_payload,
    clock_advance_payload,
    complete_handover_payload,
    create_bid_payload,
    create_bidder_account_payload,
    create_confirmation_payload,
    create_deposit_payload,
    create_lot_payload,
    create_transfer_order_payload,
    extend_payment_payload,
    fail_confirmation_payload,
    iso_now,
    iso_utc,
    raise_dispute_payload,
    resolve_dispute_payload,
    settle_payment_payload,
    system_rollback_payload,
    utcnow,
    withdraw_lot_payload,
)
from .test_users import (
    AUCTION_ADMIN_ID,
    COURT_CLERK_ID,
    TEST_USERS,
    make_auction_admin_headers,
    make_bidder_headers,
    make_court_clerk_headers,
)


# ===========================================================================
# Time helpers — the platform owns a simulated clock (PRD §3.5)
# ===========================================================================
def advance_clock_to(to_dt: datetime,
                    headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """POST /_clock/advance with an ISO 8601 instant.

    Per PRD §3.5 the endpoint is admin-only (AuctionAdmin or CourtClerk).
    """
    headers = headers or TEST_USERS["auction_admin_headers"]
    resp = api_client.clock_advance(
        clock_advance_payload(to=iso_utc(to_dt)), headers=headers,
    )
    return get_success_data(resp)


def advance_clock_by(*, days: int = 0, hours: int = 0,
                    minutes: int = 0, seconds: int = 0,
                    headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Move the simulated clock forward by the given delta from `now`."""
    base = _server_now() or utcnow()
    return advance_clock_to(
        base + timedelta(
            days=days, hours=hours, minutes=minutes, seconds=seconds,
        ),
        headers=headers,
    )


def _server_now() -> Optional[datetime]:
    """Read the simulated server clock via /_clock/now (test-harness).

    Returns None if the endpoint is not exposed; callers fall back to
    wall-clock utcnow(). Implementations are free to omit this hook.
    """
    try:
        resp = api_client._request("GET", "/_clock/now", None, {})
        if resp.status_code != 200:
            return None
        body = resp.json()
        now_str = body.get("data", {}).get("now")
        if not isinstance(now_str, str):
            return None
        if now_str.endswith("Z"):
            now_str = now_str[:-1] + "+00:00"
        return datetime.fromisoformat(now_str)
    except Exception:
        return None


def sweep_refunds(headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """POST /_sweep/refunds — PRD §3.10."""
    headers = headers or TEST_USERS["auction_admin_headers"]
    resp = api_client.sweep_refunds(headers=headers)
    return get_success_data(resp)


# ===========================================================================
# Tier 1 — atomic create-and-progress helpers
# ===========================================================================
def create_lot(
    *,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /lots; returns the registered Lot. CourtClerk-only per PRD §3.1."""
    headers = headers or TEST_USERS["court_clerk_headers"]
    resp = api_client.create_lot(create_lot_payload(**overrides), headers)
    return get_success_data(resp)


def announce_lot(lot_id: str,
                 headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """POST /lots/{id}/announce — CourtClerk-only."""
    headers = headers or TEST_USERS["court_clerk_headers"]
    resp = api_client.announce_lot(lot_id, headers=headers)
    return get_success_data(resp)


def withdraw_lot(lot_id: str,
                 reason: Optional[str] = "Court ordered withdrawal",
                 headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    headers = headers or TEST_USERS["court_clerk_headers"]
    resp = api_client.withdraw_lot(
        lot_id, headers, withdraw_lot_payload(reason=reason),
    )
    return get_success_data(resp)


def create_bidder_account(
    *,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /bidder-accounts; returns ACTIVE BidderAccount.

    AuctionAdmin-only per PRD §3.2.
    """
    headers = headers or TEST_USERS["auction_admin_headers"]
    resp = api_client.create_bidder_account(
        create_bidder_account_payload(**overrides), headers,
    )
    return get_success_data(resp)


def list_auctions_for_lot(lot_id: str,
                          headers: Optional[Dict[str, str]] = None
                          ) -> List[Dict[str, Any]]:
    """The PRD does not declare a GET /auctions list endpoint with a
    lot_id filter; instead this helper reads the Lot, derives the
    sibling auction_id from /lots/{id} (after registration the lot
    response carries the first auction's id or is reachable via a
    secondary fetch).

    For tests that only need ONE auction (the current round) this
    helper looks for it via GET /auctions/{auction_id} once the id is
    known. Most tests obtain auction_id directly from the lot-create
    response — see `setup_lot_with_auction` below — and rarely need
    a list. Kept here as a convenience for round-number cascade
    tests; callers pass auction_ids they already track.
    """
    headers = headers or TEST_USERS["court_clerk_headers"]
    # No documented list endpoint; the test_helpers track auctions
    # explicitly via the helpers below.
    return []


def get_auction(auction_id: str,
                headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    headers = headers or TEST_USERS["auction_admin_headers"]
    resp = api_client.get_auction(auction_id, headers)
    return get_success_data(resp)


def get_lot(lot_id: str,
            headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    headers = headers or TEST_USERS["court_clerk_headers"]
    resp = api_client.get_lot(lot_id, headers)
    return get_success_data(resp)


def open_auction(auction_id: str,
                 headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """POST /auctions/{id}/open — AuctionAdmin-only.

    Per PRD §3.5 the opening transition requires `now >=
    scheduled_start_at`; callers usually advance the clock first.
    """
    headers = headers or TEST_USERS["auction_admin_headers"]
    resp = api_client.open_auction(auction_id, headers=headers)
    return get_success_data(resp)


def cancel_auction(auction_id: str,
                   reason: str = "Court cancelled",
                   headers: Optional[Dict[str, str]] = None
                   ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["court_clerk_headers"]
    resp = api_client.cancel_auction(
        auction_id, cancel_auction_payload(reason=reason), headers,
    )
    return get_success_data(resp)


def post_deposit(auction_id: str, bidder_account_id: str,
                 headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """POST /deposits.

    The endpoint accepts AuctionAdmin OR Bidder (PRD §3.4). When
    called by the Bidder, the X-User-ID must equal bidder_account_id
    (ownership check per PRD §2.1). The default header here is the
    AuctionAdmin's shared constant which sidesteps ownership — fine
    for setup. Tests that need to assert the Bidder path itself pass
    `headers=make_bidder_headers(bidder_account_id)` explicitly.
    """
    headers = headers or TEST_USERS["auction_admin_headers"]
    resp = api_client.create_deposit(
        create_deposit_payload(auction_id, bidder_account_id), headers,
    )
    return get_success_data(resp)


def pay_deposit(deposit_id: str, bidder_account_id: str) -> Dict[str, Any]:
    """POST /deposits/{id}/pay — Bidder-only.

    PRD §2.1: identity threading mandatory — ownership compares the
    deposit's bidder_account_id against X-User-ID.
    """
    headers = make_bidder_headers(bidder_account_id)
    resp = api_client.pay_deposit(deposit_id, headers=headers)
    return get_success_data(resp)


def place_bid(auction_id: str, bidder_account_id: str, amount_cents: int,
              client_seq_no: int = 1) -> Dict[str, Any]:
    """POST /bids — Bidder-only, identity-threaded."""
    headers = make_bidder_headers(bidder_account_id)
    resp = api_client.create_bid(
        create_bid_payload(auction_id, amount_cents, client_seq_no), headers,
    )
    return get_success_data(resp)


def create_confirmation(auction_id: str,
                        use_second_bidder: Optional[bool] = None,
                        headers: Optional[Dict[str, str]] = None,
                        **overrides: Any) -> Dict[str, Any]:
    headers = headers or TEST_USERS["court_clerk_headers"]
    resp = api_client.create_confirmation(
        create_confirmation_payload(
            auction_id, use_second_bidder=use_second_bidder, **overrides,
        ),
        headers,
    )
    return get_success_data(resp)


def issue_confirmation(confirmation_id: str,
                       headers: Optional[Dict[str, str]] = None
                       ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["court_clerk_headers"]
    resp = api_client.issue_confirmation(confirmation_id, headers=headers)
    return get_success_data(resp)


def fail_confirmation(confirmation_id: str,
                      failure_reason: str = "COURT_OVERRIDE",
                      headers: Optional[Dict[str, str]] = None
                      ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["court_clerk_headers"]
    resp = api_client.fail_confirmation(
        confirmation_id,
        fail_confirmation_payload(failure_reason=failure_reason),
        headers,
    )
    return get_success_data(resp)


def seal_confirmation(confirmation_id: str,
                      headers: Optional[Dict[str, str]] = None
                      ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["court_clerk_headers"]
    resp = api_client.seal_confirmation(confirmation_id, headers=headers)
    return get_success_data(resp)


def settle_payment(payment_id: str, bidder_account_id: str,
                   amount_cents: int) -> Dict[str, Any]:
    """POST /payments/{id}/settle — Bidder-only, identity-threaded.

    Ownership chain (PRD §2.1): Payment ↔ Confirmation.winning_bid_id
    ↔ Bid.bidder_account_id. X-User-ID must equal that bidder_account_id.
    """
    headers = make_bidder_headers(bidder_account_id)
    resp = api_client.settle_payment(
        payment_id, settle_payment_payload(amount_cents), headers,
    )
    return get_success_data(resp)


def extend_payment(payment_id: str, extension_days: int = 7,
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    headers = headers or TEST_USERS["court_clerk_headers"]
    resp = api_client.extend_payment(
        payment_id, extend_payment_payload(extension_days=extension_days),
        headers,
    )
    return get_success_data(resp)


def forfeit_payment(payment_id: str,
                    headers: Optional[Dict[str, str]] = None
                    ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["court_clerk_headers"]
    resp = api_client.forfeit_payment(payment_id, headers=headers)
    return get_success_data(resp)


def get_payment(payment_id: str,
                bidder_account_id: Optional[str] = None,
                headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """GET /payments/{id} — read using CourtClerk (default) or the
    owning Bidder.
    """
    if headers is None:
        if bidder_account_id is not None:
            headers = make_bidder_headers(bidder_account_id)
        else:
            headers = TEST_USERS["court_clerk_headers"]
    resp = api_client.get_payment(payment_id, headers)
    return get_success_data(resp)


def initiate_transfer_order(
    confirmation_id: str,
    handover_scheduled_at: Optional[str] = None,
    tenancy_cleared: Optional[bool] = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /transfer-orders — AuctionAdmin-only (PRD §3.11)."""
    headers = headers or TEST_USERS["auction_admin_headers"]
    handover_at = handover_scheduled_at or iso_utc(
        utcnow() + timedelta(days=2),
    )
    resp = api_client.create_transfer_order(
        create_transfer_order_payload(
            confirmation_id=confirmation_id,
            handover_scheduled_at=handover_at,
            tenancy_cleared=tenancy_cleared,
            **overrides,
        ),
        headers,
    )
    return get_success_data(resp)


def notify_agency(transfer_order_id: str,
                  headers: Optional[Dict[str, str]] = None
                  ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["auction_admin_headers"]
    resp = api_client.notify_agency(transfer_order_id, headers=headers)
    return get_success_data(resp)


def complete_handover(transfer_order_id: str,
                     tenancy_cleared: Optional[bool] = None,
                     headers: Optional[Dict[str, str]] = None
                     ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["auction_admin_headers"]
    resp = api_client.complete_handover(
        transfer_order_id, headers=headers,
        payload=complete_handover_payload(tenancy_cleared=tenancy_cleared),
    )
    return get_success_data(resp)


def confirm_transfer_completion(transfer_order_id: str,
                                headers: Optional[Dict[str, str]] = None
                                ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["court_clerk_headers"]
    resp = api_client.confirm_transfer_completion(
        transfer_order_id, headers=headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 2 — Lot + first Auction (most common starting state)
# ===========================================================================
def setup_lot_with_auction(
    *,
    asset_profile: str = "VEHICLE",
    assessment_value_cents: int = TEST_DEFAULTS["ASSESSMENT_VALUE_CENTS"],
    deposit_mode: str = "PERCENT",
    deposit_percent_bps: int = TEST_DEFAULTS["PERCENT_DEPOSIT_BPS"],
    deposit_fixed_cents: Optional[int] = None,
    bid_cap_cents: Optional[int] = None,
    payment_deadline_days: int = TEST_DEFAULTS["PAYMENT_DEADLINE_DAYS"],
    auction_start_offset_days: int = 30,
    auction_duration_seconds: int = TEST_DEFAULTS["AUCTION_DURATION_SECONDS"],
    soft_close_window_seconds: int = 300,
    soft_close_extension_seconds: int = 300,
    **lot_overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Register a lot and the associated first-round auction.

    Per PRD §3.1: "A successful registration creates the Lot row in
    REGISTERED status and creates the first sibling Auction for
    round_number 1." The auction id is therefore implicit on the lot
    create response — the implementation may surface it in different
    shapes. To keep tests robust this helper:

      1. Registers the Lot with the supplied profile, value, schedule,
         and per-auction parameters spliced into the request body
         (the API layer pins these on the sibling Auction).
      2. Fetches /lots/{lot_id} and inspects for the sibling auction
         id, falling back to known response shapes.

    Returns (lot, auction) where both are full dicts.
    """
    # Anchor schedule on the server's simulated clock so prior fixtures
    # that advanced the clock don't shorten the statutory-notice window.
    base_now = _server_now() or utcnow()
    auction_start = base_now + timedelta(days=auction_start_offset_days)
    inspection_start = auction_start - timedelta(hours=6)
    inspection_end = auction_start - timedelta(hours=1)
    scheduled_end = auction_start + timedelta(seconds=auction_duration_seconds)
    # Deposit deadline = scheduled_end (PRD §3.4 lets deposits be paid
    # while auction is SCHEDULED or LIVE; allow until close).
    deposit_deadline = scheduled_end
    payload: Dict[str, Any] = create_lot_payload(
        asset_profile=asset_profile,
        assessment_value_cents=assessment_value_cents,
        auction_scheduled_start_at=iso_utc(auction_start),
        inspection_window_start_at=iso_utc(inspection_start),
        inspection_window_end_at=iso_utc(inspection_end),
        # Auction-specific fields that the registration handler pins
        # onto the sibling Auction row.
        deposit_mode=deposit_mode,
        deposit_percent_bps=(
            deposit_percent_bps if deposit_mode == "PERCENT" else None
        ),
        deposit_fixed_cents=(
            deposit_fixed_cents if deposit_mode == "FIXED" else None
        ),
        bid_cap_cents=bid_cap_cents,
        payment_deadline_days=payment_deadline_days,
        scheduled_end_at=iso_utc(scheduled_end),
        soft_close_window_seconds=soft_close_window_seconds,
        soft_close_extension_seconds=soft_close_extension_seconds,
        deposit_deadline_at=iso_utc(deposit_deadline),
    )
    payload.update(lot_overrides)
    lot = get_success_data(
        api_client.create_lot(payload, TEST_USERS["court_clerk_headers"]),
    )

    # Resolve the sibling auction id from the lot response.
    auction_id = _extract_first_auction_id(lot)
    auction = get_auction(auction_id)
    return lot, auction


def _extract_first_auction_id(lot: Dict[str, Any]) -> str:
    """The PRD says the lot-create response returns the Lot resource;
    different faithful implementations may surface the sibling
    auction id either as `auction_id`, `current_auction_id`, or as
    an `auctions` list. Try each canonical shape; raise loudly if
    none is present (a Setup-time failure beats a confusing test
    error).
    """
    candidates: List[Any] = [
        lot.get("auction_id"),
        lot.get("current_auction_id"),
        lot.get("first_auction_id"),
    ]
    for c in candidates:
        if isinstance(c, str) and c:
            return c
    auctions = lot.get("auctions")
    if isinstance(auctions, list) and auctions:
        first = auctions[0]
        if isinstance(first, dict) and isinstance(first.get("id"), str):
            return first["id"]
        if isinstance(first, str):
            return first
    raise AssertionError(
        "Lot response did not expose a sibling auction id. "
        f"Keys present: {sorted(lot.keys())}"
    )


def setup_announced_lot(**overrides: Any
                       ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Lot + auction, then POST /lots/{id}/announce.

    Returns (lot, auction) after the announcement transition. The
    auction is in SCHEDULED state with deposit_amount_cents pinned.
    """
    lot, auction = setup_lot_with_auction(**overrides)
    announce_lot(lot["id"])
    # Re-fetch to surface the post-announce state on both rows.
    return get_lot(lot["id"]), get_auction(auction["id"])


def setup_active_bidder() -> Dict[str, Any]:
    """Create one ACTIVE BidderAccount. Returns the row."""
    return create_bidder_account()


def setup_bidder_with_paid_deposit(
    auction: Dict[str, Any],
    bidder: Optional[Dict[str, Any]] = None,
    **bidder_overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create a bidder (or reuse the one supplied), post a deposit on
    the given auction, and mark it PAID.

    Returns (bidder, deposit).
    """
    bidder = bidder or create_bidder_account(**bidder_overrides)
    deposit = post_deposit(auction["id"], bidder["id"])
    paid = pay_deposit(deposit["id"], bidder["id"])
    return bidder, paid


# ===========================================================================
# Tier 3 — Drive to LIVE / SOLD / Confirmation / Payment
# ===========================================================================
def setup_live_auction(num_bidders: int = 2, **overrides: Any
                      ) -> Tuple[Dict[str, Any], Dict[str, Any],
                                  List[Tuple[Dict[str, Any], Dict[str, Any]]]]:
    """Lot → announce → auction OPEN with `num_bidders` PAID-deposit
    bidders ready. Returns (lot, auction, [(bidder, deposit), ...]).

    The clock is advanced to scheduled_start_at to permit the open.
    """
    lot, auction = setup_announced_lot(**overrides)
    bidders_and_deposits: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    for _ in range(num_bidders):
        bidder, deposit = setup_bidder_with_paid_deposit(auction)
        bidders_and_deposits.append((bidder, deposit))
    # Advance clock to scheduled_start so open is permitted.
    advance_clock_to(_parse_iso(auction["scheduled_start_at"]))
    auction = open_auction(auction["id"])
    return get_lot(lot["id"]), auction, bidders_and_deposits


def _parse_iso(value: str) -> datetime:
    # Accept both "...Z" and "+00:00" variants.
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def setup_sold_auction(
    *,
    num_bidders: int = 2,
    winning_amount_cents: Optional[int] = None,
    runner_up_amount_cents: Optional[int] = None,
    **overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any],
           List[Tuple[Dict[str, Any], Dict[str, Any]]], Dict[str, Any]]:
    """Drive an auction all the way through to SOLD.

    Returns (lot, auction, [(bidder, deposit)], winning_bid).
    The last bidder placed is the winner; auction is closed by
    advancing the clock past effective_end_at.
    """
    lot, auction, bidders = setup_live_auction(
        num_bidders=num_bidders, **overrides,
    )
    starting = auction["starting_price_cents"]
    # Bid ladder: each subsequent bid uses ladder increment above the prior.
    last_amount = starting
    winning_bid: Optional[Dict[str, Any]] = None
    for idx, (bidder, _deposit) in enumerate(bidders):
        if idx == 0:
            # First bid may equal starting_price exactly.
            amount = winning_amount_cents if (
                idx == len(bidders) - 1 and winning_amount_cents is not None
            ) else starting
        else:
            # Compute next legal amount using the ladder
            increment = _ladder_increment(last_amount)
            amount = last_amount + increment
            if idx == len(bidders) - 1:
                if winning_amount_cents is not None:
                    amount = winning_amount_cents
            elif idx == len(bidders) - 2:
                if runner_up_amount_cents is not None:
                    amount = runner_up_amount_cents
        bid = place_bid(auction["id"], bidder["id"], amount,
                        client_seq_no=idx + 1)
        last_amount = amount
        winning_bid = bid
    # Close the auction by advancing past effective_end_at.
    auction = get_auction(auction["id"])
    advance_clock_to(_parse_iso(auction["effective_end_at"])
                     + timedelta(seconds=1))
    auction = get_auction(auction["id"])
    assert auction["status"] == "SOLD", (
        f"setup_sold_auction expected SOLD, got {auction['status']}"
    )
    assert winning_bid is not None
    return get_lot(lot["id"]), auction, bidders, winning_bid


def _ladder_increment(base_cents: int) -> int:
    """PRD §3.5 bid-increment ladder."""
    if base_cents < 50_000_000:
        return 100_000
    if base_cents < 200_000_000:
        return 500_000
    if base_cents < 1_000_000_000:
        return 1_000_000
    return 5_000_000


def setup_unsold_auction(**overrides: Any
                        ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Drive an auction to UNSOLD (open + clock-advance with no bids).

    Returns (lot, auction-after-close).
    """
    lot, auction, _ = setup_live_auction(num_bidders=0, **overrides)
    auction = get_auction(auction["id"])
    advance_clock_to(_parse_iso(auction["effective_end_at"])
                     + timedelta(seconds=1))
    auction = get_auction(auction["id"])
    return get_lot(lot["id"]), auction


def setup_issued_confirmation(
    **overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any],
           List[Tuple[Dict[str, Any], Dict[str, Any]]],
           Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Full pipeline through Confirmation.ISSUED + Payment.PENDING.

    Returns (lot, auction, bidders, winning_bid, confirmation, payment).
    """
    lot, auction, bidders, winning_bid = setup_sold_auction(**overrides)
    confirmation = create_confirmation(auction["id"])
    confirmation = issue_confirmation(confirmation["id"])
    payment = _resolve_payment_from_confirmation(confirmation)
    return lot, auction, bidders, winning_bid, confirmation, payment


def _resolve_payment_from_confirmation(
    confirmation: Dict[str, Any],
) -> Dict[str, Any]:
    """The issue response carries the Confirmation; the spawned
    Payment id may surface either embedded (`payment` / `payment_id`)
    or via a separate fetch. Try each canonical shape.
    """
    payment = confirmation.get("payment")
    if isinstance(payment, dict) and "id" in payment:
        return payment
    payment_id = confirmation.get("payment_id")
    if isinstance(payment_id, str):
        return get_payment(payment_id)
    # Fallback: many implementations expose GET /payments/by-confirmation,
    # but the PRD only declares GET /payments/{id}. Re-fetch the
    # confirmation if needed.
    raise AssertionError(
        "Confirmation response did not expose the spawned Payment id. "
        f"Keys: {sorted(confirmation.keys())}"
    )


def setup_paid_payment(
    **overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any],
           List[Tuple[Dict[str, Any], Dict[str, Any]]],
           Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Full pipeline through Payment.PAID.

    Returns (lot, auction, bidders, winning_bid, confirmation, payment).
    """
    lot, auction, bidders, winning_bid, confirmation, payment = (
        setup_issued_confirmation(**overrides)
    )
    if payment["status"] == "PAID":
        # Edge case where bid == deposit; PRD §3.9 auto-marks PAID.
        return lot, auction, bidders, winning_bid, confirmation, payment
    # The winning bidder is the last entry in bidders.
    winner_account = bidders[-1][0]
    total_due = payment["balance_due_cents"] + payment["penalty_accrued_cents"]
    paid_payment = settle_payment(payment["id"], winner_account["id"],
                                  total_due)
    return lot, auction, bidders, winning_bid, confirmation, paid_payment


# ===========================================================================
# Tier 4 — Threshold / boundary targeting helpers
# ===========================================================================
def setup_payment_with_balance(
    balance_due_cents: int,
    payment_deadline_days: int = 1,
    **lot_overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Build a Payment whose balance_due_cents equals the given target.

    Constructs an assessment_value such that:
      starting_price = assessment * 0.7  (round 1)
      deposit = starting_price * 0.10   (PERCENT mode, 10%)
      winning_bid = starting_price       (no ladder needed for a single bid)
      balance_due = winning_bid - deposit = starting_price * 0.9

    Tests that need precise control of balance_due_cents pass it in;
    we pick assessment_value accordingly.

    Returns (lot, auction, confirmation, payment).
    """
    # We want balance_due = winning_bid - deposit = starting_price * (1 - 0.10)
    # = starting_price * 0.90. So starting_price = balance_due / 0.9.
    # And assessment = starting_price / 0.7.
    # Easier: pick PERCENT 0 by switching to FIXED-deposit mode and set
    # deposit_fixed_cents = 0 ⇒ balance_due = starting_price = assessment * 0.7.
    # Then we need assessment such that round_half_up(assessment * 0.7) ==
    # balance_due_cents. assessment = balance_due / 0.7.
    # Pick assessment = balance_due_cents * 10 // 7; tweak to make starting
    # exact.
    # Even simpler approach: use FIXED deposit = 0 ⇒ balance_due == starting.
    # Then pick assessment such that assessment * 7000 / 10000 (rounded
    # half-up) == balance_due_cents. The exact solver:
    #   assessment_value_cents = balance_due_cents * 10 // 7
    # then adjust by ±1 to nudge round_half_up. This is small enough.
    target_starting = balance_due_cents
    # Try a few candidate assessment values around the rough quotient.
    base = target_starting * 10000 // 7000
    assessment_value_cents: Optional[int] = None
    for delta in range(-2, 3):
        candidate = base + delta
        # round_half_up(candidate * 7000 / 10000)
        from decimal import Decimal, ROUND_HALF_UP
        starting = int(
            (Decimal(candidate) * Decimal(7000) / Decimal(10000))
            .quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
        if starting == target_starting:
            assessment_value_cents = candidate
            break
    if assessment_value_cents is None:
        raise AssertionError(
            f"Could not solve assessment_value_cents for "
            f"balance_due_cents={balance_due_cents}"
        )

    # Compress the schedule so the payment_deadline lands soon: we'll
    # set payment_deadline_days = `payment_deadline_days` (default 1)
    # so a clock-advance of >1 day flips PENDING→OVERDUE quickly.
    # Use num_bidders=1 so the single bid lands at starting_price
    # exactly and balance_due_cents == starting_price - deposit (= 0).
    lot, auction, bidders, _winning_bid, confirmation, payment = (
        setup_issued_confirmation(
            num_bidders=1,
            assessment_value_cents=assessment_value_cents,
            deposit_mode="FIXED",
            deposit_fixed_cents=0,
            payment_deadline_days=payment_deadline_days,
            **lot_overrides,
        )
    )
    assert payment["balance_due_cents"] == balance_due_cents, (
        f"Setup of balance_due_cents failed: wanted {balance_due_cents}, "
        f"got {payment['balance_due_cents']}"
    )
    return lot, auction, confirmation, payment


def setup_overdue_payment(
    balance_due_cents: int = 68_000_000,
    payment_deadline_days: int = 1,
    overdue_days: int = 5,
    **lot_overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Build a Payment, then advance the clock until it is `overdue_days`
    past its due_at — Payment.status will be OVERDUE.

    Returns (auction, confirmation, payment-after-advance).
    """
    _lot, auction, confirmation, payment = setup_payment_with_balance(
        balance_due_cents=balance_due_cents,
        payment_deadline_days=payment_deadline_days,
        **lot_overrides,
    )
    due_at = _parse_iso(payment["due_at"])
    advance_clock_to(due_at + timedelta(days=overdue_days))
    payment = get_payment(payment["id"])
    return auction, confirmation, payment


def setup_forfeited_payment(
    balance_due_cents: int = 68_000_000,
    **lot_overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Drive a Payment all the way to FORFEITED."""
    auction, confirmation, payment = setup_overdue_payment(
        balance_due_cents=balance_due_cents,
        payment_deadline_days=1,
        overdue_days=GRACE_FORFEITURE_DAYS + 1,
        **lot_overrides,
    )
    forfeited = forfeit_payment(payment["id"])
    return auction, confirmation, forfeited


def setup_reauction_round(
    *, target_round: int = 2,
    **overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Drive a Lot all the way through to round-N (N>=2) by repeatedly
    triggering UNSOLD outcomes.

    For round 2: lot → announce → open → clock-advance with no bids →
    UNSOLD → system creates round-2 auction. The system bubbles
    Lot.AUCTIONED → ANNOUNCED. Subsequent rounds repeat.

    Returns (lot-after-cascade, latest-round-auction).
    """
    lot, auction = setup_unsold_auction(**overrides)
    current_round = 1
    while current_round < target_round:
        # The implementation has created the next-round auction;
        # re-fetch the lot and read its current auction.
        lot = get_lot(lot["id"])
        next_auction_id = _extract_first_auction_id(lot)
        # If the same auction id surfaces, the system did not create the
        # next round — fail loudly.
        if next_auction_id == auction["id"]:
            raise AssertionError(
                "Re-auction was expected but no new Auction row appeared "
                f"(round {current_round}). Implementation may be skipping "
                "the AUCTIONED→ANNOUNCED cascade."
            )
        auction = get_auction(next_auction_id)
        if current_round + 1 < target_round:
            # Drive another UNSOLD outcome.
            announce_lot(lot["id"]) if lot["status"] == "REGISTERED" else None
            advance_clock_to(_parse_iso(auction["scheduled_start_at"]))
            open_auction(auction["id"])
            auction = get_auction(auction["id"])
            advance_clock_to(_parse_iso(auction["effective_end_at"])
                             + timedelta(seconds=1))
            auction = get_auction(auction["id"])
        current_round += 1
    return get_lot(lot["id"]), auction


# ===========================================================================
# Tier 5 — Finalisation / terminal-state helpers
# ===========================================================================
def setup_transfer_order_initiated(
    *,
    asset_profile: str = "VEHICLE",
    handover_at: Optional[datetime] = None,
    tenancy_cleared: Optional[bool] = None,
    **overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Build pipeline → Payment.PAID → TransferOrder (INITIATED).

    Returns (lot, auction, confirmation, transfer_order).
    """
    lot, auction, _bidders, _winning_bid, confirmation, _payment = (
        setup_paid_payment(asset_profile=asset_profile, **overrides)
    )
    if handover_at is None:
        handover_at = utcnow() + timedelta(days=2)
    transfer = initiate_transfer_order(
        confirmation_id=confirmation["id"],
        handover_scheduled_at=iso_utc(handover_at),
        tenancy_cleared=tenancy_cleared,
    )
    return lot, auction, confirmation, transfer


def setup_transfer_notified(
    **overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Through TransferOrder.AGENCY_NOTIFIED."""
    lot, auction, confirmation, transfer = setup_transfer_order_initiated(
        **overrides,
    )
    transfer = notify_agency(transfer["id"])
    return lot, auction, confirmation, transfer


def setup_transfer_completed(
    *, asset_profile: str = "VEHICLE",
    **overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Drive a transfer all the way to COMPLETED (Lot terminal TRANSFERRED)."""
    handover_at = utcnow() + timedelta(hours=1)
    lot, auction, confirmation, transfer = setup_transfer_notified(
        asset_profile=asset_profile,
        handover_at=handover_at,
        tenancy_cleared=(asset_profile == "REAL_ESTATE") or None,
        **overrides,
    )
    advance_clock_to(handover_at + timedelta(seconds=1))
    transfer = complete_handover(
        transfer["id"],
        tenancy_cleared=True if asset_profile == "REAL_ESTATE" else None,
    )
    transfer = confirm_transfer_completion(transfer["id"])
    return get_lot(lot["id"]), auction, confirmation, transfer


# ===========================================================================
# Tier 6 — Audit-event tail (used by cascade-coverage tests)
# ===========================================================================
def list_audit_events(
    *,
    subject_entity: Optional[str] = None,
    subject_id: Optional[str] = None,
    kind: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    **extra: Any,
) -> List[Dict[str, Any]]:
    """GET /audit-events — CourtClerk-only (PRD §3.12)."""
    headers = headers or TEST_USERS["court_clerk_headers"]
    params: Dict[str, Any] = {}
    if subject_entity:
        params["subject_entity"] = subject_entity
    if subject_id:
        params["subject_id"] = subject_id
    if kind:
        params["kind"] = kind
    params.update(extra)
    resp = api_client.list_audit_events(headers, params=params)
    body = get_success_data(resp)
    if isinstance(body, list):
        return body
    # Some implementations return {"items": [...]} or nest under data.
    if isinstance(body, dict):
        if isinstance(body.get("items"), list):
            return body["items"]
        if isinstance(body.get("events"), list):
            return body["events"]
    raise AssertionError(
        f"audit-events list response not understood: type {type(body)!r}"
    )


__all__ = [
    # Time
    "advance_clock_to",
    "advance_clock_by",
    "sweep_refunds",
    # Atomic
    "create_lot",
    "announce_lot",
    "withdraw_lot",
    "create_bidder_account",
    "get_auction",
    "get_lot",
    "open_auction",
    "cancel_auction",
    "post_deposit",
    "pay_deposit",
    "place_bid",
    "create_confirmation",
    "issue_confirmation",
    "fail_confirmation",
    "seal_confirmation",
    "settle_payment",
    "extend_payment",
    "forfeit_payment",
    "get_payment",
    "initiate_transfer_order",
    "notify_agency",
    "complete_handover",
    "confirm_transfer_completion",
    # Composite
    "setup_lot_with_auction",
    "setup_announced_lot",
    "setup_active_bidder",
    "setup_bidder_with_paid_deposit",
    "setup_live_auction",
    "setup_sold_auction",
    "setup_unsold_auction",
    "setup_issued_confirmation",
    "setup_paid_payment",
    "setup_payment_with_balance",
    "setup_overdue_payment",
    "setup_forfeited_payment",
    "setup_reauction_round",
    "setup_transfer_order_initiated",
    "setup_transfer_notified",
    "setup_transfer_completed",
    "list_audit_events",
]
