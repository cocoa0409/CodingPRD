"""Two resources booked over intervals, with deliberately different geometry: the
crush-pad lane occupies a dilated exclusive region, the sampling crew an undilated
half-open one with room for two."""
from test_helpers import (
    COORDINATOR,
    ApiErrorId,
    book_sampling_visit,
    create_crew,
    create_delivery_appointment_payload,
    create_sampling_visit_payload,
    move_clock,
    read_crew,
    read_lane,
    read_sampling_visit,
    record_sampling_visit,
    setup_active_contract,
    setup_harvest_ready,
    setup_scheduled_appointment,
    single_installment_plan,
    validate_error,
    validate_success,
)

SETUP_AT = "2026-08-20T08:00:00Z"

# The occupied slot, and the three probes one minute either side of its dilated edges.
OCCUPIED_SLOT = ("2026-08-25T14:00:00Z", "2026-08-25T16:00:00Z")
ONE_MINUTE_INSIDE_THE_LATE_EDGE = ("2026-08-25T16:29:00Z", "2026-08-25T18:29:00Z")
EXACTLY_ON_THE_LATE_EDGE = ("2026-08-25T16:30:00Z", "2026-08-25T18:30:00Z")
ONE_MINUTE_INSIDE_THE_EARLY_EDGE = ("2026-08-25T13:29:00Z", "2026-08-25T13:59:00Z")

# The crew's day: two overlapping visits, then the probes.
VISIT_A = ("2026-08-21T10:00:00Z", "2026-08-21T12:00:00Z")
VISIT_B = ("2026-08-21T11:00:00Z", "2026-08-21T13:00:00Z")
OVERLAPPING_BOTH = ("2026-08-21T11:30:00Z", "2026-08-21T12:30:00Z")
TOUCHING_VISIT_B = ("2026-08-21T13:00:00Z", "2026-08-21T15:00:00Z")


# --- The lane: exclusive occupancy over intervals dilated by the buffer ----------


def _lane_with_one_occupied_slot() -> dict:
    """A 30-minute-buffer lane carrying a single 14:00-16:00 slot, so the region it
    actually blocks runs from 13:30 to 16:30."""
    move_clock(SETUP_AT)
    ctx = setup_harvest_ready(
        contract_overrides={
            "base_price_per_ton_cents": 450000,
            "committed_tons": 60.000,
            "over_delivery_policy": "ACCEPT_AT_SPOT",
            "installment_plan": single_installment_plan(),
        },
        lane_overrides={
            "lane_code": "L1",
            "daily_capacity_tons": 80.000,
            "turnaround_buffer_minutes": 30,
            "max_load_tons": 40.0,
        },
        estimated_tons=40.000,
        block_overrides={"acres": 20.000},
    )
    setup_scheduled_appointment(ctx, OCCUPIED_SLOT[0], OCCUPIED_SLOT[1], planned_tons=22.000)
    return ctx


def _booking(ctx: dict, slot: tuple, planned_tons: float) -> dict:
    return create_delivery_appointment_payload(
        ctx["pick_call"]["id"], ctx["lane"]["id"], slot[0], slot[1], planned_tons
    )


def test_one_minute_inside_the_dilated_late_edge_is_a_conflict(api):
    """16:29 is a minute short of the 16:30 the buffer pushes the occupied region out
    to, so the lane is still busy and the booking is refused.

    PRD: "**Lane exclusivity** is checked first: the requested half-open window must not
    overlap the buffered window of any other appointment on the same lane in status
    `SCHEDULED` or `ARRIVED`, where the buffered window of an existing appointment runs
    from its `window_start` less the lane's `turnaround_buffer_minutes` to its
    `window_end` plus the same buffer."

    Design: Difficulty/resource_temporal_overlap/crush_pad_lane_buffered_adjacency_one_minute_either_side
    """
    ctx = _lane_with_one_occupied_slot()

    response = api.create_delivery_appointment(
        _booking(ctx, ONE_MINUTE_INSIDE_THE_LATE_EDGE, 18.000), COORDINATOR
    )
    validate_error(response, ApiErrorId.ERR_LANE_WINDOW_CONFLICT.value, 409)


def test_a_booking_that_merely_touches_the_dilated_edge_is_accepted(api):
    """One minute later — 16:30, exactly where the buffered region ends — the very same
    two-hour booking is accepted, because touching is not overlapping.

    PRD: "Windows that merely touch once the buffer has been applied are accepted; a
    genuine overlap is `ERR_LANE_WINDOW_CONFLICT` with HTTP 409."

    Design: Difficulty/resource_temporal_overlap/crush_pad_lane_buffered_adjacency_one_minute_either_side
    """
    ctx = _lane_with_one_occupied_slot()

    appointment = validate_success(
        api.create_delivery_appointment(_booking(ctx, EXACTLY_ON_THE_LATE_EDGE, 18.000), COORDINATOR),
        201,
    )
    assert appointment["status"] == "SCHEDULED"
    assert appointment["window_start"] == EXACTLY_ON_THE_LATE_EDGE[0]


