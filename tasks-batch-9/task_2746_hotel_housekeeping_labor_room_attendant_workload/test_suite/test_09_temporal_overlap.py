"""Overlap arithmetic: half-open room windows, closed rest buffers, aggregate capacity."""

from test_helpers import (
    ASSIGN_COMPLETED,
    ASSIGN_IN_PROGRESS,
    CLEAN_CLEAN,
    CLEAN_IN_SERVICE,
    CYCLE_QUEUED,
    DIRECTOR_HEADERS,
    LAUNDRY_LEAD_HEADERS,
    SERVICE_CHECKOUT,
    ApiErrorId,
    assert_instant_equals,
    assert_is_null,
    assert_linen_buckets,
    assert_whole_minutes,
    assignment_payload,
    build_scenario,
    clock_in,
    complete_payload,
    create_attendant,
    create_roster,
    dispatch_cycle,
    get_success_data,
    laundry_cycle_payload,
    make_room_attendant_headers,
    read_assignment,
    read_linen_item,
    read_room,
    read_roster,
    start_payload,
    validate_error,
    validate_success,
)


# --------------------------------------------------------------------------
# Room windows are half-open
# --------------------------------------------------------------------------


def _one_room_two_attendants(api):
    """One room cleaned to 10:30 by the first attendant, with a second one rostered."""
    scenario = build_scenario(
        api,
        rooms=[{"number": "101", "occupancy_state": "DUE_OUT"}],
        linen={"total_owned_sets": 20},
    )
    first = scenario.clean(
        "101",
        SERVICE_CHECKOUT,
        "2026-08-03T10:00:00.000Z",
        "2026-08-03T10:30:00.000Z",
    )
    other = create_attendant(
        api, scenario.property_id, employee_code="E-702", full_name="Mina Osei"
    )
    roster = create_roster(api, scenario.day_id, other["id"])
    roster = clock_in(api, roster["id"], other["id"])
    second = get_success_data(
        api.create_room_assignment(
            assignment_payload(
                roster["id"],
                scenario.room_id("101"),
                roster["version"],
                SERVICE_CHECKOUT,
            ),
            DIRECTOR_HEADERS,
        )
    )
    return scenario, first, other, second


def test_a_second_attendant_may_take_the_room_at_the_exact_finishing_instant(api):
    """One window ends at 10:30 and the next begins at 10:30, so the two only touch.

    PRD 3.5: "These room intervals are half-open, so one attendant finishing a
    room at 10:30 and another starting the same room at exactly 10:30 is permitted
    — the windows touch but do not overlap."

    Design: Difficulty/resource_temporal_overlap/room_window_half_open_touching_endpoints_allowed_but_one_minute_overlap_refused
    """
    scenario, first, other, second = _one_room_two_attendants(api)
    headers = make_room_attendant_headers(other["id"])
    get_success_data(
        api.start_assignment(
            second["id"], start_payload("2026-08-03T10:30:00.000Z"), headers
        )
    )

    finished = validate_success(
        api.complete_assignment(
            second["id"],
            complete_payload("2026-08-03T11:00:00.000Z"),
            headers,
        ),
        200,
    )

    assert finished["status"] == ASSIGN_COMPLETED
    assert_instant_equals(
        finished["started_at"], "2026-08-03T10:30:00.000Z", "started_at"
    )
    assert_whole_minutes(finished["actual_minutes"], 30, "actual_minutes")
    assert read_assignment(api, first["id"])["status"] == ASSIGN_COMPLETED
    assert read_room(api, scenario.room_id("101"))["cleanliness_status"] == CLEAN_CLEAN


