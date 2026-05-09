"""Composite setup helpers — multi-step fixtures that walk the system into target states."""
from datetime import datetime, timedelta, timezone
from typing import Optional, List

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_seller_payload, create_bidder_payload, credit_wallet_payload,
    create_lot_payload, place_bid_payload, create_proxy_payload,
    advance_clock_payload, event_payment_confirmed_payload,
    event_identity_verified_payload, event_logistics_delivered_payload,
    file_dispute_payload, resolve_dispute_payload,
    unique_serial,
)
from .test_users import (
    TEST_USERS, make_seller_headers, make_bidder_headers,
    make_admin_headers, make_arbitrator_headers,
)
from .types import LotCategory, LotCondition, DisputeOutcome


ADMIN_HEADERS = TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# clock anchoring
# ---------------------------------------------------------------------------
# The system logical clock is monotonic across the entire test session — there
# is no per-test reset endpoint exposed. Earlier tests advance it by years to
# drive lots through SCHEDULED → LIVE → SOLD transitions. Therefore any
# absolute timestamp like "2035-01-01" can fall in the past once the session
# has run a few setups.
#
# Resolution: read the current logical clock by issuing a no-op
# advance-clock(0) call, then build scheduled_start_at as a delta from that
# value. The /_clock/advance endpoint returns the current `now` in its
# response, which we use as the anchor.

def _parse_iso(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _format_iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}" + "Z"


def current_clock_now() -> datetime:
    """Return the implementation's current logical clock as a UTC datetime."""
    resp = api_client.advance_clock(advance_clock_payload(0), ADMIN_HEADERS)
    data = get_success_data(resp)
    return _parse_iso(data["now"])


def iso_relative(seconds_from_now: int) -> str:
    """ISO 8601 timestamp `seconds_from_now` after the current logical clock."""
    return _format_iso(current_clock_now() + timedelta(seconds=seconds_from_now))


# Default schedule deltas (in seconds) used by setup_live_lot etc.
DEFAULT_START_DELTA_SECONDS = 24 * 3600          # 1 day in the future
DEFAULT_DURATION_SECONDS = 24 * 3600             # 1 day duration


def iso_future(year_offset: int = 5, month: int = 1, day: int = 1) -> str:
    """Backwards-compatible name; produces a timestamp 1 day after current clock."""
    return iso_relative(DEFAULT_START_DELTA_SECONDS)


# ---------------------------------------------------------------------------
# Tier 1: Entity creation
# ---------------------------------------------------------------------------

def create_seller(display_name: str = "Acme Auction House") -> dict:
    resp = api_client.create_seller(create_seller_payload(display_name=display_name), ADMIN_HEADERS)
    return get_success_data(resp)


def create_bidder(
    display_name: str = "BidderTest",
    *,
    affiliated_seller_id: Optional[str] = None,
    wallet_amount_cents: int = 0,
    identity_verified: bool = False,
) -> dict:
    payload = create_bidder_payload(display_name=display_name)
    if affiliated_seller_id is not None:
        payload["affiliated_seller_id"] = affiliated_seller_id
    bidder = get_success_data(api_client.create_bidder(payload, ADMIN_HEADERS))
    if wallet_amount_cents > 0:
        api_client.credit_wallet(bidder["id"], credit_wallet_payload(wallet_amount_cents), ADMIN_HEADERS)
    if identity_verified:
        api_client.event_identity_verified(
            event_identity_verified_payload(bidder["id"]), ADMIN_HEADERS
        )
    # Refresh
    return get_success_data(api_client.get_bidder(bidder["id"], ADMIN_HEADERS))


# ---------------------------------------------------------------------------
# Tier 2: Lot creation in DRAFT / SCHEDULED
# ---------------------------------------------------------------------------

def create_lot_for_seller(
    seller: dict,
    *,
    title: str = "Test Lot",
    category: str = LotCategory.ART.value,
    condition: str = LotCondition.NEW.value,
    physical_item_serial: Optional[str] = None,
    reserve_price_cents: int = 100_000,
    starting_bid_cents: int = 50_000,
    scheduled_start_at: Optional[str] = None,
    scheduled_end_at: Optional[str] = None,
) -> dict:
    """Create a lot owned by `seller` and return the Lot resource (DRAFT)."""
    if scheduled_start_at is None or scheduled_end_at is None:
        anchor = current_clock_now()
        if scheduled_start_at is None:
            scheduled_start_at = _format_iso(anchor + timedelta(seconds=DEFAULT_START_DELTA_SECONDS))
        if scheduled_end_at is None:
            scheduled_end_at = _format_iso(anchor + timedelta(seconds=DEFAULT_START_DELTA_SECONDS + DEFAULT_DURATION_SECONDS))
    payload = create_lot_payload(
        seller_id=seller["id"],
        title=title,
        category=category,
        condition=condition,
        physical_item_serial=physical_item_serial or unique_serial(),
        reserve_price_cents=reserve_price_cents,
        starting_bid_cents=starting_bid_cents,
        scheduled_start_at=scheduled_start_at,
        scheduled_end_at=scheduled_end_at,
    )
    return get_success_data(api_client.create_lot(payload, make_seller_headers(seller["id"])))