def test_the_buffer_dilates_the_earlier_edge_as_well(api):
    """A short slot that finishes at 13:59 never touches the occupied 14:00-16:00 window
    itself, yet it ends inside the region the buffer opens at 13:30, so it is refused.

    PRD: "the buffered window of an existing appointment runs from its `window_start`
    less the lane's `turnaround_buffer_minutes` to its `window_end` plus the same buffer."

    Design: Difficulty/resource_temporal_overlap/crush_pad_lane_buffered_adjacency_one_minute_either_side
    """
    ctx = _lane_with_one_occupied_slot()
    validate_success(
        api.create_delivery_appointment(_booking(ctx, EXACTLY_ON_THE_LATE_EDGE, 18.000), COORDINATOR),
        201,
    )

    response = api.create_delivery_appointment(
        _booking(ctx, ONE_MINUTE_INSIDE_THE_EARLY_EDGE, 5.000), COORDINATOR
    )
    validate_error(response, ApiErrorId.ERR_LANE_WINDOW_CONFLICT.value, 409)


def test_only_the_touching_booking_joined_the_lane(api):
    """Of the three probes only the one that touched the dilated edge was booked, so the
    lane carries two slots and their combined tonnage.

    PRD: "A successful booking creates the appointment in status `SCHEDULED` and
    recomputes both the lane's `committed_tons` and `scheduled_appointment_count` and the
    pick call's `appointed_tons`."

    Design: Difficulty/resource_temporal_overlap/crush_pad_lane_buffered_adjacency_one_minute_either_side
    """
    ctx = _lane_with_one_occupied_slot()
    api.create_delivery_appointment(_booking(ctx, ONE_MINUTE_INSIDE_THE_LATE_EDGE, 18.000), COORDINATOR)
    api.create_delivery_appointment(_booking(ctx, EXACTLY_ON_THE_LATE_EDGE, 18.000), COORDINATOR)
    api.create_delivery_appointment(_booking(ctx, ONE_MINUTE_INSIDE_THE_EARLY_EDGE, 5.000), COORDINATOR)

    lane = read_lane(ctx["lane"]["id"])
    assert lane["scheduled_appointment_count"] == 2
    assert float(lane["committed_tons"]) == 40.000


# --- The crew: aggregate capacity of two over raw half-open windows --------------


def _crew_with_two_overlapping_visits() -> dict:
    """A crew whose ceiling is two simultaneous visits, already holding two that
    overlap each other between 11:00 and 12:00."""
    move_clock(SETUP_AT)
    ctx = setup_active_contract(
        contract_overrides={
            "base_price_per_ton_cents": 450000,
            "committed_tons": 40.000,
            "over_delivery_policy": "ACCEPT_AT_SPOT",
            "installment_plan": single_installment_plan(),
        },
        block_overrides={"acres": 20.000},
    )
    ctx["crew"] = create_crew(
        region_code=ctx["grower"]["region_code"], max_concurrent_visits=2
    )
    ctx["visit_a"] = book_sampling_visit(
        ctx["contract"]["id"], ctx["block"]["id"], ctx["crew"]["id"], VISIT_A[0], VISIT_A[1]
    )
    ctx["visit_b"] = book_sampling_visit(
        ctx["contract"]["id"], ctx["block"]["id"], ctx["crew"]["id"], VISIT_B[0], VISIT_B[1]
    )
    return ctx


def _visit(ctx: dict, window: tuple) -> dict:
    return create_sampling_visit_payload(
        ctx["contract"]["id"], ctx["block"]["id"], ctx["crew"]["id"], window[0], window[1]
    )


def test_a_second_overlapping_visit_is_legal_below_the_ceiling():
    """Unlike a lane, a crew is not exclusive: one overlapping visit leaves the count at
    1, which is still strictly below the ceiling of two.

    PRD: "counting only that crew's visits that are still in status `SCHEDULED` and whose
    own half-open window overlaps the requested half-open window, the count must be
    strictly less than the crew's `max_concurrent_visits`"

    Design: Difficulty/resource_temporal_overlap/sampling_crew_aggregate_concurrency_with_half_open_adjacency
    """
    ctx = _crew_with_two_overlapping_visits()

    assert ctx["visit_a"]["status"] == "SCHEDULED"
    assert ctx["visit_b"]["status"] == "SCHEDULED"
    assert read_crew(ctx["crew"]["id"])["scheduled_visit_count"] == 2


