"""Building the day: the route lifecycle, stop placement and the two temporal rules."""

from test_helpers import *  # noqa: F401,F403


def test_route_dispatch_from_draft_is_rejected(api, dispatcher):
    """PRD §3.4: "`PLANNED` moves to `DISPATCHED` only when `committed_units` is at
    least 1 — a route of empty stops is not worth sending out — again with
    `ERR_INVALID_STATE` otherwise and a `version` increment on success."
    PRD §2.7: "**Rung 34, every other state precondition.** The state precondition
    of the target transition must hold for every entity that is neither an
    `Appointment` (covered by gate 5) nor a `Route` in one of gate 2's four guarded
    operations."

    Design: Corner/state_machines/corner_route_dispatch_from_draft_is_rejected
    """
    barn = create_barn()
    farrier = create_farrier()
    route = create_route(farrier["id"], "2026-05-06")
    add_stop(route["id"], barn["id"], 1, 480)

    response = api.dispatch_route(route["id"], dispatcher)

    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)
    assert response.status_code == 409
    assert read_route(route["id"])["status"] == "DRAFT"


def test_cancelled_route_is_terminal_and_rejects_plan(api, dispatcher):
    """PRD §3.4: "Cancellation is available from `DRAFT` and from `PLANNED` and from
    nowhere else: every `PENDING` stop moves to `VOIDED`, every attached appointment
    is detached and returns to `UNROUTED`, every `RESERVED` reservation belonging to
    those appointments moves to `RELEASED`, and the route's `version` increments by
    1."
    PRD §3.4: "`DRAFT` moves to `PLANNED` once the route has at least one stop; a
    planning attempt on a route with no stops, or on a route that is not `DRAFT`, is
    refused with `ERR_INVALID_STATE`, and success increments the route's `version`
    by 1."

    Design: Corner/state_machines/corner_cancelled_route_is_terminal_and_rejects_plan
    """
    barn = create_barn()
    farrier = create_farrier()
    route = create_route(farrier["id"], "2026-05-06")
    stop = add_stop(route["id"], barn["id"], 1, 480)
    cancel_route(route["id"])

    response = api.plan_route(route["id"], dispatcher)

    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)
    assert response.status_code == 409
    assert read_route(route["id"])["status"] == "CANCELLED"
    assert read_stop(stop["id"])["status"] == "VOIDED"


def test_plan_refused_on_a_route_with_no_stops(api, dispatcher):
    """PRD §3.4: "`DRAFT` moves to `PLANNED` once the route has at least one stop; a
    planning attempt on a route with no stops, or on a route that is not `DRAFT`, is
    refused with `ERR_INVALID_STATE`, and success increments the route's `version`
    by 1."
    PRD §3.4: "The route is minted `DRAFT` with `committed_units` 0,
    `committed_minutes` 0 and `stop_count` 0."

    Design: Corner/state_machines/corner_plan_refused_on_a_route_with_no_stops
    """
    farrier = create_farrier()
    route = create_route(farrier["id"], "2026-05-06")

    response = api.plan_route(route["id"], dispatcher)

    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)
    assert response.status_code == 409
    after = read_route(route["id"])
    assert after["stop_count"] == 0
    assert after["status"] == "DRAFT"


def test_stop_at_a_barn_that_does_not_serve_that_weekday_is_rejected(api, dispatcher):
    """PRD §3.4: "The weekday of the route's `route_date` must be one of the barn's
    `served_weekdays`, else `ERR_BARN_WEEKDAY_NOT_SERVED`."
    PRD §2.4: "The weekday token of an ISO date is taken from the proleptic
    Gregorian calendar with `MON` at index 0 through `SUN` at index 6, so that
    2026-05-04 is `MON`."

    Design: Corner/validations/corner_stop_at_a_barn_that_does_not_serve_that_weekday_is_rejected
    """
    barn = create_barn(served_weekdays=["MON"])
    farrier = create_farrier()
    route = create_route(farrier["id"], "2026-05-06")
    assert weekday_token("2026-05-06") == "WED", "the route runs on a Wednesday"

    response = api.create_route_stop(
        route["id"], route_stop_payload(barn["id"], 1, 480), dispatcher
    )

    validate_error(response, ApiErrorId.ERR_BARN_WEEKDAY_NOT_SERVED.value)
    assert response.status_code == 422
    after = read_route(route["id"])
    assert after["stop_count"] == 0
    assert after["committed_minutes"] == 0


def test_stop_on_a_barn_blackout_date_is_rejected(api, dispatcher):
    """PRD §3.4: "The `route_date` must not appear in the barn's `blackout_dates`,
    else `ERR_BARN_BLACKOUT_DATE`."
    PRD §2.7: "(44) The `route_date` is not a member of that barn's
    `blackout_dates`, else `ERR_BARN_BLACKOUT_DATE` (HTTP 422); on stop insertion."

    Design: Corner/validations/corner_stop_on_a_barn_blackout_date_is_rejected
    """
    barn = create_barn(blackout_dates=["2026-05-06"])
    farrier = create_farrier()
    route = create_route(farrier["id"], "2026-05-06")

    response = api.create_route_stop(
        route["id"], route_stop_payload(barn["id"], 1, 480), dispatcher
    )

    validate_error(response, ApiErrorId.ERR_BARN_BLACKOUT_DATE.value)
    assert response.status_code == 422
    assert read_route(route["id"])["stop_count"] == 0