def publish_lot(lot: dict, seller: dict) -> dict:
    return get_success_data(api_client.publish_lot(lot["id"], make_seller_headers(seller["id"])))


def cancel_lot(lot: dict, seller: dict) -> dict:
    return get_success_data(api_client.cancel_lot(lot["id"], make_seller_headers(seller["id"])))


def create_and_publish_lot(seller: dict, **lot_kwargs) -> dict:
    """DRAFT → SCHEDULED."""
    lot = create_lot_for_seller(seller, **lot_kwargs)
    return publish_lot(lot, seller)


# ---------------------------------------------------------------------------
# Clock helpers
# ---------------------------------------------------------------------------

def advance_clock(seconds: int) -> dict:
    return get_success_data(api_client.advance_clock(advance_clock_payload(seconds), ADMIN_HEADERS))


# ---------------------------------------------------------------------------
# Tier 3: Lot in LIVE / SOLD / SOLD-and-PAID
# ---------------------------------------------------------------------------

def get_lot(lot_id: str) -> dict:
    return get_success_data(api_client.get_lot(lot_id, ADMIN_HEADERS))


def setup_live_lot(
    *,
    seller: Optional[dict] = None,
    reserve_price_cents: int = 100_000,
    starting_bid_cents: int = 50_000,
    category: str = LotCategory.ART.value,
    physical_item_serial: Optional[str] = None,
    advance_to_live: bool = True,
) -> tuple[dict, dict]:
    """Create seller (if not given) + lot + publish + advance clock so lot is LIVE."""
    seller = seller or create_seller()
    # Schedule start far in the future of the *system* clock, then advance.
    # Use very-large gap to absorb any prior clock advances during the session.
    lot = create_and_publish_lot(
        seller,
        reserve_price_cents=reserve_price_cents,
        starting_bid_cents=starting_bid_cents,
        category=category,
        physical_item_serial=physical_item_serial,
    )
    if advance_to_live:
        # Auction goes LIVE at scheduled_start_at. We don't know the absolute
        # clock value, but we know the event is in the future relative to the
        # current logical clock since publish's priority-11 check passed.
        # Advance enough to cross scheduled_start_at without crossing
        # scheduled_end_at (which is start + ~1 day). We use a small advance.
        # Strategy: advance by 1s repeatedly until lot.status == "LIVE", but
        # since we control the schedule, we just advance to the start.
        _advance_until_lot_status(lot["id"], "LIVE")
        lot = get_lot(lot["id"])
    return seller, lot


def _advance_until_lot_status(lot_id: str, target: str, max_total_seconds: int = 10 * 365 * 24 * 3600):
    """Advance clock toward the lot's scheduled_start_at (LIVE) or effective_end_at (SOLD/UNSOLD).

    Schedule windows are in the seconds-to-day range relative to the current
    clock; jumping 30 days at a time would skip past LIVE and land in SOLD.
    Strategy: read the lot's schedule, compute the exact delta needed, and
    advance precisely.
    """
    lot = get_lot(lot_id)
    if lot["status"] == target:
        return
    now = current_clock_now()
    if target == "LIVE":
        target_at = _parse_iso(lot["scheduled_start_at"])
        # Step just past start so the clock-evaluator sees now > start.
        delta = int((target_at - now).total_seconds()) + 1
    else:
        # Generic: step in 60s increments capped at max_total_seconds.
        delta = 60
    if delta > 0:
        advance_clock(delta)
    lot = get_lot(lot_id)
    if lot["status"] == target:
        return
    # Fallback: probe in 60s increments up to a generous cap.
    advanced = max(delta, 0)
    while advanced < max_total_seconds:
        lot = get_lot(lot_id)
        if lot["status"] == target:
            return
        advance_clock(60)
        advanced += 60
    final = get_lot(lot_id)
    raise AssertionError(
        f"Setup step failed: clock advanced {advanced}s but lot {lot_id} status is {final['status']!r}, "
        f"never reached {target!r}."
    )


