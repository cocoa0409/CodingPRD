"""Corner coverage: optimistic concurrency validations — existence before
ownership, OCC before state, and the audit/report stale-version cycles."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_active_program,
    create_exception,
    create_pole,
    create_report,
    get_pole,
    get_report,
    make_field_supervisor_headers,
    setup_cleared_pole,
    setup_program_district_crew,
    validate_error,
    validate_success,
)

PM = TEST_USERS["program_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]


def test_existence_before_state_dispatch_not_found(api):
    """PRD section 2.10: "4. Existence: path and body identifiers resolve, per
    §2.9" precedes "5. Ownership identity: crew and reporter checks per §2.1";
    PRD section 2.9: "Each missing resource yields its own 404: ... work order
    ERR_WORK_ORDER_NOT_FOUND".

    Design: Corner/validations/val_existence_before_state_dispatch_not_found
    """
    program, _district, _crew = setup_program_district_crew(zone="RESIDENTIAL")
    # well-formed but nonexistent work-order id; caller's crew id ALSO unknown.
    # Path-id existence (priority 4) precedes ownership (priority 5).
    resp = api.dispatch_work_order(
        NON_EXISTENT_UUID,
        {"new_fixture_wattage": 90, "new_cct_kelvin": 2700, "shielding": "FULL_CUTOFF"},
        make_field_supervisor_headers("00000000-0000-0000-0000-000000000001"),
    )
    validate_error(resp, ApiErrorId.ERR_WORK_ORDER_NOT_FOUND, expected_status=404)


def test_occ_stale_version_beats_pole_exempt_state(api):
    """PRD section 2.10: "7. Staleness: the OCC version fields of §2.8, else
    ERR_STALE_VERSION" precedes "9. Target state"; PRD section 3.2: "An EXEMPT
    pole rejects both submission and acceptance with ERR_POLE_EXEMPT."

    Design: Corner/validations/val_occ_stale_version_beats_pole_exempt_state
    """
    program, district, crew = setup_program_district_crew(zone="RESIDENTIAL")
    pole = setup_cleared_pole(program, district, crew, pole_number="OC-1",
                              ownership_type="MUNICIPAL", nameplate_wattage=250,
                              audited_wattage=250)
    exc = create_exception(pole["id"], exception_kind="CONVERSION_EXEMPTION",
                           valid_until="2027-01-01")
    resp = api.approve_compliance_exception(exc["id"], CO)
    validate_success(resp)
    pole_now = get_pole(pole["id"])
    assert pole_now["status"] == "EXEMPT"
    fresh_version = pole_now["version"]

    # stale version never reaches the EXEMPT state check
    resp = api.submit_audit(
        pole["id"],
        {"audited_wattage": 240, "expected_pole_version": fresh_version - 1},
        make_field_supervisor_headers(crew["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    # fresh version passes OCC and hits the state gate
    resp = api.submit_audit(
        pole["id"],
        {"audited_wattage": 240, "expected_pole_version": fresh_version},
        make_field_supervisor_headers(crew["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_POLE_EXEMPT, expected_status=409)

    # neither rejected submit created an audit (only the first accepted one exists)
    resp = api.list_audits(PM, params={"pole_id": pole["id"]})
    assert resp.json()["meta"]["total_count"] == 1


def test_audit_occ_stale_then_fresh_submit(api):
    """PRD section 2.8: "A request to create a wattage audit
    (POST /streetlights/poles/{poleId}/audits) must carry expected_pole_version,
    the client's last observed version of the target pole. If the pole's
    current version has advanced past that value — for example because an
    earlier audit submission or acceptance already bumped it — the create is
    rejected with ERR_STALE_VERSION (HTTP 412). Audit submission otherwise
    succeeds under natural product semantics whenever no other audit is
    pending, so this version check is the only rejection that distinguishes a
    stale client's request."

    Design: Corner/validations/val_audit_occ_stale_then_fresh_submit
    """
    program, district, crew = setup_program_district_crew(zone="RESIDENTIAL")
    pole = create_pole(district["id"], pole_number="OC-2", ownership_type="MUNICIPAL",
                       fixture_class="COBRA_HEAD", nameplate_wattage=250)
    v1 = pole["version"]

    # first submit with version 1 succeeds
    resp = api.submit_audit(
        pole["id"],
        {"audited_wattage": 260, "expected_pole_version": v1},
        make_field_supervisor_headers(crew["id"]),
    )
    aud_a = validate_success(resp, expected_status=201)
    assert aud_a["status"] == "SUBMITTED"

    # dispute A so no audit is pending
    resp = api.dispute_audit(aud_a["id"], PM)
    validate_success(resp)

    # a second submit carrying the pre-submission version trips OCC even though
    # the natural semantics (no pending audit) would allow it
    resp = api.submit_audit(
        pole["id"],
        {"audited_wattage": 240, "expected_pole_version": v1},
        make_field_supervisor_headers(crew["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    # re-read and resubmit with the fresh version succeeds
    v2 = get_pole(pole["id"])["version"]
    resp = api.submit_audit(
        pole["id"],
        {"audited_wattage": 240, "expected_pole_version": v2},
        make_field_supervisor_headers(crew["id"]),
    )
    aud_b = validate_success(resp, expected_status=201)
    assert aud_b["status"] == "SUBMITTED"


def test_report_occ_stale_then_legitimate_supersede(api):
    """PRD section 2.8: "A request to create a savings report
    (POST /streetlights/savings-reports) must likewise carry
    expected_program_version matching the program's current version. Creating a
    report legitimately supersedes the prior DRAFT or REJECTED report of the
    same period (§3.8), so a create issued with a fresh version would itself
    succeed; only a mismatched expected_program_version is rejected, again with
    ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/validations/val_report_occ_stale_then_legitimate_supersede
    """
    program, _district, _crew = setup_program_district_crew(zone="RESIDENTIAL")
    from test_helpers import get_program
    pv1 = get_program(program["id"])["version"]
    r1 = create_report(program["id"], period="2026-08", method="METERED_ACTUAL",
                       fiscal_year_label="FY2026", pm_user_id="pm-user-1")

    # version captured before R1's creation is stale after it
    resp = api.create_savings_report(
        {
            "program_id": program["id"],
            "period": "2026-08",
            "method": "ENGINEERING_ESTIMATE",
            "fiscal_year_label": "FY2026",
            "expected_program_version": pv1,
        },
        PM,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    # with a fresh version the SAME create legitimately succeeds and supersedes R1
    r2 = create_report(program["id"], period="2026-08", method="ENGINEERING_ESTIMATE",
                       fiscal_year_label="FY2026", pm_user_id="pm-user-1")
    assert r2["status"] == "DRAFT"
    assert get_report(r1["id"])["status"] == "SUPERSEDED"
