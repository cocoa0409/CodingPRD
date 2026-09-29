"""Values one step either side of a band edge or an interval boundary."""

from test_helpers import (
    ApiErrorId,
    DISPATCH_HEADERS,
    GlycolStatus,
    ReadingSource,
    WorkStatus,
    assert_score,
    factories,
    fixtures,
    validate_error,
)


def test_a_glycol_score_of_exactly_seventy_five_still_reads_normal(api):
    """PRD §3.9: "The loop's `status` is then a pure projection of that number, with both
    band edges inclusive on their lower bound: `NORMAL` at 75.00 and above, `WATCH` from
    50.00 up to but not including 75.00, and `ALARM` below 50.00."
    PRD §3.9: "The **glycol penalty** is the amount by which `glycol_pct` falls short of
    the 30.0 per cent minimum, multiplied by 2.5 points per percentage point, and floored
    at zero."

    Design: Difficulty/boundary_precision_check/glycol_health_score_of_exactly_seventy_five_is_normal_and_seventy_four_seventy_five_is_watch
    """
    ground = fixtures.setup_glycol_maintenance_visit(api, glycol_pct=20.0)
    loop = ground["loop"]
    assert_score(loop["health_score"], 75.0)

    readings = fixtures.post_cooler_readings(
        api, loop["id"], (38.0, 38.0, 38.0), ground["tech_headers"]
    )

    at_edge = fixtures.read_loop(api, loop["id"])
    # A cooler sitting exactly on target contributes no temperature penalty.
    assert_score(at_edge["health_score"], 75.0)
    assert at_edge["status"] == GlycolStatus.NORMAL, (
        f"75.00 is the inclusive lower edge of NORMAL, got {at_edge['status']}"
    )
    assert at_edge["window_avg_cooler_temp_f"] == 38.0
    assert readings[-1]["source"] == ReadingSource.TECH_MANUAL
    assert readings[0]["cooler_temp_f"] == 38.0


def test_one_tenth_less_glycol_drops_the_loop_into_the_watch_band(api):
    """PRD §3.9: "A score of exactly 75.00 is `NORMAL` while 74.99 is `WATCH`; exactly
    50.00 is `WATCH` while 49.99 is `ALARM`."
    PRD §3.9: "Four penalties are then computed, each rounded half up to two decimal places
    on its own before any subtraction, so that penalties never accumulate unrounded drift:"

    Design: Difficulty/boundary_precision_check/glycol_health_score_of_exactly_seventy_five_is_normal_and_seventy_four_seventy_five_is_watch
    """
    ground = fixtures.setup_glycol_maintenance_visit(api, glycol_pct=20.0)
    fixtures.post_cooler_readings(
        api, ground["loop"]["id"], (38.0, 38.0, 38.0), ground["tech_headers"]
    )

    serviced = fixtures.record_glycol_maintenance(
        api,
        ground["loop"]["id"],
        ground["visit"]["id"],
        ground["technician"]["id"],
        glycol_pct=19.9,
        pump_psi=12.0,
        bath_temp_f=28.0,
    )

    assert serviced["glycol_pct"] == 19.9
    # A shortfall of 10.1 percentage points costs exactly 25.25 points.
    assert_score(serviced["health_score"], 74.75)
    assert serviced["status"] == GlycolStatus.WATCH


def _route_board(api):
    """One venue, one crew, and a job already booked from 540 to 660."""
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    venue = fixtures.onboard_venue(api, venue_name="Ridgeline Growler", lines=())
    technician = fixtures.create_technician(api, full_name="Dana Ruiz")
    first = fixtures.book_visit(
        api,
        venue["account"]["id"],
        technician["id"],
        scheduled_date="2026-08-05",
        scheduled_start_minute=540,
        scheduled_end_minute=660,
    )
    return venue, technician, first


def _attempt_booking(api, account_id, technician_id, start, end):
    return api.create_service_visit(
        factories.service_visit_payload(
            account_id,
            technician_id,
            scheduled_date="2026-08-05",
            scheduled_start_minute=start,
            scheduled_end_minute=end,
        ),
        DISPATCH_HEADERS,
    )