def test_a_one_minute_overlap_on_the_same_room_is_refused(api):
    """Starting at 10:29 puts one minute of the second window inside the first.

    PRD 3.5: "The second is room-level exclusivity: the interval from `started_at`
    up to but not including `completed_at` must not overlap the corresponding
    interval of any other assignment on the **same room** whose `status` is
    `COMPLETED`, `INSPECTED_PASS` or `RECLEAN_REQUIRED`."

    Design: Difficulty/resource_temporal_overlap/room_window_half_open_touching_endpoints_allowed_but_one_minute_overlap_refused
    """
    scenario, _, other, second = _one_room_two_attendants(api)
    headers = make_room_attendant_headers(other["id"])
    get_success_data(
        api.start_assignment(
            second["id"], start_payload("2026-08-03T10:29:00.000Z"), headers
        )
    )

    response = api.complete_assignment(
        second["id"], complete_payload("2026-08-03T11:00:00.000Z"), headers
    )

    validate_error(response, ApiErrorId.ROOM_WINDOW_OVERLAP, 409)
    refused = read_assignment(api, second["id"])
    assert refused["status"] == ASSIGN_IN_PROGRESS
    assert_is_null(refused["completed_at"], "completed_at")
    assert read_room(api, scenario.room_id("101"))["cleanliness_status"] == (
        CLEAN_IN_SERVICE
    )


# --------------------------------------------------------------------------
# The attendant's own windows are closed intervals
# --------------------------------------------------------------------------


def _first_room_finished_at_ten_thirty(api):
    """One attendant, two rooms, the first finished at 10:30 and the second started."""
    scenario = build_scenario(
        api,
        rooms=[
            {"number": "101", "occupancy_state": "DUE_OUT"},
            {"number": "102", "occupancy_state": "DUE_OUT"},
        ],
        linen={"total_owned_sets": 20},
    )
    scenario.clean(
        "101",
        SERVICE_CHECKOUT,
        "2026-08-03T10:00:00.000Z",
        "2026-08-03T10:30:00.000Z",
    )
    return scenario, scenario.assign("102", SERVICE_CHECKOUT)


def test_a_gap_of_exactly_the_rest_buffer_is_admitted(api):
    """The next room may begin at 10:40, exactly ten minutes after the last one ended.

    PRD 3.5: "Back-to-back rooms with no gap therefore violate the rest buffer even
    though the room-level half-open rule would have allowed them, and under the
    default buffer of 10 minutes an attendant who finishes one room at 10:30
    cannot start their next one before 10:40."

    Design: Difficulty/resource_temporal_overlap/attendant_rest_buffer_closed_interval_admits_exact_gap_and_refuses_zero_gap
    """
    scenario, second = _first_room_finished_at_ten_thirty(api)
    scenario.start(second["id"], "2026-08-03T10:40:00.000Z")

    finished = validate_success(
        api.complete_assignment(
            second["id"],
            complete_payload("2026-08-03T11:10:00.000Z"),
            scenario.attendant_headers(),
        ),
        200,
    )

    assert finished["status"] == ASSIGN_COMPLETED
    assert_whole_minutes(finished["actual_minutes"], 30, "actual_minutes")
    roster = read_roster(api, scenario.roster_id)
    assert roster["rooms_completed_gross"] == 2
    assert roster["rooms_credited_net"] == 2


def test_a_zero_gap_between_the_attendants_own_rooms_is_refused(api):
    """Beginning the next room at 10:30 leaves no buffer at all and is refused.

    PRD 3.5: "Expanding the new window by the rest buffer on both sides must leave
    it clear of every other window on the roster; if it touches one, the
    completion is refused with `ERR_REST_BUFFER_VIOLATION` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/attendant_rest_buffer_closed_interval_admits_exact_gap_and_refuses_zero_gap
    """
    scenario, second = _first_room_finished_at_ten_thirty(api)
    scenario.start(second["id"], "2026-08-03T10:30:00.000Z")

    response = api.complete_assignment(
        second["id"],
        complete_payload("2026-08-03T11:00:00.000Z"),
        scenario.attendant_headers(),
    )

    validate_error(response, ApiErrorId.REST_BUFFER_VIOLATION, 409)
    assert read_assignment(api, second["id"])["status"] == ASSIGN_IN_PROGRESS
    assert read_room(api, scenario.room_id("102"))["cleanliness_status"] == (
        CLEAN_IN_SERVICE
    )
    roster = read_roster(api, scenario.roster_id)
    assert roster["rooms_completed_gross"] == 1, (
        "the refused completion must not enter the performed set, got "
        f"{roster['rooms_completed_gross']}"
    )


