"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce
clear "setup failed" errors, not confusing assertion failures.

Identity threading: a Customer is identity-backed. Any ownership-gated call
(create/pay/confirm/cancel a reservation, register attendees on it) uses
make_customer_headers(customer["id"]). Operational StudioManager / FrontDesk /
PlatformAdmin calls use the shared opaque headers.

OCC note: reservation create requires expected_event_version equal to the event's
current version, and each successful create bumps that version by one. Helpers
always read the event's fresh version immediately before a create so chained
creates never trip ERR_STALE_EVENT_VERSION accidentally.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_studio_payload, create_artist_payload, create_customer_payload,
    create_event_payload, create_assignment_payload, create_reservation_payload,
    create_attendee_payload, create_walk_in_payload, create_gift_card_payload,
    create_kit_batch_payload, credit_adjustment_payload, pay_payload,
)
from .test_users import TEST_USERS, make_customer_headers
from .constants import DEFAULT_CLOCK_UTC

MANAGER = TEST_USERS["manager_headers"]
FRONT_DESK = TEST_USERS["front_desk_headers"]
ADMIN = TEST_USERS["admin_headers"]


# ─── Tier 0: Clock + single-entity creators ────────────────────────────────

def set_clock(to_iso8601):
    """Drive the logical clock to an absolute UTC instant. Returns response data."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def reset_clock():
    """Reset the logical clock to the studio's documented startup default."""
    return set_clock(DEFAULT_CLOCK_UTC)


def create_studio(room_capacity_seats=30, name="Test Studio", **overrides):
    return get_success_data(api_client.create_studio(
        create_studio_payload(name=name, room_capacity_seats=room_capacity_seats, **overrides),
        MANAGER))


def create_artist(full_name="Test Artist", hourly_rate_cents=0, **overrides):
    return get_success_data(api_client.create_artist(
        create_artist_payload(full_name=full_name, hourly_rate_cents=hourly_rate_cents,
                              **overrides), MANAGER))


def create_customer(email="test@example.com", full_name="Test Customer", **overrides):
    return get_success_data(api_client.create_customer(
        create_customer_payload(email=email, full_name=full_name, **overrides), MANAGER))


def create_gift_card(code="GC-TEST", issued_value_cents=10000, **overrides):
    return get_success_data(api_client.create_gift_card(
        create_gift_card_payload(code=code, issued_value_cents=issued_value_cents,
                                 **overrides), MANAGER))


def create_draft_event(studio_id, **overrides):
    """Create a DRAFT event. Returns event dict."""
    return get_success_data(api_client.create_event(
        create_event_payload(studio_id, **overrides), MANAGER))


def assign_artist(event_id, artist_id):
    return get_success_data(api_client.create_assignment(
        create_assignment_payload(event_id, artist_id), MANAGER))


def grant_credit(customer_id, amount_cents, reason="grant"):
    return get_success_data(api_client.adjust_credit(
        customer_id, credit_adjustment_payload(amount_cents, reason), MANAGER))


# ─── Tier 1: Event state progression ───────────────────────────────────────

def create_open_event(room_capacity_seats=30, seats_capacity=10,
                      price_cents_per_seat=4500, studio_name="Open Studio",
                      artist_name="Open Artist", clock=DEFAULT_CLOCK_UTC,
                      **event_overrides):
    """Create studio + artist + event, staff it, schedule, and open it for booking.

    Returns (event_dict_open, studio_dict, artist_dict). The event is OPEN and its
    version reflects schedule + open bumps.
    """
    if clock is not None:
        set_clock(clock)
    studio = create_studio(room_capacity_seats=room_capacity_seats, name=studio_name)
    artist = create_artist(full_name=artist_name)
    event = create_draft_event(
        studio["id"], seats_capacity=seats_capacity,
        price_cents_per_seat=price_cents_per_seat, **event_overrides)
    assign_artist(event["id"], artist["id"])
    get_success_data(api_client.schedule_event(event["id"], MANAGER))
    opened = get_success_data(api_client.open_event(event["id"], MANAGER))
    return opened, studio, artist


def event_current_version(event_id):
    """Read the event's current version (fresh) for an OCC-safe create."""
    fresh = get_success_data(api_client.get_event(event_id, MANAGER))
    return fresh["version"]


# ─── Tier 2: Reservation creation against an OPEN event ─────────────────────

def book_reservation(event_id, customer_id, seats=1, booking_mode="PUBLIC",
                     include_supply_kit=False, expected_event_version=None):
    """Create a HELD reservation as the owning Customer. Reads the event's fresh
    version for the OCC check unless an explicit expected_event_version is given.

    Returns the reservation dict.
    """
    if expected_event_version is None:
        expected_event_version = event_current_version(event_id)
    payload = create_reservation_payload(
        event_id, customer_id, expected_event_version,
        booking_mode=booking_mode, seats=seats, include_supply_kit=include_supply_kit)
    return get_success_data(api_client.create_reservation(
        payload, make_customer_headers(customer_id)))


def setup_open_event_with_customer(room_capacity_seats=30, seats_capacity=10,
                                   price_cents_per_seat=4500, credit_cents=0,
                                   clock=DEFAULT_CLOCK_UTC, **event_overrides):
    """OPEN event + one registered customer (optionally pre-granted studio credit).

    Returns (event_dict_open, customer_dict).
    """
    event, _studio, _artist = create_open_event(
        room_capacity_seats=room_capacity_seats, seats_capacity=seats_capacity,
        price_cents_per_seat=price_cents_per_seat, clock=clock, **event_overrides)
    customer = create_customer(email=f"cust-{event['id'][:8]}@x.com")
    if credit_cents:
        grant_credit(customer["id"], credit_cents)
    return event, customer


