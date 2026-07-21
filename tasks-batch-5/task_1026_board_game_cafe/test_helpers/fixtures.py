"""Composite setup helpers.

Every helper takes the ApiClient as its first argument and builds its
preconditions from scratch using only PRD-declared endpoints, because the
server database is empty at the start of each test. Helpers use
get_success_data() (lenient) so setup failures surface as clear errors.

Role-header conventions:
- Manager and Staff are opaque; the shared TEST_USERS constants are used.
- Member is entity_backed; ownership-gated calls thread
  make_member_headers(membership["id"]).
"""
from prd_bench_local_runner.testing import get_success_data
from .test_users import TEST_USERS, make_member_headers
from . import factories as F

_MGR = TEST_USERS["manager_headers"]
_STAFF = TEST_USERS["staff_headers"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def set_clock(api, iso_ts):
    """Set the logical clock (Manager only)."""
    return get_success_data(api.set_clock(iso_ts, headers=_MGR))


# ---------------------------------------------------------------------------
# Simple entity creators
# ---------------------------------------------------------------------------
def create_table(api, **overrides):
    """Create a table (Manager). Returns the table dict."""
    return get_success_data(api.create_table(F.create_table_payload(**overrides), headers=_MGR))


def create_membership(api, **overrides):
    """Create a membership (Staff). Returns the membership dict."""
    return get_success_data(
        api.create_membership(F.create_membership_payload(**overrides), headers=_STAFF)
    )


def grant_loyalty(api, membership_id, points_delta, reason="grant"):
    """Post a positive/negative loyalty adjustment (Manager). Returns the membership."""
    return get_success_data(
        api.loyalty_adjustment(
            membership_id, {"points_delta": points_delta, "reason": reason}, headers=_MGR
        )
    )


def create_game_copy(api, barcode, **overrides):
    """Create a library game copy (Manager). Returns the game copy dict."""
    return get_success_data(
        api.create_game_copy(F.create_game_copy_payload(barcode, **overrides), headers=_MGR)
    )


def create_room(api, **overrides):
    """Create a private room (Manager). Returns the room dict (carries version)."""
    return get_success_data(api.create_room(F.create_room_payload(**overrides), headers=_MGR))


def create_tournament(api, **overrides):
    """Create a tournament (Manager). Returns the tournament dict."""
    return get_success_data(
        api.create_tournament(F.create_tournament_payload(**overrides), headers=_MGR)
    )


def create_open_tournament(api, **overrides):
    """Create a tournament and move it to OPEN. Returns the OPEN tournament dict."""
    trn = create_tournament(api, **overrides)
    return get_success_data(api.open_tournament(trn["id"], headers=_MGR))


# ---------------------------------------------------------------------------
# Reservations
# ---------------------------------------------------------------------------
def create_reservation(api, table_id, start_at, end_at, headers=None, **overrides):
    """Book a table for a window (Staff by default). Returns the reservation dict."""
    return get_success_data(
        api.create_reservation(
            F.create_reservation_payload(table_id, start_at, end_at, **overrides),
            headers=headers or _STAFF,
        )
    )


def seat(api, reservation_id, **payload):
    """Seat a booked reservation (Staff). Returns the seated reservation dict."""
    return get_success_data(
        api.seat_reservation(reservation_id, headers=_STAFF, payload=payload or {})
    )


def add_fnb(api, reservation_id, total_cents, description="Snacks"):
    """Add an F&B line to a seated session (Staff). Returns the F&B order dict."""
    return get_success_data(
        api.create_fnb_order(
            F.create_fnb_order_payload(reservation_id, total_cents, description=description),
            headers=_STAFF,
        )
    )


def create_seated_reservation(
    api,
    *,
    table_id,
    start_at,
    end_at,
    seated_at,
    booking_clock,
    party_size=2,
    membership_id=None,
    deposit_cents=0,
):
    """Book a reservation at `booking_clock`, then advance the clock to `seated_at`
    and seat the party. Returns the seated reservation dict.

    This is the shared preamble for the bill/close, checkout, and library tests
    (they all need a SEATED session at a known seated_at)."""
    set_clock(api, booking_clock)
    overrides = {"party_size": party_size, "deposit_cents": deposit_cents}
    if membership_id is not None:
        overrides["membership_id"] = membership_id
    resv = create_reservation(api, table_id, start_at, end_at, **overrides)
    set_clock(api, seated_at)
    return seat(api, resv["id"])


# ---------------------------------------------------------------------------
# Library
# ---------------------------------------------------------------------------
def create_checkout(api, game_copy_id, reservation_id):
    """Lend a copy to a seated session (Staff). Returns the checkout dict."""
    return get_success_data(
        api.create_checkout(
            F.create_checkout_payload(game_copy_id, reservation_id), headers=_STAFF
        )
    )


def setup_seated_session_with_checkout(api, *, barcode, condition="GOOD", replacement_value_cents=4000):
    """Zero-rate table -> seated reservation -> one AVAILABLE copy checked out.
    Returns (reservation, game_copy, checkout)."""
    table = create_table(
        api,
        seats=4,
        half_hour_rate_cents=0,
        day_pass_cents=0,
        cover_fee_cents=0,
        min_spend_cents=0,
    )
    gc = create_game_copy(
        api, barcode, condition=condition, replacement_value_cents=replacement_value_cents
    )
    resv = create_seated_reservation(
        api,
        table_id=table["id"],
        start_at="2026-07-05T12:00:00Z",
        end_at="2026-07-05T14:00:00Z",
        seated_at="2026-07-05T12:00:00Z",
        booking_clock="2026-07-05T12:00:00Z",
    )
    checkout = create_checkout(api, gc["id"], resv["id"])
    return resv, gc, checkout


# ---------------------------------------------------------------------------
# Tournaments / registrations
# ---------------------------------------------------------------------------
def register(api, tournament_id, membership_id, headers=None):
    """Register a member for a tournament (Staff by default). Returns the registration."""
    return get_success_data(
        api.create_registration(
            F.create_registration_payload(tournament_id, membership_id),
            headers=headers or _STAFF,
        )
    )


def check_in(api, registration_id):
    """Check a registrant in (Staff). Returns the registration dict."""
    return get_success_data(api.check_in_registration(registration_id, headers=_STAFF))


# ---------------------------------------------------------------------------
# Private bookings
# ---------------------------------------------------------------------------
def create_hold(api, room_id, start_at, end_at, expected_room_version, headcount=8, headers=None):
    """Place a hold on a room (Staff by default). Returns the private booking dict."""
    return get_success_data(
        api.create_private_booking(
            F.create_private_booking_payload(
                room_id, start_at, end_at, expected_room_version, headcount=headcount
            ),
            headers=headers or _STAFF,
        )
    )


def current_room_version(api, room_id):
    """Read a room's current version (Staff)."""
    return get_success_data(api.get_room(room_id, headers=_STAFF))["version"]
