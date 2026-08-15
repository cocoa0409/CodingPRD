"""Corner coverage: the salvage batch lifecycle gate family and the savings
report gate family."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    attest_report,
    close_period,
    create_account,
    create_batch,
    create_report,
    dispatch_and_complete,
    find_salvage_item_for_pole,
    get_batch,
    get_program,
    get_report,
    make_auditor_headers,
    make_program_manager_headers,
    setup_cleared_pole,
    setup_program_district_crew,
    setup_released_route,
    submit_report,
    validate_error,
    validate_success,
)

PM = TEST_USERS["program_manager_headers"]
BA = TEST_USERS["billing_analyst_headers"]
CO = TEST_USERS["compliance_officer_headers"]


def _two_salvage_items():
    """Two UTILITY_OWNED poles converted on route 2026-08-02 -> two unbatched
    SalvageItems. Returns (program, item1, item2)."""
    program, district, crew = setup_program_district_crew(zone="RESIDENTIAL")
    p1 = setup_cleared_pole(program, district, crew, pole_number="SB-1",
                            ownership_type="UTILITY_OWNED", nameplate_wattage=250,
                            fixture_class="COBRA_HEAD")
    p2 = setup_cleared_pole(program, district, crew, pole_number="SB-2",
                            ownership_type="UTILITY_OWNED", nameplate_wattage=250,
                            fixture_class="FLOOD")
    route, stops, wos = setup_released_route(
        program, district, crew, [p1, p2], start="2026-08-02", end="2026-08-02")
    for wo in wos:
        dispatch_and_complete(wo["id"], crew["id"], wattage=90, cct=2700,
                              shielding="FULL_CUTOFF")
    return program, find_salvage_item_for_pole(p1["id"]), find_salvage_item_for_pole(p2["id"])


def test_salvage_batch_gate_family(api):
    """PRD section 3.7: "Sealing belongs to the `ComplianceOfficer`, requires
    the batch `ACCUMULATING` (`ERR_BATCH_NOT_ACCUMULATING`) with at least one
    item (`ERR_EMPTY_BATCH`)"; "the item currently unbatched
    (`ERR_SALVAGE_ITEM_ALREADY_BATCHED`)"; "Manifesting requires `SEALED`
    (`ERR_BATCH_NOT_SEALED`) and every item weighed — any `weight_lbs` still
    zero fails with `ERR_UNWEIGHED_ITEMS`"; "Settlement, by a `BillingAnalyst`,
    requires `MANIFESTED` (`ERR_BATCH_NOT_MANIFESTED`)"; "Rejection, by the
    `ComplianceOfficer`, is available from `SEALED` or `MANIFESTED`
    (`ERR_BATCH_NOT_REJECTABLE` otherwise)".

    Design: Corner/state_machines/sm_salvage_batch_gate_family
    """
    program, it1, it2 = _two_salvage_items()
    b1 = create_batch(program["id"], batch_label="B1")
    b2 = create_batch(program["id"], batch_label="B2")

    # seal with item_count == 0
    resp = api.seal_salvage_batch(b1["id"], {"contaminated_flag": False}, CO)
    validate_error(resp, ApiErrorId.ERR_EMPTY_BATCH, expected_status=422)

    resp = api.add_salvage_item(
        b1["id"], {"salvage_item_id": it1["id"], "weight_lbs": 20.0, "mercury_flag": False}, PM)
    validate_success(resp)

    # re-adding an already-batched item to another ACCUMULATING batch
    resp = api.add_salvage_item(
        b2["id"], {"salvage_item_id": it1["id"], "weight_lbs": 20.0, "mercury_flag": False}, PM)
    validate_error(resp, ApiErrorId.ERR_SALVAGE_ITEM_ALREADY_BATCHED, expected_status=409)

    api.seal_salvage_batch(b1["id"], {"contaminated_flag": False}, CO)
    resp = api.manifest_salvage_batch(b1["id"], CO)
    manifested = validate_success(resp)
    # 20.0 lb COBRA_HEAD = rhu(1700) = 1700; 1700 - 4500 transport -> floor at 0
    assert manifested["status"] == "MANIFESTED"
    assert manifested["settlement_value_cents"] == 0

    balance_before = get_program(program["id"])["budget_balance_cents"]
    resp = api.settle_salvage_batch(b1["id"], BA)
    settled = validate_success(resp)
    assert settled["status"] == "SETTLED"
    assert get_program(program["id"])["budget_balance_cents"] == balance_before  # credited 0

    # SETTLED is terminal for reject
    resp = api.reject_salvage_batch(b1["id"], CO)
    validate_error(resp, ApiErrorId.ERR_BATCH_NOT_REJECTABLE, expected_status=409)
    # add after settle
    resp = api.add_salvage_item(
        b1["id"], {"salvage_item_id": it2["id"], "weight_lbs": 30.0}, PM)
    validate_error(resp, ApiErrorId.ERR_BATCH_NOT_ACCUMULATING, expected_status=409)

    # settle requires MANIFESTED (b2 only SEALED)
    resp = api.add_salvage_item(b2["id"], {"salvage_item_id": it2["id"]}, PM)
    validate_success(resp)
    api.seal_salvage_batch(b2["id"], {"contaminated_flag": False}, CO)
    resp = api.settle_salvage_batch(b2["id"], BA)
    validate_error(resp, ApiErrorId.ERR_BATCH_NOT_MANIFESTED, expected_status=409)
    # it2 was added without weight -> still zero at manifest
    resp = api.manifest_salvage_batch(b2["id"], CO)
    validate_error(resp, ApiErrorId.ERR_UNWEIGHED_ITEMS, expected_status=422)


def test_report_gate_family(api):
    """PRD section 3.8: "Submission moves DRAFT -> SUBMITTED (ERR_REPORT_NOT_DRAFT
    otherwise) and requires the books to be closed underneath the period: every
    tariff account of the program must have current_period strictly later than
    the report's period, with no ESTIMATED lines remaining in that period
    (ERR_REPORT_PERIOD_OPEN)"; "Attestation and rejection belong to the Auditor,
    require SUBMITTED (ERR_REPORT_NOT_SUBMITTED)"; "revising it requires
    REJECTED (else ERR_REPORT_NOT_DRAFT)"; "Creation is refused when an
    ATTESTED report already exists for the same program and period
    (ERR_REPORT_PERIOD_FINALIZED)".

    Design: Corner/state_machines/sm_report_gate_family
    """
    program, district, _crew = setup_program_district_crew(zone="RESIDENTIAL")
    acct = create_account(district["id"], "MUNICIPAL", account_number="AC-M")
    rep = create_report(program["id"], period="2026-08", method="METERED_ACTUAL",
                        fiscal_year_label="FY2026", pm_user_id="pm-user-1")

    # attest a DRAFT
    resp = api.attest_savings_report(rep["id"], make_auditor_headers("auditor-1"))
    validate_error(resp, ApiErrorId.ERR_REPORT_NOT_SUBMITTED, expected_status=409)

    # submit while the account is still in period 2026-08
    resp = api.submit_savings_report(rep["id"], make_program_manager_headers("pm-user-1"))
    validate_error(resp, ApiErrorId.ERR_REPORT_PERIOD_OPEN, expected_status=409)

    close_period(acct["id"])
    submit_report(rep["id"], pm_user_id="pm-user-1")

    # second submit
    resp = api.submit_savings_report(rep["id"], make_program_manager_headers("pm-user-1"))
    validate_error(resp, ApiErrorId.ERR_REPORT_NOT_DRAFT, expected_status=409)

    attest_report(rep["id"], auditor_user_id="auditor-1")
    final = get_report(rep["id"])
    assert final["status"] == "ATTESTED"
    assert final["attested_credit_cents"] == 0  # zero savings, zero credit

    # ATTESTED is terminal for revise
    resp = api.revise_savings_report(rep["id"], make_program_manager_headers("pm-user-1"))
    validate_error(resp, ApiErrorId.ERR_REPORT_NOT_DRAFT, expected_status=409)

    # an ATTESTED report blocks new reports for the period
    program_now = get_program(program["id"])
    resp = api.create_savings_report(
        {
            "program_id": program["id"],
            "period": "2026-08",
            "method": "ENGINEERING_ESTIMATE",
            "fiscal_year_label": "FY2026",
            "expected_program_version": program_now["version"],
        },
        make_program_manager_headers("pm-user-1"),
    )
    validate_error(resp, ApiErrorId.ERR_REPORT_PERIOD_FINALIZED, expected_status=409)
