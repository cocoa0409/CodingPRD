"""Dispatch, the spill loop, rescheduling and running the day."""
from test_helpers import (
    ApiErrorId, DISPATCHER,
    api_client, add_stop, arrive_stop, build_config, create_run, create_technician,
    create_van, dispatch_run, make_technician_headers, read_request, read_run, read_stop,
    stage_request, validate_error, validate_paginated, validate_success,
)


def _requests_in_zone(world, count):
    return [stage_request(world, [("CHEF_KNIFE", "ROUTINE_HONE")])[0] for _ in range(count)]


def test_cancelling_a_planned_run_returns_its_requests_to_submitted():
    """PRD 3.10: "Cancelling a whole run is available only from `PLANNED` and moves it
    `PLANNED → CANCELLED`. Every `SCHEDULED` stop on it moves `SCHEDULED → CANCELLED`, each
    affected service request returns `SCHEDULED → SUBMITTED`, and `booked_service_minutes`,
    `scheduled_stop_count` and `committed_minutes_provisional` are all zeroed."

    Design: Corner/state_machines/cancelling_a_planned_run_returns_its_requests_to_submitted
    """
    world = build_config(with_bench=False)
    request, _ = stage_request(world, [("CHEF_KNIFE", "ROUTINE_HONE")])
    run = create_run(world["van"]["id"], world["tech"]["id"])
    stop = add_stop(run["id"], request["id"], sequence=1, arrival_window_start="09:00")

    cancelled = validate_success(api_client.cancel_route_run(run["id"], DISPATCHER))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["booked_service_minutes"] == 0
    assert cancelled["scheduled_stop_count"] == 0
    assert cancelled["committed_minutes_provisional"] == 0
    assert read_stop(stop["id"])["status"] == "CANCELLED"
    assert read_request(request["id"])["status"] == "SUBMITTED"


def test_spilled_stop_reschedules_onto_the_next_eligible_run():
    """PRD 3.5: "Eligible runs are those that are still `PLANNED`, whose `zone_code` equals
    the `zone_code` of the account on the stop, whose `run_date` is strictly later than the
    `run_date` of the run the stop was spilled off, that can take one more stop without
    breaching their `stop_cap`, and whose `committed_minutes_provisional` plus this stop's
    provisional service minutes plus one further 14-minute drive buffer is at most their
    `service_minute_budget`."
    PRD 3.5: "On success the stop moves `SPILLED → SCHEDULED`, its `route_run_id` is
    re-pointed at the chosen run, its minutes are re-booked there, and the service request
    moves `SUBMITTED → SCHEDULED`."
    PRD 3.5: "The stop's new `sequence` is one greater than the largest `sequence` among that
    run's stops in `SCHEDULED`, `ARRIVED` or `SERVICED`, or 1 when the run has none."

    Design: Corner/state_machines/spilled_stop_reschedules_onto_the_next_eligible_run
    """
    world = build_config(with_bench=False)
    request, _ = stage_request(world, [("CHEF_KNIFE", "ROUTINE_HONE")])
    run_a = create_run(world["van"]["id"], world["tech"]["id"], run_date="2026-05-01")
    run_b = create_run(world["van"]["id"], world["tech"]["id"], run_date="2026-05-02")
    stop = add_stop(run_a["id"], request["id"], sequence=1, arrival_window_start="09:00")
    validate_success(api_client.spill_route_stop(stop["id"], DISPATCHER))

    rescheduled = validate_success(api_client.reschedule_route_stop(stop["id"], DISPATCHER))
    assert rescheduled["status"] == "SCHEDULED"
    assert rescheduled["route_run_id"] == run_b["id"]
    assert rescheduled["spilled_from_route_run_id"] == run_a["id"]
    assert rescheduled["spill_hop_count"] == 1
    assert rescheduled["sequence"] == 1
    assert rescheduled["arrival_window_start"] == "08:00"

    reread_b = read_run(run_b["id"])
    assert reread_b["booked_service_minutes"] == 6
    assert reread_b["committed_minutes_provisional"] == 20
    assert read_run(run_a["id"])["booked_service_minutes"] == 0
    assert read_request(request["id"])["status"] == "SCHEDULED"