def place_bid_on_lot(bidder: dict, lot: dict, amount_cents: int) -> dict:
    """Place a single bid; uses bidder's identity correctly."""
    resp = api_client.place_bid(
        lot["id"], place_bid_payload(amount_cents), make_bidder_headers(bidder["id"])
    )
    return get_success_data(resp)


def setup_live_lot_with_bid(
    *,
    seller: Optional[dict] = None,
    reserve_price_cents: int = 100_000,
    starting_bid_cents: int = 50_000,
    bid_amount_cents: int = 100_000,
    bidder_wallet: int = 1_000_000,
    bidder_identity_verified: bool = False,
    category: str = LotCategory.ART.value,
) -> tuple[dict, dict, dict, dict]:
    """Returns (seller, lot, bidder, bid). Lot is LIVE with a single bid above reserve (default)."""
    seller, lot = setup_live_lot(
        seller=seller,
        reserve_price_cents=reserve_price_cents,
        starting_bid_cents=starting_bid_cents,
        category=category,
    )
    bidder = create_bidder("Buyer-One", wallet_amount_cents=bidder_wallet, identity_verified=bidder_identity_verified)
    bid = place_bid_on_lot(bidder, lot, bid_amount_cents)
    lot = get_lot(lot["id"])
    return seller, lot, bidder, bid


def close_lot_to_sold(lot_id: str) -> dict:
    """Advance clock past scheduled_end_at; lot transitions to SOLD or UNSOLD."""
    _advance_until_lot_status_one_of(lot_id, ("SOLD", "UNSOLD"))
    return get_lot(lot_id)


def _advance_until_lot_status_one_of(lot_id: str, targets: tuple, max_total_seconds: int = 10 * 365 * 24 * 3600):
    """Advance precisely past the lot's effective_end_at (the close trigger), then drain."""
    lot = get_lot(lot_id)
    if lot["status"] in targets:
        return
    now = current_clock_now()
    eff_end = lot.get("effective_end_at") or lot["scheduled_end_at"]
    target_at = _parse_iso(eff_end)
    delta = int((target_at - now).total_seconds()) + 1
    if delta > 0:
        advance_clock(delta)
    lot = get_lot(lot_id)
    if lot["status"] in targets:
        return
    # Fallback fine probe (handles soft-close extensions).
    advanced = max(delta, 0)
    while advanced < max_total_seconds:
        lot = get_lot(lot_id)
        if lot["status"] in targets:
            return
        # If we are still LIVE, recompute target_at since soft-close may have extended it.
        if lot["status"] == "LIVE":
            now = current_clock_now()
            eff_end = lot.get("effective_end_at") or lot["scheduled_end_at"]
            target_at = _parse_iso(eff_end)
            step = max(int((target_at - now).total_seconds()) + 1, 1)
        else:
            step = 60
        advance_clock(step)
        advanced += step
    final = get_lot(lot_id)
    raise AssertionError(
        f"Setup step failed: lot {lot_id} status {final['status']!r}, never reached {targets!r}."
    )


def setup_sold_lot(
    *,
    seller: Optional[dict] = None,
    reserve_price_cents: int = 100_000,
    starting_bid_cents: int = 50_000,
    bid_amount_cents: int = 100_000,
    bidder_wallet: int = 1_000_000,
    bidder_identity_verified: bool = False,
    category: str = LotCategory.ART.value,
) -> tuple[dict, dict, dict, dict]:
    """Returns (seller, lot_after_close, bidder, invoice). Lot status is SOLD."""
    seller, lot, bidder, bid = setup_live_lot_with_bid(
        seller=seller,
        reserve_price_cents=reserve_price_cents,
        starting_bid_cents=starting_bid_cents,
        bid_amount_cents=bid_amount_cents,
        bidder_wallet=bidder_wallet,
        bidder_identity_verified=bidder_identity_verified,
        category=category,
    )
    lot = close_lot_to_sold(lot["id"])
    if lot["status"] != "SOLD":
        raise AssertionError(f"setup_sold_lot expected SOLD but got {lot['status']!r}")
    invoice = get_success_data(api_client.get_invoice(lot["id"], ADMIN_HEADERS))
    return seller, lot, bidder, invoice


def pay_invoice(invoice: dict) -> dict:
    """Mark invoice PAID via /_events/payment-confirmed."""
    paid_at = invoice.get("paid_at") or _approx_now_iso_after_clock_advance()
    payload = event_payment_confirmed_payload(invoice["id"], paid_at)
    return get_success_data(api_client.event_payment_confirmed(payload, ADMIN_HEADERS))


