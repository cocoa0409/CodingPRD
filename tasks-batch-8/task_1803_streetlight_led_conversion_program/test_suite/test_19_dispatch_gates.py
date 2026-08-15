"""Corner coverage: dispatch and stop-add business gates surfacing alone —
fiscal budget, wattage reduction boundary, shielding, active work order
across replacement orders, cross-district stop, duplicate sequence/stop,
and the blocked-stop dispatch gate."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_stop,
    create_active_program,
    create_crew,
    create_district,
    create_route,
    create_ticket,
    dispatch_and_complete,
    dispatch_work_order,
    get_pole,
    get_program,
    get_route,
    get_stop,
    get_work_order,
    list_work_orders_for_route,
    make_citizen_reporter_headers,
    make_field_supervisor_headers,
    qc_pass,
    resolve_ticket,
    setup_cleared_pole,
    setup_program_district_crew,
    setup_released_route,
    triage_and_dispatch_ticket,
    validate_error,
    validate_success,
)

PM = TEST_USERS["program_manager_headers"]


def test_fiscal_budget_exceeded_surfaces_alone(api):
    """PRD section 3.4: "Finally the fiscal gate: the straight-time estimate
    estimated_labor_cost_cents — the crew's hourly_rate_cents multiplied by the
    order's stop_minutes and divided by 60, rounded half-up — must not exceed
    the program's budget_balance_cents (ERR_PROGRAM_BUDGET_EXCEEDED)."

    Design: Corner/errors/err_fiscal_budget_exceeded_surfaces_alone
    """
    program, district, crew = setup_program_district_crew(budget=4000, zone="ARTERIAL")
    pole = setup_cleared_pole(program, district, crew, pole_number="FB-1",
                              ownership_type="UTILITY_OWNED", nameplate_wattage=250)
    route, stops, wos = setup_released_route(
        program, district, crew, [pole], start="2026-08-03", end="2026-08-03")

    # STANDARD stop: estimate rhu(6000*45/60) = 4500 > 4000 balance
    resp = api.dispatch_work_order(
        wos[0]["id"],
        {"new_fixture_wattage": 90, "new_cct_kelvin": 3000, "shielding": "SEMI_CUTOFF"},
        make_field_supervisor_headers(crew["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PROGRAM_BUDGET_EXCEEDED, expected_status=402)
    assert get_work_order(wos[0]["id"])["execution_status"] == "PENDING"
    assert get_program(program["id"])["budget_balance_cents"] == 4000


def test_wattage_reduction_boundary_surfaces_alone(api):
    """PRD section 3.4: "Then the wattage-reduction gate: five times
    new_fixture_wattage must not exceed four times the pole's effective_wattage
    — at least a twenty percent reduction, with exactly eighty percent of the
    old wattage allowed (ERR_INSUFFICIENT_WATTAGE_REDUCTION)."

    Design: Corner/errors/err_wattage_reduction_boundary_surfaces_alone
    """
    program, district, crew = setup_program_district_crew(zone="RESIDENTIAL")
    pole = setup_cleared_pole(program, district, crew, pole_number="WR-1",
                              ownership_type="MUNICIPAL", nameplate_wattage=250,
                              audited_wattage=250)
    route, stops, wos = setup_released_route(
        program, district, crew, [pole], start="2026-08-03", end="2026-08-03")

    # 240W vs 250W effective: 240*5 = 1200 > 1000 = 250*4 (only 4% reduction)
    resp = api.dispatch_work_order(
        wos[0]["id"],
        {"new_fixture_wattage": 240, "new_cct_kelvin": 2700, "shielding": "FULL_CUTOFF"},
        make_field_supervisor_headers(crew["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_WATTAGE_REDUCTION, expected_status=422)

    # exactly 80% of 250 is allowed: 200*5 == 250*4
    resp = api.dispatch_work_order(
        wos[0]["id"],
        {"new_fixture_wattage": 200, "new_cct_kelvin": 2700, "shielding": "FULL_CUTOFF"},
        make_field_supervisor_headers(crew["id"]),
    )
    dispatched = validate_success(resp)
    assert dispatched["execution_status"] == "DISPATCHED"
    assert dispatched["new_fixture_wattage"] == 200


def test_shielding_required_residential_zone(api):
    """PRD section 3.4: "Then shielding: in a district where
    `full_cutoff_required` is true, only `FULL_CUTOFF` is accepted
    (`ERR_SHIELDING_REQUIRED`)"; PRD section 2.6: "Its `full_cutoff_required`
    flag is true in `RESIDENTIAL` and `RURAL` districts".

    Design: Corner/errors/err_shielding_required_residential_zone
    """
    program, district, crew = setup_program_district_crew(zone="RESIDENTIAL")
    pole = setup_cleared_pole(program, district, crew, pole_number="SH-1",
                              ownership_type="MUNICIPAL", nameplate_wattage=250,
                              audited_wattage=250)
    route, stops, wos = setup_released_route(
        program, district, crew, [pole], start="2026-08-03", end="2026-08-03")

    resp = api.dispatch_work_order(
        wos[0]["id"],
        {"new_fixture_wattage": 90, "new_cct_kelvin": 2700, "shielding": "SEMI_CUTOFF"},
        make_field_supervisor_headers(crew["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SHIELDING_REQUIRED, expected_status=422)

    resp = api.dispatch_work_order(
        wos[0]["id"],
        {"new_fixture_wattage": 90, "new_cct_kelvin": 2700, "shielding": "FULL_CUTOFF"},
        make_field_supervisor_headers(crew["id"]),
    )
    dispatched = validate_success(resp)
    assert dispatched["execution_status"] == "DISPATCHED"


def test_active_work_order_exists_via_replacement(api):
    """PRD section 3.4: "Then exclusivity: no other work order for the same
    pole may be DISPATCHED (ERR_ACTIVE_WORK_ORDER_EXISTS)."

    Design: Corner/errors/err_active_work_order_exists_via_replacement
    """
    program, district, crew = setup_program_district_crew(zone="ARTERIAL")
    pole = setup_cleared_pole(program, district, crew, pole_number="AW-1",
                              ownership_type="MUNICIPAL", nameplate_wattage=250,
                              audited_wattage=250)
    route, stops, wos = setup_released_route(
        program, district, crew, [pole], start="2026-08-03", end="2026-08-03")
    dispatch_and_complete(wos[0]["id"], crew["id"], wattage=90, cct=3500,
                          shielding="SEMI_CUTOFF")
    qc_pass(wos[0]["id"])
    assert get_pole(pole["id"])["status"] == "VERIFIED"

    # first outage cycle: replacement order repl1 created and dispatched
    t1 = create_ticket(pole["id"], reporter_user_id="citizen-1",
                       description="dead after storm", hazard_flag=False)
    triage_and_dispatch_ticket(t1["id"], crew["id"])
    resolve_ticket(t1["id"], crew["id"], resolution_code="FIXTURE_REPLACED")
    resp = api.list_work_orders(PM, params={"ticket_id": t1["id"]})
    repl1 = resp.json()["data"][0]
    dispatch_work_order(repl1["id"], crew["id"], wattage=85, cct=3500, shielding="SEMI_CUTOFF")
    # verify t1 so the next report is not auto-duplicated
    resp = api.verify_ticket(t1["id"], make_citizen_reporter_headers("citizen-1"))
    validate_success(resp)

    # second outage cycle spawns repl2 while repl1 is DISPATCHED
    t2 = create_ticket(pole["id"], reporter_user_id="citizen-2", description="dead again",
                       hazard_flag=False)
    triage_and_dispatch_ticket(t2["id"], crew["id"])
    resolve_ticket(t2["id"], crew["id"], resolution_code="FIXTURE_REPLACED")
    resp = api.list_work_orders(PM, params={"ticket_id": t2["id"]})
    repl2 = resp.json()["data"][0]

    resp = api.dispatch_work_order(
        repl2["id"],
        {"new_fixture_wattage": 85, "new_cct_kelvin": 3500, "shielding": "SEMI_CUTOFF"},
        make_field_supervisor_headers(crew["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ACTIVE_WORK_ORDER_EXISTS, expected_status=409)
    assert get_work_order(repl2["id"])["execution_status"] == "PENDING"
    assert get_work_order(repl1["id"])["execution_status"] == "DISPATCHED"
    assert get_work_order(repl1["id"])["is_replacement"] is True
    assert get_work_order(repl2["id"])["is_replacement"] is True
    assert get_pole(pole["id"])["status"] == "UNDER_REPAIR"


def test_cross_district_stop_rejected(api):
    """PRD section 3.3: "The pole must live in the route's own district
    (ERR_CROSS_DISTRICT_STOP)".

    Design: Corner/errors/err_cross_district_stop_rejected
    """
    program = create_active_program()
    dist_a = create_district(program["id"], zone="ARTERIAL", district_name="DA")
    dist_b = create_district(program["id"], zone="RESIDENTIAL", district_name="DB")
    crew = create_crew(program["id"])
    pole = setup_cleared_pole(program, dist_a, crew, pole_number="CD-1",
                              ownership_type="UTILITY_OWNED", nameplate_wattage=250)
    route = create_route(dist_b["id"], crew["id"], start="2026-08-03", end="2026-08-03")

    resp = api.add_stop(
        route["id"],
        {"pole_id": pole["id"], "sequence_number": 1, "difficulty_class": "STANDARD"},
        PM,
    )
    validate_error(resp, ApiErrorId.ERR_CROSS_DISTRICT_STOP, expected_status=422)
    assert get_pole(pole["id"])["status"] == "AUDIT_CLEARED"
    assert get_route(route["id"])["stop_count"] == 0


def test_duplicate_sequence_and_duplicate_stop(api):
    """PRD section 3.3: "a sequence_number greater than zero that is unique
    within the route (ERR_DUPLICATE_SEQUENCE)"; "[the pole] may not already
    hold a PENDING stop on any non-terminal route (ERR_DUPLICATE_STOP)".

    Design: Corner/errors/err_duplicate_sequence_and_duplicate_stop
    """
    program, district, crew = setup_program_district_crew(zone="ARTERIAL")
    q1 = setup_cleared_pole(program, district, crew, pole_number="DS-1",
                            ownership_type="UTILITY_OWNED", nameplate_wattage=250)
    q2 = setup_cleared_pole(program, district, crew, pole_number="DS-2",
                            ownership_type="UTILITY_OWNED", nameplate_wattage=250)
    route = create_route(district["id"], crew["id"], start="2026-08-03", end="2026-08-05")
    add_stop(route["id"], q1["id"], 1, difficulty_class="STANDARD")

    # same sequence, different pole
    resp = api.add_stop(
        route["id"],
        {"pole_id": q2["id"], "sequence_number": 1, "difficulty_class": "STANDARD"},
        PM,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SEQUENCE, expected_status=409)

    # same pole, fresh sequence
    resp = api.add_stop(
        route["id"],
        {"pole_id": q1["id"], "sequence_number": 2, "difficulty_class": "STANDARD"},
        PM,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_STOP, expected_status=409)

    # the clean combination (new pole, free sequence) succeeds
    resp = api.add_stop(
        route["id"],
        {"pole_id": q2["id"], "sequence_number": 2, "difficulty_class": "STANDARD"},
        PM,
    )
    validate_success(resp, expected_status=201)
    assert get_route(route["id"])["stop_count"] == 2


def test_stop_blocked_dispatch_gate(api):
    """PRD section 3.4: "The linked stop, when present, must be PENDING
    (ERR_STOP_BLOCKED)"; PRD section 3.3: "The comparison is made on the
    doubled count, so exactly half blocked suspends (two blocked of four does)
    while one blocked of three does not."

    Design: Corner/errors/err_stop_blocked_dispatch_gate
    """
    program, district, crew1 = setup_program_district_crew(zone="ARTERIAL")
    crew2 = create_crew(program["id"], crew_name="Crew-2")
    pa = setup_cleared_pole(program, district, crew1, pole_number="SB-1",
                            ownership_type="MUNICIPAL", nameplate_wattage=250,
                            audited_wattage=250)
    pb = setup_cleared_pole(program, district, crew1, pole_number="SB-2",
                            ownership_type="MUNICIPAL", nameplate_wattage=250,
                            audited_wattage=250)
    pc = setup_cleared_pole(program, district, crew1, pole_number="SB-3",
                            ownership_type="MUNICIPAL", nameplate_wattage=250,
                            audited_wattage=250)
    route, stops, wos = setup_released_route(
        program, district, crew1, [pa, pb, pc], start="2026-08-10", end="2026-08-12")
    wo_by_pole = {wo["pole_id"]: wo for wo in wos}
    dispatch_work_order(wo_by_pole[pb["id"]]["id"], crew1["id"], wattage=90, cct=3500,
                        shielding="SEMI_CUTOFF")

    # pole A -> UNDER_REPAIR via FIXTURE_REPLACED, blocking stop 1 only
    ticket = create_ticket(pa["id"], reporter_user_id="citizen-9",
                           description="broken bracket", hazard_flag=False)
    triage_and_dispatch_ticket(ticket["id"], crew2["id"])
    resolve_ticket(ticket["id"], crew2["id"], resolution_code="FIXTURE_REPLACED")
    assert get_stop(stops[0]["id"])["status"] == "BLOCKED"

    # 1 blocked of 3 does NOT suspend: route stays IN_PROGRESS
    route_after = get_route(route["id"])
    assert route_after["status"] == "IN_PROGRESS"

    # the blocked stop's work order is reachable: dispatch fails ERR_STOP_BLOCKED
    resp = api.dispatch_work_order(
        wo_by_pole[pa["id"]]["id"],
        {"new_fixture_wattage": 90, "new_cct_kelvin": 3500, "shielding": "SEMI_CUTOFF"},
        make_field_supervisor_headers(crew1["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STOP_BLOCKED, expected_status=409)
    assert get_work_order(wo_by_pole[pa["id"]]["id"])["execution_status"] == "PENDING"
    # pole B's work order is untouched
    assert get_work_order(wo_by_pole[pb["id"]]["id"])["execution_status"] == "DISPATCHED"
