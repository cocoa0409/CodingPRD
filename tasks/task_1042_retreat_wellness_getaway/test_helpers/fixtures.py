"""Composite setup helpers.

Every test runs against a freshly restarted server with an empty database, so
each helper builds its preconditions from scratch using only PRD-declared
endpoints. Helpers use get_success_data() (lenient) so setup failures surface as
clear "Setup failed" errors rather than confusing assertion failures.
"""
import uuid

from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_retreat_payload, create_room_payload, create_guest_payload,
    create_facilitator_payload, create_booking_payload, create_waiver_payload,
    create_activity_slot_payload, create_shuttle_payload,
    create_transport_segment_payload, create_addon_payload,
    create_booking_addon_payload,
)
from .test_users import TEST_USERS, make_guest_headers
from .constants import DEFAULT_CLOCK

_OP = TEST_USERS["operator_headers"]
_ANON = TEST_USERS["anonymous_headers"]


def _uniq_email(prefix="g"):
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------
def set_clock(api, to_iso8601=DEFAULT_CLOCK):
    return get_success_data(api.set_clock(to_iso8601, _OP))


# --------------------------------------------------------------------------
# Single-entity builders
# --------------------------------------------------------------------------
def new_retreat(api, **overrides):
    return get_success_data(api.create_retreat(create_retreat_payload(**overrides), _OP))


def new_room(api, retreat_id, **overrides):
    return get_success_data(api.create_room(create_room_payload(retreat_id, **overrides), _OP))


def new_guest(api, **overrides):
    if "email" not in overrides:
        overrides["email"] = _uniq_email()
    return get_success_data(api.create_guest(create_guest_payload(**overrides), _ANON))


def new_facilitator(api, **overrides):
    if "email" not in overrides:
        overrides["email"] = _uniq_email("f")
    return get_success_data(api.create_facilitator(create_facilitator_payload(**overrides), _OP))


def new_addon(api, **overrides):
    return get_success_data(api.create_addon(create_addon_payload(**overrides), _OP))


def new_shuttle(api, retreat_id, **overrides):
    return get_success_data(api.create_shuttle(create_shuttle_payload(retreat_id, **overrides), _OP))


def publish(api, retreat_id):
    return get_success_data(api.publish_retreat(retreat_id, _OP))


# --------------------------------------------------------------------------
# Published retreat + one lodging room
# --------------------------------------------------------------------------
def setup_published_retreat(api, *, retreat_overrides=None, room_overrides=None,
                            set_default_clock=True):
    """Clock->default, create retreat, add one LODGING room, publish.

    Returns dict: retreat (DRAFT create body), room, published (publish body,
    carrying the post-publish version), version (int).
    """
    if set_default_clock:
        set_clock(api, DEFAULT_CLOCK)
    retreat = new_retreat(api, **(retreat_overrides or {}))
    room = new_room(api, retreat["id"], **(room_overrides or {}))
    published = publish(api, retreat["id"])
    return {
        "retreat": retreat,
        "room": room,
        "published": published,
        "version": published["version"],
    }


# --------------------------------------------------------------------------
# Booking builders (guest ownership threaded via make_guest_headers)
# --------------------------------------------------------------------------
def setup_booking(api, *, party_size=2, retreat_overrides=None, room_overrides=None,
                  booking_overrides=None, guest_overrides=None, set_default_clock=True):
    """Published retreat + room + guest + one PENDING_DEPOSIT booking.

    Returns dict: retreat, room, published, version, guest, guest_headers, booking.
    """
    base = setup_published_retreat(
        api, retreat_overrides=retreat_overrides, room_overrides=room_overrides,
        set_default_clock=set_default_clock,
    )
    guest = new_guest(api, **(guest_overrides or {}))
    gh = make_guest_headers(guest["id"])
    payload = create_booking_payload(
        base["retreat"]["id"], guest["id"], base["room"]["id"],
        party_size, base["version"], **(booking_overrides or {}),
    )
    booking = get_success_data(api.create_booking(payload, gh))
    return {**base, "guest": guest, "guest_headers": gh, "booking": booking}


