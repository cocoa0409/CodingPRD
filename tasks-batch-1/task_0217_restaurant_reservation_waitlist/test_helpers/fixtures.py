"""Composite setup helpers for multi-step test prerequisites.

Every individual pytest test runs against a freshly-restarted, empty-database
server, so every fixture builds its preconditions from scratch using only
PRD-declared endpoints. Fixtures use get_success_data() (lenient validator)
internally so setup failures surface as clear "Setup failed" errors.

Identity threading: the Customer role is entity-backed, so any ownership-gated
call (cancel/reschedule own reservation, cancel own waitlist entry) MUST use
make_customer_headers(customer["id"]). Host and Manager are opaque.

Shared fixture convention (matches the design indices): timezone "UTC" so
local time == UTC; DINNER service period 17:00–23:00; clock pinned to
2026-06-15T12:00:00Z; the canonical reservation_start is 2026-06-15T18:00:00Z
(18:00 local, inside DINNER, grid-aligned, 6h out → early/refundable).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_restaurant_payload, create_dining_area_payload, create_table_payload,
    create_service_period_payload, create_customer_payload, create_reservation_payload,
    create_deposit_hold_payload, create_waitlist_entry_payload,
    create_private_dining_event_payload, create_confirm_buyout_payload,
    unique_phone,
)
from .test_users import TEST_USERS, make_customer_headers

MANAGER = TEST_USERS["manager_headers"]
HOST = TEST_USERS["host_headers"]

DEFAULT_CLOCK = "2026-06-15T12:00:00Z"
CANONICAL_START = "2026-06-15T18:00:00Z"


# ─── Low-level single-entity creators ─────────────────────────────────────
def make_restaurant(**overrides):
    """Create a restaurant (Manager). Returns the Restaurant dict."""
    return get_success_data(
        api_client.create_restaurant(create_restaurant_payload(**overrides), MANAGER)
    )


def make_dining_area(restaurant_id, **overrides):
    return get_success_data(
        api_client.create_dining_area(
            create_dining_area_payload(restaurant_id, **overrides), MANAGER
        )
    )


def make_table(dining_area_id, **overrides):
    return get_success_data(
        api_client.create_table(
            create_table_payload(dining_area_id, **overrides), MANAGER
        )
    )


def make_service_period(restaurant_id, **overrides):
    return get_success_data(
        api_client.create_service_period(
            create_service_period_payload(restaurant_id, **overrides), MANAGER
        )
    )


def make_customer(**overrides):
    """Register a customer (self-service, no auth). Returns the Customer dict."""
    return get_success_data(api_client.create_customer(create_customer_payload(**overrides)))


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, MANAGER))


def current_table_version(table_id):
    """Read a table's live version (for threading expected_table_version)."""
    return get_success_data(api_client.get_table(table_id, HOST))["version"]


# ─── Tier 2: standard floor setup ─────────────────────────────────────────
def setup_floor(
    *, restaurant_overrides=None, area_overrides=None, table_overrides=None,
    period_overrides=None, clock=DEFAULT_CLOCK, with_customer=True,
    customer_overrides=None,
):
    """Restaurant + one STANDARD dining area + one table + DINNER period,
    clock pinned, and (optionally) one ACTIVE customer.

    Returns a dict with keys: restaurant, area, table, period, customer (or
    None). The table's current version is also exposed as ``table_version``.
    """
    restaurant = make_restaurant(**(restaurant_overrides or {}))
    area = make_dining_area(restaurant["id"], **(area_overrides or {}))
    table = make_table(area["id"], **(table_overrides or {}))
    period = make_service_period(restaurant["id"], **(period_overrides or {}))
    if clock is not None:
        set_clock(clock)
    customer = make_customer(**(customer_overrides or {})) if with_customer else None
    return {
        "restaurant": restaurant,
        "area": area,
        "table": table,
        "period": period,
        "customer": customer,
        "table_version": table["version"],
    }


# ─── Tier 1/3: reservation creation and lifecycle shortcuts ───────────────
def book_reservation(
    restaurant_id, customer_id, table_id, *, expected_table_version=None, **overrides
):
    """Create a REQUESTED reservation owned by `customer_id`.

    Threads the entity-backed Customer identity (X-User-ID == customer_id) so
    ownership is satisfied, and reads the table's live version when one is not
    supplied. Returns the Reservation dict.
    """
    if expected_table_version is None:
        expected_table_version = current_table_version(table_id)
    payload = create_reservation_payload(
        restaurant_id, customer_id, table_id, expected_table_version, **overrides
    )
    return get_success_data(
        api_client.create_reservation(payload, make_customer_headers(customer_id))
    )


def place_hold(reservation_id, customer_id, **overrides):
    """Place a deposit hold on a reservation (owned by customer_id)."""
    return get_success_data(
        api_client.place_deposit_hold(
            reservation_id, create_deposit_hold_payload(**overrides),
            make_customer_headers(customer_id),
        )
    )


def confirm(reservation_id):
    """Host-confirm a REQUESTED reservation. Returns the Reservation dict."""
    return get_success_data(api_client.confirm_reservation(reservation_id, HOST))


