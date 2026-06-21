"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints, because the server database is empty at the start of each test.

Identity threading rule (PRD §2.1): a Seller / Buyer is entity_backed, so any
ownership-gated call uses make_seller_headers(seller_id) / make_buyer_headers(
buyer_id) with the real entity id — never the shared TEST_USERS fallback.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .test_users import (
    TEST_USERS,
    make_seller_headers,
    make_buyer_headers,
    make_platform_admin_headers,
    make_trust_safety_headers,
)
from . import factories as F

ADMIN = TEST_USERS["platform_admin_headers"]
TRUST = TEST_USERS["trust_safety_headers"]


# ==========================================================================
# Tier 0: primitives
# ==========================================================================
def create_venue(name="Test Arena", timezone="UTC") -> dict:
    return get_success_data(api.create_venue(F.create_venue_payload(name=name, timezone=timezone), ADMIN))


def create_section(venue_id, face_value_cents=10000, row_count=1, seats_per_row=1,
                   price_zone="STANDARD", name="FLOOR-A") -> dict:
    payload = F.create_section_payload(
        venue_id, face_value_cents=face_value_cents, row_count=row_count,
        seats_per_row=seats_per_row, price_zone=price_zone, name=name,
    )
    return get_success_data(api.create_section(payload, ADMIN))


def create_event(venue_id, price_cap_multiplier=3.0, doors_open_at="2026-09-01T19:00:00.000Z",
                 title="Test Show", last_minute_cutoff_minutes=None) -> dict:
    extra = {}
    if last_minute_cutoff_minutes is not None:
        extra["last_minute_cutoff_minutes"] = last_minute_cutoff_minutes
    payload = F.create_event_payload(
        venue_id, price_cap_multiplier=price_cap_multiplier,
        doors_open_at=doors_open_at, title=title, **extra,
    )
    return get_success_data(api.create_event(payload, ADMIN))


def open_sales(event_id) -> dict:
    return get_success_data(api.open_sales(event_id, ADMIN))


def create_seller(display_name="Test Seller", trust_tier=None) -> dict:
    seller = get_success_data(api.create_seller(F.create_seller_payload(display_name=display_name), ADMIN))
    if trust_tier is not None and trust_tier != "NEW":
        seller = get_success_data(
            api.set_trust_tier(seller["id"], F.set_trust_tier_payload(trust_tier), ADMIN)
        )
    return seller


def create_buyer(display_name="Test Buyer") -> dict:
    return get_success_data(api.create_buyer(F.create_buyer_payload(display_name=display_name), ADMIN))


def set_clock(to_iso8601) -> dict:
    return get_success_data(api.clock_set({"to_iso8601": to_iso8601}, ADMIN))


def advance_clock(by_minutes) -> dict:
    return get_success_data(api.clock_advance({"by_minutes": by_minutes}, ADMIN))


# ==========================================================================
# Tier 1: catalog base
# ==========================================================================
def setup_catalog(face_value_cents=10000, row_count=1, seats_per_row=1,
                  price_cap_multiplier=3.0, doors_open_at="2026-09-01T19:00:00.000Z",
                  open_for_sale=True, last_minute_cutoff_minutes=None):
    """Venue + Section + Event(+open-sales) + Seller + Buyer.
    Returns dict with venue, section, event, seller, buyer and *_id keys."""
    venue = create_venue()
    section = create_section(venue["id"], face_value_cents=face_value_cents,
                             row_count=row_count, seats_per_row=seats_per_row)
    event = create_event(venue["id"], price_cap_multiplier=price_cap_multiplier,
                         doors_open_at=doors_open_at,
                         last_minute_cutoff_minutes=last_minute_cutoff_minutes)
    if open_for_sale:
        event = open_sales(event["id"])
    seller = create_seller()
    buyer = create_buyer()
    return {
        "venue": venue, "section": section, "event": event,
        "seller": seller, "buyer": buyer,
        "venue_id": venue["id"], "section_id": section["id"], "event_id": event["id"],
        "seller_id": seller["id"], "buyer_id": buyer["id"],
    }


# ==========================================================================
# Tier 2: listings + seats + activation
# ==========================================================================
def add_seats(listing_id, seller_id, count, barcode_prefix="S"):
    """Add `count` AVAILABLE seats to a DRAFT listing. Returns list of seats."""
    headers = make_seller_headers(seller_id)
    seats = []
    for i in range(1, count + 1):
        payload = F.create_seat_payload(
            listing_id, row_label="1", seat_number=i,
            barcode_token=f"{barcode_prefix}-{listing_id[:8]}-{i}",
        )
        seats.append(get_success_data(api.create_seat(payload, headers)))
    return seats


def create_draft_listing(event_id, seller_id, section_id, *, pricing_mode="FIXED",
                         ask_price_cents=20000, split_rule="ANY",
                         delivery_method="MOBILE_TRANSFER", dynamic_floor_cents=None) -> dict:
    headers = make_seller_headers(seller_id)
    extra = {}
    if dynamic_floor_cents is not None:
        extra["dynamic_floor_cents"] = dynamic_floor_cents
    payload = F.create_listing_payload(
        event_id, seller_id, section_id, pricing_mode=pricing_mode,
        ask_price_cents=ask_price_cents, split_rule=split_rule,
        delivery_method=delivery_method, **extra,
    )
    return get_success_data(api.create_listing(payload, headers))


