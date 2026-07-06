"""State-machine transitions: invalid/terminal guards, initial state, deferred
sweeps, guarded confirm, cascade-down, bubble-up, and cross-entity advancement.

Queue B (Corner): section state_machines.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    create_dome,
    create_open_show,
    create_show,
    create_classroom_program,
    create_registration,
    create_hold,
    create_sponsor,
    submit_and_approve_accommodation,
)

ADMIN = TEST_USERS["facility_admin_headers"]
BOX_OFFICE = TEST_USERS["box_office_headers"]
PROGRAM = TEST_USERS["program_coordinator_headers"]
DEV = TEST_USERS["development_officer_headers"]
ACCESS = TEST_USERS["accessibility_headers"]


def test_open_already_open_show_rejected(api):
    """PRD §3.3: "Opening transitions the show `SCHEDULED → OPEN` and bumps its
    `version`; it is permitted only while the show is still `SCHEDULED` and the logical
    clock is still before the show's `starts_at`."

    Design: Corner/state_machines/open_already_open_show_invalid_state
    """
    show = create_open_show(seated_capacity=30, base_price_cents=1000, title="Once")
    resp = api.open_show(show["id"], BOX_OFFICE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_cancel_already_cancelled_show_rejected(api):
    """PRD §3.3: "the show is set to `CANCELLED`, and its `version` is incremented.
    `CANCELLED` is terminal."

    Design: Corner/state_machines/cancel_already_cancelled_show_invalid_state
    """
    show = create_open_show(seated_capacity=30, base_price_cents=1000, title="Term")
    validate_success(api.cancel_show(show["id"], BOX_OFFICE))
    resp = api.cancel_show(show["id"], BOX_OFFICE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_new_show_starts_in_scheduled(api):
    """PRD §3.3: "A freshly scheduled show starts in `SCHEDULED` status with
    `seats_sold` at 0 and `version` at 1."

    Design: Corner/state_machines/new_show_starts_in_scheduled
    """
    dome = create_dome(seated_capacity=30, name="Dome S")
    show = create_show(dome["id"], base_price_cents=1000, title="Init",
                       starts_at="2026-05-07T10:00:00Z", ends_at="2026-05-07T11:00:00Z")
    assert show["status"] == "SCHEDULED", f"expected SCHEDULED, got {show['status']}"


def test_hold_expiry_sweep_cancels_held_booking_and_releases_seat(api):
    """PRD §2.5: "every show booking still in `HELD` whose hold window has elapsed is
    released: the booking moves to `CANCELLED`, its seats are returned to the show, and
    the show reopens from `SOLD_OUT` to `OPEN` if the freed seats bring it back below
    capacity."

    A hold created at the default clock 2026-03-01T00:00:00Z elapses after the clock
    advances 31 minutes; the sweep cancels it and releases the seat.

    Design: Corner/state_machines/hold_expiry_sweep_cancels_held_booking
    """
    show = create_open_show(seated_capacity=30, base_price_cents=1000, title="Sweep")
    booking = create_hold(show["id"], party_size=1)

    validate_success(api.set_clock("2026-03-01T00:31:00Z", ADMIN))
    validate_success(api.run_sweeps(ADMIN))

    booking_after = validate_success(api.get_show_booking(booking["id"], BOX_OFFICE))
    assert booking_after["status"] == "CANCELLED", \
        f"swept hold should be CANCELLED, got {booking_after['status']}"
    show_after = validate_success(api.get_show(show["id"], BOX_OFFICE))
    assert show_after["seats_sold"] == 0, \
        f"seat should be released, got seats_sold {show_after['seats_sold']}"


def test_confirm_after_hold_window_expired_rejected(api):
    """PRD §3.4: "A confirm attempted after the 30-minute window has elapsed is
    rejected with `ERR_HOLD_EXPIRED`."

    Hold at default clock; advance 31 minutes; confirm fails with ERR_HOLD_EXPIRED.

    Design: Corner/state_machines/confirm_booking_after_hold_window_expired
    """
    show = create_open_show(seated_capacity=30, base_price_cents=1000, title="Expire")
    booking = create_hold(show["id"], party_size=1)

    validate_success(api.set_clock("2026-03-01T00:31:00Z", ADMIN))
    resp = api.confirm_show_booking(booking["id"], BOX_OFFICE)
    validate_error(resp, ApiErrorId.ERR_HOLD_EXPIRED.value, expected_status=409)


def test_program_cancel_cascades_all_registrations(api):
    """PRD §3.6: "Cancelling the session is permitted from `ENROLLING` or `FULL` and
    cascades to every registration that is `ENROLLED` or `WAITLISTED`, moving each to
    `CANCELLED`, then sets the session's `enrolled_count` to 0, sets the session to
    `CANCELLED`, and increments its `version`."

    Design: Corner/state_machines/program_cancel_cascades_all_registrations
    """
    program = create_classroom_program(capacity=5, tuition_cents=5000, min_age=5, max_age=99,
                                        title="CascadeCamp")
    r1 = create_registration(program["id"], participant_name="R1", participant_age=10)
    r2 = create_registration(program["id"], participant_name="R2", participant_age=11)

    validate_success(api.cancel_program(program["id"], PROGRAM))

    r1_after = validate_success(api.get_registration(r1["id"], PROGRAM))
    r2_after = validate_success(api.get_registration(r2["id"], PROGRAM))
    session_after = validate_success(api.get_program(program["id"], PROGRAM))
    assert r1_after["status"] == "CANCELLED"
    assert r2_after["status"] == "CANCELLED"
    assert session_after["enrolled_count"] == 0, \
        f"enrolled_count must be 0 after cancel, got {session_after['enrolled_count']}"


def test_last_enroll_bubbles_session_to_full(api):
    """PRD §3.6: "When a registration is enrolled, the system recomputes the session's
    `enrolled_count`; if that count has reached `capacity`, the session bubbles
    `ENROLLING → FULL`; and the session's `version` is incremented."

    Design: Corner/state_machines/program_full_bubbles_up_on_last_enroll
    """
    program = create_classroom_program(capacity=1, tuition_cents=5000, min_age=5, max_age=99,
                                        program_kind="CLASS", title="FillCamp")
    reg = create_registration(program["id"], participant_name="Only", participant_age=10)
    assert reg["status"] == "ENROLLED"

    session_after = validate_success(api.get_program(program["id"], PROGRAM))
    assert session_after["status"] == "FULL", \
        f"session should bubble to FULL, got {session_after['status']}"


def test_partial_contribution_advances_sponsor_state(api):
    """PRD §3.8: "From `PLEDGED`, if the new `received_cents` lands strictly above 0
    and strictly below `pledged_cents`, the sponsor moves to `PARTIALLY_FULFILLED`."
    PRD §3.8: "the `fulfillment_ratio` is the `received_cents` divided by the
    `pledged_cents`, rounded to four decimal places".

    A 3000 contribution against a 10000 pledge: received 3000, ratio 0.3.

    Design: Corner/state_machines/sponsor_contribution_advances_fulfillment_state
    """
    sponsor = create_sponsor(pledged_cents=10000, sponsor_kind="SPONSOR", org_name="Partial")
    validate_success(api.create_contribution(
        sponsor["id"], {"amount_cents": 3000, "expected_sponsor_version": sponsor["version"]}, DEV),
        expected_status=201)

    sponsor_after = validate_success(api.get_sponsor(sponsor["id"], DEV))
    assert sponsor_after["status"] == "PARTIALLY_FULFILLED", \
        f"expected PARTIALLY_FULFILLED, got {sponsor_after['status']}"
    assert sponsor_after["received_cents"] == 3000
    assert sponsor_after["fulfillment_ratio"] == 0.3, \
        f"expected fulfillment_ratio 0.3, got {sponsor_after['fulfillment_ratio']}"


def test_accommodation_approve_then_fulfill(api):
    """PRD §3.9: "Approving a request moves it `SUBMITTED → APPROVED`. ... An approved
    request can be fulfilled, moving it `APPROVED → FULFILLED`."

    Design: Corner/state_machines/accommodation_approve_then_fulfill
    """
    program = create_classroom_program(capacity=5, tuition_cents=5000, min_age=5, max_age=99,
                                        title="AccCamp")
    reg = create_registration(program["id"], participant_name="Acc", participant_age=10)
    acc = submit_and_approve_accommodation("REGISTRATION", accommodation_kind="SENSORY_FRIENDLY",
                                           registration_id=reg["id"])
    assert acc["status"] == "APPROVED"

    fulfilled = validate_success(api.fulfill_accommodation(acc["id"], ACCESS))
    assert fulfilled["status"] == "FULFILLED", f"expected FULFILLED, got {fulfilled['status']}"