def test_non_contiguous_sequence_index_is_rejected(api, dispatcher):
    """PRD §3.4: "A route may hold fewer than 8 stops (`MAX_STOPS_PER_ROUTE`): the
    insertion is refused with `ERR_VALUE_OUT_OF_RANGE` when the route's `stop_count`
    has already reached 8, and likewise when `sequence_index` is below 1 or above
    the route's current `stop_count` plus one, which is what keeps the ordering
    contiguous."

    Design: Corner/validations/corner_non_contiguous_sequence_index_is_rejected
    """
    barn = create_barn()
    farrier = create_farrier()
    route = create_route(farrier["id"], "2026-05-06")
    add_stop(route["id"], barn["id"], 1, 480)

    response = api.create_route_stop(
        route["id"], route_stop_payload(barn["id"], 3, 700), dispatcher
    )

    validate_error(response, ApiErrorId.ERR_VALUE_OUT_OF_RANGE.value)
    assert response.status_code == 422
    assert read_route(route["id"])["stop_count"] == 1


def test_reorder_swaps_the_two_sequence_indices(api, dispatcher):
    """PRD §3.4: "Reordering moves a stop one place earlier or later. It takes a
    `direction` of `EARLIER` or `LATER` together with a fresh
    `planned_start_minute`, exchanges this stop's `sequence_index` with that of the
    sibling it swaps past, writes the new start minute, and increments the route's
    `version` by 1."
    PRD §3.4: "The route's `committed_minutes` rises by the stop's `travel_minutes`,
    its `stop_count` rises by 1, and its `version` increments by 1."

    Design: Corner/endpoints/corner_reorder_swaps_the_two_sequence_indices
    """
    barn = create_barn()
    farrier = create_farrier()
    route = create_route(farrier["id"], "2026-05-06")
    first = add_stop(route["id"], barn["id"], 1, 480)
    second = add_stop(route["id"], barn["id"], 2, 700)

    # The reorder writes a fresh start minute for the moved stop only; the
    # sibling it swaps past keeps its own 480 and becomes the LATER of the pair,
    # so the buffer rule re-checked here reads 480 >= new_start + 0 service
    # minutes + 15 travel minutes.  420, the barn's access_open_minute, clears it
    # with room to spare; 480 would put both stops at the same minute.
    data = validate_success(
        api.reorder_route_stop(
            second["id"], {"direction": "EARLIER", "planned_start_minute": 420}, dispatcher
        )
    )

    assert_route_stop(data)
    assert data["sequence_index"] == 1
    assert data["planned_start_minute"] == 420
    assert read_stop(first["id"])["sequence_index"] == 2
    after = read_route(route["id"])
    assert after["stop_count"] == 2
    # Two zone A stops carry 15 travel minutes each and no service minutes yet.
    assert after["committed_minutes"] == 2 * STOP_TRAVEL_MINUTES_ZONE_A


# ---------------------------------------------------------------------------
# Containment on the barn's access window
# ---------------------------------------------------------------------------


def _setup_late_stop_world():
    """A zone A barn open 420-1020, one stop starting at 960, and an UNROUTED
    appointment carrying four NEW_SHOES limbs (86 service minutes)."""
    world = setup_reference()
    setup_route_with_stop(world, route_date="2026-05-06", planned_start_minute=960)
    setup_unrouted_visit(
        world, service_type="NEW_SHOES", use_sku=True, scheduled_date="2026-05-06"
    )
    return world


def test_attach_that_would_overrun_the_access_window_is_refused(api, dispatcher):
    """PRD §3.4: "The stop must sit **inside** the barn's access window: its
    `planned_start_minute` must be at least the barn's `access_open_minute`, and its
    `planned_start_minute` plus its `service_minutes` must be at most the barn's
    `access_close_minute`."
    PRD §2.7: "(45) The stop fits inside the barn's access window, else
    `ERR_OUTSIDE_ACCESS_WINDOW` (HTTP 422); on stop insertion, attachment and
    reorder."

    Design: Difficulty/resource_temporal_overlap/stop_must_finish_inside_the_barns_access_window_containment
    """
    world = _setup_late_stop_world()
    # 4 x 20 chair minutes + 6 handling minutes = 86.
    assert world["appointment"]["service_minutes"] == expected_service_minutes(
        ["NEW_SHOES"] * 4, False
    )
    assert world["appointment"]["service_minutes"] == 86
    # 960 + 86 = 1046, past the 1020 close.

    response = attach_response(
        world["stop"]["id"], world["appointment"]["id"], world["route"]["id"]
    )

    validate_error(response, ApiErrorId.ERR_OUTSIDE_ACCESS_WINDOW.value)
    assert response.status_code == 422