def test_reschedule_without_a_later_run_reports_an_empty_candidate_pool():
    """PRD 3.5: "Candidates are ranked by `run_date` ascending, with ties broken by the run's
    `created_at` ascending, and the first is chosen. When no run qualifies, the reschedule
    fails with `ERR_NO_ELIGIBLE_RUN`."
    PRD 2.6 rung 50: "The receiving-run candidate pool described in §3.5 is not empty.
    Otherwise `ERR_NO_ELIGIBLE_RUN` (409). Applies to reschedule; pre-empts rungs 51–57."

    Design: Corner/state_machines/reschedule_with_no_later_run_returns_no_eligible_run
    """
    world = build_config(with_bench=False)
    request, _ = stage_request(world, [("CHEF_KNIFE", "ROUTINE_HONE")])
    run_a = create_run(world["van"]["id"], world["tech"]["id"], run_date="2026-05-01")
    stop = add_stop(run_a["id"], request["id"], sequence=1, arrival_window_start="09:00")
    validate_success(api_client.spill_route_stop(stop["id"], DISPATCHER))

    response = api_client.reschedule_route_stop(stop["id"], DISPATCHER)
    validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_RUN.value, 409)

    reread = read_stop(stop["id"])
    assert reread["status"] == "SPILLED"
    assert reread["spill_hop_count"] == 1
    assert read_request(request["id"])["status"] == "SUBMITTED"


def test_dispatching_a_run_with_no_scheduled_stops_is_refused():
    """PRD 3.5: "A run may be dispatched only from `PLANNED`, only when it carries at least
    one stop in `SCHEDULED`, `ARRIVED` or `SERVICED`, and only when its `run_date` is not
    earlier than the logical clock's date."
    PRD 2.6 rung 14: "Examples of preconditions that land on this rung rather than on a rung
    of their own: the clock-versus-`hold_expires_at` comparison on hold expiry, the
    abandonment-grace comparison on abandonment, the at-least-one-scheduled-stop requirement
    on dispatch, the no-stop-still-open requirement on run completion, and the
    every-item-finished requirement on delivery."

    Design: Corner/state_machines/dispatching_a_run_with_no_scheduled_stops_is_refused
    """
    technician = create_technician()
    van = create_van()
    run = validate_success(api_client.create_route_run(
        {"van_id": van["id"], "technician_id": technician["id"], "run_date": "2026-05-01",
         "zone_code": "ZONE_N", "service_minute_budget": 420, "stop_cap": 8}, DISPATCHER), 201)

    response = api_client.dispatch_route_run(run["id"], DISPATCHER)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)

    reread = read_run(run["id"])
    assert reread["status"] == "PLANNED"
    assert reread["committed_minutes_final"] is None


def test_third_spill_of_the_same_stop_is_refused_at_the_hop_cap():
    """PRD 2.6 rung 42: "The stop's `spill_hop_count` plus one is at most 2. Otherwise
    `ERR_SPILL_LIMIT_REACHED` (409). Applies to the explicit spill and to dispatch, whose
    overflow loop can trigger it; pre-empts rungs 43–57."
    PRD 3.5: "A spill that would take the stop past two hops is refused with
    `ERR_SPILL_LIMIT_REACHED`."

    Design: Corner/validations/spill_hop_limit_is_reached_on_the_third_spill
    """
    world = build_config(with_bench=False)
    request, _ = stage_request(world, [("CHEF_KNIFE", "ROUTINE_HONE")])
    run_a = create_run(world["van"]["id"], world["tech"]["id"], run_date="2026-05-01")
    create_run(world["van"]["id"], world["tech"]["id"], run_date="2026-05-02")
    run_c = create_run(world["van"]["id"], world["tech"]["id"], run_date="2026-05-03")
    stop = add_stop(run_a["id"], request["id"], sequence=1, arrival_window_start="09:00")

    validate_success(api_client.spill_route_stop(stop["id"], DISPATCHER))
    validate_success(api_client.reschedule_route_stop(stop["id"], DISPATCHER))
    validate_success(api_client.spill_route_stop(stop["id"], DISPATCHER))
    hopped = validate_success(api_client.reschedule_route_stop(stop["id"], DISPATCHER))
    assert hopped["spill_hop_count"] == 2

    response = api_client.spill_route_stop(stop["id"], DISPATCHER)
    validate_error(response, ApiErrorId.ERR_SPILL_LIMIT_REACHED.value, 409)

    reread = read_stop(stop["id"])
    assert reread["spill_hop_count"] == 2
    assert reread["status"] == "SCHEDULED"
    assert reread["route_run_id"] == run_c["id"]
    assert read_request(request["id"])["status"] == "SCHEDULED"


