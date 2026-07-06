"""Entity lifecycle transitions: the cyclic officiant status machine and the
generic invalid-transition guard for bookings and officiants (PRD Sections 2.4,
3.1, 3.8).
"""
from test_helpers import (
    fixtures as fx,
    validate_success, validate_error,
    ApiErrorId,
    make_coordinator_headers, make_officiant_headers, make_couple_headers,
)

COORD = make_coordinator_headers()


def test_officiant_suspend_then_reinstate_returns_to_active(api):
    """PRD §3.1: "an active officiant is suspended by moving `ACTIVE → SUSPENDED`;
    and a suspended officiant is reinstated by moving `SUSPENDED → ACTIVE`."
    PRD §2.4: "`version` is an integer that begins at creation and increments by
    one on every mutation of the resource, including mutations to its computed fields."

    Design: Difficulty/non_linear_state_machine/officiant_suspend_reinstate_cycle
    """
    officiant = fx.create_officiant(api)                 # version 1
    fx.transition_officiant(api, officiant["id"], "ACTIVE")     # version 2
    fx.transition_officiant(api, officiant["id"], "SUSPENDED")  # version 3
    resp = api.transition_officiant(officiant["id"], {"to_state": "ACTIVE"}, COORD)  # version 4
    data = validate_success(resp, 200)
    assert data["status"] == "ACTIVE"
    assert data["version"] == 4


def test_officiant_active_moves_to_suspended(api):
    """PRD §3.1: "an active officiant is suspended by moving `ACTIVE → SUSPENDED`".

    Design: Difficulty/non_linear_state_machine/officiant_suspend_reinstate_cycle
    """
    officiant = fx.create_active_officiant(api)
    resp = api.transition_officiant(officiant["id"], {"to_state": "SUSPENDED"}, COORD)
    data = validate_success(resp, 200)
    assert data["status"] == "SUSPENDED"


def test_complete_booking_from_inquiry_returns_invalid_state(api):
    """PRD §3.8: "Completion requires that the current clock be at or after the
    booking's `ceremony_start` and that the booking be in `CONFIRMED` or
    `BACKUP_CONFIRMED`; a request that does not meet the state requirement is
    rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/complete_booking_from_inquiry_returns_invalid_state
    """
    ref = fx.setup_reference(api)
    booking = fx.create_booking(api, ref.officiant, ref.couple, ref.package, ref.venue)
    resp = api.complete_booking(booking["id"], make_officiant_headers(ref.officiant["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    after = fx.get_success_data(api.get_booking(booking["id"], COORD))
    assert after["status"] == "INQUIRY"


def test_cancel_already_cancelled_booking_returns_invalid_state(api):
    """PRD §3.8: "A booking may be cancelled from any of `HOLD`, `CONFIRMED`,
    `BACKUP_PENDING`, or `BACKUP_CONFIRMED`; a cancel requested from any other
    state is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancel_already_cancelled_booking_returns_invalid_state
    """
    ctx = fx.setup_held_booking(api)
    fx.cancel_booking(api, ctx.booking, ctx.couple)  # HOLD -> CANCELLED (terminal)
    resp = api.cancel_booking(
        ctx.booking["id"], {"cancel_reason": "COUPLE_REQUEST"}, make_couple_headers(ctx.couple["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    after = fx.get_success_data(api.get_booking(ctx.booking["id"], COORD))
    assert after["status"] == "CANCELLED"


def test_approve_already_active_officiant_returns_invalid_state(api):
    """PRD §3.1: "A pending officiant is approved by moving `PENDING_REVIEW →
    ACTIVE`; ... Any of these requested from the wrong current state is rejected
    with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/approve_already_active_officiant_returns_invalid_state
    """
    officiant = fx.create_active_officiant(api)
    resp = api.transition_officiant(officiant["id"], {"to_state": "ACTIVE"}, COORD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
