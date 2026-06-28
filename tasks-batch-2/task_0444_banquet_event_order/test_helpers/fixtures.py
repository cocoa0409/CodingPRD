"""Composite setup helpers for the Banquet Event Order API.

These encapsulate the multi-step API-call preambles that the design-index test
recipes share, so test bodies focus on the trigger + assertions. All setup calls
use get_success_data() (lenient 2xx) so a broken precondition surfaces as a clear
"Setup step failed" error.

All four roles are opaque (PRD §2.1): the shared role-constant headers are the
canonical form for every call; no entity-backed ownership threading is required.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_function_room_payload, create_hotel_room_block_payload,
    create_event_payload, create_booking_payload, create_menu_line_payload,
    create_service_line_payload, create_room_block_link_payload,
    create_payment_schedule_item_payload, create_payment_payload,
)
from .test_users import TEST_USERS

_ADMIN = TEST_USERS["platform_admin_headers"]
_SALES = TEST_USERS["sales_manager_headers"]
_CAPTAIN = TEST_USERS["banquet_captain_headers"]
_CLERK = TEST_USERS["accounting_clerk_headers"]


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str) -> dict:
    """Set the server logical clock (PlatformAdmin)."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, _ADMIN))


# ---------------------------------------------------------------------------
# Shared inventory primitives
# ---------------------------------------------------------------------------
def create_function_room(**overrides) -> dict:
    """POST /function-rooms as PlatformAdmin."""
    return get_success_data(api_client.create_function_room(create_function_room_payload(**overrides), _ADMIN))


def create_hotel_room_block(**overrides) -> dict:
    """POST /hotel-room-blocks as PlatformAdmin."""
    return get_success_data(api_client.create_hotel_room_block(create_hotel_room_block_payload(**overrides), _ADMIN))


def get_block(block_id) -> dict:
    return get_success_data(api_client.get_hotel_room_block(block_id, _ADMIN))


# ---------------------------------------------------------------------------
# Event primitives
# ---------------------------------------------------------------------------
def create_event(**overrides) -> dict:
    """POST /events as SalesManager. Returns the created event (status INQUIRY)."""
    return get_success_data(api_client.create_event(create_event_payload(**overrides), _SALES))


def get_event(event_id) -> dict:
    return get_success_data(api_client.get_event(event_id, _SALES))


def get_event_version(event_id) -> int:
    return get_event(event_id)["version"]


def create_booking(event_id, room_id, start_utc, end_utc, expected_event_version, **overrides) -> dict:
    """POST /events/{id}/bookings as SalesManager (OCC-guarded)."""
    payload = create_booking_payload(room_id, start_utc, end_utc, expected_event_version, **overrides)
    return get_success_data(api_client.create_booking(event_id, payload, _SALES))


def make_definite(event_id, booking_id) -> dict:
    return get_success_data(api_client.make_definite(event_id, booking_id, _SALES))


def add_menu_line(event_id, **overrides) -> dict:
    return get_success_data(api_client.create_menu_line(event_id, create_menu_line_payload(**overrides), _SALES))


def add_service_line(event_id, **overrides) -> dict:
    return get_success_data(api_client.create_service_line(event_id, create_service_line_payload(**overrides), _SALES))


def add_schedule_item(event_id, amount_due_cents, **overrides) -> dict:
    payload = create_payment_schedule_item_payload(amount_due_cents, **overrides)
    return get_success_data(api_client.create_payment_schedule_item(event_id, payload, _CLERK))


def record_payment(event_id, amount_cents, expected_event_version, **overrides) -> dict:
    """POST /events/{id}/payments as AccountingClerk (OCC-guarded). Reads version from caller."""
    payload = create_payment_payload(amount_cents, expected_event_version, **overrides)
    return get_success_data(api_client.create_payment(event_id, payload, _CLERK))


def create_room_block_link(event_id, block_id, rooms_reserved, check_in_date, check_out_date,
                           as_role="SALES", **overrides) -> dict:
    """POST /events/{id}/room-block-links. SalesManager or AccountingClerk may create."""
    headers = _CLERK if as_role == "CLERK" else _SALES
    payload = create_room_block_link_payload(block_id, check_in_date, check_out_date, rooms_reserved, **overrides)
    return get_success_data(api_client.create_room_block_link(event_id, payload, headers))


# ---------------------------------------------------------------------------
# Tier 1: state-progression shortcuts
# ---------------------------------------------------------------------------
def setup_event_with_hold_booking(event_overrides=None, room_overrides=None,
                                  start_utc="2026-09-10T18:00:00Z",
                                  end_utc="2026-09-10T22:00:00Z"):
    """INQUIRY event + one room + one HOLD booking. Returns (event, room, booking).

    The event is left in INQUIRY (no hold placed). The booking sits in HOLD.
    """
    room = create_function_room(**(room_overrides or {}))
    event = create_event(**(event_overrides or {}))
    booking = create_booking(event["id"], room["id"], start_utc, end_utc, event["version"])
    return event, room, booking


def setup_tentative_event_with_hold_booking(event_overrides=None, room_overrides=None,
                                            start_utc="2026-09-10T18:00:00Z",
                                            end_utc="2026-09-10T22:00:00Z"):
    """TENTATIVE event (hold placed) with one booking still in HOLD.
    Returns (event_after_hold, room, booking)."""
    event, room, booking = setup_event_with_hold_booking(
        event_overrides=event_overrides, room_overrides=room_overrides,
        start_utc=start_utc, end_utc=end_utc,
    )
    held = get_success_data(api_client.hold_event(event["id"], _SALES))
    return held, room, booking


