"""Auth pipeline, role authorization, segregation of duties, ownership, OCC."""
from test_helpers import (
    validate_success, validate_error,
    create_credential_payload, create_background_check_payload,
    create_support_request_payload, create_active_incident, register_volunteer,
    vet_volunteer, create_published_request, create_open_shift,
    create_completed_assignment_with_entry, create_risk_report_payload,
    set_clock, make_intake_headers, make_vetting_headers,
    make_supervisor_headers, make_risk_headers, TEST_USERS,
)

MGR = TEST_USERS["manager_headers"]
INTAKE = TEST_USERS["intake_headers"]
VET = TEST_USERS["vetting_headers"]
SITE = TEST_USERS["supervisor_headers"]
RISK = TEST_USERS["risk_headers"]
AGENCY = TEST_USERS["agency_headers"]


def test_missing_auth_headers_returns_400_before_not_found(api):
    """PRD section 2.11: "Every request is validated against an ordered
    pipeline, and a request that would fail several checks reports the earliest
    failing stage. The stages, in order, are: 1. Header presence and role
    validity (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`)."

    Design: Corner/validations/missing_auth_headers_returns_400_before_not_found
    """
    set_clock("2026-08-01T00:00:00Z")
    res = api.get_volunteer("99999999-8888-7777-6666-555555555555", headers={})
    validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", expected_status=400)


def test_demobilize_with_vetting_role_returns_unauthorized(api):
    """PRD section 2.1: "Each endpoint declares the roles permitted to call it;
    an authenticated caller whose role is not on that list is rejected with
    `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

    Design: Corner/validations/demobilize_with_vetting_role_returns_unauthorized
    """
    incident = create_active_incident(name="Flood N2",
                                      ppe_stock={"GLOVES": 1, "MASK": 1, "HARD_HAT": 1,
                                                 "VEST": 1, "GOGGLES": 1})
    volunteer = register_volunteer(incident["id"], full_name="Fay Finn")
    res = api.demobilize_volunteer(volunteer["id"], VET)
    validate_error(res, "ERR_UNAUTHORIZED_ROLE", expected_status=403)


def test_site_supervisor_cannot_verify_credential(api):
    """PRD section 2.1: "`VettingOfficer` is the credentialing specialist who
    verifies skill credentials and adjudicates background checks, deliberately
    segregated from intake."

    Design: Corner/rbac/site_supervisor_cannot_verify_credential
    """
    incident = create_active_incident(name="Flood U3",
                                      ppe_stock={"GLOVES": 1, "MASK": 1, "HARD_HAT": 1,
                                                 "VEST": 1, "GOGGLES": 1})
    volunteer = register_volunteer(incident["id"], full_name="Noa Nio")
    credential = validate_success(api.create_credential(
        create_credential_payload(volunteer["id"], skill_code="CDL",
                                  credential_class="ADVANCED"), INTAKE), 201)
    res = api.verify_credential(credential["id"], SITE)
    validate_error(res, "ERR_UNAUTHORIZED_ROLE")


def test_registrar_cannot_clear_own_background_check(api):
    """PRD section 2.8: "The operator who clears or flags a volunteer's
    background check must not be the operator whose identifier was recorded in
    that volunteer's `registered_by_user_id`; a violation is rejected with
    `ERR_SOD_CLEARANCE_VIOLATION` (HTTP 403)."

    Design: Corner/validations/registrar_cannot_clear_own_background_check
    """
    incident = create_active_incident(name="Fire O2",
                                      ppe_stock={"GLOVES": 1, "MASK": 1, "HARD_HAT": 1,
                                                 "VEST": 1, "GOGGLES": 1})
    registrar = make_intake_headers("intake-7")
    volunteer = register_volunteer(incident["id"], registrar_headers=registrar,
                                   full_name="Gus Gay")
    validate_success(api.create_credential(
        create_credential_payload(volunteer["id"]), registrar), 201)
    validate_success(api.submit_for_vetting(volunteer["id"], registrar))
    check = validate_success(api.create_background_check(
        create_background_check_payload(volunteer["id"]), VET), 201)
    res = api.clear_background_check(check["id"], make_vetting_headers("intake-7"))
    validate_error(res, "ERR_SOD_CLEARANCE_VIOLATION", expected_status=403)


def _setup_completed_entry_submitted_by(supervisor_id: str):
    """Incident + READY volunteer + COMPLETED assignment + 8.0h entry submitted
    by the given SiteSupervisor id. Returns (volunteer, entry)."""
    incident = create_active_incident(name="Flood P2",
                                      ppe_stock={"GLOVES": 2, "MASK": 2, "HARD_HAT": 2,
                                                 "VEST": 2, "GOGGLES": 2})
    volunteer = vet_volunteer(incident["id"], full_name="Hal Hoy")["volunteer"]
    request = create_published_request(incident["id"])
    shift = create_open_shift(incident["id"])
    _, entry = create_completed_assignment_with_entry(
        volunteer, request, shift, work_date="2026-08-10", hours=8.0,
        checkin_at="2026-08-10T08:00:00Z",
        submit_as="supervisor")
    # create_completed_assignment_with_entry uses the shared supervisor header;
    # re-file under the requested identity by creating the entry directly.
    return volunteer, entry


