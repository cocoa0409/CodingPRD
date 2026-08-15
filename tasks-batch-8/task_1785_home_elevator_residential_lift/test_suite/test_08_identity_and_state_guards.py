"""Queue B errors: ownership bindings, per-resource state guards, register
protections (PRD §2.1, §2.7, §2.8, §3.4–§3.8)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    create_acceptance_passed_project,
    create_contractor,
    create_dispatched_call,
    create_grant_application_payload,
    create_grant_program,
    create_install_complete_project,
    create_project_payload,
    create_quoted_project,
    create_registered_project,
    create_technician,
    create_unit_with_contract,
    create_service_call,
    factories,
    get_success_data,
    make_contractor_headers,
    make_homeowner_headers,
    make_inspector_headers,
    make_installer_headers,
    make_surveyor_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
ADMIN = TEST_USERS["dealer_admin_headers"]
REGULATOR = TEST_USERS["regulator_headers"]
OFFICER = TEST_USERS["grant_officer_headers"]


# ===========================================================================
# Queue B — Corner/errors/non_owner_cannot_withdraw_application
# ===========================================================================

def test_non_owner_cannot_withdraw_application(api):
    """PRD §3.8: "Withdrawal is the homeowner's compensating action and requires
    property ownership (`ERR_NOT_PROPERTY_OWNER`)."

    Design: Corner/errors/non_owner_cannot_withdraw_application
    """
    ctx = create_quoted_project()
    program = create_grant_program()
    app = get_success_data(api.create_grant_application(
        create_grant_application_payload(ctx["project"]["id"], program["id"]),
        make_homeowner_headers(ctx["prop"]["owner_user_id"])))
    resp = api.withdraw_grant_application(app["id"], make_homeowner_headers("u-other"))
    validate_error(resp, ApiErrorId.ERR_NOT_PROPERTY_OWNER)
    app = get_success_data(api.get_grant_application(app["id"], OFFICER))
    assert app["status"] == "SUBMITTED"


# ===========================================================================
# Queue B — Corner/errors/non_lead_installer_cannot_complete_installation
# ===========================================================================

def test_non_lead_installer_cannot_complete_installation(api):
    """PRD §3.5: "Completion is performed by the installer of record: the caller's
    `X-User-ID` must equal the project's `lead_installer_technician_id`
    (`ERR_NOT_LEAD_INSTALLER`)".

    Design: Corner/errors/non_lead_installer_cannot_complete_installation
    """
    ctx = create_quoted_project()
    other = create_technician(name="Al Alt", certification="CET", region="south")
    permit = get_success_data(api.create_permit(
        factories.create_permit_payload(ctx["project"]["id"]), COORD))
    get_success_data(api.approve_permit(permit["id"], REGULATOR))
    get_success_data(api.schedule_installation(
        ctx["project"]["id"], factories.schedule_installation_payload(), COORD))
    get_success_data(api.set_clock({"to_iso8601": "2026-08-12T09:00:00Z"}, ADMIN))
    resp = api.complete_installation(
        ctx["project"]["id"], {"serial_number": "SN-777"}, make_installer_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_LEAD_INSTALLER)
    project = get_success_data(api.get_project(ctx["project"]["id"], COORD))
    assert project["status"] == "INSTALL_SCHEDULED"


# ===========================================================================
# Queue B — Corner/errors/unassigned_inspector_cannot_record_result
# ===========================================================================

def test_unassigned_inspector_cannot_record_result(api):
    """PRD §3.5: "Only the assigned inspector records the result
    (`ERR_NOT_ASSIGNED_INSPECTOR`)".

    Design: Corner/errors/unassigned_inspector_cannot_record_result
    """
    ctx = create_install_complete_project()
    inspector = create_technician(name="Quinn Inspector", certification="QEI")
    other_qei = create_technician(name="Quincy Second", certification="QEI", region="south")
    insp = get_success_data(api.create_inspection(
        factories.create_inspection_payload(ctx["unit"]["id"], inspector["id"],
                                            project_id=ctx["project"]["id"]), COORD))
    get_success_data(api.set_clock({"to_iso8601": "2026-08-12T10:05:00Z"}, ADMIN))
    resp = api.record_inspection_result(
        insp["id"], {"result": "PASSED"}, make_inspector_headers(other_qei["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_ASSIGNED_INSPECTOR)
    insp = get_success_data(api.get_inspection(insp["id"], COORD))
    assert insp["status"] == "SCHEDULED"


# ===========================================================================
# Queue B — Corner/errors/dependent_inspector_rejected
# ===========================================================================

def test_dependent_inspector_rejected(api):
    """PRD §2.8: "Beyond certification, the system enforces segregation of duties: the
    inspector on any inspection tied to a project must differ from that project's lead
    installer, so a technician can never inspect work they installed."

    Design: Corner/errors/dependent_inspector_rejected
    """
    # Lead installer holds CET_AND_QEI so the certification check passes and only
    # the independence rule can reject.
    ctx = create_quoted_project()
    installer = get_success_data(api.create_technician(
        factories.create_technician_payload(full_name="Ivy Installer",
                                            certification="CET_AND_QEI"), ADMIN))
    project = get_success_data(api.get_project(ctx["project"]["id"], COORD))
    project = get_success_data(api.update_project(project["id"],
        factories.select_product_payload(ctx["model"]["id"], installer["id"],
                                         project["version"]), COORD))
    permit = get_success_data(api.create_permit(
        factories.create_permit_payload(project["id"]), COORD))
    get_success_data(api.approve_permit(permit["id"], REGULATOR))
    get_success_data(api.schedule_installation(
        project["id"], factories.schedule_installation_payload(), COORD))
    get_success_data(api.set_clock({"to_iso8601": "2026-08-12T09:00:00Z"}, ADMIN))
    get_success_data(api.complete_installation(
        project["id"], {"serial_number": "SN-100"}, make_installer_headers(installer["id"])))
    units, _meta = validate_paginated(api.list_units(COORD, params={"project_id": project["id"]}))
    resp = api.create_inspection(
        factories.create_inspection_payload(
            units[0]["id"], installer["id"],
            scheduled_start="2026-08-13T10:00:00Z", scheduled_end="2026-08-13T11:00:00Z",
            project_id=project["id"]), COORD)
    validate_error(resp, ApiErrorId.ERR_INSPECTOR_NOT_INDEPENDENT)
    inspections, _meta = validate_paginated(
        api.list_inspections(COORD, params={"unit_id": units[0]["id"]}))
    assert inspections == []


# ===========================================================================
# Queue B — Corner/errors/non_assigned_surveyor_cannot_complete
# ===========================================================================

def test_non_assigned_surveyor_cannot_complete(api):
    """PRD §3.1: "When the field visit happens, the assigned surveyor — and only that
    surveyor, with any other caller refused `ERR_NOT_ASSIGNED_SURVEYOR` — records
    completion".

    Design: Corner/errors/non_assigned_surveyor_cannot_complete
    """
    prop = get_success_data(api.create_property(factories.create_property_payload(), COORD))
    surveyor = create_technician(name="Sam Surveyor", certification="CET_AND_QEI")
    other = create_technician(name="Al Alt", certification="CET_AND_QEI", region="south")
    survey = get_success_data(api.create_survey(
        factories.create_survey_payload(prop["id"], surveyor["id"]), COORD))
    resp = api.complete_survey(
        survey["id"], factories.complete_survey_payload(), make_surveyor_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_ASSIGNED_SURVEYOR)
    survey = get_success_data(api.get_survey(survey["id"], COORD))
    assert survey["status"] == "SCHEDULED"


# ===========================================================================
# Queue B — Corner/errors/basic_visits_exhausted
# ===========================================================================

def test_basic_visits_exhausted(api):
    """PRD §3.7: "dispatching a `MAINTENANCE_VISIT` under an attached contract requires
    `visits_consumed` to be below `included_visits` (`ERR_NO_VISITS_REMAINING`)".
    PRD §3.7: "`BASIC` carries an `annual_fee` of $600.00 with 1 included maintenance
    visit per contract year".

    Design: Corner/errors/basic_visits_exhausted
    """
    ctx = create_unit_with_contract(tier="BASIC")
    call1 = create_dispatched_call(ctx, call_type="MAINTENANCE_VISIT")
    assert call1["status"] == "DISPATCHED"
    call2 = create_service_call(ctx, call_type="MAINTENANCE_VISIT")
    resp = api.dispatch_service_call(call2["id"], {"technician_id": ctx["installer"]["id"]}, COORD)
    validate_error(resp, ApiErrorId.ERR_NO_VISITS_REMAINING)
    call2 = get_success_data(api.get_service_call(call2["id"], COORD))
    assert call2["status"] == "OPEN"


# ===========================================================================
# Queue B — Corner/errors/pool_exhausted_at_approval_rejected
# ===========================================================================

def test_pool_exhausted_at_approval_rejected(api):
    """PRD §3.8: "the `remaining_pool` must be greater than zero
    (`ERR_GRANT_POOL_EXHAUSTED`)".
    PRD §3.8: "the program must be `OPEN` or `EXHAUSTED` (`ERR_PROGRAM_NOT_OPEN`) —
    submission requires `OPEN`, but an already-submitted application may be approved
    even after the program exhausts".

    Design: Corner/errors/pool_exhausted_at_approval_rejected
    """
    ctx1 = create_quoted_project(prop_overrides={"address_line": "1 Pine St"})
    ctx2 = create_quoted_project(prop_overrides={"address_line": "2 Oak Ave"})
    program = create_grant_program(program_name="TinyPool", funder_name="County Fund",
                                   max_award=10000.00, coverage_percent=0.50,
                                   total_pool=5000.00)
    owner1 = make_homeowner_headers(ctx1["prop"]["owner_user_id"])
    owner2 = make_homeowner_headers(ctx2["prop"]["owner_user_id"])
    app1 = get_success_data(api.create_grant_application(
        create_grant_application_payload(ctx1["project"]["id"], program["id"]), owner1))
    app2 = get_success_data(api.create_grant_application(
        create_grant_application_payload(ctx2["project"]["id"], program["id"]), owner2))
    get_success_data(api.approve_grant_application(
        app1["id"], {"verified_income": 42000.00}, OFFICER))
    program = get_success_data(api.get_grant_program(program["id"], OFFICER))
    assert program["remaining_pool"] == 0.00
    assert program["status"] == "EXHAUSTED"
    resp = api.approve_grant_application(app2["id"], {"verified_income": 42000.00}, OFFICER)
    validate_error(resp, ApiErrorId.ERR_GRANT_POOL_EXHAUSTED)
    app2 = get_success_data(api.get_grant_application(app2["id"], OFFICER))
    assert app2["status"] == "SUBMITTED"


# ===========================================================================
# Queue B — Corner/errors/patch_tier_on_active_contract_rejected
# ===========================================================================

def test_patch_tier_on_active_contract_rejected(api):
    """PRD §3.7: "a tier change on a contract that has left `DRAFT` is refused with
    `ERR_CONTRACT_STATE_FORBIDS`."

    Design: Corner/errors/patch_tier_on_active_contract_rejected
    """
    ctx = create_unit_with_contract(tier="BASIC")  # ACTIVE after activation
    contract = get_success_data(api.get_service_contract(ctx["contract"]["id"], COORD))
    resp = api.update_service_contract(contract["id"], {
        "tier": "PREMIUM", "expected_contract_version": contract["version"],
    }, COORD)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_STATE_FORBIDS)
    contract = get_success_data(api.get_service_contract(contract["id"], COORD))
    assert contract["tier"] == "BASIC"


# ===========================================================================
# Queue B — Corner/errors/arrive_on_open_call_rejected
# ===========================================================================

def test_arrive_on_open_call_rejected(api):
    """PRD §3.7: "Calls in a terminal state refuse further transitions with
    `ERR_SERVICE_CALL_STATE_FORBIDS`." and the call lifecycle moves arrival only from
    `DISPATCHED` to `ON_SITE` ("moving the call from `DISPATCHED` to `ON_SITE`").

    Design: Corner/errors/arrive_on_open_call_rejected
    """
    ctx = create_registered_project()
    call = create_service_call(ctx, call_type="REPAIR")
    assert call["status"] == "OPEN"
    resp = api.arrive_service_call(call["id"], make_installer_headers(ctx["installer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_SERVICE_CALL_STATE_FORBIDS)
    call = get_success_data(api.get_service_call(call["id"], COORD))
    assert call["status"] == "OPEN"


# ===========================================================================
# Queue B — Corner/errors/renew_active_certificate_before_due_rejected
# ===========================================================================

def test_renew_active_certificate_before_due_rejected(api):
    """PRD §3.6: "Acting on a certificate in a state that forbids the operation yields
    `ERR_CERTIFICATE_STATE_FORBIDS`." Renewal is defined from `RENEWAL_DUE`, `EXPIRED`,
    and `REVOKED` only.

    Design: Corner/errors/renew_active_certificate_before_due_rejected
    """
    ctx = create_registered_project()
    cert = get_success_data(api.get_certificate(ctx["certificate"]["id"], COORD))
    assert cert["status"] == "ACTIVE"
    resp = api.renew_certificate(cert["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_CERTIFICATE_STATE_FORBIDS)
    cert = get_success_data(api.get_certificate(cert["id"], COORD))
    assert cert["renewal_count"] == 0


# ===========================================================================
# Queue B — Corner/errors/cancel_passed_inspection_rejected
# ===========================================================================

def test_cancel_passed_inspection_rejected(api):
    """PRD §3.5: "Inspections may also be cancelled by the coordinator while still
    `SCHEDULED`, and are cancelled automatically by the project-cancel cascade.
    Operating on an inspection that has left `SCHEDULED` yields
    `ERR_INSPECTION_STATE_FORBIDS`."

    Design: Corner/errors/cancel_passed_inspection_rejected
    """
    ctx = create_acceptance_passed_project()
    resp = api.cancel_inspection(ctx["inspection"]["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_INSPECTION_STATE_FORBIDS)
    insp = get_success_data(api.get_inspection(ctx["inspection"]["id"], COORD))
    assert insp["status"] == "PASSED"


# ===========================================================================
# Queue B — Corner/errors/approve_withdrawn_application_rejected
# ===========================================================================

def test_approve_withdrawn_application_rejected(api):
    """PRD §3.8: "Acting on an application in the wrong state yields
    `ERR_APPLICATION_STATE_FORBIDS`."

    Design: Corner/errors/approve_withdrawn_application_rejected
    """
    ctx = create_quoted_project()
    program = create_grant_program()
    app = get_success_data(api.create_grant_application(
        create_grant_application_payload(ctx["project"]["id"], program["id"]),
        make_homeowner_headers(ctx["prop"]["owner_user_id"])))
    get_success_data(api.withdraw_grant_application(
        app["id"], make_homeowner_headers(ctx["prop"]["owner_user_id"])))
    resp = api.approve_grant_application(app["id"], {"verified_income": 42000.00}, OFFICER)
    validate_error(resp, ApiErrorId.ERR_APPLICATION_STATE_FORBIDS)
    program = get_success_data(api.get_grant_program(program["id"], OFFICER))
    assert program["remaining_pool"] == 50000.00


# ===========================================================================
# Queue B — Corner/errors/approve_rejected_change_order_rejected
# ===========================================================================

def test_approve_rejected_change_order_rejected(api):
    """PRD §3.8: "Rejection moves the order to `REJECTED`. Acting on an order that is
    not `PROPOSED` yields `ERR_CHANGE_ORDER_STATE_FORBIDS`."

    Design: Corner/errors/approve_rejected_change_order_rejected
    """
    ctx = create_quoted_project()
    owner = make_homeowner_headers(ctx["prop"]["owner_user_id"])
    co = get_success_data(api.create_change_order(
        factories.create_change_order_payload(ctx["project"]["id"],
                                              description="Cab upgrade", amount=3000.00), COORD))
    get_success_data(api.reject_change_order(co["id"], owner))
    resp = api.approve_change_order(co["id"], owner)
    validate_error(resp, ApiErrorId.ERR_CHANGE_ORDER_STATE_FORBIDS)
    project = get_success_data(api.get_project(ctx["project"]["id"], COORD))
    assert project["approved_change_order_total"] == 0
    assert project["homeowner_balance"] == 33000.00


# ===========================================================================
# Queue B — Corner/errors/resume_closed_program_rejected
# ===========================================================================

def test_resume_closed_program_rejected(api):
    """PRD §3.8: "Program actions against a program in a forbidding state yield
    `ERR_PROGRAM_STATE_FORBIDS`."

    Design: Corner/errors/resume_closed_program_rejected
    """
    program = create_grant_program()
    program = get_success_data(api.close_grant_program(program["id"], ADMIN))
    assert program["status"] == "CLOSED"
    resp = api.resume_grant_program(program["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_STATE_FORBIDS)
    program = get_success_data(api.get_grant_program(program["id"], ADMIN))
    assert program["status"] == "CLOSED"


# ===========================================================================
# Queue B — Corner/errors/modernize_installed_unit_rejected
# ===========================================================================

def test_modernize_installed_unit_rejected(api):
    """PRD §3.2: "Creating a modernization project immediately moves the target unit's
    equipment status from `IN_SERVICE` or `OUT_OF_SERVICE` to `UNDER_MODERNIZATION`; a
    unit in any other equipment state triggers `ERR_UNIT_STATE_FORBIDS`".

    Design: Corner/errors/modernize_installed_unit_rejected
    """
    ctx = create_install_complete_project()  # unit INSTALLED, acceptance not yet passed
    resp = api.create_project(
        create_project_payload(ctx["prop"]["id"], ctx["survey"]["id"],
                               project_type="MODERNIZATION",
                               modernize_unit_id=ctx["unit"]["id"]), COORD)
    validate_error(resp, ApiErrorId.ERR_UNIT_STATE_FORBIDS)
    unit = get_success_data(api.get_unit(ctx["unit"]["id"], COORD))
    assert unit["equipment_status"] == "INSTALLED"


# ===========================================================================
# Queue B — Corner/errors/reinspection_without_failure_rejected
# ===========================================================================

def test_reinspection_without_failure_rejected(api):
    """PRD §3.6: "a `REINSPECTION` may be scheduled only when the unit's latest terminal
    inspection was `FAILED`, else `ERR_REINSPECTION_NOT_APPLICABLE`".

    Design: Corner/errors/reinspection_without_failure_rejected
    """
    ctx = create_registered_project()  # latest terminal inspection: PASSED acceptance
    resp = api.create_inspection(
        factories.create_inspection_payload(
            ctx["unit"]["id"], ctx["inspector"]["id"], inspection_type="REINSPECTION",
            scheduled_start="2026-09-02T09:00:00Z", scheduled_end="2026-09-02T10:00:00Z"),
        COORD)
    validate_error(resp, ApiErrorId.ERR_REINSPECTION_NOT_APPLICABLE)


# ===========================================================================
# Queue B — Corner/errors/inspection_equal_window_rejected
# ===========================================================================

def test_inspection_equal_window_rejected(api):
    """PRD §3.5: "The coordinator schedules inspections by supplying `unit_id`, an
    `inspection_type`, the `inspector_technician_id`, and a window from
    `scheduled_start` to `scheduled_end` (end strictly after start,
    `ERR_INVALID_DATE_RANGE`)."

    Design: Corner/errors/inspection_equal_window_rejected
    """
    ctx = create_install_complete_project()
    inspector = create_technician(name="Quinn Inspector", certification="QEI")
    resp = api.create_inspection(
        factories.create_inspection_payload(
            ctx["unit"]["id"], inspector["id"],
            scheduled_start="2026-08-13T10:00:00Z", scheduled_end="2026-08-13T10:00:00Z",
            project_id=ctx["project"]["id"]), COORD)
    validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE)


# ===========================================================================
# Queue B — Corner/errors/renew_without_annual_pass_rejected
# ===========================================================================

def test_renew_without_annual_pass_rejected(api):
    """PRD §3.6: "From `RENEWAL_DUE`, renewal requires the unit's latest `ANNUAL`
    inspection to have `PASSED` (`ERR_ANNUAL_INSPECTION_REQUIRED`)".

    Design: Corner/errors/renew_without_annual_pass_rejected
    """
    ctx = create_registered_project()
    # Sweep into RENEWAL_DUE without recording any ANNUAL inspection.
    get_success_data(api.set_clock({"to_iso8601": "2027-07-20T00:00:00Z"}, ADMIN))
    cert = get_success_data(api.get_certificate(ctx["certificate"]["id"], COORD))
    assert cert["status"] == "RENEWAL_DUE"
    resp = api.renew_certificate(cert["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_ANNUAL_INSPECTION_REQUIRED)
    cert = get_success_data(api.get_certificate(cert["id"], COORD))
    assert cert["status"] == "RENEWAL_DUE"


# ===========================================================================
# Queue B — Corner/errors/renew_revoked_requires_reinspection_pass
# ===========================================================================

def test_renew_revoked_requires_reinspection_pass(api):
    """PRD §3.6: "From `REVOKED`, reinstatement requires the unit's latest
    `REINSPECTION` to have `PASSED` (`ERR_REINSPECTION_REQUIRED`)".

    Design: Corner/errors/renew_revoked_requires_reinspection_pass
    """
    ctx = create_registered_project()
    annual = get_success_data(api.create_inspection(
        factories.create_inspection_payload(
            ctx["unit"]["id"], ctx["inspector"]["id"], inspection_type="ANNUAL",
            scheduled_start="2026-09-02T09:00:00Z", scheduled_end="2026-09-02T10:00:00Z"),
        COORD))
    get_success_data(api.set_clock({"to_iso8601": "2026-09-02T09:05:00Z"}, ADMIN))
    get_success_data(api.record_inspection_result(
        annual["id"], {"result": "FAILED", "deficiency_codes": ["DOOR_INTERLOCK"]},
        make_inspector_headers(ctx["inspector"]["id"])))
    cert = get_success_data(api.get_certificate(ctx["certificate"]["id"], COORD))
    assert cert["status"] == "REVOKED"
    resp = api.renew_certificate(cert["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_REINSPECTION_REQUIRED)
    cert = get_success_data(api.get_certificate(cert["id"], COORD))
    assert cert["status"] == "REVOKED"
    unit = get_success_data(api.get_unit(ctx["unit"]["id"], COORD))
    assert unit["equipment_status"] == "OUT_OF_SERVICE"


# ===========================================================================
# Queue B — Corner/errors/complete_before_install_window_rejected
# ===========================================================================

def test_complete_before_install_window_rejected(api):
    """PRD §3.5: "the logical clock must have reached `install_start_date`
    (`ERR_INSTALL_WINDOW_NOT_STARTED`)".

    Design: Corner/errors/complete_before_install_window_rejected
    """
    ctx = create_quoted_project()
    permit = get_success_data(api.create_permit(
        factories.create_permit_payload(ctx["project"]["id"]), COORD))
    get_success_data(api.approve_permit(permit["id"], REGULATOR))
    get_success_data(api.schedule_installation(
        ctx["project"]["id"], factories.schedule_installation_payload(), COORD))
    # Clock stays at the 2026-08-01 default; the window starts 2026-08-10.
    resp = api.complete_installation(
        ctx["project"]["id"], {"serial_number": "SN-100"},
        make_installer_headers(ctx["installer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INSTALL_WINDOW_NOT_STARTED)
    project = get_success_data(api.get_project(ctx["project"]["id"], COORD))
    assert project["status"] == "INSTALL_SCHEDULED"
    units, _meta = validate_paginated(api.list_units(COORD, params={"project_id": project["id"]}))
    assert units == []


# ===========================================================================
# Queue B — Corner/errors/second_work_order_on_project_rejected
# ===========================================================================

def test_second_work_order_on_project_rejected(api):
    """PRD §3.4: "Creation is gated: the project must be in `PERMIT_APPROVED` with
    `requires_structural` true, and it must not already carry a non-terminal work order
    (`ERR_OPEN_WORK_ORDER_EXISTS`)."

    Design: Corner/errors/second_work_order_on_project_rejected
    """
    ctx = create_quoted_project(
        model_overrides={"model_code": "HYD-200", "min_pit_depth_inches": 16,
                         "min_overhead_clearance_inches": 100, "capacity_lbs": 950,
                         "base_price": 30000.00, "install_labor_price": 9500.00},
        prop_overrides={"address_line": "7 Hill Ct", "state_code": "WA"},
        contractor=True)
    permit = get_success_data(api.create_permit(
        factories.create_permit_payload(ctx["project"]["id"], ahj_name="Tacoma AHJ"), COORD))
    get_success_data(api.approve_permit(permit["id"], REGULATOR))
    get_success_data(api.create_work_order(
        factories.create_work_order_payload(ctx["project"]["id"], ctx["contractor"]["id"],
                                            scope_description="Deepen pit"), COORD))
    resp = api.create_work_order(
        factories.create_work_order_payload(
            ctx["project"]["id"], ctx["contractor"]["id"], scope_description="Raise overhead",
            scheduled_start_date="2026-08-12T08:00:00Z",
            scheduled_end_date="2026-08-14T17:00:00Z", estimated_cost=1500.00), COORD)
    validate_error(resp, ApiErrorId.ERR_OPEN_WORK_ORDER_EXISTS)
    orders, _meta = validate_paginated(
        api.list_work_orders(COORD, params={"project_id": ctx["project"]["id"]}))
    assert len(orders) == 1


# ===========================================================================
# Queue B — Corner/errors/second_modernization_on_unit_rejected
# ===========================================================================

def test_second_modernization_on_unit_rejected(api):
    """PRD §3.2: "Creating a modernization project immediately moves the target unit's
    equipment status from `IN_SERVICE` or `OUT_OF_SERVICE` to `UNDER_MODERNIZATION`;
    a unit in any other equipment state triggers `ERR_UNIT_STATE_FORBIDS`, and a unit
    already referenced by another non-terminal modernization project triggers
    `ERR_UNIT_PROJECT_IN_PROGRESS`."
    PRD §2.7: state admission (item 5, covering "the creation-time cross-entity gates
    enumerated in §3") precedes uniqueness and overlap (item 9). The first
    modernization leaves the unit `UNDER_MODERNIZATION`, so the second attempt trips
    the earlier equipment-state gate.

    Design: Corner/errors/second_modernization_on_unit_rejected
    """
    ctx = create_registered_project()
    get_success_data(api.create_project(
        create_project_payload(ctx["prop"]["id"], ctx["survey"]["id"],
                               project_type="MODERNIZATION",
                               modernize_unit_id=ctx["unit"]["id"]), COORD))
    resp = api.create_project(
        create_project_payload(ctx["prop"]["id"], ctx["survey"]["id"],
                               project_type="MODERNIZATION",
                               modernize_unit_id=ctx["unit"]["id"]), COORD)
    validate_error(resp, ApiErrorId.ERR_UNIT_STATE_FORBIDS)
    unit = get_success_data(api.get_unit(ctx["unit"]["id"], COORD))
    assert unit["equipment_status"] == "UNDER_MODERNIZATION"


# ===========================================================================
# Queue B — Corner/errors/dispatch_inactive_technician_rejected
# ===========================================================================

def test_dispatch_inactive_technician_rejected(api):
    """PRD §3.7: "Dispatch by the coordinator assigns a `technician_id`: the technician
    must be `ACTIVE` (`ERR_TECHNICIAN_NOT_ACTIVE`)".

    Design: Corner/errors/dispatch_inactive_technician_rejected
    """
    ctx = create_registered_project()
    alt = create_technician(name="Al Alt", certification="CET", region="south")
    get_success_data(api.deactivate_technician(alt["id"], ADMIN))
    call = create_service_call(ctx, call_type="REPAIR")
    resp = api.dispatch_service_call(call["id"], {"technician_id": alt["id"]}, COORD)
    validate_error(resp, ApiErrorId.ERR_TECHNICIAN_NOT_ACTIVE)
    call = get_success_data(api.get_service_call(call["id"], COORD))
    assert call["status"] == "OPEN"


# ===========================================================================
# Queue B — Corner/errors/deactivate_technician_with_open_calls_rejected
# ===========================================================================

def test_deactivate_technician_with_open_calls_rejected(api):
    """PRD §2.8: "deactivation itself is refused with `ERR_TECHNICIAN_HAS_OPEN_CALLS`
    while the technician still has service calls in `OPEN`, `DISPATCHED`, or `ON_SITE`".

    Design: Corner/errors/deactivate_technician_with_open_calls_rejected
    """
    ctx = create_registered_project()
    create_dispatched_call(ctx, call_type="REPAIR")
    resp = api.deactivate_technician(ctx["installer"]["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_TECHNICIAN_HAS_OPEN_CALLS)
    tech = get_success_data(api.get_technician(ctx["installer"]["id"], ADMIN))
    assert tech["status"] == "ACTIVE"


# ===========================================================================
# Queue B — Corner/errors/unit_get_not_found_returns_404
# ===========================================================================

def test_unit_get_not_found_returns_404(api):
    """PRD §2.7: "3. **Path existence** — path resource identifiers exist, validated
    left to right along the URL, each yielding its resource-specific not-found error
    (`ERR_PROPERTY_NOT_FOUND`, `ERR_SURVEY_NOT_FOUND`, `ERR_PRODUCT_MODEL_NOT_FOUND`,
    `ERR_TECHNICIAN_NOT_FOUND`, `ERR_CONTRACTOR_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`,
    `ERR_PERMIT_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`,
    `ERR_INSPECTION_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`,
    `ERR_SERVICE_CALL_NOT_FOUND`, `ERR_GRANT_PROGRAM_NOT_FOUND`,
    `ERR_GRANT_APPLICATION_NOT_FOUND`, `ERR_CHANGE_ORDER_NOT_FOUND`; all HTTP 404)."

    Design: Corner/errors/unit_get_not_found_returns_404
    """
    resp = api.get_unit(NON_EXISTENT_UUID, COORD)
    validate_error(resp, ApiErrorId.ERR_UNIT_NOT_FOUND)


# ===========================================================================
# Queue B — Corner/errors/release_suspended_contractor_beats_overlap
# ===========================================================================

def test_release_suspended_contractor_beats_overlap(api):
    """PRD §2.7: "Every endpoint applies its guard checks in a fixed priority order,
    and when several checks could fail on the same request the earliest one wins." PRD
    §2.7 item 8 covers contractor active (`ERR_CONTRACTOR_NOT_ACTIVE`, 409) before item
    9's contractor window overlap (`ERR_CONTRACTOR_WINDOW_OVERLAP`).

    Design: Corner/errors/release_suspended_contractor_beats_overlap
    """
    gc = create_contractor(license_state_code="WA")
    ctxs = []
    for idx, address in enumerate(("1 Pine St", "2 Oak Ave")):
        # The structural model forces requires_structural, so the initial
        # selection must already name a contractor (PRD §3.2,
        # ERR_CONTRACTOR_REQUIRED); the re-select below attaches the shared gc.
        # model_code must be unique per catalog row (PRD §2.8), hence per-idx.
        ctx = create_quoted_project(
            model_overrides={"model_code": f"HYD-20{idx}", "min_pit_depth_inches": 16,
                             "min_overhead_clearance_inches": 100, "capacity_lbs": 950,
                             "base_price": 30000.00, "install_labor_price": 9500.00},
            prop_overrides={"address_line": address, "state_code": "WA"},
            contractor=True)
        project = get_success_data(api.get_project(ctx["project"]["id"], COORD))
        ctx["project"] = get_success_data(api.update_project(project["id"], {
            "product_model_id": ctx["model"]["id"],
            "lead_installer_technician_id": ctx["installer"]["id"],
            "contractor_id": gc["id"],
            "expected_project_version": project["version"],
        }, COORD))
        permit = get_success_data(api.create_permit(
            factories.create_permit_payload(ctx["project"]["id"], ahj_name="Tacoma AHJ"), COORD))
        get_success_data(api.approve_permit(permit["id"], REGULATOR))
        ctx["contractor"] = gc
        ctxs.append(ctx)
    wo1 = get_success_data(api.create_work_order(
        factories.create_work_order_payload(
            ctxs[0]["project"]["id"], gc["id"], scope_description="Pit deepening P1",
            scheduled_start_date="2026-08-10T08:00:00Z",
            scheduled_end_date="2026-08-20T17:00:00Z"), COORD))
    get_success_data(api.release_work_order(wo1["id"], COORD))
    wo2 = get_success_data(api.create_work_order(
        factories.create_work_order_payload(
            ctxs[1]["project"]["id"], gc["id"], scope_description="Pit deepening P2",
            scheduled_start_date="2026-08-15T08:00:00Z",
            scheduled_end_date="2026-08-25T17:00:00Z"), COORD))
    get_success_data(api.suspend_contractor(gc["id"], ADMIN))
    resp = api.release_work_order(wo2["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_CONTRACTOR_NOT_ACTIVE)
    assert resp.json()["data"]["error_id"] != "ERR_CONTRACTOR_WINDOW_OVERLAP"
    wo2 = get_success_data(api.get_work_order(wo2["id"], COORD))
    assert wo2["status"] == "DRAFT"


# ===========================================================================
# Queue B — Corner/errors/contractor_adjacency_allowed
# ===========================================================================

def test_contractor_adjacency_allowed(api):
    """PRD §3.4: "the windows are treated as half-open intervals, so a conflict exists
    exactly when the new window's start is before an existing window's end **and** the
    existing window's start is before the new window's end; pure adjacency — one
    window's end equal to the other's start — is allowed."

    Design: Corner/errors/contractor_adjacency_allowed
    """
    gc = create_contractor(license_state_code="WA")
    ctxs = []
    for idx, address in enumerate(("1 Pine St", "2 Oak Ave")):
        # The structural model forces requires_structural, so the initial
        # selection must already name a contractor (PRD §3.2,
        # ERR_CONTRACTOR_REQUIRED); the re-select below attaches the shared gc.
        # model_code must be unique per catalog row (PRD §2.8), hence per-idx.
        ctx = create_quoted_project(
            model_overrides={"model_code": f"HYD-20{idx}", "min_pit_depth_inches": 16,
                             "min_overhead_clearance_inches": 100, "capacity_lbs": 950,
                             "base_price": 30000.00, "install_labor_price": 9500.00},
            prop_overrides={"address_line": address, "state_code": "WA"},
            contractor=True)
        project = get_success_data(api.get_project(ctx["project"]["id"], COORD))
        ctx["project"] = get_success_data(api.update_project(project["id"], {
            "product_model_id": ctx["model"]["id"],
            "lead_installer_technician_id": ctx["installer"]["id"],
            "contractor_id": gc["id"],
            "expected_project_version": project["version"],
        }, COORD))
        permit = get_success_data(api.create_permit(
            factories.create_permit_payload(ctx["project"]["id"], ahj_name="Tacoma AHJ"), COORD))
        get_success_data(api.approve_permit(permit["id"], REGULATOR))
        ctx["contractor"] = gc
        ctxs.append(ctx)
    wo1 = get_success_data(api.create_work_order(
        factories.create_work_order_payload(
            ctxs[0]["project"]["id"], gc["id"], scope_description="Pit deepening P1",
            scheduled_start_date="2026-08-10T08:00:00Z",
            scheduled_end_date="2026-08-20T17:00:00Z"), COORD))
    get_success_data(api.release_work_order(wo1["id"], COORD))
    wo2 = get_success_data(api.create_work_order(
        factories.create_work_order_payload(
            ctxs[1]["project"]["id"], gc["id"], scope_description="Pit deepening P2",
            scheduled_start_date="2026-08-20T17:00:00Z",  # exactly WO1's end
            scheduled_end_date="2026-08-30T17:00:00Z"), COORD))
    wo2 = get_success_data(api.release_work_order(wo2["id"], COORD))
    assert wo2["status"] == "RELEASED"
    project2 = get_success_data(api.get_project(ctxs[1]["project"]["id"], COORD))
    assert project2["status"] == "STRUCTURAL_IN_PROGRESS"


# ===========================================================================
# Queue B — Corner/errors/inspector_buffer_exact_45_allowed
# ===========================================================================

def test_inspector_buffer_exact_45_allowed(api):
    """PRD §3.5: "a new inspection window may not begin within 45 minutes of another
    `SCHEDULED` inspection for the same inspector — adjacency without a full 45-minute
    gap is rejected with `ERR_INSPECTOR_BUFFER_CONFLICT`." A gap of exactly 45 minutes
    satisfies the buffer.

    Design: Corner/errors/inspector_buffer_exact_45_allowed
    """
    ctx = create_registered_project()
    get_success_data(api.create_inspection(
        factories.create_inspection_payload(
            ctx["unit"]["id"], ctx["inspector"]["id"], inspection_type="ANNUAL",
            scheduled_start="2026-09-02T09:00:00Z", scheduled_end="2026-09-02T10:00:00Z"),
        COORD))
    second = validate_success(api.create_inspection(
        factories.create_inspection_payload(
            ctx["unit"]["id"], ctx["inspector"]["id"], inspection_type="ANNUAL",
            scheduled_start="2026-09-02T10:45:00Z", scheduled_end="2026-09-02T11:45:00Z"),
        COORD), expected_status=201)
    assert second["status"] == "SCHEDULED"