def create_active_listing(event_id, seller_id, section_id, *, seat_count=1,
                          pricing_mode="FIXED", ask_price_cents=20000, split_rule="ANY",
                          delivery_method="MOBILE_TRANSFER", dynamic_floor_cents=None,
                          barcode_prefix="S"):
    """DRAFT listing + N seats + activate. Returns (listing_after_activate, seats)."""
    listing = create_draft_listing(
        event_id, seller_id, section_id, pricing_mode=pricing_mode,
        ask_price_cents=ask_price_cents, split_rule=split_rule,
        delivery_method=delivery_method, dynamic_floor_cents=dynamic_floor_cents,
    )
    seats = add_seats(listing["id"], seller_id, seat_count, barcode_prefix=barcode_prefix)
    activated = get_success_data(
        api.activate_listing(listing["id"], make_seller_headers(seller_id))
    )
    return activated, seats


def get_listing_version(listing_id, buyer_id) -> int:
    data = get_success_data(api.get_listing(listing_id, make_buyer_headers(buyer_id)))
    return data["version"]


# ==========================================================================
# Tier 3: orders — reserve / charge
# ==========================================================================
def reserve_order(listing_id, buyer_id, quantity, expected_listing_version, **overrides) -> dict:
    payload = F.create_order_payload(
        listing_id, buyer_id, expected_listing_version, quantity=quantity, **overrides
    )
    return get_success_data(api.create_order(payload, make_buyer_headers(buyer_id)))


def charge_order(order_id, buyer_id) -> dict:
    return get_success_data(api.charge_order(order_id, make_buyer_headers(buyer_id)))


def reserve_and_charge(listing_id, buyer_id, quantity, expected_listing_version, **overrides):
    """Reserve seats then charge. Returns the CHARGED order (post-charge read)."""
    order = reserve_order(listing_id, buyer_id, quantity, expected_listing_version, **overrides)
    return charge_order(order["id"], buyer_id)


def get_payout_for_order(order_id) -> dict:
    data = get_success_data(api.list_payouts(ADMIN, params={"order_id": order_id}))
    items = data if isinstance(data, list) else data.get("items", data)
    assert items, f"no payout found for order {order_id}"
    return items[0]


def get_credit_for_source_order(source_order_id) -> dict:
    data = get_success_data(
        api.list_event_credits(ADMIN, params={"source_order_id": source_order_id})
    )
    items = data if isinstance(data, list) else data.get("items", data)
    assert items, f"no event credit found for source order {source_order_id}"
    return items[0]


# ==========================================================================
# Tier 4: composite scenarios used by the design indices
# ==========================================================================
def setup_charged_order(*, quantity=1, seat_count=None, ask_price_cents=20000,
                        face_value_cents=10000, trust_tier="NEW"):
    """Active FIXED listing + reserved+charged order.
    Returns dict with all entities plus order (CHARGED) and payout."""
    seat_count = seat_count if seat_count is not None else quantity
    base = setup_catalog(face_value_cents=face_value_cents, seats_per_row=max(seat_count, 1))
    if trust_tier != "NEW":
        get_success_data(api.set_trust_tier(base["seller_id"],
                                            F.set_trust_tier_payload(trust_tier), ADMIN))
        base["seller"] = get_success_data(api.get_seller(base["seller_id"], ADMIN))
    listing, seats = create_active_listing(
        base["event_id"], base["seller_id"], base["section_id"],
        seat_count=seat_count, ask_price_cents=ask_price_cents,
    )
    order = reserve_and_charge(listing["id"], base["buyer_id"], quantity, listing["version"])
    payout = get_payout_for_order(order["id"])
    base.update({"listing": listing, "seats": seats, "order": order, "payout": payout})
    return base


def setup_delivery_failed_with_claim(*, quantity=2, reason="NOT_DELIVERED",
                                     face_value_cents=10000):
    """CHARGED order whose delivery FAILED, with an INVESTIGATING guarantee claim.
    Returns dict with order, payout, claim, transfer plus base entities."""
    ctx = setup_charged_order(quantity=quantity, seat_count=quantity,
                              face_value_cents=face_value_cents)
    seller_h = make_seller_headers(ctx["seller_id"])
    buyer_h = make_buyer_headers(ctx["buyer_id"])
    transfer = get_success_data(api.initiate_transfer(ctx["order"]["id"], seller_h))
    get_success_data(api.fail_transfer(transfer["id"], seller_h))
    claim = get_success_data(
        api.create_guarantee_claim(
            F.create_guarantee_claim_payload(ctx["order"]["id"], reason=reason), buyer_h)
    )
    claim = get_success_data(api.investigate_claim(claim["id"], TRUST))
    ctx.update({"transfer": transfer, "claim": claim})
    return ctx


def setup_replacement_listing(ctx, *, seat_count=2):
    """Add a second ACTIVE listing on the same event (same seller) to serve as a
    guarantee replacement target. Returns (listing, seats)."""
    return create_active_listing(
        ctx["event_id"], ctx["seller_id"], ctx["section_id"],
        seat_count=seat_count, barcode_prefix="REPL",
    )


def setup_credit_earning_order(*, quantity=1, face_value_cents=10000, seat_count=None):
    """Buyer earns a genuine EventCredit by charging an order on an event that is
    then CANCELLED. Returns dict with credit, buyer, the cancelled event etc."""
    seat_count = seat_count if seat_count is not None else quantity
    base = setup_catalog(face_value_cents=face_value_cents, seats_per_row=max(seat_count, 1))
    listing, seats = create_active_listing(
        base["event_id"], base["seller_id"], base["section_id"], seat_count=seat_count,
    )
    order = reserve_and_charge(listing["id"], base["buyer_id"], quantity, listing["version"])
    get_success_data(api.cancel_event(base["event_id"], ADMIN))
    credit = get_credit_for_source_order(order["id"])
    base.update({"credit_listing": listing, "credit_order": order, "credit": credit})
    return base
