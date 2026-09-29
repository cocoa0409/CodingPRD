"""Two different shapes of resource contention (PRD §3.5, §3.6).

Escort crews are excluded pairwise on buffered, half-open windows, so whether a
back-to-back booking collides is decided entirely by the crew's own
`buffer_minutes`.  Set crews are capped by aggregate per-day counting on
*inclusive* endpoints, so two jobs that merely touch on a single calendar date
both occupy it.  Each file half books an identical second commitment against two
differently configured resources and pins the accept/refuse split plus the
resulting rollups.
"""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    book_set_job,
    create_escort_assignment_payload,
    create_set_job_payload,
    current_order_version,
    make_transport_manager_headers,
    open_order,
    read_escort_crew,
    read_set_job,
    register_plant,
    register_set_crew,
    reserve_escort,
    set_logical_clock,
    setup_leg_awaiting_escorts,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["network_admin_headers"]

FIRST_WINDOW_START = "2026-08-03T06:00:00.000Z"
FIRST_WINDOW_END = "2026-08-03T14:00:00.000Z"
ADJACENT_WINDOW_START = "2026-08-03T14:00:00.000Z"
ADJACENT_WINDOW_END = "2026-08-03T18:00:00.000Z"


def _leg_with_two_crews_each_holding_the_morning_window():
    """One twelve-hour leg, two crews, one identical morning reservation each.

    The crews differ in exactly one field: `Buffered Escort` carries the
    45-minute turnaround buffer and `Tight Escort` carries none.  Both hold a
    reserved 06:00Z-14:00Z window on the same leg, and both have a
    1200-minute ceiling, so neither is anywhere near overbooked.
    """
    scenario = setup_leg_awaiting_escorts(
        window_start=FIRST_WINDOW_START,
        window_end="2026-08-03T18:00:00.000Z",
        escort_crews=[
            {
                "vendor_name": "Buffered Escort",
                "endorsement_class": "STANDARD",
                "buffer_minutes": 45,
                "max_reserved_minutes": 1200,
            },
            {
                "vendor_name": "Tight Escort",
                "endorsement_class": "STANDARD",
                "buffer_minutes": 0,
                "max_reserved_minutes": 1200,
            },
        ],
    )
    scenario["buffered_crew"], scenario["tight_crew"] = scenario["escort_crews"]
    for crew in (scenario["buffered_crew"], scenario["tight_crew"]):
        reserve_escort(
            scenario["leg"]["id"],
            crew["id"],
            scenario["hauler"]["id"],
            role="ESCORT",
            window_start=FIRST_WINDOW_START,
            window_end=FIRST_WINDOW_END,
        )
    return scenario


def _book_the_adjacent_afternoon_window(scenario, crew_id):
    """Ask for 14:00Z-18:00Z, opening exactly when the morning window closes."""
    return api_client.create_escort_assignment(
        create_escort_assignment_payload(
            scenario["leg"]["id"],
            crew_id,
            role="ESCORT",
            window_start=ADJACENT_WINDOW_START,
            window_end=ADJACENT_WINDOW_END,
        ),
        make_transport_manager_headers(scenario["hauler"]["id"]),
    )


def test_buffered_crew_refuses_the_window_that_opens_when_its_own_closes():
    """PRD §3.5: "Reservation windows are treated as half-open intervals — the
    closing instant is not itself occupied — and both the candidate window and each
    existing window are inflated symmetrically by the crew's `buffer_minutes` on
    each side before comparison."
    PRD §3.5: "The consequence worth internalising is the adjacency case: when the
    buffer is greater than zero, a back-to-back booking that opens at the exact
    instant an existing reservation closes **does** conflict; when the buffer is
    zero, that same back-to-back booking is accepted, because the strict half-open
    comparison then fails."
    PRD §3.5: "A conflict is refused with `ERR_ESCORT_WINDOW_CONFLICT` and HTTP
    409."

    Design: Difficulty/resource_temporal_overlap/escort_buffer_inflated_adjacent_window_conflict
    """
    scenario = _leg_with_two_crews_each_holding_the_morning_window()

    refused = _book_the_adjacent_afternoon_window(
        scenario, scenario["buffered_crew"]["id"]
    )
    validate_error(refused, ApiErrorId.ERR_ESCORT_WINDOW_CONFLICT.value, 409)

    crew = read_escort_crew(scenario["buffered_crew"]["id"])
    assert crew["reserved_minutes"] == 480, (
        "the refused booking adds nothing, so only the morning window's 480 minutes "
        f"stand, got {crew['reserved_minutes']}"
    )
    assert crew["status"] == "AVAILABLE", (
        "480 minutes stay inside the 1200-minute ceiling, got " f"{crew['status']}"
    )


def test_zero_buffer_crew_accepts_the_byte_identical_adjacent_window():
    """PRD §3.5: "A conflict exists when some other reservation of the same crew, in
    `RESERVED` status, satisfies both of two strict comparisons: the candidate's
    opening instant falls before that reservation's closing instant advanced by the
    buffer, and that reservation's opening instant falls before the candidate's
    closing instant advanced by the buffer."
    PRD §3.1: "`buffer_minutes` is the turnaround buffer that inflates both ends of
    every reserved window when overlaps are tested; it defaults to three quarters of
    an hour — 45 minutes — and must lie between 0 and 240 inclusive."
    PRD §3.5: "A crew's `reserved_minutes` is never incremented; it is recomputed in
    full as the sum of the frozen `reserved_minutes` of every one of that crew's
    reservations currently in `RESERVED` status."

    Design: Difficulty/resource_temporal_overlap/escort_buffer_inflated_adjacent_window_conflict
    """
    scenario = _leg_with_two_crews_each_holding_the_morning_window()

    refused = _book_the_adjacent_afternoon_window(
        scenario, scenario["buffered_crew"]["id"]
    )
    validate_error(refused, ApiErrorId.ERR_ESCORT_WINDOW_CONFLICT.value, 409)

    accepted = validate_success(
        _book_the_adjacent_afternoon_window(scenario, scenario["tight_crew"]["id"]), 201
    )
    assert accepted["reserved_minutes"] == 240, (
        "a four-hour afternoon window freezes at 240 minutes, got "
        f"{accepted['reserved_minutes']}"
    )

    crew = read_escort_crew(scenario["tight_crew"]["id"])
    assert crew["reserved_minutes"] == 720, (
        "the crew's ledger sums its two reserved rows, 480 + 240, got "
        f"{crew['reserved_minutes']}"
    )
    assert crew["status"] == "AVAILABLE", (
        "720 minutes stay inside the 1200-minute ceiling, got " f"{crew['status']}"
    )


