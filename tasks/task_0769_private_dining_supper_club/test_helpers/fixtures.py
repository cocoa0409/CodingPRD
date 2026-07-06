"""
Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce clear
"Setup failed" style errors rather than confusing assertion failures. Every helper builds
its preconditions from scratch: the test harness restarts the server (empty DB) before each
test, so nothing is carried over.

Identity threading: bookings/waitlist calls act as the Guest that owns them, using
make_guest_headers(guest_id); all catalog/event lifecycle calls act as PlatformAdmin (the
operator superset that may perform any event/booking operation without ownership limits).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_series_payload, create_venue_payload, create_chef_payload,
    create_guest_payload, create_event_payload, create_menu_course_payload,
    create_booking_payload, create_waitlist_payload,
)
from .test_users import TEST_USERS, make_guest_headers

ADMIN = TEST_USERS["platform_admin_headers"]


# ─── Primitive creators ───────────────────────────────────────────────

def set_clock(iso: str):
    """Advance the logical clock to the given ISO-8601 instant (PlatformAdmin only)."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso}, ADMIN))


def create_series(**overrides) -> dict:
    return get_success_data(api_client.create_series(create_series_payload(**overrides), ADMIN))


def create_venue(**overrides) -> dict:
    return get_success_data(api_client.create_venue(create_venue_payload(**overrides), ADMIN))


def create_chef(**overrides) -> dict:
    return get_success_data(api_client.create_chef(create_chef_payload(**overrides), ADMIN))


def create_guest(**overrides) -> dict:
    return get_success_data(api_client.create_guest(create_guest_payload(**overrides), ADMIN))


def create_event(series_id, venue_id, chef_id, **overrides) -> dict:
    return get_success_data(api_client.create_event(
        create_event_payload(series_id, venue_id, chef_id, **overrides), ADMIN))


def add_menu_course(event_id, **overrides) -> dict:
    return get_success_data(api_client.create_menu_course(
        event_id, create_menu_course_payload(**overrides), ADMIN))


def schedule_event(event_id, head_table_count=None) -> dict:
    payload = {} if head_table_count is None else {"head_table_count": head_table_count}
    return get_success_data(api_client.schedule_event(event_id, payload, ADMIN))


def open_event(event_id) -> dict:
    return get_success_data(api_client.open_event(event_id, ADMIN))


def list_seats(event_id) -> list:
    return get_success_data(api_client.list_event_seats(event_id, ADMIN))


def book_seats(event_id, guest_id, seat_ids, party_size=None, **overrides) -> dict:
    """Create a booking acting as the owning guest."""
    return get_success_data(api_client.create_booking(
        create_booking_payload(event_id, guest_id, seat_ids, party_size, **overrides),
        make_guest_headers(guest_id)))


def pay_deposit(booking_id, guest_id, amount_cents) -> dict:
    return get_success_data(api_client.pay_deposit(
        booking_id, {"amount_cents": amount_cents}, make_guest_headers(guest_id)))


def join_waitlist(event_id, guest_id, party_size=1) -> dict:
    return get_success_data(api_client.join_waitlist(
        event_id, create_waitlist_payload(guest_id, party_size), make_guest_headers(guest_id)))


# ─── Tier 1/2: Event provisioning to a target lifecycle state ──────────

def provision_draft_event(event_overrides=None, series_overrides=None,
                          venue_overrides=None, chef_overrides=None):
    """Seed catalog + a DRAFT event. Returns a context dict."""
    series = create_series(**(series_overrides or {}))
    venue = create_venue(**(venue_overrides or {}))
    chef = create_chef(**(chef_overrides or {}))
    event = create_event(series["id"], venue["id"], chef["id"], **(event_overrides or {}))
    return {"series": series, "venue": venue, "chef": chef, "event": event}


def provision_scheduled_event(head_table_count=None, event_overrides=None, **kwargs):
    """DRAFT -> SCHEDULED (seats generated), no menu yet. Returns context dict with seats."""
    ctx = provision_draft_event(event_overrides=event_overrides, **kwargs)
    schedule_event(ctx["event"]["id"], head_table_count=head_table_count)
    ctx["seats"] = list_seats(ctx["event"]["id"])
    return ctx


def provision_open_event(head_table_count=None, menu_allergens=None,
                         event_overrides=None, **kwargs):
    """DRAFT -> SCHEDULED -> (add one menu course) -> OPEN. Returns context dict with seats."""
    ctx = provision_draft_event(event_overrides=event_overrides, **kwargs)
    schedule_event(ctx["event"]["id"], head_table_count=head_table_count)
    add_menu_course(ctx["event"]["id"],
                    contains_allergens=(menu_allergens if menu_allergens is not None else []))
    open_event(ctx["event"]["id"])
    ctx["seats"] = list_seats(ctx["event"]["id"])
    return ctx


# ─── Tier 3: Booking lifecycle shortcuts ───────────────────────────────

def provision_confirmed_booking(seat_count=1, seat_price_cents=10000, deposit_pct=0.25,
                                table_mode="COMMUNAL", event_overrides=None,
                                amount_cents=None, **kwargs):
    """
    Open event -> guest books `seat_count` seats -> pays the exact deposit (CONFIRMED).
    Returns (ctx, guest, booking). `amount_cents` overrides the paid deposit; when omitted
    the booking's computed deposit_due_cents is used.
    """
    ov = {"seat_capacity": seat_count, "seat_price_cents": seat_price_cents,
          "deposit_pct": deposit_pct, "table_mode": table_mode}
    ov.update(event_overrides or {})
    ctx = provision_open_event(event_overrides=ov, **kwargs)
    guest = create_guest()
    seat_ids = [s["id"] for s in ctx["seats"][:seat_count]]
    booking = book_seats(ctx["event"]["id"], guest["id"], seat_ids, party_size=seat_count)
    pay = amount_cents if amount_cents is not None else booking["deposit_due_cents"]
    booking = pay_deposit(booking["id"], guest["id"], pay)
    return ctx, guest, booking


def provision_pending_booking(seat_count=1, seat_price_cents=10000, deposit_pct=0.25,
                              table_mode="COMMUNAL", event_overrides=None, **kwargs):
    """Open event -> guest books `seat_count` seats (still PENDING_DEPOSIT, UNPAID)."""
    ov = {"seat_capacity": seat_count, "seat_price_cents": seat_price_cents,
          "deposit_pct": deposit_pct, "table_mode": table_mode}
    ov.update(event_overrides or {})
    ctx = provision_open_event(event_overrides=ov, **kwargs)
    guest = create_guest()
    seat_ids = [s["id"] for s in ctx["seats"][:seat_count]]
    booking = book_seats(ctx["event"]["id"], guest["id"], seat_ids, party_size=seat_count)
    return ctx, guest, booking


# ─── Read-back helpers ─────────────────────────────────────────────────

def get_event(event_id) -> dict:
    return get_success_data(api_client.get_event(event_id, ADMIN))


def get_booking(booking_id) -> dict:
    return get_success_data(api_client.get_booking(booking_id, ADMIN))


def get_waitlist_entry(entry_id) -> dict:
    return get_success_data(api_client.get_waitlist_entry(entry_id, ADMIN))


def get_seat_by_id(event_id, seat_id) -> dict:
    for s in list_seats(event_id):
        if s["id"] == seat_id:
            return s
    raise AssertionError(f"seat {seat_id} not found on event {event_id}")


def get_booking_payments(booking_id) -> list:
    return get_success_data(api_client.list_booking_payments(booking_id, ADMIN))