# --------------------------------------------------------------------------
# Plant capacity is an aggregate of overlapping batches
# --------------------------------------------------------------------------


def _two_overlapping_batches_at_the_plant(api):
    """A 20-set plant holding two overlapping eight-set batches."""
    scenario = build_scenario(
        api,
        property_overrides={"laundry_capacity_sets": 20},
        linen={"total_owned_sets": 40, "initial_soiled_sets": 30},
        with_worker=False,
        with_inspector=False,
        with_day=False,
        with_roster=False,
    )
    dispatch_cycle(
        api,
        scenario.linen_id,
        8,
        "2026-08-03T08:00:00.000Z",
        "2026-08-03T12:00:00.000Z",
        read_linen_item(api, scenario.linen_id)["version"],
    )
    dispatch_cycle(
        api,
        scenario.linen_id,
        8,
        "2026-08-03T10:00:00.000Z",
        "2026-08-03T14:00:00.000Z",
        read_linen_item(api, scenario.linen_id)["version"],
    )
    return scenario


def test_a_third_overlapping_batch_breaches_the_plant_in_aggregate(api):
    """Eight sets are unobjectionable alone, yet twenty-four overlap a twenty-set plant.

    PRD 3.8: "Add the `batch_sets` of every such overlapping cycle to the new
    `batch_sets`; if that sum exceeds the property's `laundry_capacity_sets`, the
    dispatch is refused with `ERR_LAUNDRY_CAPACITY_EXCEEDED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/laundry_plant_capacity_breached_only_by_the_aggregate_of_overlapping_batches
    """
    scenario = _two_overlapping_batches_at_the_plant(api)
    line_before = read_linen_item(api, scenario.linen_id)

    response = api.create_laundry_cycle(
        laundry_cycle_payload(
            scenario.linen_id,
            8,
            "2026-08-03T11:00:00.000Z",
            "2026-08-03T15:00:00.000Z",
            line_before["version"],
        ),
        LAUNDRY_LEAD_HEADERS,
    )

    validate_error(response, ApiErrorId.LAUNDRY_CAPACITY_EXCEEDED, 409)
    line = read_linen_item(api, scenario.linen_id)
    assert_linen_buckets(line, 10, 16, 14)
    assert line["version"] == line_before["version"], (
        "a refused dispatch must not move the linen line's version"
    )


def test_a_batch_whose_window_merely_touches_the_others_is_accepted(api):
    """Dispatching from 14:00 clears both windows, so only its own eight sets count.

    PRD 3.8: "Occupation windows run from `dispatched_at` up to but not including
    `expected_return_at`, so two windows that merely touch at an instant do not
    overlap."

    Design: Difficulty/resource_temporal_overlap/laundry_plant_capacity_breached_only_by_the_aggregate_of_overlapping_batches
    """
    scenario = _two_overlapping_batches_at_the_plant(api)

    cycle = validate_success(
        api.create_laundry_cycle(
            laundry_cycle_payload(
                scenario.linen_id,
                8,
                "2026-08-03T14:00:00.000Z",
                "2026-08-03T18:00:00.000Z",
                read_linen_item(api, scenario.linen_id)["version"],
            ),
            LAUNDRY_LEAD_HEADERS,
        ),
        201,
    )

    assert cycle["status"] == CYCLE_QUEUED
    assert cycle["batch_sets"] == 8
    assert cycle["sla_breach"] is False
    assert_linen_buckets(read_linen_item(api, scenario.linen_id), 10, 24, 6)
