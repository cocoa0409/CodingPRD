"""Composite setup helpers.

The interesting claims in this PRD require the system to be in a specific state
that takes several API calls to reach (a submitted DTC order, a published
tasting event with booked seats, an ATTESTED member, a completed event that
grants loyalty points). These helpers encapsulate those multi-step sequences.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database) and uses get_success_data() so setup failures surface as clear
"Setup step failed" errors. Ownership-gated calls by Member always thread the
real Member.id through make_member_headers().
"""
from prd_bench_local_runner.testing import get_success_data, validate_success

from .api_client import api_client
from .constants import CLOCK_START
from .factories import (
    add_order_line_payload,
    book_seat_payload,
    create_attestation_payload,
    create_category_payload,
    create_club_plan_payload,
    create_club_subscription_payload,
    create_flight_item_payload,
    create_lot_payload,
    create_member_payload,
    create_order_payload,
    create_shipment_payload,
    create_shipping_state_rule_payload,
    create_sku_payload,
    create_special_order_payload,
    create_tasting_event_payload,
    submit_order_payload,
)
from .test_users import TEST_USERS, make_member_headers

ADMIN = TEST_USERS["platform_admin_headers"]
STAFF = TEST_USERS["shop_staff_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ---------------------------------------------------------------------------
# Tier 0: primitive creators
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=CLOCK_START):
    """Advance the logical UTC clock (PlatformAdmin test-driving capability)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def make_category(**overrides):
    payload = create_category_payload(**overrides)
    return get_success_data(api_client.create_category(payload, ADMIN))


def make_sku(category_id, **overrides):
    payload = create_sku_payload(category_id, **overrides)
    return get_success_data(api_client.create_sku(payload, ADMIN))


def make_lot(sku_id, **overrides):
    payload = create_lot_payload(**overrides)
    return get_success_data(api_client.create_lot(sku_id, payload, ADMIN))


def make_member(**overrides):
    payload = create_member_payload(**overrides)
    return get_success_data(api_client.create_member(payload, ADMIN))


def make_shipping_rule(**overrides):
    payload = create_shipping_state_rule_payload(**overrides)
    return get_success_data(api_client.create_shipping_state_rule(payload, ADMIN))


def get_member(member_id):
    return get_success_data(api_client.get_member(member_id, STAFF))


def get_order(order_id, headers=None):
    return get_success_data(api_client.get_order(order_id, headers or STAFF))


def get_event(event_id):
    return get_success_data(api_client.get_tasting_event(event_id, STAFF))


def get_lot(lot_id):
    return get_success_data(api_client.get_lot(lot_id, STAFF))


def get_sku(sku_id):
    return get_success_data(api_client.get_sku(sku_id, STAFF))


# ---------------------------------------------------------------------------
# Tier 1: state progression
# ---------------------------------------------------------------------------

def make_attested_member(attester_id="staff-attester-1", officer_key="compliance_officer_headers",
                         **member_overrides):
    """Register a member and walk UNVERIFIED -> PENDING_REVIEW -> ATTESTED.

    The approving officer's opaque user id differs from attested_by_user_id,
    satisfying the attestation segregation-of-duties rule (PRD §3.4).
    """
    member = make_member(**member_overrides)
    attestation = get_success_data(
        api_client.create_attestation(
            member["id"],
            create_attestation_payload(attested_by_user_id=attester_id),
            STAFF,
        )
    )
    get_success_data(
        api_client.approve_attestation(
            member["id"], attestation["id"], TEST_USERS[officer_key]
        )
    )
    return get_member(member["id"])


def make_published_event(sku_id=None, host=None, starts_at="2026-05-10T10:00:00Z",
                         ends_at="2026-05-10T12:00:00Z", **event_overrides):
    """Create a tasting event with one flight item and publish it (DRAFT -> PUBLISHED).

    Returns (event, host, sku). If sku_id is None, a STANDARD category + SKU +
    lot are created so publication's inventory reservation can proceed.
    """
    if sku_id is None:
        category = make_category()
        sku = make_sku(category["id"])
        make_lot(sku["id"], qty_received=50)
    else:
        sku = get_sku(sku_id)
    if host is None:
        host = make_member(date_of_birth="1980-01-01")
    payload = create_tasting_event_payload(
        host["id"], starts_at=starts_at, ends_at=ends_at, **event_overrides
    )
    event = get_success_data(api_client.create_tasting_event(payload, STAFF))
    get_success_data(
        api_client.add_flight_item(
            event["id"], create_flight_item_payload(sku["id"]), STAFF
        )
    )
    event = get_success_data(api_client.publish_tasting_event(event["id"], STAFF))
    return event, host, sku


def book_seat_for_member(event_id, member_id):
    """Book a seat against the event's current version (OCC-fresh)."""
    event = get_event(event_id)
    payload = book_seat_payload(member_id, event["version"])
    return get_success_data(
        api_client.book_seat(event_id, payload, make_member_headers(member_id))
    )


