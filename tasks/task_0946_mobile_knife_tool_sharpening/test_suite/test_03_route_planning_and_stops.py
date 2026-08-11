"""Planning a van run and placing stops on it."""
from test_helpers import (
    ApiErrorId, DISPATCHER,
    api_client, add_stop, build_config, create_run, create_technician, create_van,
    read_request, read_run, read_stop, route_stop_payload, set_clock, stage_request,
    validate_error, validate_success, assert_route_run, assert_route_stop,
    assert_route_minute_conservation, list_stops_of_run,
)


def _two_submitted_requests(**config_kwargs):
    world = build_config(with_bench=False, **config_kwargs)
    first, _ = stage_request(world, [("CHEF_KNIFE", "ROUTINE_HONE")])
    second, _ = stage_request(world, [("CHEF_KNIFE", "ROUTINE_HONE")])
    return world, first, second


def test_run_created_without_budgets_inherits_the_vans_defaults():
    """PRD 3.4: "Four inputs are optional and fall back on defaults:
    `service_minute_budget` and `stop_cap` are copied from the chosen van's
    `default_service_minute_budget` and `default_stop_cap` when omitted, and
    `day_window_start` and `day_window_end` default to 08:00 and 17:00 local time
    respectively."
    PRD 3.4: "The run is born `PLANNED` with `scheduled_stop_count`,
    `booked_service_minutes` and `committed_minutes_provisional` all at 0 and
    `committed_minutes_final` null."

    Design: Corner/entities/route_run_omitting_budget_and_cap_copies_van_defaults
    """
    van = create_van(code="VAN-07", default_service_minute_budget=300, default_stop_cap=5)
    technician = create_technician()
    run = validate_success(api_client.create_route_run(
        {"van_id": van["id"], "technician_id": technician["id"],
         "run_date": "2026-05-04", "zone_code": "ZONE_S"}, DISPATCHER), 201)
    assert_route_run(run)
    assert run["service_minute_budget"] == 300
    assert run["stop_cap"] == 5
    assert run["day_window_start"] == "08:00"
    assert run["day_window_end"] == "17:00"
    assert run["status"] == "PLANNED"
    assert run["committed_minutes_final"] is None


def test_stop_cap_refuses_the_second_stop_on_a_one_stop_run():
    """PRD 2.6 rung 52: "The run's `scheduled_stop_count` plus one is at most its
    `stop_cap`. Otherwise `ERR_STOP_CAP_EXCEEDED` (409). Applies to stop addition and
    reschedule; pre-empts rungs 53–57."

    Design: Corner/validations/stop_cap_exceeded_when_the_run_is_capped_at_one_stop
    """
    world, first, second = _two_submitted_requests()
    run = create_run(world["van"]["id"], world["tech"]["id"], service_minute_budget=420,
                     stop_cap=1)
    add_stop(run["id"], first["id"], sequence=1, arrival_window_start="09:00")

    response = api_client.add_route_stop(run["id"], route_stop_payload(
        second["id"], read_run(run["id"])["version"], sequence=2,
        arrival_window_start="11:00"), DISPATCHER)
    validate_error(response, ApiErrorId.ERR_STOP_CAP_EXCEEDED.value, 409)
    assert read_run(run["id"])["scheduled_stop_count"] == 1
    assert read_request(second["id"])["status"] == "SUBMITTED"


def test_run_minute_budget_refuses_the_overshooting_second_stop():
    """PRD 2.6 rung 53: "The run's `committed_minutes_provisional`, recomputed with the new
    stop included, is at most its `service_minute_budget`; equality passes. Otherwise
    `ERR_RUN_MINUTES_EXCEEDED` (409). Applies to stop addition and reschedule; pre-empts
    rungs 54–57."

    Design: Corner/validations/run_minutes_exceeded_when_the_second_stop_overshoots_the_budget
    """
    world, first, second = _two_submitted_requests()
    run = create_run(world["van"]["id"], world["tech"]["id"], service_minute_budget=20,
                     stop_cap=8)
    add_stop(run["id"], first["id"], sequence=1, arrival_window_start="09:00")

    response = api_client.add_route_stop(run["id"], route_stop_payload(
        second["id"], read_run(run["id"])["version"], sequence=2,
        arrival_window_start="11:00"), DISPATCHER)
    validate_error(response, ApiErrorId.ERR_RUN_MINUTES_EXCEEDED.value, 409)
    reread = read_run(run["id"])
    assert reread["committed_minutes_provisional"] == 20
    assert reread["scheduled_stop_count"] == 1


