"""Corner coverage: work-order fail auto-requeue, route auto-close bubble-up,
route cancel cascade refunds, stop skip unwinding, and route release/stop-add
gates."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_route,
    dispatch_and_complete,
    dispatch_work_order,
    get_pole,
    get_program,
    get_route,
    get_stop,
    get_work_order,
    list_work_orders_for_route,
    make_field_supervisor_headers,
    qc_pass,
    setup_cleared_pole,
    setup_program_district_crew,
    setup_released_route,
    validate_error,
    validate_success,
)

PM = TEST_USERS["program_manager_headers"]


def test_work_order_fail_auto_requeues_to_pending(api):
    """PRD section 3.4: "Failure moves DISPATCHED -> FAILED, moves no money —
    the estimate stays outstanding — and the system immediately re-queues the
    order FAILED -> PENDING through an automatic retry."

    Design: Corner/state_machines/sm_work_order_fail_auto_requeue
    """
    program, district, crew = setup_program_district_crew(budget=100000, zone="ARTERIAL")
    pole = setup_cleared_pole(program, district, crew, pole_number="F-1",
                              ownership_type="UTILITY_OWNED", nameplate_wattage=250)
    route, stops, wos = setup_released_route(
        program, district, crew, [pole], start="2026-08-03", end="2026-08-03")
    dispatch_work_order(wos[0]["id"], crew["id"], wattage=90, cct=3000, shielding="SEMI_CUTOFF")

    resp = api.fail_work_order(wos[0]["id"], make_field_supervisor_headers(crew["id"]))
    validate_success(resp)
    after = get_work_order(wos[0]["id"])
    # FAILED is transient; the automatic retry re-queues to PENDING
    assert after["execution_status"] == "PENDING"
    # the estimate is NOT refunded on fail
    assert get_program(program["id"])["budget_balance_cents"] == 95500
    assert get_stop(stops[0]["id"])["status"] == "PENDING"
    assert get_pole(pole["id"])["status"] == "SCHEDULED"


def test_route_auto_closes_when_all_stops_terminal_and_qc_decided(api):
    """PRD section 3.3: "A route also closes itself: once every stop is COMPLETE
    or SKIPPED, no linked work order remains in PENDING, DISPATCHED, FAILED, or
    REWORK_PENDING, and no work order stands at AWAITING_QC, the route moves
    IN_PROGRESS -> CLOSED."

    Design: Corner/state_machines/sm_route_auto_close_bubble_up
    """
    program, district, crew = setup_program_district_crew(zone="RESIDENTIAL")
    pole = setup_cleared_pole(program, district, crew, pole_number="AC-1",
                              ownership_type="MUNICIPAL", nameplate_wattage=250,
                              audited_wattage=250)
    route, stops, wos = setup_released_route(
        program, district, crew, [pole], start="2026-08-03", end="2026-08-03")
    dispatch_and_complete(wos[0]["id"], crew["id"], wattage=90, cct=2700,
                          shielding="FULL_CUTOFF")
    # Still IN_PROGRESS while QC is awaited
    assert get_route(route["id"])["status"] == "IN_PROGRESS"
    qc_pass(wos[0]["id"])
    route_after = get_route(route["id"])
    assert route_after["status"] == "CLOSED"
    assert get_stop(stops[0]["id"])["status"] == "COMPLETE"
    assert get_pole(pole["id"])["status"] == "VERIFIED"
    assert get_work_order(wos[0]["id"])["qc_status"] == "QC_PASSED"


def test_route_cancel_cascade_refunds_estimates(api):
    """PRD section 3.3: "From the three later states the cascade additionally
    cancels every non-terminal work order, refunding outstanding estimates per
    the ledger of §2.5" and "From PLANNED the cascade skips every PENDING or
    BLOCKED stop and returns each linked pole still SCHEDULED to AUDIT_CLEARED";
    PRD section 2.5: "Cancelling a DISPATCHED work order credits back
    estimated_labor_cost_cents while the estimate is still outstanding".

    Design: Corner/state_machines/sm_route_cancel_cascade_refunds_estimates
    """
    program, district, crew = setup_program_district_crew(budget=100000, zone="ARTERIAL")
    p1 = setup_cleared_pole(program, district, crew, pole_number="RC-1",
                            ownership_type="UTILITY_OWNED", nameplate_wattage=250)
    p2 = setup_cleared_pole(program, district, crew, pole_number="RC-2",
                            ownership_type="UTILITY_OWNED", nameplate_wattage=250)
    route, stops, wos = setup_released_route(
        program, district, crew, [p1, p2], start="2026-08-03", end="2026-08-04")
    for wo in wos:
        dispatch_work_order(wo["id"], crew["id"], wattage=90, cct=3000, shielding="SEMI_CUTOFF")
    assert get_program(program["id"])["budget_balance_cents"] == 91000  # 100000 - 2*4500

    resp = api.cancel_route(route["id"], PM)
    cancelled = validate_success(resp)
    assert cancelled["status"] == "CANCELLED"
    for wo in wos:
        assert get_work_order(wo["id"])["execution_status"] == "CANCELLED"
    for stop in stops:
        assert get_stop(stop["id"])["status"] == "SKIPPED"
    assert get_pole(p1["id"])["status"] == "AUDIT_CLEARED"
    assert get_pole(p2["id"])["status"] == "AUDIT_CLEARED"
    # both outstanding estimates refunded
    assert get_program(program["id"])["budget_balance_cents"] == 100000


def test_stop_skip_unschedules_pole_and_allows_reroute(api):
    """PRD section 3.3: "skipping cancels the linked PENDING work order with no
    refund — a PENDING order never carried a debit — and returns the pole
    SCHEDULED -> AUDIT_CLEARED"; PRD section 3.3: "[the pole] may not already
    hold a PENDING stop on any non-terminal route (ERR_DUPLICATE_STOP)" — after
    the skip it no longer does.

    Design: Corner/state_machines/sm_stop_skip_unschedules_pole_and_allows_reroute
    """
    program, district, crew = setup_program_district_crew(zone="ARTERIAL")
    pole = setup_cleared_pole(program, district, crew, pole_number="SK-1",
                              ownership_type="UTILITY_OWNED", nameplate_wattage=250)
    route1, stops1, _wos = setup_released_route(
        program, district, crew, [pole], start="2026-08-03", end="2026-08-04")

    resp = api.skip_stop(stops1[0]["id"], PM)
    skipped = validate_success(resp)
    assert skipped["status"] == "SKIPPED"
    assert get_pole(pole["id"])["status"] == "AUDIT_CLEARED"
    resp = api.list_work_orders(PM, params={"stop_id": stops1[0]["id"]})
    linked = resp.json()["data"]
    assert len(linked) == 1 and linked[0]["execution_status"] == "CANCELLED"

    # the same pole is eligible for a later disjoint-window route with the same crew
    route2 = create_route(district["id"], crew["id"], start="2026-08-05", end="2026-08-05")
    resp = api.add_stop(
        route2["id"],
        {"pole_id": pole["id"], "sequence_number": 1, "difficulty_class": "HEAVY"},
        PM,
    )
    stop2 = validate_success(resp, expected_status=201)
    assert stop2["status"] == "PENDING"
    assert stop2["stop_minutes"] == 75
    assert get_pole(pole["id"])["status"] == "SCHEDULED"


def test_route_release_and_stop_add_gates(api):
    """PRD section 3.3: "Release moves PLANNED -> RELEASED — from any other
    state the release is ERR_ROUTE_NOT_PLANNED — and requires at least one
    counted stop (ERR_EMPTY_ROUTE)"; "Stops join a route only while it is
    PLANNED (ERR_ROUTE_NOT_PLANNED)"; "Releasing auto-creates one work order
    per non-SKIPPED stop".

    Design: Corner/state_machines/sm_route_release_and_stop_add_gates
    """
    program, district, crew = setup_program_district_crew(zone="ARTERIAL")
    p1 = setup_cleared_pole(program, district, crew, pole_number="G-1",
                            ownership_type="UTILITY_OWNED", nameplate_wattage=250)
    p2 = setup_cleared_pole(program, district, crew, pole_number="G-2",
                            ownership_type="UTILITY_OWNED", nameplate_wattage=250)
    route = create_route(district["id"], crew["id"], start="2026-08-03", end="2026-08-04")

    # release on an empty route
    resp = api.release_route(route["id"], PM)
    validate_error(resp, ApiErrorId.ERR_EMPTY_ROUTE, expected_status=422)
    assert get_route(route["id"])["status"] == "PLANNED"

    # a stop joins while PLANNED, then release succeeds
    from test_helpers import add_stop
    add_stop(route["id"], p1["id"], 1, difficulty_class="STANDARD")
    resp = api.release_route(route["id"], PM)
    released = validate_success(resp)
    assert released["status"] == "RELEASED"
    wos = list_work_orders_for_route(route["id"])
    assert len(wos) == 1  # one work order auto-created

    # stop-add after release is a state error; pole P2 stays AUDIT_CLEARED
    resp = api.add_stop(
        route["id"],
        {"pole_id": p2["id"], "sequence_number": 2, "difficulty_class": "STANDARD"},
        PM,
    )
    validate_error(resp, ApiErrorId.ERR_ROUTE_NOT_PLANNED, expected_status=409)
    assert get_pole(p2["id"])["status"] == "AUDIT_CLEARED"