def setup_held_reservation(seats=3, room_capacity_seats=30, seats_capacity=10,
                           price_cents_per_seat=4500, include_supply_kit=False,
                           clock=DEFAULT_CLOCK_UTC, **event_overrides):
    """OPEN event + customer + one HELD reservation.

    Returns (event_dict, customer_dict, reservation_dict).
    """
    event, customer = setup_open_event_with_customer(
        room_capacity_seats=room_capacity_seats, seats_capacity=seats_capacity,
        price_cents_per_seat=price_cents_per_seat, clock=clock, **event_overrides)
    res = book_reservation(event["id"], customer["id"], seats=seats,
                           include_supply_kit=include_supply_kit)
    return event, customer, res


# ─── Tier 3: Reservation lifecycle shortcuts ───────────────────────────────

def pay_reservation(reservation_id, customer_id, gift_card_ids=None,
                    use_studio_credit=False):
    return get_success_data(api_client.pay_reservation(
        reservation_id, pay_payload(gift_card_ids=gift_card_ids,
                                    use_studio_credit=use_studio_credit),
        make_customer_headers(customer_id)))


def confirm_reservation(reservation_id, customer_id):
    return get_success_data(api_client.confirm_reservation(
        reservation_id, make_customer_headers(customer_id)))


def add_attendees(reservation_id, customer_id, count, age_years=30, waiver_signed=False):
    """Add `count` attendee rows to a reservation. Returns list of attendee dicts."""
    out = []
    for i in range(count):
        att = get_success_data(api_client.create_attendee(
            create_attendee_payload(reservation_id, full_name=f"Attendee {i + 1}",
                                    age_years=age_years, waiver_signed=waiver_signed),
            make_customer_headers(customer_id)))
        out.append(att)
    return out


def setup_paid_reservation(seats=3, price_cents_per_seat=4500, room_capacity_seats=30,
                           seats_capacity=10, use_studio_credit=False, gift_card_ids=None,
                           credit_cents=0, clock=DEFAULT_CLOCK_UTC, **event_overrides):
    """OPEN event + customer + one PAID (still HELD) reservation.

    Returns (event_dict, customer_dict, reservation_dict_paid).
    """
    event, customer = setup_open_event_with_customer(
        room_capacity_seats=room_capacity_seats, seats_capacity=seats_capacity,
        price_cents_per_seat=price_cents_per_seat, credit_cents=credit_cents,
        clock=clock, **event_overrides)
    res = book_reservation(event["id"], customer["id"], seats=seats)
    paid = pay_reservation(res["id"], customer["id"], gift_card_ids=gift_card_ids,
                           use_studio_credit=use_studio_credit)
    return event, customer, paid


def setup_confirmed_reservation(seats=3, price_cents_per_seat=4500, room_capacity_seats=30,
                                seats_capacity=10, clock=DEFAULT_CLOCK_UTC, **event_overrides):
    """OPEN event + customer + one PAID + CONFIRMED reservation (CARD-paid).

    Returns (event_dict, customer_dict, reservation_dict_confirmed).
    """
    event, customer, paid = setup_paid_reservation(
        seats=seats, price_cents_per_seat=price_cents_per_seat,
        room_capacity_seats=room_capacity_seats, seats_capacity=seats_capacity,
        clock=clock, **event_overrides)
    confirmed = confirm_reservation(paid["id"], customer["id"])
    return event, customer, confirmed


def setup_checked_in_reservation(seats=2, price_cents_per_seat=4500,
                                 room_capacity_seats=30, seats_capacity=10,
                                 byob_allowed=False, min_age=0, attendee_age=30,
                                 waiver_signed=False, clock=DEFAULT_CLOCK_UTC,
                                 **event_overrides):
    """OPEN event + customer + a CHECKED_IN reservation with a full attendee roster.

    Returns (event_dict, customer_dict, reservation_dict_checked_in).
    """
    extra = dict(event_overrides)
    if byob_allowed:
        extra["byob_allowed"] = True
        extra["min_age"] = min_age
    event, customer, confirmed = setup_confirmed_reservation(
        seats=seats, price_cents_per_seat=price_cents_per_seat,
        room_capacity_seats=room_capacity_seats, seats_capacity=seats_capacity,
        clock=clock, **extra)
    add_attendees(confirmed["id"], customer["id"], seats,
                  age_years=attendee_age, waiver_signed=waiver_signed)
    checked = get_success_data(api_client.check_in_reservation(confirmed["id"], FRONT_DESK))
    return event, customer, checked


# ─── Tier 4: Two-event resource-overlap scaffolds ──────────────────────────

def create_studio_with_event(start_utc, end_utc, room_capacity_seats=10,
                             studio_name="Conflict Studio", seats_capacity=10):
    """Studio with one DRAFT event in a given window (no artist).

    Returns (studio_dict, event_dict).
    """
    studio = create_studio(room_capacity_seats=room_capacity_seats, name=studio_name)
    event = create_draft_event(studio["id"], seats_capacity=seats_capacity,
                               start_utc=start_utc, end_utc=end_utc)
    return studio, event