def _approx_now_iso_after_clock_advance() -> str:
    # Read the actual logical clock to use as the timestamp for payment-confirmed,
    # logistics-delivered, etc. Returning a fixed far-future string would either
    # land before the lot's payment_deadline_at (and be rejected) or drift past
    # the dispute window, depending on how many setups preceded.
    return _format_iso(current_clock_now())


def setup_paid_lot(**kwargs) -> tuple[dict, dict, dict, dict]:
    """Returns (seller, lot, bidder, invoice_paid)."""
    seller, lot, bidder, invoice = setup_sold_lot(**kwargs)
    pay_invoice(invoice)
    invoice_paid = get_success_data(api_client.get_invoice(lot["id"], ADMIN_HEADERS))
    return seller, lot, bidder, invoice_paid


def deliver_lot(lot: dict, delivered_at: Optional[str] = None) -> dict:
    payload = event_logistics_delivered_payload(
        lot["id"], delivered_at or _approx_now_iso_after_clock_advance()
    )
    return get_success_data(api_client.event_logistics_delivered(payload, ADMIN_HEADERS))


def setup_paid_and_delivered_lot(**kwargs) -> tuple[dict, dict, dict, dict]:
    """Returns (seller, lot_with_delivered_at, bidder, invoice_paid)."""
    seller, lot, bidder, invoice = setup_paid_lot(**kwargs)
    deliver_lot(lot)
    lot = get_lot(lot["id"])
    return seller, lot, bidder, invoice


# ---------------------------------------------------------------------------
# Tier 4: Disputes
# ---------------------------------------------------------------------------

def file_dispute_for_lot(
    lot: dict, bidder: dict, *,
    claimed_refund_amount_cents: int = 50_000,
    reason: str = "Item not as described",
    evidence: Optional[List[dict]] = None,
) -> dict:
    payload = file_dispute_payload(
        reason=reason,
        evidence=evidence,
        claimed_refund_amount_cents=claimed_refund_amount_cents,
    )
    return get_success_data(api_client.file_dispute(lot["id"], payload, make_bidder_headers(bidder["id"])))


def setup_dispute_under_review(
    *,
    hammer_amount_cents: int = 100_000,
    reserve_price_cents: int = 100_000,
    claimed_refund_amount_cents: int = 50_000,
    bidder_identity_verified: bool = False,
    category: str = LotCategory.ART.value,
) -> tuple[dict, dict, dict, dict, dict]:
    """Returns (seller, lot_disputed, bidder, invoice, dispute_under_review)."""
    seller, lot, bidder, invoice = setup_paid_and_delivered_lot(
        reserve_price_cents=reserve_price_cents,
        starting_bid_cents=hammer_amount_cents,
        bid_amount_cents=hammer_amount_cents,
        category=category,
        bidder_identity_verified=bidder_identity_verified,
    )
    dispute = file_dispute_for_lot(lot, bidder, claimed_refund_amount_cents=claimed_refund_amount_cents)
    arb_headers = make_arbitrator_headers()
    dispute = get_success_data(api_client.start_dispute_review(lot["id"], dispute["id"], arb_headers))
    lot = get_lot(lot["id"])
    invoice = get_success_data(api_client.get_invoice(lot["id"], ADMIN_HEADERS))
    return seller, lot, bidder, invoice, dispute


def resolve_dispute(lot_id: str, dispute_id: str, outcome: str, *, refund_amount: int = None) -> dict:
    payload = resolve_dispute_payload(outcome, resolution_refund_amount_cents=refund_amount)
    return get_success_data(api_client.resolve_dispute(
        lot_id, dispute_id, payload, make_arbitrator_headers()
    ))


# ---------------------------------------------------------------------------
# Find-by-bidder helpers (the system stores deposits internally; tests need to
# locate them via lot+bidder pairing). We expose a helper that finds a deposit
# by traversing the GET endpoints. Since there's no list-deposits endpoint, we
# infer state via the bid record (Bid.deposit_id) for placed bids, and via
# Bidder.held_deposit_cents for aggregate held.
# ---------------------------------------------------------------------------

def find_deposit_id_for_bid(lot_id: str, bid_id: str) -> Optional[str]:
    """Look up a bid in the per-lot listing, return its deposit_id."""
    resp = api_client.list_bids(lot_id, ADMIN_HEADERS)
    body = resp.json()
    for bid in body.get("data", []):
        if bid.get("id") == bid_id:
            return bid.get("deposit_id")
    return None