def test_a_window_overlapping_both_visits_saturates_the_crew(api):
    """11:30-12:30 overlaps A and B at once, so the count reaches 2 and is no longer
    strictly below the ceiling.

    PRD: "Finally the crew must not be saturated: counting only that crew's visits that
    are still in status `SCHEDULED` and whose own half-open window overlaps the requested
    half-open window, the count must be strictly less than the crew's
    `max_concurrent_visits`, otherwise `ERR_CREW_WINDOW_OVERLAP_LIMIT` with HTTP 409."

    Design: Difficulty/resource_temporal_overlap/sampling_crew_aggregate_concurrency_with_half_open_adjacency
    """
    ctx = _crew_with_two_overlapping_visits()

    response = api.create_sampling_visit(_visit(ctx, OVERLAPPING_BOTH), COORDINATOR)
    validate_error(response, ApiErrorId.ERR_CREW_WINDOW_OVERLAP_LIMIT.value, 409)

    assert read_crew(ctx["crew"]["id"])["scheduled_visit_count"] == 2


def test_a_visit_starting_where_another_ends_does_not_overlap_it(api):
    """13:00 is exactly visit B's `window_end`, and no turnaround buffer is applied to a
    crew, so the booking is accepted while the saturating one is refused.

    PRD: "Because both windows are treated as half-open, a visit ending exactly at the
    requested `window_start` does not overlap it."

    Design: Difficulty/resource_temporal_overlap/sampling_crew_aggregate_concurrency_with_half_open_adjacency
    """
    ctx = _crew_with_two_overlapping_visits()
    api.create_sampling_visit(_visit(ctx, OVERLAPPING_BOTH), COORDINATOR)

    visit = validate_success(api.create_sampling_visit(_visit(ctx, TOUCHING_VISIT_B), COORDINATOR), 201)
    assert visit["status"] == "SCHEDULED"
    assert visit["window_start"] == TOUCHING_VISIT_B[0]
    assert read_crew(ctx["crew"]["id"])["scheduled_visit_count"] == 3


def test_recording_a_visit_frees_the_concurrency_it_was_holding(api):
    """The refused 11:30-12:30 window becomes bookable the moment visit A is recorded,
    because a recorded visit is no longer `SCHEDULED` and the rule counts only those.

    PRD: "Recording the readings is likewise a `HarvestCoordinator` action and drives the
    visit `SCHEDULED → COMPLETED`."

    Design: Difficulty/resource_temporal_overlap/sampling_crew_aggregate_concurrency_with_half_open_adjacency
    """
    ctx = _crew_with_two_overlapping_visits()
    api.create_sampling_visit(_visit(ctx, OVERLAPPING_BOTH), COORDINATOR)
    validate_success(api.create_sampling_visit(_visit(ctx, TOUCHING_VISIT_B), COORDINATOR), 201)

    record_sampling_visit(
        ctx["visit_a"]["id"], measured_brix=24.5, measured_ta_gl=6.5, measured_ph=3.45, measured_rot_pct=1.0
    )
    recorded = read_sampling_visit(ctx["visit_a"]["id"])
    assert recorded["status"] == "COMPLETED"
    assert recorded["maturity_flag"] == "PICK_READY"

    accepted = validate_success(api.create_sampling_visit(_visit(ctx, OVERLAPPING_BOTH), COORDINATOR), 201)
    assert accepted["status"] == "SCHEDULED"


def test_the_crew_counts_completed_visits_towards_its_workload(api):
    """The concurrency rule ignores the completed visit, but the crew's workload figure
    does not: all four surviving visits are counted.

    PRD: "A crew also exposes a derived `scheduled_visit_count`, the number of its visits
    that are either still scheduled or already completed."

    Design: Difficulty/resource_temporal_overlap/sampling_crew_aggregate_concurrency_with_half_open_adjacency
    """
    ctx = _crew_with_two_overlapping_visits()
    api.create_sampling_visit(_visit(ctx, OVERLAPPING_BOTH), COORDINATOR)
    validate_success(api.create_sampling_visit(_visit(ctx, TOUCHING_VISIT_B), COORDINATOR), 201)
    record_sampling_visit(
        ctx["visit_a"]["id"], measured_brix=24.5, measured_ta_gl=6.5, measured_ph=3.45, measured_rot_pct=1.0
    )
    validate_success(api.create_sampling_visit(_visit(ctx, OVERLAPPING_BOTH), COORDINATOR), 201)

    assert read_crew(ctx["crew"]["id"])["scheduled_visit_count"] == 4