def test_refused_access_window_attach_writes_nothing(api, dispatcher):
    """PRD §3.4: "The end boundary is inclusive, so a stop finishing exactly at
    closing time is accepted; anything else is `ERR_OUTSIDE_ACCESS_WINDOW`."
    PRD §3.4: "The stop is minted `PENDING`, its `travel_minutes` is fixed from the
    barn's zone — 15 minutes for zone `A` (`STOP_TRAVEL_MINUTES_ZONE_A`), 30 for
    zone `B` (`STOP_TRAVEL_MINUTES_ZONE_B`) and 50 for zone `C`
    (`STOP_TRAVEL_MINUTES_ZONE_C`) — its `service_minutes` starts at 0, its
    `end_minute` is its `planned_start_minute` plus its `service_minutes`, its
    `trip_fee_cents` starts at 0 and its `billable_horse_count` starts at 0."

    Design: Difficulty/resource_temporal_overlap/stop_must_finish_inside_the_barns_access_window_containment
    """
    world = _setup_late_stop_world()

    response = attach_response(
        world["stop"]["id"], world["appointment"]["id"], world["route"]["id"]
    )
    validate_error(response, ApiErrorId.ERR_OUTSIDE_ACCESS_WINDOW.value)

    stop = read_stop(world["stop"]["id"])
    assert stop["service_minutes"] == 0
    assert stop["end_minute"] == 960
    route = read_route(world["route"]["id"])
    assert route["committed_units"] == 0
    assert route["committed_minutes"] == STOP_TRAVEL_MINUTES_ZONE_A
    assert reservations_for(world["appointment"]["id"]) == []
    assert read_appointment(world["appointment"]["id"])["status"] == "UNROUTED"


# ---------------------------------------------------------------------------
# Buffered adjacency between consecutive stops
# ---------------------------------------------------------------------------


def _setup_route_with_one_full_stop():
    """A zone A stop starting at 480 whose attached 86-minute visit ends it at 566."""
    world = setup_reference()
    setup_route_with_stop(world, route_date="2026-05-06", planned_start_minute=480)
    setup_scheduled_visit(
        world, service_type="NEW_SHOES", use_sku=True, scheduled_date="2026-05-06"
    )
    return world


def test_second_stop_inside_the_travel_buffer_is_refused(api, dispatcher):
    """PRD §3.4: "And consecutive stops must respect the travel buffer: for two
    stops whose `sequence_index` values differ by exactly one, the later stop's
    `planned_start_minute` must be at least the earlier stop's `end_minute` plus the
    **later** stop's own `travel_minutes`."
    PRD §3.4: "Equality is accepted; a start anywhere inside that buffer is
    `ERR_STOP_TIME_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/next_stop_must_clear_predecessor_end_plus_its_own_travel_buffer
    """
    world = _setup_route_with_one_full_stop()
    first = read_stop(world["stop"]["id"])
    assert first["travel_minutes"] == STOP_TRAVEL_MINUTES_ZONE_A
    assert first["end_minute"] == 566, "480 start plus 86 service minutes"

    # The earliest legal start is 566 + 15 = 581; 575 sits inside the buffer.
    response = api.create_route_stop(
        world["route"]["id"], route_stop_payload(world["barn"]["id"], 2, 575), dispatcher
    )

    validate_error(response, ApiErrorId.ERR_STOP_TIME_CONFLICT.value)
    assert response.status_code == 409
    route = read_route(world["route"]["id"])
    assert route["stop_count"] == 1
    assert route["committed_minutes"] == 101, "15 travel minutes plus 86 service minutes"


def test_second_stop_exactly_on_the_travel_buffer_is_accepted(api, dispatcher):
    """PRD §3.4: "And consecutive stops must respect the travel buffer: for two
    stops whose `sequence_index` values differ by exactly one, the later stop's
    `planned_start_minute` must be at least the earlier stop's `end_minute` plus the
    **later** stop's own `travel_minutes`."
    PRD §3.4: "Equality is accepted; a start anywhere inside that buffer is
    `ERR_STOP_TIME_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/next_stop_must_clear_predecessor_end_plus_its_own_travel_buffer
    """
    world = _setup_route_with_one_full_stop()

    data = validate_success(
        api.create_route_stop(
            world["route"]["id"],
            route_stop_payload(world["barn"]["id"], 2, 581),
            dispatcher,
        ),
        201,
    )

    assert_route_stop(data)
    assert data["sequence_index"] == 2
    assert data["planned_start_minute"] == 581
    assert data["travel_minutes"] == STOP_TRAVEL_MINUTES_ZONE_A
    assert data["service_minutes"] == 0
    assert data["end_minute"] == 581
    route = read_route(world["route"]["id"])
    assert route["stop_count"] == 2
    assert route["committed_minutes"] == 116, "101 plus the new stop's 15 travel minutes"
