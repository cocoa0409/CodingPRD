"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims in this PRD require the booking to be in a late lifecycle
stage (CONFIRMED, CHECKED_IN, CHECKED_OUT) which takes several API calls to reach:
create inn -> room -> guest -> booking -> cover the deposit (cash and/or gift
redemption) -> confirm -> (optionally) check-in -> check-out. These fixtures
encapsulate those preambles so tests focus on assertions.

Every helper uses get_success_data() (lenient validator) internally so setup
failures surface as clear "Setup step failed" errors rather than confusing
assertion mismatches. Each test starts against an empty database (the harness
restarts the server before every test), so every fixture builds its state from
scratch using only PRD-declared endpoints.

Identity threading: the Guest role is entity_backed. Any ownership-gated guest
call uses make_guest_headers(guest["id"]) with the real Guest id. Innkeeper is an
opaque operator, so Innkeeper-driven booking actions use the shared constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_inn_payload,
    create_room_payload,
    create_rate_period_payload,
    create_package_payload,
    create_guest_payload,
    create_gift_certificate_payload,
    create_booking_payload,
    create_breakfast_plan_payload,
    create_tax_remittance_payload,
)
from .test_users import (
    TEST_USERS,
    make_guest_headers,
)

INNKEEPER = TEST_USERS["innkeeper_headers"]
HOUSEKEEPER = TEST_USERS["housekeeper_headers"]
FINANCE = TEST_USERS["finance_headers"]


# ─── Clock helpers ───────────────────────────────────────────────────────────
def set_clock(iso8601: str):
    """Set the server logical clock (any role may; we use Innkeeper)."""
    return get_success_data(api_client.set_clock(iso8601, INNKEEPER))


# ─── Tier 1/2: base inventory ────────────────────────────────────────────────
def create_inn(**overrides) -> dict:
    """Create an inn as Innkeeper. Returns the inn entity."""
    return get_success_data(api_client.create_inn(create_inn_payload(**overrides), INNKEEPER))


def create_room(inn_id: str, **overrides) -> dict:
    """Create a room under an inn as Innkeeper."""
    return get_success_data(
        api_client.create_room(inn_id, create_room_payload(inn_id, **overrides), INNKEEPER)
    )


def create_rate_period(inn_id: str, start_date: str, end_date: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_rate_period(
            inn_id, create_rate_period_payload(inn_id, start_date, end_date, **overrides), INNKEEPER
        )
    )


def create_package(inn_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_package(inn_id, create_package_payload(inn_id, **overrides), INNKEEPER)
    )


def create_guest(inn_id: str, **overrides) -> dict:
    """Create a guest under an inn (as Innkeeper). Returns the guest entity whose
    id is used as X-User-ID for ownership-gated guest actions."""
    return get_success_data(
        api_client.create_guest(inn_id, create_guest_payload(inn_id, **overrides), INNKEEPER)
    )


def create_gift_certificate(inn_id: str, face_value_cents: int, **overrides) -> dict:
    """Issue a gift certificate as FinanceManager."""
    return get_success_data(
        api_client.create_gift_certificate(
            inn_id, create_gift_certificate_payload(inn_id, face_value_cents, **overrides), FINANCE
        )
    )


def setup_inn_room_guest(inn_overrides=None, room_overrides=None, guest_overrides=None):
    """Create inn + one room + one guest. Returns (inn, room, guest).

    The most common base for booking tests.
    """
    inn = create_inn(**(inn_overrides or {}))
    room = create_room(inn["id"], **(room_overrides or {}))
    guest = create_guest(inn["id"], **(guest_overrides or {}))
    return inn, room, guest


# ─── Booking creation ────────────────────────────────────────────────────────
def create_booking(inn_id, room_id, guest_id, checkin_date, checkout_date, as_guest=False, **overrides):
    """Create a PENDING booking. If as_guest is True the call is made by the guest
    (owner) using their entity-backed headers; otherwise by the Innkeeper."""
    headers = make_guest_headers(guest_id) if as_guest else INNKEEPER
    return get_success_data(
        api_client.create_booking(
            inn_id,
            create_booking_payload(inn_id, room_id, guest_id, checkin_date, checkout_date, **overrides),
            headers,
        )
    )


def cover_deposit_via_gift(inn_id, booking_id, gift_amount_cents, gift_face_cents=None):
    """Issue a gift cert and redeem gift_amount_cents toward the booking so its
    deposit is covered. Returns the gift certificate entity (pre-redemption).

    Used to drive bookings to a confirmable state without cash. The redemption
    carries the certificate's current version as the OCC guard.
    """
    face = gift_face_cents if gift_face_cents is not None else gift_amount_cents
    gift = create_gift_certificate(inn_id, face)
    get_success_data(
        api_client.redeem_gift(
            inn_id,
            booking_id,
            {
                "gift_certificate_id": gift["id"],
                "amount_cents": gift_amount_cents,
                "expected_gift_certificate_version": gift["version"],
            },
            INNKEEPER,
        )
    )
    return gift


