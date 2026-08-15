"""Corner coverage: exception expiry and waiver lapse, conversion exemption
terminal exclusion, schedule filing gates, account freeze cycle, the repair
return path, the inclusive reopen window, and exception decision lockdown."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_account,
    create_crew,
    create_exception,
    create_pole,
    create_rate_schedule_payload,
    create_ticket,
    dispatch_work_order,
    find_salvage_item_for_pole,
    generate_lines,
    get_pole,
    get_route,
    get_stop,
    get_work_order,
    list_lines,
    list_work_orders_for_route,
    make_citizen_reporter_headers,
    make_field_supervisor_headers,
    make_qa_inspector_headers,
    qc_pass,
    resolve_ticket,
    set_clock,
    setup_cleared_pole,
    setup_effective_rate_schedule,
    setup_program_district_crew,
    setup_released_route,
    triage_and_dispatch_ticket,
    validate_error,
    validate_success,
)

PM = TEST_USERS["program_manager_headers"]
BA = TEST_USERS["billing_analyst_headers"]
CO = TEST_USERS["compliance_officer_headers"]
MUNI_RATES = {"T1": 700, "T2": 1100, "T3": 1500, "T4": 2000, "T5": 2600}


def test_exception_expiry_and_waiver_lapse(api):
    """PRD section 3.8: "Expiry is materialized by any authenticated role once
    the current date has passed valid_until (ERR_EXCEPTION_NOT_EXPIRED before
    then), moving APPROVED -> EXPIRED; dispatch-time waiver evaluation does not
    wait for that materialization and treats a past-valid_until approval as
    expired on its own (§3.4)"; PRD section 3.4: "unless the pole holds an
    APPROVED CCT_WAIVER whose requested_cct_kelvin covers the requested value
    and whose valid_until has not passed".

    Design: Corner/state_machines/sm_exception_expiry_and_waiver_lapse
    """
    program, district, crew = setup_program_district_crew(zone="RESIDENTIAL")
    pole = setup_cleared_pole(program, district, crew, pole_number="EX-1",
                              ownership_type="MUNICIPAL", nameplate_wattage=250,
                              audited_wattage=250)
    exc = create_exception(pole["id"], exception_kind="CCT_WAIVER",
                           requested_cct_kelvin=5000, valid_until="2026-08-10")
    resp = api.approve_compliance_exception(exc["id"], CO)
    validate_success(resp)
    route, stops, wos = setup_released_route(
        program, district, crew, [pole], start="2026-08-03", end="2026-08-08")
    set_clock("2026-08-05T09:00:00Z")

    # refresh before expiry is a state error on the exception
    resp = api.refresh_compliance_exception(exc["id"], CO)
    validate_error(resp, ApiErrorId.ERR_EXCEPTION_NOT_EXPIRED, expected_status=409)

    # dispatch at exactly the waiver ceiling (5000 == requested_cct_kelvin) succeeds
    dispatch_work_order(wos[0]["id"], crew["id"], wattage=90, cct=5000, shielding="FULL_CUTOFF")
    resp = api.complete_work_order(wos[0]["id"], make_field_supervisor_headers(crew["id"]))
    validate_success(resp)

    # after the clock passes valid_until, refresh materializes EXPIRED
    set_clock("2026-08-11T09:00:00Z")
    resp = api.refresh_compliance_exception(exc["id"], CO)
    expired = validate_success(resp)
    assert expired["status"] == "EXPIRED"

    # the lapsed waiver no longer covers a rework dispatch of the same 5000K spec
    api.qc_fail_work_order(wos[0]["id"], make_qa_inspector_headers("qa-1"))
    resp = api.dispatch_work_order(
        wos[0]["id"],
        {"new_fixture_wattage": 90, "new_cct_kelvin": 5000, "shielding": "FULL_CUTOFF"},
        make_field_supervisor_headers(crew["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CCT_EXCEEDS_ZONE_CAP, expected_status=422)
    assert get_work_order(wos[0]["id"])["execution_status"] == "REWORK_PENDING"


def test_conversion_exemption_excludes_pole(api):
    """PRD section 3.8: "Approving a `CONVERSION_EXEMPTION` additionally
    requires the pole to be `AUDIT_CLEARED` (`ERR_POLE_NOT_AUDIT_CLEARED`) and
    moves it `AUDIT_CLEARED` → `EXEMPT`, excluding it from all future
    line-generation runs"; PRD section 3.2: "An `EXEMPT` pole rejects both
    submission and acceptance with `ERR_POLE_EXEMPT`"; PRD section 3.6:
    "reports against an `EXEMPT` pole are refused with `ERR_POLE_EXEMPT`".

    Design: Corner/state_machines/sm_conversion_exemption_excludes_pole
    """
    program, district, crew = setup_program_district_crew(zone="RESIDENTIAL")
    p1 = setup_cleared_pole(program, district, crew, pole_number="XM-1",
                            ownership_type="MUNICIPAL", nameplate_wattage=150,
                            audited_wattage=150, fixture_class="DECORATIVE")
    p2 = create_pole(district["id"], pole_number="XM-2", ownership_type="MUNICIPAL",
                     fixture_class="DECORATIVE", nameplate_wattage=150)  # stays SURVEYED
    setup_effective_rate_schedule(program["id"], "MUNICIPAL", tier_rates=MUNI_RATES)
    acct = create_account(district["id"], "MUNICIPAL", account_number="AC-M")

    # a SURVEYED pole cannot be exempted
    exc2 = create_exception(p2["id"], exception_kind="CONVERSION_EXEMPTION",
                            valid_until="2027-01-01")
    resp = api.approve_compliance_exception(exc2["id"], CO)
    validate_error(resp, ApiErrorId.ERR_POLE_NOT_AUDIT_CLEARED, expected_status=409)

    # approving for the AUDIT_CLEARED pole moves it to EXEMPT
    exc1 = create_exception(p1["id"], exception_kind="CONVERSION_EXEMPTION",
                            valid_until="2027-01-01")
    resp = api.approve_compliance_exception(exc1["id"], CO)
    validate_success(resp)
    assert get_pole(p1["id"])["status"] == "EXEMPT"

    # EXEMPT is terminal for audits and tickets (fresh OCC version passes first)
    pole_now = get_pole(p1["id"])
    resp = api.submit_audit(
        p1["id"],
        {"audited_wattage": 150, "expected_pole_version": pole_now["version"]},
        make_field_supervisor_headers(crew["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_POLE_EXEMPT, expected_status=409)
    resp = api.create_outage_ticket(
        {"pole_id": p1["id"], "description": "dark", "hazard_flag": False},
        make_citizen_reporter_headers("citizen-1"),
    )
    validate_error(resp, ApiErrorId.ERR_POLE_EXEMPT, expected_status=409)

    # EXEMPT p1 excluded from the account's input set; SURVEYED p2 remains billable
    gen = generate_lines(acct["id"])
    assert gen["created_count"] == 1
    line = list_lines(account_id=acct["id"], period="2026-08")[0]
    assert line["pole_id"] == p2["id"]
    assert line["charge_cents"] == 1100  # 150W -> T2
    assert list_lines(pole_id=p1["id"]) == []


def test_schedule_filing_gates(api):
    """PRD section 3.5: "Filing moves `DRAFT` → `FILED`
    (`ERR_RATE_SCHEDULE_NOT_DRAFT` from elsewhere)"; "Activation moves `FILED`
    → `EFFECTIVE` (`ERR_RATE_SCHEDULE_NOT_FILED`). Retirement moves `EFFECTIVE`
    → `SUPERSEDED` (`ERR_RATE_SCHEDULE_NOT_EFFECTIVE`), requires a payload
    `effective_until` after `effective_from` and not before the current date
    (`ERR_INVALID_REQUEST`), and shortens the window to that value."

    Design: Corner/state_machines/sm_schedule_filing_gates
    """
    program, _district, _crew = setup_program_district_crew(zone="RESIDENTIAL")
    resp = api.create_rate_schedule(
        create_rate_schedule_payload(program["id"], ownership_class="MUNICIPAL",
                                     effective_from="2026-01-01", tier_rates=MUNI_RATES),
        BA,
    )
    rs = validate_success(resp, expected_status=201)

    # activate on DRAFT
    resp = api.activate_rate_schedule(rs["id"], BA)
    validate_error(resp, ApiErrorId.ERR_RATE_SCHEDULE_NOT_FILED, expected_status=409)
    # file, then re-file
    resp = api.file_rate_schedule(rs["id"], BA)
    validate_success(resp)
    resp = api.file_rate_schedule(rs["id"], BA)
    validate_error(resp, ApiErrorId.ERR_RATE_SCHEDULE_NOT_DRAFT, expected_status=409)
    # activate, retire, retire again
    api.activate_rate_schedule(rs["id"], BA)
    resp = api.retire_rate_schedule(rs["id"], {"effective_until": "2026-12-01"}, BA)
    retired = validate_success(resp)
    assert retired["status"] == "SUPERSEDED"
    assert retired["effective_until"] == "2026-12-01"
    resp = api.retire_rate_schedule(rs["id"], {"effective_until": "2026-12-15"}, BA)
    validate_error(resp, ApiErrorId.ERR_RATE_SCHEDULE_NOT_EFFECTIVE, expected_status=409)
    # activate after retire
    resp = api.activate_rate_schedule(rs["id"], BA)
    validate_error(resp, ApiErrorId.ERR_RATE_SCHEDULE_NOT_FILED, expected_status=409)
    final = validate_success(api.get_rate_schedule(rs["id"], BA))
    assert final["status"] == "SUPERSEDED" and final["effective_until"] == "2026-12-01"


def test_account_freeze_cycle_gates_generate(api):
    """PRD section 3.5: "Freezing moves OPEN -> FROZEN and unfreezing returns
    it; line generation and period close both require OPEN
    (ERR_ACCOUNT_NOT_OPEN)."

    Design: Corner/state_machines/sm_account_freeze_cycle_gates_generate
    """
    program, district, crew = setup_program_district_crew(zone="RESIDENTIAL")
    setup_cleared_pole(program, district, crew, pole_number="FZ-1",
                       ownership_type="UTILITY_OWNED", nameplate_wattage=250)
    setup_effective_rate_schedule(program["id"], "UTILITY_OWNED")
    acct = create_account(district["id"], "UTILITY_OWNED", account_number="AC-U")

    resp = api.freeze_tariff_account(acct["id"], BA)
    validate_success(resp)
    resp = api.generate_lines(acct["id"], BA)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_OPEN, expected_status=409)

    resp = api.unfreeze_tariff_account(acct["id"], BA)
    validate_success(resp)
    gen = generate_lines(acct["id"])
    assert gen["created_count"] == 1
    line = list_lines(account_id=acct["id"], period="2026-08")[0]
    assert line["charge_cents"] == 1800  # utility T3, no conversion

    # a second freeze/unfreeze cycle is legal
    resp = api.freeze_tariff_account(acct["id"], BA)
    validate_success(resp)
    resp = api.unfreeze_tariff_account(acct["id"], BA)
    reopened = validate_success(resp)
    assert reopened["status"] == "OPEN"


def _setup_blocked_route():
    """Route with stops A(seq1) and B(seq2) IN_PROGRESS; pole A sent
    UNDER_REPAIR via FIXTURE_REPLACED by crew2, blocking stop A and
    auto-suspending the route. Returns (program, route, stop_a, crew2, ticket,
    pole_a, repl_wo)."""
    program, district, crew1 = setup_program_district_crew(zone="ARTERIAL")
    crew2 = create_crew(program["id"], crew_name="Crew-2")
    pa = setup_cleared_pole(program, district, crew1, pole_number="RP-A",
                            ownership_type="MUNICIPAL", nameplate_wattage=250,
                            audited_wattage=250)
    pb = setup_cleared_pole(program, district, crew1, pole_number="RP-B",
                            ownership_type="MUNICIPAL", nameplate_wattage=250,
                            audited_wattage=250)
    route, stops, wos = setup_released_route(
        program, district, crew1, [pa, pb], start="2026-08-10", end="2026-08-12")
    wo_by_pole = {wo["pole_id"]: wo for wo in wos}
    dispatch_work_order(wo_by_pole[pb["id"]]["id"], crew1["id"], wattage=90, cct=3500,
                        shielding="SEMI_CUTOFF")
    ticket = create_ticket(pa["id"], reporter_user_id="citizen-9", description="smashed",
                           hazard_flag=False)
    triage_and_dispatch_ticket(ticket["id"], crew2["id"])
    resolve_ticket(ticket["id"], crew2["id"], resolution_code="FIXTURE_REPLACED")
    resp = api_client.list_work_orders(PM, params={"ticket_id": ticket["id"]})
    repl = resp.json()["data"][0]
    return program, route, stops[0], crew2, ticket, pa, repl


def test_repair_return_unblocks_stop_resume_gate(api):
    """PRD section 3.3: "it requires twice the blocked count to be strictly less
    than stop_count, failing with ERR_ROUTE_STILL_BLOCKED otherwise"; PRD
    section 3.4: "a replacement order returns its pole from UNDER_REPAIR — to
    SCHEDULED when pre_repair_status is SCHEDULED, returning the blocked stop to
    PENDING and recomputing route counters".

    Design: Corner/state_machines/sm_repair_return_unblocks_stop_resume_gate
    """
    _program, route, stop_a, crew2, _ticket, pa, repl = _setup_blocked_route()

    # 1 blocked of 2 stops still meets blocked*2 >= stop_count
    resp = api.resume_route(route["id"], PM)
    validate_error(resp, ApiErrorId.ERR_ROUTE_STILL_BLOCKED, expected_status=409)

    dispatch_work_order(repl["id"], crew2["id"], wattage=90, cct=3500, shielding="SEMI_CUTOFF")
    resp = api.complete_work_order(repl["id"], make_field_supervisor_headers(crew2["id"]))
    validate_success(resp)
    qc_pass(repl["id"])

    pole_after = get_pole(pa["id"])
    assert pole_after["status"] == "SCHEDULED"
    assert pole_after["pre_repair_status"] is None
    assert get_stop(stop_a["id"])["status"] == "PENDING"
    # completion at the default clock -> in-service date 2026-08-01
    assert pole_after["led_in_service_date"] == "2026-08-01"

    resp = api.resume_route(route["id"], PM)
    resumed = validate_success(resp)
    assert resumed["status"] == "IN_PROGRESS"
    assert resumed["blocked_stop_count"] == 0
    assert get_work_order(repl["id"])["qc_status"] == "QC_PASSED"


def test_reopen_window_boundary_inclusive(api):
    """PRD section 3.6: "Reopening is allowed only within 72 hours of
    resolved_at — at exactly 72 hours it still succeeds, later it fails with
    ERR_REOPEN_WINDOW_EXPIRED".

    Design: Corner/state_machines/sm_reopen_window_boundary_inclusive
    """
    program, district, crew = setup_program_district_crew(zone="RESIDENTIAL")
    pole = setup_cleared_pole(program, district, crew, pole_number="RW-1",
                              ownership_type="UTILITY_OWNED", nameplate_wattage=90)
    ticket = create_ticket(pole["id"], reporter_user_id="citizen-1", description="flicker",
                           hazard_flag=False)
    triage_and_dispatch_ticket(ticket["id"], crew["id"])
    set_clock("2026-08-02T00:00:00Z")
    resolve_ticket(ticket["id"], crew["id"], resolution_code="LIGHT_OUT_FIXED")

    # reopen at exactly resolved_at + 72h00m00s succeeds
    set_clock("2026-08-05T00:00:00Z")
    resp = api.reopen_ticket(ticket["id"], make_citizen_reporter_headers("citizen-1"))
    reopened = validate_success(resp)
    assert reopened["status"] == "REOPENED"
    assert reopened["reopen_count"] == 1

    # resolve again, then reopen one second past the second +72h window
    triage_and_dispatch_ticket(ticket["id"], crew["id"])
    set_clock("2026-08-05T01:00:00Z")
    resolve_ticket(ticket["id"], crew["id"], resolution_code="LIGHT_OUT_FIXED")
    set_clock("2026-08-08T01:00:01Z")
    resp = api.reopen_ticket(ticket["id"], make_citizen_reporter_headers("citizen-1"))
    validate_error(resp, ApiErrorId.ERR_REOPEN_WINDOW_EXPIRED, expected_status=422)
    from test_helpers import get_ticket
    assert get_ticket(ticket["id"])["status"] == "RESOLVED"


def test_exception_decision_lockdown(api):
    """PRD section 3.8: "Approval and denial belong to the `ComplianceOfficer`,
    require `REQUESTED` (`ERR_EXCEPTION_NOT_PENDING`), and record
    `decided_by_user_id`".

    Design: Corner/errors/err_exception_decision_lockdown
    """
    program, district, crew = setup_program_district_crew(zone="RESIDENTIAL")
    pole = setup_cleared_pole(program, district, crew, pole_number="DL-1",
                              ownership_type="UTILITY_OWNED", nameplate_wattage=250)
    x1 = create_exception(pole["id"], exception_kind="CCT_WAIVER",
                          requested_cct_kelvin=5000, valid_until="2027-01-01")
    x2 = create_exception(pole["id"], exception_kind="CCT_WAIVER",
                          requested_cct_kelvin=4500, valid_until="2027-01-01")

    resp = api.deny_compliance_exception(x1["id"], CO)
    validate_success(resp)
    # DENIED is terminal
    resp = api.deny_compliance_exception(x1["id"], CO)
    validate_error(resp, ApiErrorId.ERR_EXCEPTION_NOT_PENDING, expected_status=409)
    resp = api.approve_compliance_exception(x1["id"], CO)
    validate_error(resp, ApiErrorId.ERR_EXCEPTION_NOT_PENDING, expected_status=409)

    resp = api.approve_compliance_exception(x2["id"], CO)
    validate_success(resp)
    # APPROVED cannot be denied afterwards
    resp = api.deny_compliance_exception(x2["id"], CO)
    validate_error(resp, ApiErrorId.ERR_EXCEPTION_NOT_PENDING, expected_status=409)

    from test_helpers import get_success_data
    d1 = get_success_data(api.get_compliance_exception(x1["id"], PM))
    d2 = get_success_data(api.get_compliance_exception(x2["id"], PM))
    assert d1["status"] == "DENIED" and d2["status"] == "APPROVED"