def test_arrival_window_running_past_the_day_end_is_refused():
    """PRD 2.6 rung 33: "The `arrival_window_start` is at or after the run's
    `day_window_start`, and that start plus 60 minutes is at or before the run's
    `day_window_end`. Otherwise `ERR_WINDOW_OUT_OF_DAY` (422). Applies to stop addition and
    reschedule; pre-empts rungs 34–57."

    Design: Corner/validations/arrival_window_running_past_the_day_end_is_refused
    """
    world = build_config(with_bench=False)
    request, _ = stage_request(world, [("CHEF_KNIFE", "ROUTINE_HONE")])
    run = create_run(world["van"]["id"], world["tech"]["id"], service_minute_budget=420,
                     stop_cap=8, day_window_start="08:00", day_window_end="17:00")

    response = api_client.add_route_stop(run["id"], route_stop_payload(
        request["id"], run["version"], sequence=1, arrival_window_start="16:30"), DISPATCHER)
    validate_error(response, ApiErrorId.ERR_WINDOW_OUT_OF_DAY.value, 422)
    assert read_run(run["id"])["scheduled_stop_count"] == 0


def test_planning_a_run_in_the_past_is_refused():
    """PRD 2.6 rung 31: "The `run_date` is not earlier than the logical clock's date.
    Otherwise `ERR_DATE_IN_PAST` (422). Applies to run creation and to dispatch; pre-empts
    rungs 32–57."

    Design: Corner/validations/planning_a_run_in_the_past_is_refused
    """
    technician = create_technician()
    van = create_van()
    set_clock("2026-05-10T00:00:00Z")

    response = api_client.create_route_run(
        {"van_id": van["id"], "technician_id": technician["id"], "run_date": "2026-05-01",
         "zone_code": "ZONE_N", "service_minute_budget": 420, "stop_cap": 8}, DISPATCHER)
    validate_error(response, ApiErrorId.ERR_DATE_IN_PAST.value, 422)


def test_stop_for_an_out_of_zone_account_is_refused():
    """PRD 2.6 rung 27: "The service request's account `zone_code` equals the run's
    `zone_code`. Otherwise `ERR_STOP_ACCOUNT_MISMATCH` (422). Applies to stop addition and
    reschedule; pre-empts rungs 28–57."
    PRD 3.1: "The zone code, by contrast, is load-bearing: a stop may only be placed on a run
    whose `zone_code` equals the account's."

    Design: Corner/validations/stop_in_the_wrong_zone_is_refused
    """
    world = build_config(with_bench=False,
                         account_kwargs={"name": "South Grill", "zone_code": "ZONE_S",
                                         "contact_email": "ops@southgrill.test"})
    request, _ = stage_request(world, [("CHEF_KNIFE", "ROUTINE_HONE")])
    run = create_run(world["van"]["id"], world["tech"]["id"], zone_code="ZONE_N")

    response = api_client.add_route_stop(run["id"], route_stop_payload(
        request["id"], run["version"], sequence=1, arrival_window_start="09:00"), DISPATCHER)
    validate_error(response, ApiErrorId.ERR_STOP_ACCOUNT_MISMATCH.value, 422)
    assert read_request(request["id"])["status"] == "SUBMITTED"