def pay_deposit(api, booking, guest_headers):
    return get_success_data(
        api.pay_deposit(booking["id"], booking["deposit_cents"], guest_headers))


def clear_waiver(api, booking_id, guest_headers, signature_name="Signer"):
    """Create -> sign -> operator-review(CLEAR) a waiver for a booking. Returns cleared waiver."""
    waiver = get_success_data(api.create_waiver(create_waiver_payload(booking_id), guest_headers))
    get_success_data(api.sign_waiver(waiver["id"], signature_name, guest_headers))
    return get_success_data(api.review_waiver(waiver["id"], "CLEAR", _OP))


def setup_booking_deposit_paid(api, *, party_size=2, **kwargs):
    """A booking taken to DEPOSIT_PAID. Returns the setup_booking dict updated with the paid booking."""
    ctx = setup_booking(api, party_size=party_size, **kwargs)
    ctx["booking"] = pay_deposit(api, ctx["booking"], ctx["guest_headers"])
    return ctx


def setup_booking_confirmed(api, *, party_size=2, **kwargs):
    """A booking taken to CONFIRMED (deposit + cleared waiver + balance).

    Returns the setup_booking dict updated with the confirmed booking and the cleared waiver.
    """
    ctx = setup_booking_deposit_paid(api, party_size=party_size, **kwargs)
    gh = ctx["guest_headers"]
    ctx["waiver"] = clear_waiver(api, ctx["booking"]["id"], gh)
    ctx["booking"] = get_success_data(
        api.pay_balance(ctx["booking"]["id"], ctx["booking"]["balance_due_cents"], gh))
    return ctx


# --------------------------------------------------------------------------
# Transport
# --------------------------------------------------------------------------
def book_transport_segment(api, booking_id, shuttle_id, guest_headers):
    return get_success_data(
        api.create_transport_segment(
            create_transport_segment_payload(booking_id, shuttle_id), guest_headers))


# --------------------------------------------------------------------------
# Add-ons
# --------------------------------------------------------------------------
def attach_addon(api, booking_id, addon_id, guest_headers):
    return get_success_data(
        api.create_booking_addon(
            create_booking_addon_payload(booking_id, addon_id), guest_headers))


# --------------------------------------------------------------------------
# Activity scheduling
# --------------------------------------------------------------------------
def setup_retreat_with_common_room_and_facilitator(api, *, retreat_overrides=None):
    """Clock->default, retreat, one COMMON room, one ACTIVE facilitator.

    Returns dict: retreat, common_room, facilitator.
    """
    set_clock(api, DEFAULT_CLOCK)
    retreat = new_retreat(api, **(retreat_overrides or {}))
    common_room = new_room(api, retreat["id"], kind="COMMON", bed_count=0, label="Hall")
    facilitator = new_facilitator(api)
    return {"retreat": retreat, "common_room": common_room, "facilitator": facilitator}


def new_slot(api, retreat_id, facilitator_id, room_id, start_dt, end_dt, **overrides):
    return get_success_data(
        api.create_activity_slot(
            create_activity_slot_payload(retreat_id, facilitator_id, room_id, start_dt, end_dt, **overrides),
            _OP))


# --------------------------------------------------------------------------
# Read helpers for entities that have no GET-by-id endpoint (Room, Shuttle).
# They are reachable only through their parent retreat's list endpoints.
# --------------------------------------------------------------------------
def get_room(api, retreat_id, room_id, headers=None):
    rooms = get_success_data(api.list_retreat_rooms(retreat_id, headers or _OP))
    for r in rooms:
        if r["id"] == room_id:
            return r
    raise AssertionError(f"Setup failed: room {room_id} not found under retreat {retreat_id}")


def get_shuttle(api, retreat_id, shuttle_id, headers=None):
    shuttles = get_success_data(api.list_retreat_shuttles(retreat_id, headers or _OP))
    for s in shuttles:
        if s["id"] == shuttle_id:
            return s
    raise AssertionError(f"Setup failed: shuttle {shuttle_id} not found under retreat {retreat_id}")