def test_submitter_cannot_verify_own_hour_entry(api):
    """PRD section 2.8: "The operator who verifies or disputes an hour entry
    must not be the one recorded as its `submitted_by_user_id`; a violation is
    `ERR_SOD_HOUR_VERIFICATION` (HTTP 403) — and because resubmission never
    rewrites `submitted_by_user_id`, the original submitter remains the
    segregation target for the life of the entry."

    Design: Corner/validations/submitter_cannot_verify_own_hour_entry
    """
    from test_helpers import (propose_accept_confirm_assignment, issue_ppe,
                              check_in_and_complete, create_hour_entry_payload)
    incident = create_active_incident(name="Flood P2",
                                      ppe_stock={"GLOVES": 2, "MASK": 2, "HARD_HAT": 2,
                                                 "VEST": 2, "GOGGLES": 2})
    volunteer = vet_volunteer(incident["id"], full_name="Hal Hoy")["volunteer"]
    request = create_published_request(incident["id"])
    shift = create_open_shift(incident["id"])
    assignment = propose_accept_confirm_assignment(volunteer, request, shift)
    issue_ppe(volunteer["id"])
    assignment = check_in_and_complete(assignment, volunteer["id"], "2026-08-10T08:00:00Z")
    entry = validate_success(api.create_hour_entry(
        create_hour_entry_payload(assignment["id"], work_date="2026-08-10", hours=8.0),
        make_supervisor_headers("site-7")), 201)
    assert entry["submitted_by_user_id"] == "site-7"
    res = api.verify_hour_entry(entry["id"], make_supervisor_headers("site-7"))
    validate_error(res, "ERR_SOD_HOUR_VERIFICATION", expected_status=403)
    verified = validate_success(api.verify_hour_entry(
        entry["id"], make_supervisor_headers("site-8")))
    assert verified["status"] == "VERIFIED"


def test_reporter_cannot_substantiate_own_risk_report(api):
    """PRD section 2.8: "The operator who substantiates or dismisses a risk
    report must not be its `reporter_user_id`; a violation is
    `ERR_SOD_RISK_ADJUDICATION` (HTTP 403)."

    Design: Corner/validations/reporter_cannot_substantiate_own_risk_report
    """
    incident = create_active_incident(name="Fire Q2",
                                      ppe_stock={"GLOVES": 1, "MASK": 1, "HARD_HAT": 1,
                                                 "VEST": 1, "GOGGLES": 1})
    volunteer = register_volunteer(incident["id"], registrar_headers=make_intake_headers("intake-8"),
                                   full_name="Ila Ives")
    report = validate_success(api.create_risk_report(
        create_risk_report_payload(volunteer["id"], description="late"),
        make_intake_headers("intake-8")), 201)
    res = api.substantiate_risk_report(report["id"], make_risk_headers("intake-8"))
    validate_error(res, "ERR_SOD_RISK_ADJUDICATION", expected_status=403)
    substantiated = validate_success(api.substantiate_risk_report(
        report["id"], make_risk_headers("risk-1")))
    assert substantiated["status"] == "SUBSTANTIATED"
    assert substantiated["points_awarded"] == 5