def test_stop_list_filtered_by_status_returns_only_the_spilled_row():
    """PRD 2.3: "Every list endpoint's declared filter parameters are optional and combine
    conjunctively: supplying two filters returns only rows matching both."
    PRD 4: "Lists stops, filterable by run, request, account, spill origin and status."

    Design: Corner/endpoints/stop_list_filtered_by_status_returns_only_the_spilled_row
    """
    world = build_config(with_bench=False)
    first, second = _requests_in_zone(world, 2)
    run = create_run(world["van"]["id"], world["tech"]["id"])
    stop_one = add_stop(run["id"], first["id"], sequence=1, arrival_window_start="09:00")
    stop_two = add_stop(run["id"], second["id"], sequence=2, arrival_window_start="10:00")
    validate_success(api_client.spill_route_stop(stop_two["id"], DISPATCHER))

    rows, meta = validate_paginated(api_client.list_route_stops(
        DISPATCHER, params={"route_run_id": run["id"], "status": "SPILLED",
                            "limit": 10, "offset": 0}))
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert len(rows) == 1
    assert rows[0]["id"] == stop_two["id"]
    assert read_stop(stop_one["id"])["status"] == "SCHEDULED"


def test_provisional_minutes_charge_only_the_per_stop_drive_buffer():
    """PRD 3.4: "Under the **provisional** variant — recomputed on every stop add, stop
    delete, spill and reschedule while the run is `PLANNED`, and the variant the feasibility
    check at rung 53 tests against — each stop's `stop_service_minutes` is the sum of
    `service_minutes_declared` over its billable items, and `committed_minutes_provisional` is
    `booked_service_minutes` plus 14 minutes of drive buffer for each active stop. No
    return-leg buffer is charged under this variant."

    Design: Difficulty/dual_variant_calc/run_minutes_provisional_vs_dispatch_final
    """
    world = build_config(with_bench=False)
    request, _ = stage_request(
        world, [("CHEF_KNIFE", "ROUTINE_HONE"), ("CHEF_KNIFE", "ROUTINE_HONE")])
    run = create_run(world["van"]["id"], world["tech"]["id"], service_minute_budget=420,
                     stop_cap=8)
    add_stop(run["id"], request["id"], sequence=1, arrival_window_start="09:00")

    before = read_run(run["id"])
    assert before["booked_service_minutes"] == 12
    assert before["committed_minutes_provisional"] == 26
    assert before["committed_minutes_final"] is None


def test_dispatch_final_minutes_add_the_single_return_leg_buffer():
    """PRD 3.4: "Under the **dispatch-final** variant — computed once, at dispatch — each
    stop's `stop_service_minutes` is the sum, over its billable items, of
    `service_minutes_assessed` when that is set and `service_minutes_declared` otherwise, and
    `committed_minutes_final` is `booked_service_minutes` plus 14 minutes of drive buffer for
    each active stop plus a single 25-minute return-leg buffer for the run as a whole."

    Design: Difficulty/dual_variant_calc/run_minutes_provisional_vs_dispatch_final
    """
    world = build_config(with_bench=False)
    request, _ = stage_request(
        world, [("CHEF_KNIFE", "ROUTINE_HONE"), ("CHEF_KNIFE", "ROUTINE_HONE")])
    run = create_run(world["van"]["id"], world["tech"]["id"], service_minute_budget=420,
                     stop_cap=8)
    stop = add_stop(run["id"], request["id"], sequence=1, arrival_window_start="09:00")

    dispatched = dispatch_run(run["id"])
    assert dispatched["status"] == "DISPATCHED"
    assert dispatched["booked_service_minutes"] == 12
    assert dispatched["committed_minutes_provisional"] == 26
    assert dispatched["committed_minutes_final"] == 51
    assert dispatched["committed_minutes_final"] != dispatched["committed_minutes_provisional"]
    assert read_stop(stop["id"])["status"] == "SCHEDULED"


def _three_stop_overbooked_run():
    world = build_config(with_bench=False)
    requests = _requests_in_zone(world, 3)
    run = create_run(world["van"]["id"], world["tech"]["id"], service_minute_budget=70,
                     stop_cap=8)
    stops = []
    for index, request in enumerate(requests):
        stops.append(add_stop(run["id"], request["id"], sequence=index + 1,
                              arrival_window_start=f"{9 + index:02d}:00"))
    return world, requests, run, stops


