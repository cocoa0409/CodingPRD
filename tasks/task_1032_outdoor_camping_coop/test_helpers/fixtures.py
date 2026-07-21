"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures surface
as clear "Setup failed" errors rather than confusing assertion failures.

Identity threading: after creating a Member, every ownership-gated Member call
uses make_member_headers(member["id"]) so X-User-ID equals the member's real id.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_member_payload, create_gear_sku_payload, create_gear_unit_payload,
    create_rental_payload, create_order_payload, create_trade_in_payload,
    create_class_trip_payload, create_booking_payload,
    create_permit_allocation_payload, create_permit_pass_payload,
)
from .test_users import TEST_USERS, make_member_headers

STAFF = TEST_USERS["staff_headers"]
PUBLIC = TEST_USERS["public_headers"]


# ─── Primitive creators ───────────────────────────────────────────────────

def new_member(tier=None, status=None, credit=0, **overrides) -> dict:
    """Register a member (as Public), optionally set tier/status, and fund credit.

    Returns the latest member representation (after any store-credit funding)."""
    payload = create_member_payload(**overrides)
    if tier is not None:
        payload["membership_tier"] = tier
    if status is not None:
        payload["membership_status"] = status
    member = get_success_data(api_client.create_member(payload, PUBLIC))
    if credit:
        member = get_success_data(api_client.adjust_store_credit(
            member["id"], {"amount_cents": credit}, STAFF))
    return member


def fund_member(member_id: str, amount_cents: int) -> dict:
    return get_success_data(api_client.adjust_store_credit(
        member_id, {"amount_cents": amount_cents}, STAFF))


def new_gear_sku(name="Test Gear", category="TENT", price_cents=10000,
                 rentable=False, daily_rental_rate_cents=0) -> dict:
    payload = create_gear_sku_payload(
        name=name, category=category, retail_price_cents=price_cents)
    if rentable:
        payload["rentable"] = True
        payload["daily_rental_rate_cents"] = daily_rental_rate_cents
    return get_success_data(api_client.create_gear_sku(payload, STAFF))


def new_gear_unit(sku_id: str, serial=None, condition=None) -> dict:
    payload = create_gear_unit_payload(sku_id)
    if serial is not None:
        payload["serial_number"] = serial
    if condition is not None:
        payload["condition_grade"] = condition
    return get_success_data(api_client.create_gear_unit(payload, STAFF))


def new_rentable_unit(daily_rental_rate_cents=2000, category="KAYAK",
                      price_cents=90000) -> tuple:
    """Rentable SKU + one physical unit. Returns (sku, unit)."""
    sku = new_gear_sku(name="Rentable Gear", category=category,
                       price_cents=price_cents, rentable=True,
                       daily_rental_rate_cents=daily_rental_rate_cents)
    unit = new_gear_unit(sku["id"])
    return sku, unit


# ─── Rentals ──────────────────────────────────────────────────────────────

def quote_rental(member: dict, unit_id: str, start_at: str, due_at: str,
                 damage_waiver=None, deposit_cents=None) -> dict:
    """Create (quote) a rental as the owning member."""
    payload = create_rental_payload(member["id"], unit_id, start_at, due_at)
    if damage_waiver is not None:
        payload["damage_waiver"] = damage_waiver
    if deposit_cents is not None:
        payload["deposit_cents"] = deposit_cents
    return get_success_data(api_client.create_rental(
        payload, make_member_headers(member["id"])))


def pickup(rental_id: str) -> dict:
    return get_success_data(api_client.pickup_rental(rental_id, STAFF))


def return_rental(rental_id: str) -> dict:
    return get_success_data(api_client.return_rental(rental_id, STAFF))


def set_clock(iso: str):
    return api_client.set_clock({"to_iso8601": iso}, STAFF)


def setup_picked_up_rental(tier="PREMIER", daily_rental_rate_cents=2000,
                           start_at="2026-07-05T09:00:00Z",
                           due_at="2026-07-12T09:00:00Z",
                           damage_waiver=None) -> tuple:
    """Active member + rentable unit + rental quoted then picked up.

    Returns (member, sku, unit, rental) where the rental is PICKED_UP."""
    member = new_member(tier=tier)
    sku, unit = new_rentable_unit(daily_rental_rate_cents=daily_rental_rate_cents)
    rental = quote_rental(member, unit["id"], start_at, due_at,
                          damage_waiver=damage_waiver)
    pickup(rental["id"])
    return member, sku, unit, rental


# ─── Sales orders ─────────────────────────────────────────────────────────

def _lines(*sku_qty_pairs) -> list:
    return [{"gear_sku_id": sku_id, "quantity": qty} for sku_id, qty in sku_qty_pairs]


def create_order(member: dict, sku_qty_pairs: list, use_store_credit=None) -> dict:
    """sku_qty_pairs: list of (sku_id, quantity) tuples."""
    payload = create_order_payload(member["id"], _lines(*sku_qty_pairs))
    if use_store_credit is not None:
        payload["use_store_credit"] = use_store_credit
    return get_success_data(api_client.create_order(
        payload, make_member_headers(member["id"])))


def pay_order(member: dict, order_id: str) -> dict:
    return get_success_data(api_client.pay_order(
        order_id, make_member_headers(member["id"])))


def fulfill_order(order_id: str) -> dict:
    return get_success_data(api_client.fulfill_order(order_id, STAFF))


