"""State-machine tests: the Booking reschedule revision loop, the Cleaner
branching+reinstatement machine, initial states, invalid transitions, terminal
lockdown, and the adjudication side effects.
"""
from test_helpers import (
    get_success_data, validate_success, validate_error, ApiErrorId,
    make_customer_headers, make_cleaner_headers,
    setup_booking_world, create_one_time_booking,
    create_applied_cleaner, create_active_cleaner, create_check_failed_cleaner,
    create_customer, create_address, setup_series, setup_series_with_one_occurrence,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# ===========================================================================
# Queue A — Rule 3: non_linear_state_machine
# ===========================================================================
def test_booking_reschedule_revision_loop_stays_rescheduled(api):
    """PRD §3.5: "A `RESCHEDULED` booking can be rescheduled again, returning to
    `RESCHEDULED`; this is the revision loop."

    A booking rescheduled twice (far from start, no fee) remains RESCHEDULED with
    its scheduled_start at the latest instant.

    Design: Difficulty/non_linear_state_machine/booking_reschedule_revision_loop
    """
    world = setup_booking_world(home_size="TWO_BR", loyalty_count=0)
    booking = create_one_time_booking(world, scheduled_start="2026-06-20T09:00:00Z")
    cust_hdr = make_customer_headers(world["customer"]["id"])
    get_success_data(api.reschedule_booking(booking["id"], {"scheduled_start": "2026-06-21T09:00:00Z"}, cust_hdr))
    data = validate_success(
        api.reschedule_booking(booking["id"], {"scheduled_start": "2026-06-22T09:00:00Z"}, cust_hdr)
    )
    assert data["status"] == "RESCHEDULED", f"Expected RESCHEDULED after second reschedule, got {data['status']}"
    assert data["scheduled_start"].startswith("2026-06-22T09:00:00"), \
        f"Expected scheduled_start 2026-06-22T09:00:00, got {data['scheduled_start']}"


def test_cleaner_branch_terminal_failure_and_reinstatement_loop(api):
    """PRD §3.1: "`CHECK_FAILED` is terminal: a cleaner who has failed vetting can
    never be activated and is permanently barred from work."
    PRD §3.1: "the same activation action reinstates a suspended cleaner, moving
    `SUSPENDED` back to `ACTIVE`. This `ACTIVE → SUSPENDED → ACTIVE` reinstatement
    loop is distinct from the terminal `CHECK_FAILED` branch."

    One applicant adjudicated ADVERSE lands terminal CHECK_FAILED; a cleared one
    traverses ACTIVE -> SUSPENDED -> ACTIVE and ends ACTIVE.

    Design: Difficulty/non_linear_state_machine/cleaner_branch_terminal_failure_and_reinstatement_loop
    """
    bad = create_check_failed_cleaner()
    assert bad["status"] == "CHECK_FAILED", f"Expected terminal CHECK_FAILED, got {bad['status']}"

    good = create_active_cleaner()
    get_success_data(api.suspend_cleaner(good["id"], ADMIN))
    reinstated = validate_success(api.activate_cleaner(good["id"], ADMIN))
    assert reinstated["status"] == "ACTIVE", \
        f"Expected ACTIVE after SUSPENDED->ACTIVE reinstatement, got {reinstated['status']}"


def test_booking_first_reschedule_enters_rescheduled(api):
    """PRD §3.5: "A booking in `SCHEDULED` or `RESCHEDULED` status may be moved by
    its owning customer ... and moves the booking to `RESCHEDULED`."

    The first reschedule of a SCHEDULED booking enters RESCHEDULED — the entry
    leg of the cyclic machine, prior to the self-loop.

    Design: Difficulty/non_linear_state_machine/booking_reschedule_revision_loop
    """
    world = setup_booking_world(home_size="TWO_BR", loyalty_count=0)
    booking = create_one_time_booking(world, scheduled_start="2026-06-20T09:00:00Z")
    assert booking["status"] == "SCHEDULED"
    cust_hdr = make_customer_headers(world["customer"]["id"])
    data = validate_success(
        api.reschedule_booking(booking["id"], {"scheduled_start": "2026-06-21T09:00:00Z"}, cust_hdr)
    )
    assert data["status"] == "RESCHEDULED", \
        f"Expected RESCHEDULED after first reschedule, got {data['status']}"


def test_adverse_adjudication_reaches_terminal_check_failed(api):
    """PRD §3.1: "When the adjudication outcome is adverse, the check's `result`
    is set to `ADVERSE`, `adjudicated_at` is stamped, and the cleaner advances
    from `CHECK_PENDING` to `CHECK_FAILED`."

    Adjudicating ADVERSE drives the cleaner to the terminal CHECK_FAILED fork —
    the failure branch distinct from the reinstatement loop.

    Design: Difficulty/non_linear_state_machine/cleaner_branch_terminal_failure_and_reinstatement_loop
    """
    cleaner = create_applied_cleaner()
    bc = get_success_data(api.create_background_check(cleaner["id"], {"provider_ref": "ext-bad"}, ADMIN))
    check = validate_success(api.adjudicate_background_check(bc["id"], {"result": "ADVERSE"}, ADMIN))
    assert check["result"] == "ADVERSE"
    after = validate_success(api.get_cleaner(cleaner["id"], ADMIN))
    assert after["status"] == "CHECK_FAILED", \
        f"Expected terminal CHECK_FAILED after ADVERSE, got {after['status']}"


# ===========================================================================
# Queue B — Corner: state_machines
# ===========================================================================
def test_new_booking_starts_in_scheduled(api):
    """PRD §3.3: "A booking begins in `SCHEDULED` status, and a booking created
    directly by a customer leaves its `series_id` null while a series-generated
    booking carries the originating `series_id`."

    Design: Corner/state_machines/new_booking_starts_in_scheduled
    """
    world = setup_booking_world(home_size="STUDIO", loyalty_count=0)
    booking = create_one_time_booking(world, scheduled_start="2026-06-10T09:00:00Z")
    assert booking["status"] == "SCHEDULED", f"Expected SCHEDULED, got {booking['status']}"


def test_second_cancel_on_cancelled_booking_returns_invalid_state(api):
    """PRD §3.4/§3.5: A booking that is cancelled reaches "the terminal
    `CANCELLED` state".
    PRD §2.6: "then whether the target resource is in a state from which the
    requested transition is defined (`ERR_INVALID_STATE`)."

    Cancelling an already-CANCELLED booking is rejected with ERR_INVALID_STATE.

    Design: Corner/state_machines/cancel_booking_from_cancelled_returns_invalid_state
    """
    world = setup_booking_world(home_size="STUDIO", loyalty_count=0)
    booking = create_one_time_booking(world, scheduled_start="2026-06-20T09:00:00Z")
    cust_hdr = make_customer_headers(world["customer"]["id"])
    get_success_data(api.cancel_booking(booking["id"], cust_hdr))
    validate_error(api.cancel_booking(booking["id"], cust_hdr), ApiErrorId.ERR_INVALID_STATE.value)


def test_complete_before_scheduled_start_returns_invalid_state(api):
    """PRD §3.7: "The assigned cleaner marks a visit done once the current clock
    has reached or passed the booking's `scheduled_start`, the booking is in
    `SCHEDULED` or `RESCHEDULED`, and the acting cleaner is the booking's assigned
    `cleaner_id`."

    Completing while the clock is still before scheduled_start violates the time
    precondition -> ERR_INVALID_STATE.

    Design: Corner/state_machines/complete_before_scheduled_start_returns_invalid_state
    """
    world = setup_booking_world(home_size="STUDIO", loyalty_count=0)
    booking = create_one_time_booking(
        world, scheduled_start="2026-06-10T09:00:00Z", cleaner_id=world["cleaner"]["id"]
    )
    # clock is still 2026-06-01, before the 2026-06-10 start
    cleaner_hdr = make_cleaner_headers(world["cleaner"]["id"])
    validate_error(
        api.complete_booking(booking["id"], {"rating": 5}, cleaner_hdr),
        ApiErrorId.ERR_INVALID_STATE.value,
    )


def test_pause_resume_series_round_trip(api):
    """PRD §3.4: "A customer may pause an `ACTIVE` series, moving it to `PAUSED`
    so no further occurrences generate, and resume a `PAUSED` series back to
    `ACTIVE` with generation re-enabled from the current `next_occurrence_date`."
    PRD §3.4: "Each pause, resume, and cancel increments the series `version`"

    Pause then resume returns the series to ACTIVE; version goes 1 -> 3.

    Design: Corner/state_machines/pause_resume_series_round_trip
    """
    world = setup_series(cadence="WEEKLY", first_occurrence_date="2026-06-20T09:00:00Z")
    series = world["series"]
    assert series["version"] == 1
    cust_hdr = make_customer_headers(world["customer"]["id"])
    get_success_data(api.pause_series(series["id"], cust_hdr))
    resumed = validate_success(api.resume_series(series["id"], cust_hdr))
    assert resumed["status"] == "ACTIVE", f"Expected ACTIVE after resume, got {resumed['status']}"
    assert resumed["version"] == 3, f"Expected version 3 after pause+resume, got {resumed['version']}"


def test_generate_on_cancelled_series_returns_invalid_state(api):
    """PRD §3.4: "A customer may cancel a series that is in either `ACTIVE` or
    `PAUSED`, moving it to the terminal `CANCELLED` state."
    PRD §3.4: "A `PlatformAdmin` mints the next visit by generating against an
    `ACTIVE` series whose `next_occurrence_date` is at or before the current
    clock."

    Generating on a terminal CANCELLED series is rejected with ERR_INVALID_STATE.

    Design: Corner/state_machines/generate_on_cancelled_series_returns_invalid_state
    """
    world = setup_series(cadence="WEEKLY", first_occurrence_date="2026-06-20T09:00:00Z")
    series = world["series"]
    cust_hdr = make_customer_headers(world["customer"]["id"])
    cancelled = get_success_data(api.cancel_series(series["id"], cust_hdr))
    validate_error(
        api.generate_occurrence(series["id"], {"expected_series_version": cancelled["version"]}, ADMIN),
        ApiErrorId.ERR_INVALID_STATE.value,
    )


def test_adjudicate_clear_moves_cleaner_to_check_passed(api):
    """PRD §3.1: "When a `PlatformAdmin` adjudicates with a clear outcome, the
    check's `result` is set to `CLEAR`, `adjudicated_at` is stamped with the
    current instant, and the cleaner advances from `CHECK_PENDING` to
    `CHECK_PASSED`."

    Design: Corner/state_machines/adjudicate_clear_moves_cleaner_to_check_passed
    """
    cleaner = create_applied_cleaner()
    bc = get_success_data(api.create_background_check(cleaner["id"], {"provider_ref": "ext-1"}, ADMIN))
    check = validate_success(api.adjudicate_background_check(bc["id"], {"result": "CLEAR"}, ADMIN))
    assert check["result"] == "CLEAR", f"Expected result CLEAR, got {check['result']}"
    assert check["adjudicated_at"] is not None, "adjudicated_at must be stamped non-null"
    cleaner_after = validate_success(api.get_cleaner(cleaner["id"], ADMIN))
    assert cleaner_after["status"] == "CHECK_PASSED", \
        f"Expected cleaner CHECK_PASSED, got {cleaner_after['status']}"