def test_dispatch_spills_the_greatest_sequence_stop_until_the_budget_fits():
    """PRD 3.5: "If that figure exceeds `service_minute_budget`, the run sheds its tail: the
    `SCHEDULED` stop with the greatest `sequence` is moved to `SPILLED`, its service request
    returns `SCHEDULED → SUBMITTED`, and `committed_minutes_final` is recomputed. That loop
    repeats until the committed figure fits inside the budget."

    Design: Difficulty/combinatorial_formula/dispatch_spill_fixed_point_evaluation_order_mode_c
    """
    _world, _requests, run, stops = _three_stop_overbooked_run()

    dispatched = dispatch_run(run["id"])
    assert dispatched["status"] == "DISPATCHED"
    assert dispatched["committed_minutes_final"] == 65

    third = read_stop(stops[2]["id"])
    assert third["status"] == "SPILLED"
    assert third["spill_hop_count"] == 1
    assert read_stop(stops[1]["id"])["status"] == "SCHEDULED"


def test_dispatch_spill_releases_the_shed_stops_minutes_and_request():
    """PRD 3.5: "Each such spill increments the affected stop's `spill_hop_count`; if any of
    those increments would take a stop past two hops, the entire dispatch fails with
    `ERR_SPILL_LIMIT_REACHED` and nothing is changed."
    PRD 2.10: "A run's `booked_service_minutes` equals the sum of `stop_service_minutes` over
    that run's stops whose status is `SCHEDULED`, `ARRIVED` or `SERVICED`, and its
    `scheduled_stop_count` equals the number of those same stops."

    Design: Difficulty/combinatorial_formula/dispatch_spill_fixed_point_evaluation_order_mode_c
    """
    _world, requests, run, _stops = _three_stop_overbooked_run()

    dispatch_run(run["id"])

    reread = read_run(run["id"])
    assert reread["booked_service_minutes"] == 12
    assert reread["scheduled_stop_count"] == 2
    assert read_request(requests[2]["id"])["status"] == "SUBMITTED"


def test_arrive_is_refused_while_the_parent_run_is_still_planned():
    """PRD 2.6 rung 15: "The parent `RouteRun` is in a status that permits the stop
    operation: `PLANNED` for stop add, stop delete and reschedule; `PLANNED` or `DISPATCHED`
    for spill; `DISPATCHED` or `IN_PROGRESS` for arrival. Otherwise `ERR_RUN_NOT_MUTABLE`
    (409)."

    Design: Difficulty/cross_entity_state_dependency/stop_arrive_blocked_while_parent_run_still_planned
    """
    world = build_config(with_bench=False)
    request, _ = stage_request(world, [("CHEF_KNIFE", "ROUTINE_HONE")])
    run = create_run(world["van"]["id"], world["tech"]["id"])
    stop = add_stop(run["id"], request["id"], sequence=1, arrival_window_start="09:00")

    response = api_client.arrive_route_stop(
        stop["id"], make_technician_headers(world["tech"]["id"]))
    validate_error(response, ApiErrorId.ERR_RUN_NOT_MUTABLE.value, 409)
    assert read_stop(stop["id"])["status"] == "SCHEDULED"
    assert read_run(run["id"])["status"] == "PLANNED"


def test_arrive_succeeds_once_the_run_has_been_dispatched():
    """PRD 3.5: "A `Technician` marks arrival at a stop, which moves it `SCHEDULED → ARRIVED`
    and requires its run to be `DISPATCHED` or `IN_PROGRESS`. The first arrival on a run also
    moves the run itself `DISPATCHED → IN_PROGRESS` and increments the run's `version`; later
    arrivals leave the run's status alone."

    Design: Difficulty/cross_entity_state_dependency/stop_arrive_blocked_while_parent_run_still_planned
    """
    world = build_config(with_bench=False)
    request, _ = stage_request(world, [("CHEF_KNIFE", "ROUTINE_HONE")])
    run = create_run(world["van"]["id"], world["tech"]["id"])
    stop = add_stop(run["id"], request["id"], sequence=1, arrival_window_start="09:00")
    dispatch_run(run["id"])

    arrived = arrive_stop(stop["id"], world["tech"]["id"])
    assert arrived["status"] == "ARRIVED"
    assert read_run(run["id"])["status"] == "IN_PROGRESS"