def current_room_version(inn_id, room_id) -> int:
    room = get_success_data(api_client.get_room(inn_id, room_id, INNKEEPER))
    return room["version"]


def confirm_booking(inn_id, room_id, booking_id):
    """Confirm a booking using the room's current version. Returns the booking."""
    rv = current_room_version(inn_id, room_id)
    return get_success_data(
        api_client.confirm_booking(
            inn_id, booking_id, {"expected_room_version": rv}, INNKEEPER
        )
    )


# ─── Tier 3: full lifecycle shortcuts ────────────────────────────────────────
def setup_confirmed_booking(
    inn_overrides=None,
    room_overrides=None,
    booking_overrides=None,
    checkin_date="2026-05-10",
    checkout_date="2026-05-12",
    deposit_via_gift=20000,
    clock=None,
):
    """Full preamble to a CONFIRMED DIRECT booking with the deposit covered by a
    gift redemption.

    Steps: (optional clock) -> inn -> room -> guest -> booking -> gift redemption
    covering the deposit -> confirm. Returns (inn, room, guest, booking_confirmed,
    gift). The default base_rate (10000) with a 2-night stay and the default
    20000 gift fully covers a DIRECT deposit (first-night floor 10000).
    """
    if clock:
        set_clock(clock)
    inn, room, guest = setup_inn_room_guest(inn_overrides, room_overrides)
    booking = create_booking(
        inn["id"], room["id"], guest["id"], checkin_date, checkout_date,
        **(booking_overrides or {})
    )
    gift = cover_deposit_via_gift(inn["id"], booking["id"], deposit_via_gift)
    confirmed = confirm_booking(inn["id"], room["id"], booking["id"])
    return inn, room, guest, confirmed, gift


def setup_checked_out_booking(
    inn_overrides=None,
    room_overrides=None,
    checkin_date="2026-06-10",
    checkout_date="2026-06-12",
    checkin_clock="2026-06-10T16:00:00Z",
    checkout_clock="2026-06-12T11:00:00Z",
    open_clock="2026-06-01T00:00:00Z",
    deposit_via_gift=20000,
):
    """Drive a booking the whole way to CHECKED_OUT (which spawns a turnover task).

    Steps: set clock before checkin -> confirmed booking -> advance clock to/after
    checkin -> check-in -> advance clock to checkout -> check-out. Returns
    (inn, room, guest, booking_checked_out).
    """
    inn, room, guest, confirmed, _gift = setup_confirmed_booking(
        inn_overrides=inn_overrides,
        room_overrides=room_overrides,
        checkin_date=checkin_date,
        checkout_date=checkout_date,
        deposit_via_gift=deposit_via_gift,
        clock=open_clock,
    )
    set_clock(checkin_clock)
    get_success_data(api_client.check_in(inn["id"], confirmed["id"], INNKEEPER))
    set_clock(checkout_clock)
    checked_out = get_success_data(api_client.check_out(inn["id"], confirmed["id"], INNKEEPER))
    return inn, room, guest, checked_out


def get_turnover_task(inn_id, booking_id):
    """Return the single HousekeepingTask spawned for a booking, or None."""
    data, _meta = _list(api_client.list_housekeeping_tasks(inn_id, INNKEEPER, params={"booking_id": booking_id}))
    return data[0] if data else None


# ─── Tier 4: breakfast plans ─────────────────────────────────────────────────
def create_breakfast_plan(inn_id, booking_id, party_size, guest_id, **overrides):
    """Request a breakfast plan as the booking's owning guest. Returns the plan."""
    return get_success_data(
        api_client.create_breakfast_plan(
            inn_id,
            create_breakfast_plan_payload(booking_id, party_size, **overrides),
            make_guest_headers(guest_id),
        )
    )


def setup_pending_booking_with_breakfast(party_size=2, dietary_flags=None, max_occupancy=3):
    """A PENDING booking (never confirmed) with a REQUESTED breakfast plan.
    Returns (inn, room, guest, booking, plan)."""
    inn, room, guest = setup_inn_room_guest(room_overrides={"max_occupancy": max_occupancy})
    booking = create_booking(
        inn["id"], room["id"], guest["id"], "2026-05-10", "2026-05-12", guest_count=2
    )
    overrides = {}
    if dietary_flags is not None:
        overrides["dietary_flags"] = dietary_flags
    plan = create_breakfast_plan(inn["id"], booking["id"], party_size, guest["id"], **overrides)
    return inn, room, guest, booking, plan


# ─── Tier 5: tax remittance ──────────────────────────────────────────────────
def open_remittance(inn_id, period_start, period_end, variant):
    return get_success_data(
        api_client.create_tax_remittance(
            inn_id, create_tax_remittance_payload(inn_id, period_start, period_end, variant), FINANCE
        )
    )


# ─── internal ────────────────────────────────────────────────────────────────
def _list(response):
    """Lenient list extraction returning (data, meta)."""
    if not (200 <= response.status_code < 300):
        get_success_data(response)  # raises with a clear message
    body = response.json()
    return body["data"], body["meta"]