def setup_tentative_event_with_definite_booking(event_overrides=None, room_overrides=None,
                                                start_utc="2026-09-10T18:00:00Z",
                                                end_utc="2026-09-10T22:00:00Z"):
    """TENTATIVE event with its single booking made DEFINITE.
    Returns (event_after_hold, room, booking_definite)."""
    held, room, booking = setup_tentative_event_with_hold_booking(
        event_overrides=event_overrides, room_overrides=room_overrides,
        start_utc=start_utc, end_utc=end_utc,
    )
    definite = make_definite(held["id"], booking["id"])
    return held, room, definite


def setup_definite_event(event_overrides=None, room_overrides=None,
                         start_utc="2026-09-10T18:00:00Z",
                         end_utc="2026-09-10T22:00:00Z",
                         menu_lines=None):
    """DEFINITE event: booking made definite, then confirm-space.
    Optionally seeds menu lines BEFORE confirm-space.
    Returns (event_definite, room, booking)."""
    held, room, booking = setup_tentative_event_with_hold_booking(
        event_overrides=event_overrides, room_overrides=room_overrides,
        start_utc=start_utc, end_utc=end_utc,
    )
    for ml in (menu_lines or []):
        add_menu_line(held["id"], **ml)
    definite_booking = make_definite(held["id"], booking["id"])
    event_definite = get_success_data(api_client.confirm_space(held["id"], _SALES))
    return event_definite, room, definite_booking


# ---------------------------------------------------------------------------
# Tier 3: deposit-settling + guarantee lifecycle
# ---------------------------------------------------------------------------
def settle_deposit(event_id, deposit_amount_cents):
    """Create the deposit milestone (sequence_no 1) and pay it in full so it settles.
    Reads the live event version before paying (OCC). Returns the deposit item."""
    item = add_schedule_item(event_id, deposit_amount_cents, label="Deposit")
    version = get_event_version(event_id)
    record_payment(event_id, deposit_amount_cents, version, method="WIRE")
    return item


def setup_confirmed_event(event_overrides=None, room_overrides=None,
                          start_utc="2026-09-10T18:00:00Z",
                          end_utc="2026-09-10T22:00:00Z",
                          menu_lines=None, guarantee_count=120,
                          deposit_amount_cents=500000):
    """Full walk to CONFIRMED: DEFINITE event -> settle deposit -> lock-guarantee.
    Returns (event_confirmed, room, booking, menu_line_ids).

    menu_lines is a list of create_menu_line_payload override dicts seeded before
    confirm-space; their created ids are returned in order."""
    held, room, booking = setup_tentative_event_with_hold_booking(
        event_overrides=event_overrides, room_overrides=room_overrides,
        start_utc=start_utc, end_utc=end_utc,
    )
    menu_line_ids = []
    for ml in (menu_lines or []):
        created = add_menu_line(held["id"], **ml)
        menu_line_ids.append(created["id"])
    definite_booking = make_definite(held["id"], booking["id"])
    get_success_data(api_client.confirm_space(held["id"], _SALES))
    settle_deposit(held["id"], deposit_amount_cents)
    confirmed = get_success_data(
        api_client.lock_guarantee(held["id"], {"guarantee_count": guarantee_count}, _CAPTAIN)
    )
    return confirmed, room, definite_booking, menu_line_ids


def setup_completed_event(event_overrides=None, room_overrides=None,
                          start_utc="2026-09-10T18:00:00Z",
                          end_utc="2026-09-10T22:00:00Z",
                          menu_lines=None, guarantee_count=120,
                          actual_attendance=140, deposit_amount_cents=500000):
    """Full walk to COMPLETED: CONFIRMED event -> actualize.
    Returns (event_completed, room, booking, menu_line_ids)."""
    confirmed, room, booking, menu_line_ids = setup_confirmed_event(
        event_overrides=event_overrides, room_overrides=room_overrides,
        start_utc=start_utc, end_utc=end_utc, menu_lines=menu_lines,
        guarantee_count=guarantee_count, deposit_amount_cents=deposit_amount_cents,
    )
    completed = get_success_data(
        api_client.actualize_event(confirmed["id"], {"actual_attendance": actual_attendance}, _CAPTAIN)
    )
    return completed, room, booking, menu_line_ids


# ---------------------------------------------------------------------------
# Tier 2: an existing DEFINITE booking on a shared room (for overlap tests)
# ---------------------------------------------------------------------------
def setup_existing_definite_booking_on_room(room_id_or_overrides,
                                            a_start="2027-04-01T18:00:00Z",
                                            a_end="2027-04-01T22:00:00Z",
                                            event_overrides=None):
    """Create event A on a given room with one DEFINITE booking on [a_start, a_end].
    Accepts either a room id (str) or a dict of room overrides (then creates the room).
    Returns (room_id, event_a, booking_a)."""
    if isinstance(room_id_or_overrides, str):
        room_id = room_id_or_overrides
    else:
        room = create_function_room(**(room_id_or_overrides or {}))
        room_id = room["id"]
    event_a = create_event(**(event_overrides or {"account_name": "Existing A"}))
    booking_a = create_booking(event_a["id"], room_id, a_start, a_end, event_a["version"])
    get_success_data(api_client.hold_event(event_a["id"], _SALES))
    make_definite(event_a["id"], booking_a["id"])
    return room_id, event_a, booking_a


# ---------------------------------------------------------------------------
# Tier 5: cancelled / terminal events
# ---------------------------------------------------------------------------
def setup_cancelled_event(event_overrides=None) -> dict:
    """Create an INQUIRY event and cancel it. Returns the cancelled event."""
    event = create_event(**(event_overrides or {}))
    return get_success_data(api_client.cancel_event(event["id"], _SALES))