# ---------------------------------------------------------------------------
# Tier 2: order hierarchy
# ---------------------------------------------------------------------------

def create_draft_order(member_id, channel="RETAIL", ship_to_state_code=None,
                       loyalty_points_redeemed=None, applied_club_subscription_id=None):
    """Create an empty DRAFT order owned by member_id (Member self-call)."""
    overrides = {"channel": channel}
    if ship_to_state_code is not None:
        overrides["ship_to_state_code"] = ship_to_state_code
    if loyalty_points_redeemed is not None:
        overrides["loyalty_points_redeemed"] = loyalty_points_redeemed
    if applied_club_subscription_id is not None:
        overrides["applied_club_subscription_id"] = applied_club_subscription_id
    payload = create_order_payload(member_id, **overrides)
    return get_success_data(
        api_client.create_order(payload, make_member_headers(member_id))
    )


def add_line(order_id, member_id, sku_id, qty=1):
    payload = add_order_line_payload(sku_id, qty=qty)
    return get_success_data(
        api_client.add_order_line(
            order_id, payload, make_member_headers(member_id)
        )
    )


def fresh_order_version(order_id, member_id=None):
    headers = make_member_headers(member_id) if member_id else STAFF
    return get_order(order_id, headers)["version"]


def submit_order_fresh(order_id, member_id):
    """Submit with the order's current version (OCC-fresh)."""
    version = fresh_order_version(order_id, member_id)
    payload = submit_order_payload(version)
    return api_client.submit_order(
        order_id, payload, make_member_headers(member_id)
    )


def setup_submitted_order(member=None, sku=None, qty=1, channel="RETAIL",
                          ship_to_state_code=None, **order_kwargs):
    """Order walked to (AUTHORIZED, PICKING). Returns (order, member, sku).

    Creates member/sku/lot when not supplied. For DTC orders the caller is
    responsible for creating the destination state's ShippingStateRule.
    """
    if member is None:
        member = make_member()
    if sku is None:
        category = make_category()
        sku = make_sku(category["id"])
        make_lot(sku["id"], qty_received=50)
    order = create_draft_order(
        member["id"], channel=channel, ship_to_state_code=ship_to_state_code,
        **order_kwargs,
    )
    add_line(order["id"], member["id"], sku["id"], qty=qty)
    response = submit_order_fresh(order["id"], member["id"])
    order = validate_success(response, 200)
    return order, member, sku


def setup_packed_order(**kwargs):
    """Order walked to (AUTHORIZED, PACKED). Returns (order, member, sku)."""
    order, member, sku = setup_submitted_order(**kwargs)
    get_success_data(api_client.pack_order(order["id"], STAFF))
    return get_order(order["id"]), member, sku