def setup_confirmed_reservation(
    *, party_size=2, deposit=False, restaurant_overrides=None, table_overrides=None,
    period_overrides=None, reservation_start=CANONICAL_START, clock=DEFAULT_CLOCK,
):
    """Floor + one CONFIRMED reservation (optionally backed by a HELD deposit).

    Returns a dict: restaurant, area, table, period, customer, reservation, and
    hold (or None). Used by no-show / cancel / reschedule / seat scenarios.
    """
    floor = setup_floor(
        restaurant_overrides=restaurant_overrides, table_overrides=table_overrides,
        period_overrides=period_overrides, clock=clock,
    )
    res = book_reservation(
        floor["restaurant"]["id"], floor["customer"]["id"], floor["table"]["id"],
        party_size=party_size, reservation_start=reservation_start,
    )
    hold = None
    if deposit:
        hold = place_hold(res["id"], floor["customer"]["id"])
    res = confirm(res["id"])
    return {**floor, "reservation": res, "hold": hold}


def setup_seated_reservation(**kwargs):
    """Floor + a SEATED reservation. Advances clock to 18:05 before seating."""
    ctx = setup_confirmed_reservation(**kwargs)
    set_clock("2026-06-15T18:05:00Z")
    seated = get_success_data(api_client.seat_reservation(ctx["reservation"]["id"], HOST))
    return {**ctx, "reservation": seated}


# ─── Waitlist setup ───────────────────────────────────────────────────────
def setup_floor_for_waitlist(
    *, table_overrides=None, restaurant_overrides=None, clock="2026-06-15T18:00:00Z",
    with_customer=True, customer_overrides=None,
):
    """Restaurant + STANDARD area + one fitting table (no service period needed
    for waitlist join/notify), clock pinned, optional customer. Returns dict
    with restaurant, area, table, customer."""
    restaurant = make_restaurant(**(restaurant_overrides or {}))
    area = make_dining_area(restaurant["id"])
    table = make_table(area["id"], **(table_overrides or {"max_party_size": 6}))
    if clock is not None:
        set_clock(clock)
    customer = make_customer(**(customer_overrides or {})) if with_customer else None
    return {"restaurant": restaurant, "area": area, "table": table, "customer": customer}


def join_waitlist(restaurant_id, customer_id, **overrides):
    """Customer joins the waitlist. Returns the WaitlistEntry dict."""
    payload = create_waitlist_entry_payload(restaurant_id, customer_id, **overrides)
    return get_success_data(
        api_client.create_waitlist_entry(payload, make_customer_headers(customer_id))
    )


def setup_notified_waitlist_entry(
    *, party_size=2, table_overrides=None, restaurant_overrides=None,
    clock="2026-06-15T18:00:00Z", requested_start="2026-06-15T18:30:00Z",
):
    """Floor + one WAITING entry promoted to NOTIFIED. Returns dict with
    restaurant, area, table, customer, entry."""
    floor = setup_floor_for_waitlist(
        table_overrides=table_overrides, restaurant_overrides=restaurant_overrides,
        clock=clock,
    )
    entry = join_waitlist(
        floor["restaurant"]["id"], floor["customer"]["id"],
        party_size=party_size, requested_start=requested_start,
    )
    notified = get_success_data(api_client.notify_waitlist_entry(entry["id"], HOST))
    return {**floor, "entry": notified}


# ─── Private-dining setup ─────────────────────────────────────────────────
def setup_private_area(*, restaurant_overrides=None, with_table=False, table_overrides=None,
                       with_period=False, clock=DEFAULT_CLOCK):
    """Restaurant + one PRIVATE dining area (optionally a table inside it and a
    DINNER period). Returns dict with restaurant, area, customer, and optionally
    table, period."""
    restaurant = make_restaurant(**(restaurant_overrides or {}))
    area = make_dining_area(restaurant["id"], name="PRIVATE_ROOM", kind="PRIVATE")
    out = {"restaurant": restaurant, "area": area}
    if with_table:
        out["table"] = make_table(area["id"], **(table_overrides or {"max_party_size": 12}))
    if with_period:
        out["period"] = make_service_period(restaurant["id"])
    if clock is not None:
        set_clock(clock)
    out["customer"] = make_customer()
    return out


def make_private_event(restaurant_id, area_id, customer_id, **overrides):
    """Open a private-dining INQUIRY. Returns the PrivateDiningEvent dict."""
    payload = create_private_dining_event_payload(
        restaurant_id, area_id, customer_id, **overrides
    )
    return get_success_data(api_client.create_private_dining_event(payload, MANAGER))


def propose_private_event(event_id):
    return get_success_data(api_client.propose_private_dining_event(event_id, MANAGER))


def confirm_private_event(event_id, expected_dining_area_version):
    return get_success_data(
        api_client.confirm_private_dining_event(
            event_id, create_confirm_buyout_payload(expected_dining_area_version), MANAGER
        )
    )


def setup_confirmed_buyout(
    *, event_start="2026-06-15T18:00:00Z", event_end="2026-06-15T22:00:00Z",
    food_minimum_cents=200000, table_overrides=None, restaurant_overrides=None,
    clock=DEFAULT_CLOCK,
):
    """A PRIVATE area with a table whose buyout over [event_start, event_end] is
    CONFIRMED (area BOUGHT_OUT). Returns dict with restaurant, area, table,
    customer, event, and the pre-buyout table_version."""
    ctx = setup_private_area(
        restaurant_overrides=restaurant_overrides, with_table=True,
        table_overrides=table_overrides, with_period=True, clock=clock,
    )
    area_version = ctx["area"]["version"]
    table_version = ctx["table"]["version"]
    event = make_private_event(
        ctx["restaurant"]["id"], ctx["area"]["id"], ctx["customer"]["id"],
        event_start=event_start, event_end=event_end, food_minimum_cents=food_minimum_cents,
    )
    propose_private_event(event["id"])
    event = confirm_private_event(event["id"], area_version)
    return {**ctx, "event": event, "table_version": table_version}