def test_a_route_gap_of_exactly_the_travel_buffer_is_accepted(api):
    """PRD §3.3: "The booking is rejected with `ERR_TECHNICIAN_ROUTE_CONFLICT` when the
    new slot's start is strictly earlier than the existing visit's end plus 30 minutes
    **and** the existing visit's start is strictly earlier than the new slot's end plus 30
    minutes."
    PRD §3.3: "Both comparisons here are strict, so a gap of exactly 30 minutes between two
    jobs is accepted while a gap of 29 minutes is rejected — the opposite convention from the
    venue rule, on purpose, because a van needs half an hour to cross town but a floor cannot
    be shared for even a minute."

    Design: Difficulty/boundary_precision_check/technician_route_gap_of_exactly_thirty_minutes_is_accepted_and_twenty_nine_is_rejected
    """
    venue, technician, first = _route_board(api)

    second = fixtures.book_visit(
        api,
        venue["account"]["id"],
        technician["id"],
        scheduled_date="2026-08-05",
        scheduled_start_minute=690,
        scheduled_end_minute=780,
    )

    assert second["scheduled_start_minute"] == 690, (
        "690 leaves exactly the half-hour the van needs after a job ending at 660"
    )
    assert second["work_status"] == WorkStatus.SCHEDULED
    assert fixtures.read_visit(api, first["id"])["work_status"] == WorkStatus.SCHEDULED


def test_a_route_gap_one_minute_short_of_the_buffer_is_refused(api):
    """PRD §3.3: "**Technician route feasibility** compares the new slot against every
    existing visit for the *same* `technician_id` on the *same* `scheduled_date`, again
    only those `SCHEDULED` or `IN_PROGRESS`, and adds a half-hour travel allowance to each
    side."
    PRD §3.3: "the opposite convention from the venue rule, on purpose, because a van
    needs half an hour to cross town but a floor cannot be shared for even a minute."

    Design: Difficulty/boundary_precision_check/technician_route_gap_of_exactly_thirty_minutes_is_accepted_and_twenty_nine_is_rejected
    """
    venue, technician, _first = _route_board(api)
    fixtures.book_visit(
        api,
        venue["account"]["id"],
        technician["id"],
        scheduled_date="2026-08-05",
        scheduled_start_minute=690,
        scheduled_end_minute=780,
    )

    refused = _attempt_booking(api, venue["account"]["id"], technician["id"], 809, 900)
    validate_error(refused, ApiErrorId.TECHNICIAN_ROUTE_CONFLICT, 409)

    accepted = fixtures.book_visit(
        api,
        venue["account"]["id"],
        technician["id"],
        scheduled_date="2026-08-05",
        scheduled_start_minute=810,
        scheduled_end_minute=900,
    )
    assert accepted["scheduled_start_minute"] == 810, (
        "one minute later restores the full buffer and the booking stands"
    )


def _shared_floor(api):
    """One venue, two crews, and a job already booked from 540 to 660 for the first."""
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    venue = fixtures.onboard_venue(api, venue_name="Ironworks Tavern", lines=())
    first_tech = fixtures.create_technician(api, full_name="Dana Ruiz")
    second_tech = fixtures.create_technician(
        api, full_name="Kem Adeyemi", certification_level="CERTIFIED", caustic_certified=False
    )
    booked = fixtures.book_visit(
        api,
        venue["account"]["id"],
        first_tech["id"],
        scheduled_date="2026-08-05",
        scheduled_start_minute=540,
        scheduled_end_minute=660,
    )
    return venue, first_tech, second_tech, booked


def test_a_second_crew_arriving_on_the_closing_minute_conflicts_on_the_floor(api):
    """PRD §3.3: "The new booking is rejected with `ERR_VENUE_SLOT_CONFLICT` when its
    start is at or before the existing visit's end **and** its end is at or after the
    existing visit's start."
    PRD §3.3: "Both comparisons are non-strict, so two back-to-back slots that merely
    touch — the new one starting on the exact minute the existing one ends — are a
    conflict: only one crew at a time works a venue floor."

    Design: Difficulty/boundary_precision_check/venue_slots_that_merely_touch_at_the_minute_boundary_conflict
    """
    venue, _first_tech, second_tech, _booked = _shared_floor(api)

    refused = _attempt_booking(api, venue["account"]["id"], second_tech["id"], 660, 780)

    validate_error(refused, ApiErrorId.VENUE_SLOT_CONFLICT, 409)


def test_the_same_floor_is_free_one_minute_after_the_first_crew_leaves(api):
    """PRD §3.3: "**Venue slot exclusivity** compares the new slot against every existing
    visit on the *same* account and the *same* `scheduled_date` whose `work_status` is
    `SCHEDULED` or `IN_PROGRESS`; visits already `ABANDONED` or `WORK_COMPLETE` are
    ignored entirely."

    Design: Difficulty/boundary_precision_check/venue_slots_that_merely_touch_at_the_minute_boundary_conflict
    """
    venue, _first_tech, second_tech, booked = _shared_floor(api)

    accepted = fixtures.book_visit(
        api,
        venue["account"]["id"],
        second_tech["id"],
        scheduled_date="2026-08-05",
        scheduled_start_minute=661,
        scheduled_end_minute=780,
    )

    assert accepted["scheduled_start_minute"] == 661
    assert accepted["technician_id"] == second_tech["id"]
    assert fixtures.read_visit(api, booked["id"])["work_status"] == WorkStatus.SCHEDULED