def setup_shipped_order(delivered=False, **kwargs):
    """DTC order walked to SHIPPED (or DELIVERED when delivered=True).

    Returns (order, member, sku, shipment).
    """
    kwargs.setdefault("channel", "DTC")
    kwargs.setdefault("ship_to_state_code", "CA")
    order, member, sku = setup_packed_order(**kwargs)
    shipment = get_success_data(
        api_client.create_shipment(order["id"], create_shipment_payload(), STAFF)
    )
    if delivered:
        get_success_data(api_client.mark_shipment_in_transit(shipment["id"], STAFF))
        get_success_data(
            api_client.mark_shipment_out_for_delivery(shipment["id"], STAFF)
        )
        get_success_data(
            api_client.mark_shipment_delivered(
                shipment["id"], {"delivered_on": "2026-05-05"}, STAFF
            )
        )
        order = get_order(order["id"])
        shipment = get_success_data(api_client.get_shipment(shipment["id"], STAFF))
    return order, member, sku, shipment


# ---------------------------------------------------------------------------
# Tier 3: club subscription
# ---------------------------------------------------------------------------

def make_club_plan(**overrides):
    payload = create_club_plan_payload(**overrides)
    return get_success_data(api_client.create_club_plan(payload, ADMIN))


def subscribe_member(plan_id, member_id, started_on="2026-04-01", trial_days=0):
    """Subscribe with the plan's current version (OCC-fresh)."""
    plan = get_success_data(api_client.get_club_plan(plan_id, ADMIN))
    payload = create_club_subscription_payload(
        plan_id, member_id, plan["version"],
        started_on=started_on, trial_days=trial_days,
    )
    return get_success_data(
        api_client.create_club_subscription(payload, make_member_headers(member_id))
    )


# ---------------------------------------------------------------------------
# Tier 4: loyalty accumulation via tasting attendance
# ---------------------------------------------------------------------------

def award_points_via_seat(member_id, flight_price_cents, starts_at, ends_at,
                          in_session_clock, completed_clock):
    """Run one full tasting cycle that grants the member the seat award.

    Points are granted when the event reaches COMPLETED (PRD §3.5), so this
    helper drives the clock through IN_SESSION (check-in) and then past
    ends_at (completion). Returns the checked-in seat.
    """
    event, _host, _sku = make_published_event(
        starts_at=starts_at, ends_at=ends_at, flight_price_cents=flight_price_cents
    )
    seat = book_seat_for_member(event["id"], member_id)
    get_success_data(api_client.confirm_seat(seat["id"], make_member_headers(member_id)))
    set_clock(in_session_clock)
    get_success_data(api_client.check_in_seat(seat["id"], STAFF))
    set_clock(completed_clock)
    return get_success_data(api_client.get_seat(seat["id"], STAFF))


# ---------------------------------------------------------------------------
# Tier 5: special order lifecycle
# ---------------------------------------------------------------------------

def make_special_order(member_id, **overrides):
    payload = create_special_order_payload(member_id, **overrides)
    return get_success_data(
        api_client.create_special_order(payload, make_member_headers(member_id))
    )


def walk_special_order(special_order_id, resolved_sku_id,
                       approved_by_user_id="staff-approver-1", stop_at="FULFILLED"):
    """Walk a special order REQUESTED -> APPROVED -> SOURCED -> RECEIVED
    (-> FULFILLED). Each step uses the lenient validator; callers that only
    need an early stage pass stop_at."""
    get_success_data(
        api_client.approve_special_order(
            special_order_id,
            {"resolved_sku_id": resolved_sku_id,
             "approved_by_user_id": approved_by_user_id},
            STAFF,
        )
    )
    if stop_at == "APPROVED":
        return
    get_success_data(api_client.mark_special_order_sourced(special_order_id, STAFF))
    if stop_at == "SOURCED":
        return
    from .factories import receive_special_order_payload
    get_success_data(
        api_client.receive_special_order(
            special_order_id, receive_special_order_payload(), STAFF
        )
    )
    if stop_at == "RECEIVED":
        return
    get_success_data(api_client.fulfill_special_order(special_order_id, STAFF))