def test_second_stop_add_carrying_the_pre_add_run_version_is_stale():
    """PRD 2.7: "Adding a stop to a route run requires `expected_route_run_version` in the
    request body, carrying the client's last observed `version` of the target `RouteRun`. If
    it does not equal that run's current `version`, the add is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."
    PRD 2.6 rung 12: "The supplied `expected_route_run_version`, `expected_invoice_version` or
    `expected_subscription_version` equals the parent's current `version`. Otherwise
    `ERR_STALE_VERSION` (412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_route_run_version_on_the_second_stop_add
    """
    world, first, second = _two_submitted_requests()
    run = create_run(world["van"]["id"], world["tech"]["id"])
    original_version = run["version"]
    add_stop(run["id"], first["id"], sequence=1, arrival_window_start="09:00",
             expected_route_run_version=original_version)

    response = api_client.add_route_stop(run["id"], route_stop_payload(
        second["id"], original_version, sequence=2, arrival_window_start="10:00"), DISPATCHER)
    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value, 412)

    reread = read_run(run["id"])
    assert reread["scheduled_stop_count"] == 1
    assert reread["booked_service_minutes"] == 6
    assert read_request(second["id"])["status"] == "SUBMITTED"


def test_window_overlap_pre_empts_the_run_minute_budget():
    """PRD 2.6 rung 34: "The half-open interval running from `arrival_window_start` up to but
    not including `arrival_window_end` does not intersect the interval of any stop on the same
    run whose status is `SCHEDULED`, `ARRIVED` or `SERVICED`. Touching endpoints — one window
    ending exactly where another begins — do not intersect and are accepted. Otherwise
    `ERR_WINDOW_OVERLAP` (409). Applies to stop addition and reschedule; pre-empts rungs
    35–57."
    PRD 2.6 rung 53: "The run's `committed_minutes_provisional`, recomputed with the new stop
    included, is at most its `service_minute_budget`; equality passes. Otherwise
    `ERR_RUN_MINUTES_EXCEEDED` (409)."

    Design: Difficulty/priority_pair_validation_conflict/window_overlap_beats_run_minutes_exceeded_on_stop_add
    """
    world, first, second = _two_submitted_requests()
    run = create_run(world["van"]["id"], world["tech"]["id"], service_minute_budget=20,
                     stop_cap=8)
    add_stop(run["id"], first["id"], sequence=1, arrival_window_start="09:00")

    response = api_client.add_route_stop(run["id"], route_stop_payload(
        second["id"], read_run(run["id"])["version"], sequence=2,
        arrival_window_start="09:30"), DISPATCHER)
    error = validate_error(response, ApiErrorId.ERR_WINDOW_OVERLAP.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_RUN_MINUTES_EXCEEDED.value


def test_stop_refused_for_overlap_leaves_the_run_aggregates_at_their_pre_add_values():
    """PRD 2.6 rung 34: "Otherwise `ERR_WINDOW_OVERLAP` (409). Applies to stop addition and
    reschedule; pre-empts rungs 35–57."
    PRD 2.4: "a request that mutates several rows bumps the `version` of each row it actually
    changes, and a request that is rejected bumps nothing."

    Design: Difficulty/priority_pair_validation_conflict/window_overlap_beats_run_minutes_exceeded_on_stop_add
    """
    world, first, second = _two_submitted_requests()
    run = create_run(world["van"]["id"], world["tech"]["id"], service_minute_budget=20,
                     stop_cap=8)
    add_stop(run["id"], first["id"], sequence=1, arrival_window_start="09:00")
    before = read_run(run["id"])

    api_client.add_route_stop(run["id"], route_stop_payload(
        second["id"], before["version"], sequence=2, arrival_window_start="09:30"), DISPATCHER)

    after = read_run(run["id"])
    assert after["committed_minutes_provisional"] == 20
    assert after["scheduled_stop_count"] == 1
    assert after["version"] == before["version"]
    assert read_request(second["id"])["status"] == "SUBMITTED"


def test_stop_is_accepted_when_provisional_minutes_exactly_equal_the_budget():
    """PRD 2.6 rung 53: "The run's `committed_minutes_provisional`, recomputed with the new
    stop included, is at most its `service_minute_budget`; equality passes. Otherwise
    `ERR_RUN_MINUTES_EXCEEDED` (409)."
    PRD 3.4: "each stop's `stop_service_minutes` is the sum of `service_minutes_declared` over
    its billable items, and `committed_minutes_provisional` is `booked_service_minutes` plus
    14 minutes of drive buffer for each active stop."

    Design: Difficulty/boundary_precision_check/run_minutes_exactly_at_budget_is_accepted
    """
    world = build_config(with_bench=False)
    request, _ = stage_request(world, [("CHEF_KNIFE", "ROUTINE_HONE")])
    run = create_run(world["van"]["id"], world["tech"]["id"], service_minute_budget=20,
                     stop_cap=8)

    stop = validate_success(api_client.add_route_stop(run["id"], route_stop_payload(
        request["id"], run["version"], sequence=1, arrival_window_start="09:00"),
        DISPATCHER), 201)
    assert_route_stop(stop)
    reread = read_run(run["id"])
    assert reread["committed_minutes_provisional"] == 20
    assert reread["booked_service_minutes"] == 6
    assert reread["scheduled_stop_count"] == 1


def test_accepted_boundary_stop_derives_its_window_and_schedules_the_request():
    """PRD 3.4: "The stop's `arrival_window_end` is always derived, never supplied: it is the
    start plus 60 minutes, and it is an *exclusive* upper bound."
    PRD 3.4: "On success the request moves `SUBMITTED → SCHEDULED`, the run's aggregates are
    recomputed, and the run's `version` increments."

    Design: Difficulty/boundary_precision_check/run_minutes_exactly_at_budget_is_accepted
    """
    world = build_config(with_bench=False)
    request, _ = stage_request(world, [("CHEF_KNIFE", "ROUTINE_HONE")])
    run = create_run(world["van"]["id"], world["tech"]["id"], service_minute_budget=20,
                     stop_cap=8)

    stop = add_stop(run["id"], request["id"], sequence=1, arrival_window_start="09:00")
    assert stop["stop_service_minutes"] == 6
    assert stop["arrival_window_end"] == "10:00"
    assert read_request(request["id"])["status"] == "SCHEDULED"
    assert read_run(run["id"])["version"] > run["version"]


def test_touching_arrival_windows_are_accepted():
    """PRD 2.6 rung 34: "Touching endpoints — one window ending exactly where another begins
    — do not intersect and are accepted. Otherwise `ERR_WINDOW_OVERLAP` (409)."
    PRD 3.4: "the window must not intersect the window of any stop on the same run whose
    status is `SCHEDULED`, `ARRIVED` or `SERVICED`, where intersection is judged on half-open
    intervals so that two windows merely touching at a boundary are accepted, or
    `ERR_WINDOW_OVERLAP`"

    Design: Difficulty/resource_temporal_overlap/arrival_windows_touch_is_allowed_but_straddle_is_rejected
    """
    world, first, second = _two_submitted_requests()
    run = create_run(world["van"]["id"], world["tech"]["id"], service_minute_budget=420,
                     stop_cap=8, day_window_start="08:00", day_window_end="17:00")
    stop_one = add_stop(run["id"], first["id"], sequence=1, arrival_window_start="09:00")
    stop_two = add_stop(run["id"], second["id"], sequence=2, arrival_window_start="10:00")

    assert stop_one["arrival_window_end"] == "10:00"
    assert read_stop(stop_two["id"])["status"] == "SCHEDULED"
    assert read_run(run["id"])["scheduled_stop_count"] == 2


def test_straddling_arrival_window_is_rejected():
    """PRD 2.6 rung 34: "The half-open interval running from `arrival_window_start` up to but
    not including `arrival_window_end` does not intersect the interval of any stop on the same
    run whose status is `SCHEDULED`, `ARRIVED` or `SERVICED`. Touching endpoints — one window
    ending exactly where another begins — do not intersect and are accepted. Otherwise
    `ERR_WINDOW_OVERLAP` (409)."

    Design: Difficulty/resource_temporal_overlap/arrival_windows_touch_is_allowed_but_straddle_is_rejected
    """
    world = build_config(with_bench=False)
    first, _ = stage_request(world, [("CHEF_KNIFE", "ROUTINE_HONE")])
    second, _ = stage_request(world, [("CHEF_KNIFE", "ROUTINE_HONE")])
    third, _ = stage_request(world, [("CHEF_KNIFE", "ROUTINE_HONE")])
    run = create_run(world["van"]["id"], world["tech"]["id"], service_minute_budget=420,
                     stop_cap=8, day_window_start="08:00", day_window_end="17:00")
    add_stop(run["id"], first["id"], sequence=1, arrival_window_start="09:00")
    add_stop(run["id"], second["id"], sequence=2, arrival_window_start="10:00")

    response = api_client.add_route_stop(run["id"], route_stop_payload(
        third["id"], read_run(run["id"])["version"], sequence=3,
        arrival_window_start="09:30"), DISPATCHER)
    validate_error(response, ApiErrorId.ERR_WINDOW_OVERLAP.value, 409)
    assert read_run(run["id"])["scheduled_stop_count"] == 2
    assert read_request(third["id"])["status"] == "SUBMITTED"


def test_stop_delete_returns_the_run_aggregates_to_their_pre_add_values():
    """PRD 2.10: "A run's `booked_service_minutes` equals the sum of `stop_service_minutes`
    over that run's stops whose status is `SCHEDULED`, `ARRIVED` or `SERVICED`, and its
    `scheduled_stop_count` equals the number of those same stops. Adding a stop and then
    deleting it must return both fields to exactly their pre-add values."

    Design: Difficulty/compensating_invariant/route_minute_conservation_across_stop_add_then_delete
    """
    world = build_config(with_bench=False)
    request, _ = stage_request(world, [("CHEF_KNIFE", "ROUTINE_HONE")])
    run = create_run(world["van"]["id"], world["tech"]["id"], service_minute_budget=420,
                     stop_cap=8)
    stop = add_stop(run["id"], request["id"], sequence=1, arrival_window_start="09:00")
    booked = read_run(run["id"])
    assert booked["booked_service_minutes"] == 6
    assert booked["committed_minutes_provisional"] == 20

    api_client.delete_route_stop(stop["id"], DISPATCHER)

    after = read_run(run["id"])
    assert after["booked_service_minutes"] == 0
    assert after["scheduled_stop_count"] == 0
    assert after["committed_minutes_provisional"] == 0
    assert_route_minute_conservation(after, list_stops_of_run(run["id"]))


def test_stop_delete_answers_204_and_returns_the_request_to_submitted():
    """PRD 3.4: "Deleting a stop is available only while its run is `PLANNED` and the stop is
    `SCHEDULED`. It removes the stop's row, returns the service request `SCHEDULED →
    SUBMITTED`, releases the stop's minutes from `booked_service_minutes` and recomputes
    `scheduled_stop_count` and `committed_minutes_provisional`, and increments the run's
    `version`. It answers with no body at all."
    PRD 4: "every other successful call answers with HTTP 200, with one exception — removing a
    stop from a run answers with HTTP 204 and no body."

    Design: Difficulty/compensating_invariant/route_minute_conservation_across_stop_add_then_delete
    """
    world = build_config(with_bench=False)
    request, _ = stage_request(world, [("CHEF_KNIFE", "ROUTINE_HONE")])
    run = create_run(world["van"]["id"], world["tech"]["id"], service_minute_budget=420,
                     stop_cap=8)
    stop = add_stop(run["id"], request["id"], sequence=1, arrival_window_start="09:00")

    response = api_client.delete_route_stop(stop["id"], DISPATCHER)
    assert response.status_code == 204, (
        f"Expected HTTP 204 with no body on stop removal, got {response.status_code}")
    assert read_request(request["id"])["status"] == "SUBMITTED"
