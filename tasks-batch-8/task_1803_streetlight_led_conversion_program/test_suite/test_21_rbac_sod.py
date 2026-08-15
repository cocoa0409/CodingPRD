"""Corner coverage: role-based access control and segregation of duties."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    close_period,
    create_account,
    create_crew,
    create_pole,
    create_report,
    create_ticket,
    dispatch_and_complete,
    find_salvage_item_for_pole,
    get_pole,
    get_report,
    get_ticket,
    get_work_order,
    list_work_orders_for_route,
    make_auditor_headers,
    make_billing_analyst_headers,
    make_citizen_reporter_headers,
    make_compliance_officer_headers,
    make_field_supervisor_headers,
    make_program_manager_headers,
    make_qa_inspector_headers,
    qc_pass,
    resolve_ticket,
    setup_cleared_pole,
    setup_program_district_crew,
    setup_released_route,
    submit_and_accept_audit,
    submit_report,
    triage_and_dispatch_ticket,
    validate_error,
    validate_success,
)

PM = TEST_USERS["program_manager_headers"]
BA = TEST_USERS["billing_analyst_headers"]
CO = TEST_USERS["compliance_officer_headers"]


def test_creation_ops_cannot_cross_roles(api):
    """PRD section 2.1: "A request whose role is recognized but not permitted
    on the target endpoint is rejected with ERR_FORBIDDEN (403)"; the write
    operations are exclusive to the roles named: ProgramManager "Creates,
    activates, and closes programs; creates districts, poles, crews, routes,
    and route stops"; BillingAnalyst handles "rate schedules".

    Design: Corner/rbac/rbac_creation_ops_cannot_cross_roles
    """
    program, district, _crew = setup_program_district_crew(zone="RESIDENTIAL")

    # CitizenReporter cannot create programs
    resp = api.create_program(
        {"program_name": "X", "program_budget_cents": 1000,
         "fy_rebate_cap_cents": 1000, "rebate_cents_per_kwh": 1},
        make_citizen_reporter_headers("citizen-9"),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
    # Auditor cannot create districts
    resp = api.create_district(
        {"program_id": program["id"], "district_name": "ZZ", "zone": "RURAL"},
        make_auditor_headers("auditor-9"),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
    # QaInspector cannot create rate schedules
    resp = api.create_rate_schedule(
        {"program_id": program["id"], "ownership_class": "MUNICIPAL",
         "effective_from": "2026-01-01",
         "tier_rates": {"T1": 700, "T2": 1100, "T3": 1500, "T4": 2000, "T5": 2600}},
        make_qa_inspector_headers("qa-9"),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
    # BillingAnalyst cannot create crews
    resp = api.create_crew(
        {"program_id": program["id"], "crew_name": "Nope", "base_stops_per_shift": 4,
         "hourly_rate_cents": 5000},
        make_billing_analyst_headers("ba-9"),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    # no side effects (the setup crew is the only crew; every cross-role
    # create above was rejected)
    assert api.list_programs(PM).json()["meta"]["total_count"] == 1
    assert api.list_districts(PM, params={"program_id": program["id"]}).json()["meta"]["total_count"] == 1
    assert api.list_rate_schedules(BA, params={"program_id": program["id"]}).json()["meta"]["total_count"] == 0
    assert api.list_crews(PM, params={"program_id": program["id"]}).json()["meta"]["total_count"] == 1


def test_supervisor_cannot_accept_or_dispute_audit(api):
    """PRD section 2.1: FieldSupervisor "submits and resubmits wattage audits"
    while ProgramManager "accepts and disputes wattage audits" — "the write
    operations enumerated above are exclusive to the roles named", violations
    rejected "with ERR_FORBIDDEN (403)."

    Design: Corner/rbac/rbac_supervisor_cannot_accept_or_dispute_audit
    """
    program, district, crew = setup_program_district_crew(zone="RESIDENTIAL")
    pole = create_pole(district["id"], pole_number="RB-1", ownership_type="MUNICIPAL",
                       fixture_class="COBRA_HEAD", nameplate_wattage=250)
    resp = api.submit_audit(
        pole["id"],
        {"audited_wattage": 250, "expected_pole_version": pole["version"]},
        make_field_supervisor_headers(crew["id"]),
    )
    audit = validate_success(resp, expected_status=201)

    resp = api.accept_audit(audit["id"], make_field_supervisor_headers(crew["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
    resp = api.dispute_audit(audit["id"], make_field_supervisor_headers(crew["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    # control: ProgramManager accept succeeds
    resp = api.accept_audit(audit["id"], PM)
    accepted = validate_success(resp)
    assert accepted["status"] == "ACCEPTED"
    assert get_pole(pole["id"])["status"] == "AUDIT_CLEARED"


def test_work_order_ops_cannot_cross_roles(api):
    """PRD section 2.1: FieldSupervisor "dispatches, completes, and fails work
    orders, and resolves assigned outage tickets"; QaInspector is "an
    independent quality inspector who passes or fails completed work" — "the
    write operations enumerated above are exclusive to the roles named", and a
    request "whose role is recognized but not permitted on the target endpoint
    is rejected with `ERR_FORBIDDEN` (403)."

    Design: Corner/rbac/rbac_work_order_ops_cannot_cross_roles
    """
    program, district, crew = setup_program_district_crew(zone="ARTERIAL")
    pole = setup_cleared_pole(program, district, crew, pole_number="RB-2",
                              ownership_type="UTILITY_OWNED", nameplate_wattage=250)
    route, stops, wos = setup_released_route(
        program, district, crew, [pole], start="2026-08-03", end="2026-08-03")

    # QaInspector cannot dispatch
    resp = api.dispatch_work_order(
        wos[0]["id"],
        {"new_fixture_wattage": 90, "new_cct_kelvin": 3000, "shielding": "SEMI_CUTOFF"},
        make_qa_inspector_headers("qa-1"),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
    # BillingAnalyst cannot complete
    resp = api.complete_work_order(wos[0]["id"], make_billing_analyst_headers("ba-1"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
    # ProgramManager cannot QC-pass
    resp = api.qc_pass_work_order(wos[0]["id"], make_program_manager_headers("pm-1"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    # control: the owning crew dispatches
    resp = api.dispatch_work_order(
        wos[0]["id"],
        {"new_fixture_wattage": 90, "new_cct_kelvin": 3000, "shielding": "SEMI_CUTOFF"},
        make_field_supervisor_headers(crew["id"]),
    )
    assert validate_success(resp)["execution_status"] == "DISPATCHED"


def test_salvage_chain_cannot_cross_roles(api):
    """PRD section 2.1: ComplianceOfficer "seals, manifests, or rejects salvage
    batches"; BillingAnalyst handles "salvage settlement"; ProgramManager
    "creates salvage batches and adds items to them" — exclusive writes,
    violations "rejected with ERR_FORBIDDEN (403)."

    Design: Corner/rbac/rbac_salvage_chain_cannot_cross_roles
    """
    program, district, crew = setup_program_district_crew(zone="RESIDENTIAL")
    pole = setup_cleared_pole(program, district, crew, pole_number="RB-3",
                              ownership_type="UTILITY_OWNED", nameplate_wattage=250)
    route, stops, wos = setup_released_route(
        program, district, crew, [pole], start="2026-08-03", end="2026-08-03")
    dispatch_and_complete(wos[0]["id"], crew["id"], wattage=90, cct=2700,
                          shielding="FULL_CUTOFF")
    item = find_salvage_item_for_pole(pole["id"])
    from test_helpers import create_batch
    batch = create_batch(program["id"], batch_label="B-R")
    resp = api.add_salvage_item(
        batch["id"], {"salvage_item_id": item["id"], "weight_lbs": 25.0}, PM)
    validate_success(resp)

    # BillingAnalyst cannot seal
    resp = api.seal_salvage_batch(batch["id"], {"contaminated_flag": False},
                                  make_billing_analyst_headers("ba-1"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
    resp = api.seal_salvage_batch(batch["id"], {"contaminated_flag": False}, CO)
    validate_success(resp)

    # ProgramManager cannot manifest
    resp = api.manifest_salvage_batch(batch["id"], make_program_manager_headers("pm-1"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
    resp = api.manifest_salvage_batch(batch["id"], CO)
    validate_success(resp)

    # ComplianceOfficer cannot settle
    resp = api.settle_salvage_batch(batch["id"], make_compliance_officer_headers("co-1"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
    resp = api.settle_salvage_batch(batch["id"], BA)
    settled = validate_success(resp)
    assert settled["status"] == "SETTLED"
    # 25.0 * 85 = 2125; 2125 - 4500 transport -> floor at 0
    assert settled["settlement_value_cents"] == 0


def test_reporter_cannot_verify_or_reopen_others_ticket(api):
    """PRD section 2.1: CitizenReporter — "the verify and reopen operations
    compare X-User-ID against that recorded reporter, rejecting anyone else
    with ERR_FORBIDDEN"; PRD section 3.6: "The reporter alone closes the loop."

    Design: Corner/rbac/rbac_reporter_cannot_verify_or_reopen_others_ticket
    """
    program, district, crew = setup_program_district_crew(zone="RESIDENTIAL")
    pole = setup_cleared_pole(program, district, crew, pole_number="RB-4",
                              ownership_type="UTILITY_OWNED", nameplate_wattage=90)
    ticket = create_ticket(pole["id"], reporter_user_id="citizen-1", description="out",
                           hazard_flag=False)
    triage_and_dispatch_ticket(ticket["id"], crew["id"])
    resolve_ticket(ticket["id"], crew["id"], resolution_code="LIGHT_OUT_FIXED")

    resp = api.verify_ticket(ticket["id"], make_citizen_reporter_headers("citizen-2"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
    resp = api.reopen_ticket(ticket["id"], make_citizen_reporter_headers("citizen-2"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    resp = api.verify_ticket(ticket["id"], make_citizen_reporter_headers("citizen-1"))
    verified = validate_success(resp)
    assert verified["status"] == "VERIFIED"


def test_supervisor_cannot_dispatch_other_crews_order(api):
    """PRD section 2.1: "When X-User-Role is FieldSupervisor, X-User-ID is the
    id of the acting Crew; ownership checks on any resource that references a
    Crew compare the resource's foreign-key field to X-User-ID — concretely, a
    work order's crew_id at dispatch, completion, and failure ... and a
    mismatch is rejected with ERR_FORBIDDEN."

    Design: Corner/rbac/rbac_supervisor_cannot_dispatch_other_crews_order
    """
    program, district, crew1 = setup_program_district_crew(zone="ARTERIAL")
    crew2 = create_crew(program["id"], crew_name="Crew-2")
    pole = setup_cleared_pole(program, district, crew1, pole_number="RB-5",
                              ownership_type="UTILITY_OWNED", nameplate_wattage=250)
    route, stops, wos = setup_released_route(
        program, district, crew1, [pole], start="2026-08-03", end="2026-08-03")

    resp = api.dispatch_work_order(
        wos[0]["id"],
        {"new_fixture_wattage": 90, "new_cct_kelvin": 3000, "shielding": "SEMI_CUTOFF"},
        make_field_supervisor_headers(crew2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    resp = api.dispatch_work_order(
        wos[0]["id"],
        {"new_fixture_wattage": 90, "new_cct_kelvin": 3000, "shielding": "SEMI_CUTOFF"},
        make_field_supervisor_headers(crew1["id"]),
    )
    assert validate_success(resp)["execution_status"] == "DISPATCHED"


def test_manager_cannot_attest_and_auditor_cannot_submit(api):
    """PRD section 2.1: Auditor — "an external savings verifier who attests or
    rejects submitted savings reports"; ProgramManager "prepares and revises
    savings reports" — exclusive writes, violations "rejected with
    ERR_FORBIDDEN (403)."

    Design: Corner/rbac/rbac_manager_cannot_attest_and_auditor_cannot_submit
    """
    program, district, _crew = setup_program_district_crew(zone="RESIDENTIAL")
    acct = create_account(district["id"], "MUNICIPAL", account_number="AC-M")
    close_period(acct["id"])
    r1 = create_report(program["id"], period="2026-08", method="METERED_ACTUAL",
                       fiscal_year_label="FY2026", pm_user_id="pm-user-1")
    submit_report(r1["id"], pm_user_id="pm-user-1")
    r2 = create_report(program["id"], period="2026-07", method="METERED_ACTUAL",
                       fiscal_year_label="FY2026", pm_user_id="pm-user-1")

    # ProgramManager (even a different one than the submitter) cannot attest
    resp = api.attest_savings_report(r1["id"], make_program_manager_headers("pm-user-2"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
    # Auditor cannot submit
    resp = api.submit_savings_report(r2["id"], make_auditor_headers("auditor-1"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    # control: the Auditor attests the submitted report (zero savings -> 0 credit)
    resp = api.attest_savings_report(r1["id"], make_auditor_headers("auditor-1"))
    attested = validate_success(resp)
    assert attested["status"] == "ATTESTED"
    assert attested["attested_credit_cents"] == 0


def test_sod_completer_cannot_qc_own_work(api):
    """PRD section 3.4: "may not be decided by the user recorded as
    performed_by_user_id (ERR_SEGREGATION_OF_DUTIES)"; PRD section 2.1: "for a
    FieldSupervisor, that is their crew's id".

    Design: Corner/rbac/sod_completer_cannot_qc_own_work
    """
    program, district, crew = setup_program_district_crew(zone="RESIDENTIAL")
    pole = setup_cleared_pole(program, district, crew, pole_number="SD-1",
                              ownership_type="UTILITY_OWNED", nameplate_wattage=250)
    route, stops, wos = setup_released_route(
        program, district, crew, [pole], start="2026-08-03", end="2026-08-03")
    dispatch_and_complete(wos[0]["id"], crew["id"], wattage=90, cct=2700,
                          shielding="FULL_CUTOFF")

    # a QaInspector whose X-User-ID equals the completer's user id (the crew id)
    resp = api.qc_pass_work_order(wos[0]["id"], make_qa_inspector_headers(crew["id"]))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)

    # a different inspector passes
    resp = api.qc_pass_work_order(wos[0]["id"], make_qa_inspector_headers("qa-77"))
    passed = validate_success(resp)
    assert passed["qc_status"] == "QC_PASSED"
    assert get_pole(pole["id"])["status"] == "VERIFIED"


def test_sod_submitter_cannot_attest_own_report(api):
    """PRD section 3.8: "Attestation and rejection belong to the Auditor,
    require SUBMITTED (ERR_REPORT_NOT_SUBMITTED), and may not come from the
    submitting user (ERR_SEGREGATION_OF_DUTIES)."

    Design: Corner/rbac/sod_submitter_cannot_attest_own_report
    """
    program, district, _crew = setup_program_district_crew(zone="RESIDENTIAL")
    acct = create_account(district["id"], "MUNICIPAL", account_number="AC-M")
    close_period(acct["id"])
    rep = create_report(program["id"], period="2026-08", method="METERED_ACTUAL",
                        fiscal_year_label="FY2026", pm_user_id="pm-user-1")
    submit_report(rep["id"], pm_user_id="pm-user-1")

    # an Auditor carrying the SAME X-User-ID as the submitter is rejected on both
    resp = api.attest_savings_report(rep["id"], make_auditor_headers("pm-user-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)
    resp = api.reject_savings_report(rep["id"], make_auditor_headers("pm-user-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)

    resp = api.attest_savings_report(rep["id"], make_auditor_headers("auditor-9"))
    attested = validate_success(resp)
    assert attested["status"] == "ATTESTED"
    assert attested["attested_by_user_id"] == "auditor-9"