def return_order(member: dict, order_id: str) -> dict:
    return get_success_data(api_client.return_order(
        order_id, make_member_headers(member["id"])))


def setup_paid_fulfilled_order(tier="PREMIER", credit=5000,
                               sku_prices=(1025, 1025)) -> tuple:
    """Member (funded) + N single-quantity SKUs + order paid-with-credit + fulfilled.

    Returns (member, order)."""
    member = new_member(tier=tier, credit=credit)
    pairs = []
    for i, price in enumerate(sku_prices):
        sku = new_gear_sku(name=f"Order SKU {i}", category="APPAREL", price_cents=price)
        pairs.append((sku["id"], 1))
    order = create_order(member, pairs, use_store_credit=True)
    pay_order(member, order["id"])
    fulfill_order(order["id"])
    return member, order


# ─── Trade-ins ────────────────────────────────────────────────────────────

def submit_trade_in(member: dict, sku_id: str, condition="GOOD",
                    method="INSTANT_CREDIT") -> dict:
    payload = create_trade_in_payload(member["id"], sku_id, condition, method)
    return get_success_data(api_client.create_trade_in(
        payload, make_member_headers(member["id"])))


def appraise(trade_in_id: str, appraised_value_cents: int) -> dict:
    return get_success_data(api_client.appraise_trade_in(
        trade_in_id, {"appraised_value_cents": appraised_value_cents}, STAFF))


def respond(member: dict, trade_in_id: str, action: str, counter_cents=None) -> dict:
    payload = {"action": action}
    if counter_cents is not None:
        payload["counter_cents"] = counter_cents
    return get_success_data(api_client.respond_trade_in(
        trade_in_id, payload, make_member_headers(member["id"])))


def sell(trade_in_id: str, resale_price_cents: int) -> dict:
    return get_success_data(api_client.sell_trade_in(
        trade_in_id, {"resale_price_cents": resale_price_cents}, STAFF))


# ─── Class trips & bookings ───────────────────────────────────────────────

def new_class_trip(capacity=3, price_cents=1000, category="CLASS",
                   title="Test Trip", start_at="2026-07-20T08:00:00Z",
                   end_at="2026-07-20T12:00:00Z") -> dict:
    payload = create_class_trip_payload(
        title=title, category=category, start_at=start_at, end_at=end_at,
        capacity=capacity, price_cents=price_cents)
    return get_success_data(api_client.create_class_trip(payload, STAFF))


def get_trip(class_trip_id: str) -> dict:
    return get_success_data(api_client.get_class_trip(class_trip_id, STAFF))


def book(member: dict, trip: dict, expected_version=None) -> dict:
    """Book a member onto a trip using the trip's current version unless one is
    explicitly supplied (for stale-version tests)."""
    if expected_version is None:
        expected_version = get_trip(trip["id"])["version"]
    payload = create_booking_payload(member["id"], trip["id"], expected_version)
    return get_success_data(api_client.create_booking(
        payload, make_member_headers(member["id"])))


def cancel_booking(member: dict, booking_id: str) -> dict:
    return get_success_data(api_client.cancel_booking(
        booking_id, make_member_headers(member["id"])))


def cancel_trip(class_trip_id: str) -> dict:
    return get_success_data(api_client.cancel_class_trip(class_trip_id, STAFF))


def complete_trip(class_trip_id: str) -> dict:
    return get_success_data(api_client.complete_class_trip(class_trip_id, STAFF))


def checkin(booking_id: str) -> dict:
    return get_success_data(api_client.checkin_booking(booking_id, STAFF))


def setup_trip_with_booked_and_waitlisted(price_cents=3000, credit=5000) -> tuple:
    """Capacity-1 trip; member A BOOKED, member B WAITLISTED behind A.

    Returns (trip, member_a, booking_a, member_b, booking_b)."""
    ma = new_member(credit=credit)
    mb = new_member(credit=credit)
    trip = new_class_trip(capacity=1, price_cents=price_cents,
                          start_at="2026-07-20T08:00:00Z",
                          end_at="2026-07-20T12:00:00Z")
    ba = book(ma, trip)          # takes the only seat -> BOOKED
    bb = book(mb, trip)          # zero seats -> WAITLISTED
    return trip, ma, ba, mb, bb


# ─── Permits ──────────────────────────────────────────────────────────────

def new_permit_allocation(total_quota=5, price_cents=2000, park_name="Test Park",
                          season_start="2026-08-01T00:00:00Z",
                          season_end="2026-08-31T23:59:59Z") -> dict:
    payload = create_permit_allocation_payload(
        park_name=park_name, season_start=season_start, season_end=season_end,
        total_quota=total_quota, price_cents=price_cents)
    return get_success_data(api_client.create_permit_allocation(payload, STAFF))


def get_allocation(allocation_id: str) -> dict:
    return get_success_data(api_client.get_permit_allocation(allocation_id, STAFF))


def issue_permit(member: dict, allocation: dict, entry_date: str,
                 expected_version=None) -> dict:
    if expected_version is None:
        expected_version = get_allocation(allocation["id"])["version"]
    payload = create_permit_pass_payload(
        member["id"], allocation["id"], entry_date, expected_version)
    return get_success_data(api_client.create_permit_pass(
        payload, make_member_headers(member["id"])))