def test_volunteer_cannot_accept_others_assignment(api):
    """PRD section 2.8: "When the caller's role is `Volunteer`, ownership rules
    apply: accepting or declining an assignment, resubmitting an hour entry,
    withdrawing from the center, and creating an hour entry each require
    `X-User-ID` to equal the subject volunteer's `id` — for assignment actions
    and hour entries, the assignment's `volunteer_id`. A mismatch is rejected
    with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/volunteer_cannot_accept_others_assignment
    """
    from test_helpers import propose_assignment, make_volunteer_headers
    incident = create_active_incident(name="Fire T3",
                                      ppe_stock={"GLOVES": 1, "MASK": 1, "HARD_HAT": 1,
                                                 "VEST": 1, "GOGGLES": 1})
    volunteer1 = vet_volunteer(incident["id"], full_name="Liv Loe")["volunteer"]
    volunteer2 = register_volunteer(incident["id"], full_name="Max Moe")
    request = create_published_request(incident["id"])
    shift = create_open_shift(incident["id"])
    assignment = propose_assignment(volunteer1, request, shift)
    res = api.accept_assignment(assignment["id"], make_volunteer_headers(volunteer2["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER", expected_status=403)


def test_volunteer_self_accept_succeeds(api):
    """PRD section 3.3: "The volunteer then answers: accepting moves `PROPOSED`
    to `ACCEPTED`, and declining moves it to terminal `DECLINED`, which can
    empty a `MATCHING` request back to `OPEN` when no fills and no `PROPOSED`
    or `ACCEPTED` assignments remain; both actions are ownership-checked per
    section 2.8."

    Design: Corner/rbac/volunteer_self_accept_succeeds
    """
    from test_helpers import propose_assignment, make_volunteer_headers
    incident = create_active_incident(name="Fire V3",
                                      ppe_stock={"GLOVES": 1, "MASK": 1, "HARD_HAT": 1,
                                                 "VEST": 1, "GOGGLES": 1})
    volunteer = vet_volunteer(incident["id"], full_name="Oma Oja")["volunteer"]
    request = create_published_request(incident["id"])
    shift = create_open_shift(incident["id"])
    assignment = propose_assignment(volunteer, request, shift)
    accepted = validate_success(api.accept_assignment(
        assignment["id"], make_volunteer_headers(volunteer["id"])))
    assert accepted["status"] == "ACCEPTED"


def test_occ_stale_volunteer_patch_returns_412(api):
    """PRD section 2.9: "A volunteer profile edit must carry
    `expected_volunteer_version` matching the volunteer's current `version`; a
    support-request edit must carry `expected_support_request_version` matching
    the request's current `version`. If the supplied value does not match —
    because another writer has mutated the record since the client last read
    it, whether by a profile edit, a status change, or a cascaded recompute
    such as `filled_count` — the write is rejected with `ERR_STALE_VERSION`
    (HTTP 412)"

    Design: Corner/cross_cutting_layers/occ_stale_volunteer_patch_returns_412
    """
    incident = create_active_incident(name="Flood W3",
                                      ppe_stock={"GLOVES": 1, "MASK": 1, "HARD_HAT": 1,
                                                 "VEST": 1, "GOGGLES": 1})
    volunteer = register_volunteer(incident["id"], full_name="Pia Pyo")
    stale_version = volunteer["version"]
    patched = validate_success(api.patch_volunteer(
        volunteer["id"], {"expected_volunteer_version": stale_version,
                          "phone": "555-95-NEW"}, INTAKE))
    assert patched["version"] == 2
    res = api.patch_volunteer(
        volunteer["id"], {"expected_volunteer_version": stale_version,
                          "phone": "555-95-STALE"}, INTAKE)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)
    after = validate_success(api.get_volunteer(volunteer["id"], MGR))
    assert after["phone"] == "555-95-NEW"


def test_occ_stale_support_request_put_returns_412(api):
    """PRD section 2.9: "a support-request edit must carry
    `expected_support_request_version` matching the request's current
    `version`."

    Design: Corner/cross_cutting_layers/occ_stale_support_request_put_returns_412
    """
    incident = create_active_incident(name="Fire X3",
                                      ppe_stock={"GLOVES": 1, "MASK": 1, "HARD_HAT": 1,
                                                 "VEST": 1, "GOGGLES": 1})
    request = validate_success(api.create_support_request(
        create_support_request_payload(incident["id"], headcount_needed=2), AGENCY), 201)
    stale_version = request["version"]
    validate_success(api.publish_support_request(request["id"], AGENCY))
    res = api.update_support_request(
        request["id"], {"expected_support_request_version": stale_version,
                        "headcount_needed": 5}, AGENCY)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)
    fresh = validate_success(api.get_support_request(request["id"], MGR))
    assert fresh["version"] == 2
    updated = validate_success(api.update_support_request(
        request["id"], {"expected_support_request_version": fresh["version"],
                        "headcount_needed": 5}, AGENCY))
    assert updated["headcount_needed"] == 5
    assert updated["version"] == 3


def test_version_increments_on_every_mutation_including_cascades(api):
    """PRD section 2.5: "`version` is an integer starting at 1 at creation and
    incrementing by exactly 1 on every mutation of the resource, including
    mutations produced by cascades and derived-field recomputes, with
    `updated_at` refreshed alongside."

    Design: Corner/cross_cutting_layers/version_increments_on_every_mutation_including_cascades
    """
    incident = create_active_incident(name="Flood Y3",
                                      ppe_stock={"GLOVES": 1, "MASK": 1, "HARD_HAT": 1,
                                                 "VEST": 1, "GOGGLES": 1})
    volunteer = register_volunteer(incident["id"], full_name="Quon Qiu")
    assert volunteer["version"] == 1
    validate_success(api.create_credential(
        create_credential_payload(volunteer["id"]), INTAKE), 201)
    patched = validate_success(api.patch_volunteer(
        volunteer["id"], {"expected_volunteer_version": 1, "email": "new@x.com"}, INTAKE))
    assert patched["version"] == 2
    vetting = validate_success(api.submit_for_vetting(volunteer["id"], INTAKE))
    assert vetting["version"] == 3
    suspended = validate_success(api.suspend_volunteer(volunteer["id"], RISK))
    assert suspended["version"] == 4
    assert suspended["status"] == "SUSPENDED"
