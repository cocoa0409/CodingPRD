"""Corner coverage: error gates — duplicate account, ownership-referential
audit/attest rejections, program-not-active, unauthenticated, the 404 sweep,
independent state gates, work-order/stop state gates, and temporal gates."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    add_stop,
    api_client,
    create_account,
    create_active_program,
    create_batch,
    create_crew,
    create_district,
    create_pole,
    create_program,
    create_route,
    create_ticket,
    dispatch_work_order,
    get_pole,
    make_citizen_reporter_headers,
    make_field_supervisor_headers,
    make_qa_inspector_headers,
    set_clock,
    setup_cleared_pole,
    setup_program_district_crew,
    setup_released_route,
    submit_and_accept_audit,
    validate_error,
    validate_success,
)

PM = TEST_USERS["program_manager_headers"]
BA = TEST_USERS["billing_analyst_headers"]
CO = TEST_USERS["compliance_officer_headers"]


def test_duplicate_account_rejected(api):
    """PRD section 3.5: "Unmetered accounts are one per district and ownership
    class: creating one takes district_id, the utility's account_number —
    unique within the program — and ownership_class, and a second OPEN or
    FROZEN account for the same district and class is refused with
    ERR_DUPLICATE_ACCOUNT."

    Design: Corner/errors/err_duplicate_account_rejected
    """
    program, district, _crew = setup_program_district_crew(zone="RESIDENTIAL")
    create_account(district["id"], "MUNICIPAL", account_number="AC-1")

    resp = api.create_tariff_account(
        {"district_id": district["id"], "account_number": "AC-2",
         "ownership_class": "MUNICIPAL"},
        BA,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACCOUNT, expected_status=409)

    # a UTILITY_OWNED account in the SAME district coexists
    resp = api.create_tariff_account(
        {"district_id": district["id"], "account_number": "AC-3",
         "ownership_class": "UTILITY_OWNED"},
        BA,
    )
    validate_success(resp, expected_status=201)
    resp = api.list_tariff_accounts(BA, params={"district_id": district["id"]})
    assert resp.json()["meta"]["total_count"] == 2


def test_utility_audit_and_municipal_attest_rejected(api):
    """PRD section 3.2: "Audits exist only for MUNICIPAL poles: submitting one
    against a UTILITY_OWNED pole is ERR_AUDIT_NOT_PERMITTED_UTILITY"; PRD
    section 3.1: "a BillingAnalyst attests the nameplate and the pole moves
    SURVEYED -> AUDIT_CLEARED with no audit at all; attempting that attestation
    on a MUNICIPAL pole is rejected with ERR_ATTEST_NOT_PERMITTED_MUNICIPAL."

    Design: Corner/errors/err_utility_audit_municipal_attest_rejected
    """
    program, district, crew = setup_program_district_crew(zone="RESIDENTIAL")
    up = setup_cleared_pole(program, district, crew, pole_number="UA-1",
                            ownership_type="UTILITY_OWNED", nameplate_wattage=250)
    mp = create_pole(district["id"], pole_number="UA-2", ownership_type="MUNICIPAL",
                     fixture_class="COBRA_HEAD", nameplate_wattage=250)

    up_now = get_pole(up["id"])
    resp = api.submit_audit(
        up["id"],
        {"audited_wattage": 250, "expected_pole_version": up_now["version"]},
        make_field_supervisor_headers(crew["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_AUDIT_NOT_PERMITTED_UTILITY, expected_status=422)
    resp = api.list_audits(PM, params={"pole_id": up["id"]})
    assert resp.json()["meta"]["total_count"] == 0

    resp = api.attest_nameplate(mp["id"], BA)
    validate_error(resp, ApiErrorId.ERR_ATTEST_NOT_PERMITTED_MUNICIPAL, expected_status=422)
    assert get_pole(mp["id"])["status"] == "SURVEYED"


def test_program_not_active_blocks_child_mutation(api):
    """PRD section 3.1: "Every child-resource mutation in the system requires
    the program to be ACTIVE — while DRAFT or CLOSED, such mutations fail with
    ERR_PROGRAM_NOT_ACTIVE."

    Design: Corner/errors/err_program_not_active_blocks_child_mutation
    """
    program = create_program()  # left DRAFT
    resp = api.create_district(
        {"program_id": program["id"], "district_name": "D1", "zone": "RESIDENTIAL"}, PM
    )
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_ACTIVE, expected_status=409)
    resp = api.list_districts(PM, params={"program_id": program["id"]})
    assert resp.json()["meta"]["total_count"] == 0


def test_unauthenticated_missing_auth_headers_returns_401(api):
    """PRD section 2.1: "Every request must carry two headers: X-User-ID,
    identifying the acting user, and X-User-Role, naming the role under which
    the user acts. A request missing either header, or presenting a role the
    system does not declare, is rejected with ERR_UNAUTHENTICATED (401)."

    Design: Corner/errors/err_unauthenticated_missing_auth_headers_returns_401
    """
    resp = api.list_programs(headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)
    assert resp.json()["response_type"] == "error"


def test_resource_not_found_sweep(api):
    """PRD section 2.9: "Each missing resource yields its own 404: an unknown
    program id yields ERR_PROGRAM_NOT_FOUND, district ERR_DISTRICT_NOT_FOUND,
    pole ERR_POLE_NOT_FOUND, audit ERR_AUDIT_NOT_FOUND, crew
    ERR_CREW_NOT_FOUND, route ERR_ROUTE_NOT_FOUND, route stop
    ERR_STOP_NOT_FOUND, work order ERR_WORK_ORDER_NOT_FOUND, rate schedule
    ERR_RATE_SCHEDULE_NOT_FOUND, tariff account ERR_ACCOUNT_NOT_FOUND, billing
    line ERR_BILLING_LINE_NOT_FOUND, outage ticket ERR_TICKET_NOT_FOUND,
    salvage batch ERR_BATCH_NOT_FOUND, salvage item ERR_SALVAGE_ITEM_NOT_FOUND,
    savings report ERR_REPORT_NOT_FOUND, and compliance exception
    ERR_EXCEPTION_NOT_FOUND."

    Design: Corner/errors/err_resource_not_found_sweep
    """
    cases = [
        (lambda: api.get_program(NON_EXISTENT_UUID, PM), ApiErrorId.ERR_PROGRAM_NOT_FOUND),
        (lambda: api.get_district(NON_EXISTENT_UUID, PM), ApiErrorId.ERR_DISTRICT_NOT_FOUND),
        (lambda: api.get_audit(NON_EXISTENT_UUID, PM), ApiErrorId.ERR_AUDIT_NOT_FOUND),
        (lambda: api.get_crew(NON_EXISTENT_UUID, PM), ApiErrorId.ERR_CREW_NOT_FOUND),
        (lambda: api.release_route(NON_EXISTENT_UUID, PM), ApiErrorId.ERR_ROUTE_NOT_FOUND),
        (lambda: api.get_stop(NON_EXISTENT_UUID, PM), ApiErrorId.ERR_STOP_NOT_FOUND),
        (lambda: api.get_rate_schedule(NON_EXISTENT_UUID, BA),
         ApiErrorId.ERR_RATE_SCHEDULE_NOT_FOUND),
        (lambda: api.get_tariff_account(NON_EXISTENT_UUID, BA),
         ApiErrorId.ERR_ACCOUNT_NOT_FOUND),
        (lambda: api.get_billing_line(NON_EXISTENT_UUID, BA),
         ApiErrorId.ERR_BILLING_LINE_NOT_FOUND),
        (lambda: api.get_outage_ticket(NON_EXISTENT_UUID,
                                       make_citizen_reporter_headers("citizen-1")),
         ApiErrorId.ERR_TICKET_NOT_FOUND),
        (lambda: api.get_salvage_batch(NON_EXISTENT_UUID, PM), ApiErrorId.ERR_BATCH_NOT_FOUND),
        (lambda: api.get_salvage_item(NON_EXISTENT_UUID, PM),
         ApiErrorId.ERR_SALVAGE_ITEM_NOT_FOUND),
        (lambda: api.get_savings_report(NON_EXISTENT_UUID, PM),
         ApiErrorId.ERR_REPORT_NOT_FOUND),
        (lambda: api.get_compliance_exception(NON_EXISTENT_UUID, CO),
         ApiErrorId.ERR_EXCEPTION_NOT_FOUND),
    ]
    for call, expected in cases:
        resp = call()
        validate_error(resp, expected, expected_status=404)
        assert resp.json()["response_type"] == "error", f"{expected} envelope"


def test_state_gate_sweep(api):
    """PRD section 3.2: "Acceptance belongs to the ProgramManager and requires
    the audit SUBMITTED (ERR_AUDIT_NOT_SUBMITTED otherwise)"; PRD section 3.6:
    "Dispatch, again the ProgramManager, moves TRIAGED -> DISPATCHED
    (ERR_TICKET_NOT_TRIAGED)"; PRD section 3.7: "Manifesting requires SEALED
    (ERR_BATCH_NOT_SEALED)"; PRD section 3.3: "resuming a route that is not
    SUSPENDED, is ERR_ROUTE_NOT_SUSPENDED"; PRD section 3.1: "closure ... is
    refused with ERR_ROUTES_STILL_ACTIVE while any of the program's routes is
    in a state other than CLOSED or CANCELLED."

    Design: Corner/errors/err_state_gate_sweep
    """
    program, district, crew = setup_program_district_crew(zone="RESIDENTIAL")
    pole = create_pole(district["id"], pole_number="GS-1", ownership_type="MUNICIPAL",
                       fixture_class="COBRA_HEAD", nameplate_wattage=250)
    submit_and_accept_audit(pole["id"], 250, crew["id"])
    route = create_route(district["id"], crew["id"], start="2026-08-03", end="2026-08-03")
    add_stop(route["id"], pole["id"], 1, difficulty_class="STANDARD")

    # a second audit, disputed
    pole_now = get_pole(pole["id"])
    resp = api.submit_audit(
        pole["id"],
        {"audited_wattage": 240, "expected_pole_version": pole_now["version"]},
        make_field_supervisor_headers(crew["id"]),
    )
    aud2 = validate_success(resp, expected_status=201)
    api.dispute_audit(aud2["id"], PM)

    ticket = create_ticket(pole["id"], reporter_user_id="citizen-1", description="dim",
                           hazard_flag=False)
    batch = create_batch(program["id"], batch_label="B-G")

    # accept on a DISPUTED audit
    resp = api.accept_audit(aud2["id"], PM)
    validate_error(resp, ApiErrorId.ERR_AUDIT_NOT_SUBMITTED, expected_status=409)
    # ticket dispatch before triage
    resp = api.dispatch_ticket(ticket["id"], {"crew_id": crew["id"]}, PM)
    validate_error(resp, ApiErrorId.ERR_TICKET_NOT_TRIAGED, expected_status=409)
    # manifest on an ACCUMULATING batch
    resp = api.manifest_salvage_batch(batch["id"], CO)
    validate_error(resp, ApiErrorId.ERR_BATCH_NOT_SEALED, expected_status=409)
    # resume on a PLANNED route
    resp = api.resume_route(route["id"], PM)
    validate_error(resp, ApiErrorId.ERR_ROUTE_NOT_SUSPENDED, expected_status=409)
    # program close with a live route
    resp = api.close_program(program["id"], PM)
    validate_error(resp, ApiErrorId.ERR_ROUTES_STILL_ACTIVE, expected_status=409)

    # nothing moved
    from test_helpers import get_audit, get_batch, get_program, get_route, get_ticket
    assert get_audit(aud2["id"])["status"] == "DISPUTED"
    assert get_ticket(ticket["id"])["status"] == "OPEN"
    assert get_batch(batch["id"])["status"] == "ACCUMULATING"
    assert get_route(route["id"])["status"] == "PLANNED"
    assert get_program(program["id"])["status"] == "ACTIVE"


def test_work_order_and_stop_state_gates(api):
    """PRD section 3.4: "completing or failing from any state other than
    DISPATCHED is ERR_WORK_ORDER_NOT_COMPLETABLE"; "Quality control belongs to
    the QaInspector, requires execution COMPLETED with QC AWAITING_QC
    (ERR_QC_NOT_AWAITING otherwise, including a wrong QC state)";
    "Cancellation by a ProgramManager requires PENDING, DISPATCHED, or
    REWORK_PENDING (ERR_WORK_ORDER_NOT_CANCELLABLE)"; PRD section 3.3: "An
    individual PENDING stop may be skipped by a ProgramManager provided no
    DISPATCHED or COMPLETED work order is linked to it (ERR_STOP_NOT_PENDING)".

    Design: Corner/errors/err_work_order_and_stop_state_gates
    """
    program, district, crew = setup_program_district_crew(zone="RESIDENTIAL")
    pole = setup_cleared_pole(program, district, crew, pole_number="GS-2",
                              ownership_type="MUNICIPAL", nameplate_wattage=250,
                              audited_wattage=250)
    route, stops, wos = setup_released_route(
        program, district, crew, [pole], start="2026-08-03", end="2026-08-05")

    # complete on PENDING
    resp = api.complete_work_order(wos[0]["id"], make_field_supervisor_headers(crew["id"]))
    validate_error(resp, ApiErrorId.ERR_WORK_ORDER_NOT_COMPLETABLE, expected_status=409)
    # qc-pass before any completion
    resp = api.qc_pass_work_order(wos[0]["id"], make_qa_inspector_headers("qa-1"))
    validate_error(resp, ApiErrorId.ERR_QC_NOT_AWAITING, expected_status=409)

    dispatch_work_order(wos[0]["id"], crew["id"], wattage=90, cct=2700,
                        shielding="FULL_CUTOFF")
    resp = api.complete_work_order(wos[0]["id"], make_field_supervisor_headers(crew["id"]))
    completed = validate_success(resp)
    assert completed["execution_status"] == "COMPLETED"

    # cancel after COMPLETED
    resp = api.cancel_work_order(wos[0]["id"], PM)
    validate_error(resp, ApiErrorId.ERR_WORK_ORDER_NOT_CANCELLABLE, expected_status=409)
    # skip on a COMPLETE stop
    resp = api.skip_stop(stops[0]["id"], PM)
    validate_error(resp, ApiErrorId.ERR_STOP_NOT_PENDING, expected_status=409)


def test_temporal_gates_window_past(api):
    """PRD section 3.3: "Stops join a route only while it is PLANNED ... and
    only while its window_start_date has not yet passed relative to the logical
    clock (ERR_ROUTE_WINDOW_PAST)"; PRD section 3.8: "valid_until, which must
    not be before the current date either at request or at approval
    (ERR_EXCEPTION_WINDOW_PAST)."

    Design: Corner/errors/err_temporal_gates_window_past
    """
    program, district, crew = setup_program_district_crew(zone="ARTERIAL")
    pole = setup_cleared_pole(program, district, crew, pole_number="TG-1",
                              ownership_type="UTILITY_OWNED", nameplate_wattage=250)
    route = create_route(district["id"], crew["id"], start="2026-08-02", end="2026-08-02")
    set_clock("2026-08-03T00:00:00Z")  # window start now in the past

    resp = api.add_stop(
        route["id"],
        {"pole_id": pole["id"], "sequence_number": 1, "difficulty_class": "STANDARD"},
        PM,
    )
    validate_error(resp, ApiErrorId.ERR_ROUTE_WINDOW_PAST, expected_status=422)
    assert get_pole(pole["id"])["status"] == "AUDIT_CLEARED"

    resp = api.create_compliance_exception(
        {"pole_id": pole["id"], "exception_kind": "CCT_WAIVER",
         "requested_cct_kelvin": 5000, "valid_until": "2026-08-01"},
        PM,
    )
    validate_error(resp, ApiErrorId.ERR_EXCEPTION_WINDOW_PAST, expected_status=422)
    resp = api.list_compliance_exceptions(PM, params={"pole_id": pole["id"]})
    assert resp.json()["meta"]["total_count"] == 0
