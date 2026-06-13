"""Composite setup helpers for multi-step Kids Venue Booking test prerequisites.

Most interesting claims require the system to be in a specific state reached only
after 5-15 API calls (configure venue/room/package/staff, open a booking, hold it,
sign waivers, take a deposit, assign a host, confirm, complete, etc.). These helpers
encapsulate those sequences so individual tests focus on their assertions.

All helpers use get_success_data() (lenient validator) so a broken precondition
surfaces as a clear "setup failed" rather than a confusing assertion failure.
The server starts from an empty database before every test, so each helper builds
all of its preconditions from scratch using only PRD-declared endpoints.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_venue_payload, create_room_payload, create_package_payload,
    create_staff_member_payload, create_booking_payload, create_add_on_payload,
    create_waiver_payload, create_staff_assignment_payload, create_payment_payload,
    create_guest_party_payload, set_clock_payload, DEFAULTS,
)
from .test_users import TEST_USERS

VM = TEST_USERS["venue_manager_headers"]
COORD = TEST_USERS["coordinator_headers"]
FIN = TEST_USERS["finance_clerk_headers"]

# A clock anchor comfortably before the default event window so that
# reschedule-lead / weather-hold / cancellation timing rules are exercisable.
CLOCK_BASE_UTC = DEFAULTS["CLOCK_BASE_UTC"]              # 2026-06-25T09:00:00Z
DEFAULT_EVENT_START = DEFAULTS["EVENT_START_UTC"]        # 2026-07-01T10:00:00Z


# ─── Clock ────────────────────────────────────────────────────────────────────

def set_clock(to_iso8601: str):
    """Set the server logical clock. Returns the SystemClock data."""
    return get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), COORD))


def reset_clock_base():
    """Anchor the clock at the standard pre-event instant."""
    return set_clock(CLOCK_BASE_UTC)


# ─── Tier 2: Configuration peers ───────────────────────────────────────────────

def create_venue(weather_dependent=False, **overrides):
    res = api_client.create_venue(
        create_venue_payload(weather_dependent=weather_dependent, **overrides), VM)
    return get_success_data(res)


def create_room(venue_id, **overrides):
    res = api_client.create_room(create_room_payload(venue_id, **overrides), VM)
    return get_success_data(res)


def create_package(venue_id, **overrides):
    res = api_client.create_package(create_package_payload(venue_id, **overrides), VM)
    return get_success_data(res)


def create_staff(venue_id, full_name, skills, **overrides):
    res = api_client.create_staff_member(
        create_staff_member_payload(venue_id, full_name=full_name, skills=skills, **overrides), VM)
    return get_success_data(res)


def setup_config(
    weather_dependent=False,
    room_kind="INDOOR",
    max_capacity=20,
    buffer_minutes=30,
    base_price_cents=30000,
    included_children=8,
    per_extra_child_cents=1500,
    base_duration_minutes=120,
    deposit_pct=0.25,
    set_base_clock=True,
):
    """Create a venue + room + package and (optionally) anchor the clock.

    Returns (venue, room, package). Staff are created on demand by other helpers.
    """
    venue = create_venue(weather_dependent=weather_dependent)
    room_kwargs = {"max_capacity": max_capacity, "buffer_minutes": buffer_minutes}
    if room_kind != "INDOOR":
        room_kwargs["room_kind"] = room_kind
    room = create_room(venue["id"], **room_kwargs)
    package = create_package(
        venue["id"],
        base_price_cents=base_price_cents,
        included_children=included_children,
        per_extra_child_cents=per_extra_child_cents,
        base_duration_minutes=base_duration_minutes,
        deposit_pct=deposit_pct,
    )
    if set_base_clock:
        reset_clock_base()
    return venue, room, package


# ─── Tier 1: Booking state progression ─────────────────────────────────────────

def create_quote_draft_booking(room_id, package_id, children_count=8,
                               event_start_utc=DEFAULT_EVENT_START, headers=COORD, **overrides):
    """Open a booking in QUOTE_DRAFT. Returns the booking data."""
    res = api_client.create_booking(
        create_booking_payload(room_id, package_id, children_count=children_count,
                               event_start_utc=event_start_utc, **overrides),
        headers)
    return get_success_data(res)


def hold_booking(booking_id):
    return get_success_data(api_client.hold_booking(booking_id, COORD))


def add_addon(booking_id, kind, unit_price_cents, **overrides):
    res = api_client.create_add_on(
        booking_id, create_add_on_payload(kind, unit_price_cents, **overrides), COORD)
    return get_success_data(res)


def add_waiver(booking_id, child_name="c1", signature="sig"):
    res = api_client.create_waiver(
        booking_id, create_waiver_payload(child_name=child_name, guardian_signature=signature), COORD)
    return get_success_data(res)


def sign_waiver(booking_id, waiver_id, signature="sig"):
    res = api_client.sign_waiver(booking_id, waiver_id, {"guardian_signature": signature}, COORD)
    return get_success_data(res)


def assign_staff(booking_id, staff_member_id, role_on_event):
    res = api_client.create_staff_assignment(
        booking_id, create_staff_assignment_payload(staff_member_id, role_on_event), COORD)
    return get_success_data(res)


def take_payment(booking_id, amount_cents, direction="CHARGE", purpose="BALANCE"):
    res = api_client.create_payment(
        booking_id, create_payment_payload(direction, amount_cents, purpose=purpose), FIN)
    return get_success_data(res)


def record_roster(booking_id, children_delta=0, adults_delta=0, reason="ADJUSTMENT"):
    payload = create_guest_party_payload(children_delta=children_delta,
                                         adults_delta=adults_delta, reason=reason)
    res = api_client.create_guest_party(booking_id, payload, COORD)
    return get_success_data(res)


def sign_n_waivers(booking_id, n):
    """Create and sign n waivers on a (HELD/CONFIRMED-class) booking. Returns waiver ids."""
    ids = []
    for i in range(n):
        w = add_waiver(booking_id, child_name=f"c{i + 1}")
        sign_waiver(booking_id, w["id"])
        ids.append(w["id"])
    return ids


# ─── Tier 3: Full lifecycle shortcuts ──────────────────────────────────────────

def create_held_booking(children_count=8, deposit_pct=0.25, max_capacity=20,
                        buffer_minutes=30, base_price_cents=30000, included_children=8,
                        event_start_utc=DEFAULT_EVENT_START, weather_dependent=False,
                        room_kind="INDOOR"):
    """Configure + open + hold a booking. Returns (venue, room, package, booking)."""
    venue, room, package = setup_config(
        weather_dependent=weather_dependent, room_kind=room_kind, max_capacity=max_capacity,
        buffer_minutes=buffer_minutes, base_price_cents=base_price_cents,
        included_children=included_children, deposit_pct=deposit_pct)
    booking = create_quote_draft_booking(room["id"], package["id"],
                                         children_count=children_count,
                                         event_start_utc=event_start_utc)
    booking = hold_booking(booking["id"])
    return venue, room, package, booking


def create_confirmed_booking(
    children_count=8,
    deposit_pct=0.25,
    base_price_cents=30000,
    included_children=8,
    per_extra_child_cents=1500,
    addons=None,                # list of (kind, unit_price_cents[, extra_minutes/quantity dict])
    pay_amount=None,            # amount charged before confirm; defaults to full quote
    event_start_utc=DEFAULT_EVENT_START,
    weather_dependent=False,
    room_kind="INDOOR",
    max_capacity=20,
    buffer_minutes=30,
):
    """Drive a booking all the way to CONFIRMED.

    Sequence: configure -> create -> add add-ons -> hold -> assign HOST (and the
    ENTERTAINER/COOK any active add-on requires) -> create+sign one waiver per child
    -> charge deposit/balance -> confirm.

    Returns a dict with venue, room, package, booking, staff (by role), waiver_ids.
    """
    venue, room, package = setup_config(
        weather_dependent=weather_dependent, room_kind=room_kind, max_capacity=max_capacity,
        buffer_minutes=buffer_minutes, base_price_cents=base_price_cents,
        included_children=included_children, per_extra_child_cents=per_extra_child_cents,
        deposit_pct=deposit_pct)

    booking = create_quote_draft_booking(room["id"], package["id"],
                                         children_count=children_count,
                                         event_start_utc=event_start_utc)
    bid = booking["id"]

    addons = addons or []
    need_entertainer = False
    need_cook = False
    for spec in addons:
        kind, price = spec[0], spec[1]
        extra = spec[2] if len(spec) > 2 else {}
        add_addon(bid, kind, price, **extra)
        if kind == "CHARACTER":
            need_entertainer = True
        elif kind == "CAKE":
            need_cook = True

    booking = hold_booking(bid)

    staff = {}
    host = create_staff(venue["id"], "Host H", ["HOST"])
    staff["HOST"] = assign_staff(bid, host["id"], "HOST")
    if need_entertainer:
        ent = create_staff(venue["id"], "Ent E", ["ENTERTAINER"])
        staff["ENTERTAINER"] = assign_staff(bid, ent["id"], "ENTERTAINER")
    if need_cook:
        cook = create_staff(venue["id"], "Cook C", ["COOK"])
        staff["COOK"] = assign_staff(bid, cook["id"], "COOK")

    waiver_ids = sign_n_waivers(bid, children_count)

    booking = get_success_data(api_client.get_booking(bid, COORD))
    if pay_amount is None:
        pay_amount = booking["quote_total_cents"]
    if pay_amount > 0:
        take_payment(bid, pay_amount, direction="CHARGE", purpose="BALANCE")

    booking = get_success_data(api_client.confirm_booking(bid, COORD))
    return {
        "venue": venue, "room": room, "package": package,
        "booking": booking, "staff": staff, "waiver_ids": waiver_ids,
    }


def create_completed_booking(children_count=8, base_price_cents=30000,
                            included_children=8, event_start_utc=DEFAULT_EVENT_START,
                            post_event_clock="2026-07-01T13:00:00Z", pay_amount=None):
    """Drive a booking to COMPLETED (advances the clock past event_end and completes).

    Returns the create_confirmed_booking dict with booking replaced by the COMPLETED one.
    """
    ctx = create_confirmed_booking(
        children_count=children_count, base_price_cents=base_price_cents,
        included_children=included_children, event_start_utc=event_start_utc,
        pay_amount=pay_amount)
    set_clock(post_event_clock)
    ctx["booking"] = get_success_data(api_client.complete_booking(ctx["booking"]["id"], COORD))
    return ctx


def create_weather_held_booking(children_count=8, event_start_utc=DEFAULT_EVENT_START,
                               deposit_only=True):
    """Drive a weather-eligible booking (OUTDOOR room, weather_dependent venue) to
    WEATHER_HOLD with the clock still before event_start.

    Returns the create_confirmed_booking dict with booking replaced by the WEATHER_HOLD one.
    Pays only the deposit by default (booking with no add-ons: quote 30000, deposit 7500).
    """
    pay = 7500 if deposit_only else None
    ctx = create_confirmed_booking(
        children_count=children_count, event_start_utc=event_start_utc,
        weather_dependent=True, room_kind="OUTDOOR", pay_amount=pay)
    ctx["booking"] = get_success_data(
        api_client.weather_hold_booking(ctx["booking"]["id"], COORD))
    return ctx