def _single_capacity_crew_booked_over_three_days():
    """One crew at `daily_capacity` 1, holding 2026-08-10 through 2026-08-12.

    The candidate bookings sit on their own orders, because a second job on the
    same order would retire the first and silently free its days.
    """
    set_logical_clock()
    plant = register_plant(state_code="AZ")
    set_crew = register_set_crew(company_name="Sonoran Set", daily_capacity=1)
    orders = [
        open_order(plant["id"], dealer_name=name, section_count=1)
        for name in ("Valley Homes", "Mesa Homes", "Gilbert Homes")
    ]
    first_job = book_set_job(
        orders[0]["id"],
        set_crew["id"],
        scheduled_start_date="2026-08-10",
        scheduled_end_date="2026-08-12",
    )
    return {
        "plant": plant,
        "set_crew": set_crew,
        "orders": orders,
        "first_job": first_job,
    }


def _book_days(scenario, order, start_date, end_date):
    """Ask the same crew for another inclusive calendar range."""
    return api_client.create_set_job(
        create_set_job_payload(
            order["id"],
            scenario["set_crew"]["id"],
            current_order_version(order["id"]),
            scheduled_start_date=start_date,
            scheduled_end_date=end_date,
        ),
        ADMIN,
    )


def _crew_job_count(crew_id):
    jobs, meta = validate_paginated(
        api_client.list_set_jobs(ADMIN, params={"set_crew_id": crew_id})
    )
    return meta["total_count"], jobs


def test_booking_that_starts_on_another_jobs_end_date_exceeds_daily_capacity():
    """PRD §3.6: "A set job's day commitment is a **closed** calendar interval: both
    `scheduled_start_date` and `scheduled_end_date` are occupied days, as is every
    day between them."
    PRD §3.6: "The consequence worth spelling out: two jobs that merely touch — one
    ending on a date and the next starting on that same date — both occupy it, so a
    crew with a `daily_capacity` of 1 cannot take the second."
    PRD §3.6: "If adding the candidate would take the count on any single date above
    the crew's `daily_capacity`, the booking is refused with
    `ERR_SET_CREW_CAPACITY_EXCEEDED` and HTTP 409."

    Design: Difficulty/resource_temporal_overlap/set_crew_inclusive_day_capacity_shared_end_date
    """
    scenario = _single_capacity_crew_booked_over_three_days()

    refused = _book_days(
        scenario, scenario["orders"][1], "2026-08-12", "2026-08-14"
    )
    validate_error(refused, ApiErrorId.ERR_SET_CREW_CAPACITY_EXCEEDED.value, 409)

    total_count, _jobs = _crew_job_count(scenario["set_crew"]["id"])
    assert total_count == 1, (
        "the refused booking wrote no row, so the crew still holds its one job, got "
        f"{total_count}"
    )


def test_booking_that_starts_the_day_after_clears_the_shared_date():
    """PRD §3.6: "Before the row is created, the system walks every calendar date in
    the candidate's inclusive range and, for each one, counts how many of that crew's
    existing set jobs already occupy that date — counting only jobs whose progress
    dimension is `SCHEDULED`, `DISPATCHED` or `SET_COMPLETE`, since jobs that have
    reached `CLOSED` or `SUPERSEDED` release their days."
    PRD §3.6: "The consequence worth spelling out: two jobs that merely touch — one
    ending on a date and the next starting on that same date — both occupy it, so a
    crew with a `daily_capacity` of 1 cannot take the second."
    PRD §3.6: "`CLOSED` and `SUPERSEDED` are the terminal ends of the progress
    dimension."

    Design: Difficulty/resource_temporal_overlap/set_crew_inclusive_day_capacity_shared_end_date
    """
    scenario = _single_capacity_crew_booked_over_three_days()

    refused = _book_days(
        scenario, scenario["orders"][1], "2026-08-12", "2026-08-14"
    )
    validate_error(refused, ApiErrorId.ERR_SET_CREW_CAPACITY_EXCEEDED.value, 409)

    accepted = validate_success(
        _book_days(scenario, scenario["orders"][2], "2026-08-13", "2026-08-15"), 201
    )
    assert accepted["progress_status"] == "SCHEDULED", (
        "a freshly booked job opens on the SCHEDULED progress dimension, got "
        f"{accepted['progress_status']}"
    )

    first_job = read_set_job(scenario["first_job"]["id"])
    assert first_job["progress_status"] == "SCHEDULED", (
        "the second job sits on a different order, so nothing supersedes the first, "
        f"got {first_job['progress_status']}"
    )

    total_count, _jobs = _crew_job_count(scenario["set_crew"]["id"])
    assert total_count == 2, (
        f"the crew now holds two scheduled jobs, got {total_count}"
    )
