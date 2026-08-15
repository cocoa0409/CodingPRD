"""Queue B endpoints, RBAC surface, optimistic concurrency, logical-clock default,
and not-found sweep (PRD §2.1–§2.7, §3.5, §3.7, §4)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    create_approved_application,
    create_dispatched_call,
    create_grant_program,
    create_install_complete_project,
    create_project_draft,
    create_quoted_project,
    create_registered_project,
    create_technician,
    create_unit_with_contract,
    create_service_call,
    factories,
    get_success_data,
    make_homeowner_headers,
    make_inspector_headers,
    make_installer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
ADMIN = TEST_USERS["dealer_admin_headers"]
REGULATOR = TEST_USERS["regulator_headers"]
OFFICER = TEST_USERS["grant_officer_headers"]


# ===========================================================================
# Queue B — Corner/endpoints/service_call_auto_attach_contract
# ===========================================================================

def test_service_call_auto_attach_contract(api):
    """PRD §3.7: "Creation stamps `reported_at` from the logical clock, sets the call to
    `OPEN`, and auto-attaches the unit's `ACTIVE` contract into `contract_id` when one
    exists, leaving it null for ad-hoc calls."

    Design: Corner/endpoints/service_call_auto_attach_contract
    """
    ctx = create_unit_with_contract(tier="STANDARD")
    # Logical clock is 2026-08-12T10:05:00Z after the registered-project chain.
    call = create_service_call(ctx, call_type="REPAIR", description="Noisy door")
    assert call["contract_id"] == ctx["contract"]["id"]
    assert call["reported_at"] == "2026-08-12T10:05:00.000Z"
    assert call.get("provisional_estimate") is None, "estimate is computed at dispatch"


# ===========================================================================
# Queue B — Corner/endpoints/project_computed_read_after_grant
# ===========================================================================

def test_project_computed_read_after_grant(api):
    """PRD §3.8: "when the total is positive but below the value it is
    `PARTIALLY_FUNDED`". PRD §3.2: "Before close, the running `homeowner_balance` is
    `contract_price` plus `approved_change_order_total` minus `disbursed_grants`."

    Design: Corner/endpoints/project_computed_read_after_grant
    """
    ctx = create_quoted_project()
    program = create_grant_program()
    create_approved_application(ctx, program)  # 10000.00 committed
    project = get_success_data(api.get_project(
        ctx["project"]["id"], make_homeowner_headers(ctx["prop"]["owner_user_id"])))
    assert project["funding_posture"] == "PARTIALLY_FUNDED"
    assert project["homeowner_balance"] == 33000.00
    assert project["disbursed_grants"] == 0


# ===========================================================================
# Queue B — Corner/rbac/homeowner_cannot_create_product_model
# ===========================================================================

def test_homeowner_cannot_create_product_model(api):
    """PRD §2.1: "A request whose role is not permitted on the target endpoint is
    rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the
    specific error. The `message` provides a human-readable explanation of what went
    wrong."

    Design: Corner/rbac/homeowner_cannot_create_product_model
    """
    resp = api.create_product_model(
        factories.create_product_model_payload(model_code="HYD-100"),
        make_homeowner_headers("u-own-1"))
    error = validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert resp.status_code == 403
    assert isinstance(error.get("message"), str) and error["message"]


# ===========================================================================
# Queue B — Corner/rbac/grant_officer_cannot_approve_permit
# ===========================================================================

def test_grant_officer_cannot_approve_permit(api):
    """PRD §2.1: "A request whose role is not permitted on the target endpoint is
    rejected with `ERR_FORBIDDEN` (HTTP 403)." PRD §4 lists permit approval under the
    Regulator role.

    Design: Corner/rbac/grant_officer_cannot_approve_permit
    """
    ctx = create_quoted_project()
    permit = get_success_data(api.create_permit(
        factories.create_permit_payload(ctx["project"]["id"]), COORD))
    resp = api.approve_permit(permit["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    permit = get_success_data(api.get_permit(permit["id"], COORD))
    assert permit["status"] == "UNDER_REVIEW"


# ===========================================================================
# Queue B — Corner/rbac/coordinator_cannot_issue_certificate
# ===========================================================================

def test_coordinator_cannot_issue_certificate(api):
    """PRD §2.1: "A request whose role is not permitted on the target endpoint is
    rejected with `ERR_FORBIDDEN` (HTTP 403)." PRD §4 lists certificate issuance under
    the Regulator role.

    Design: Corner/rbac/coordinator_cannot_issue_certificate
    """
    ctx = create_acceptance_passed_project_helper(api)
    resp = api.issue_certificate(ctx["cert"]["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    cert = get_success_data(api.get_certificate(ctx["cert"]["id"], COORD))
    assert cert["status"] == "PENDING_ISSUANCE"


def create_acceptance_passed_project_helper(api):
    from test_helpers import create_acceptance_passed_project
    ctx = create_acceptance_passed_project()
    cert = get_success_data(api.create_certificate(
        factories.create_certificate_payload(ctx["unit"]["id"]), COORD))
    ctx["cert"] = cert
    return ctx


# ===========================================================================
# Queue B — Corner/rbac/homeowner_cannot_dispatch_service_call
# ===========================================================================

def test_homeowner_cannot_dispatch_service_call(api):
    """PRD §2.1: "A request whose role is not permitted on the target endpoint is
    rejected with `ERR_FORBIDDEN` (HTTP 403)." PRD §4 lists dispatch under the
    ProjectCoordinator role.

    Design: Corner/rbac/homeowner_cannot_dispatch_service_call
    """
    ctx = create_registered_project()
    call = create_service_call(ctx, call_type="REPAIR")
    resp = api.dispatch_service_call(
        call["id"], {"technician_id": ctx["installer"]["id"]},
        make_homeowner_headers(ctx["prop"]["owner_user_id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    call = get_success_data(api.get_service_call(call["id"], COORD))
    assert call["status"] == "OPEN"


# ===========================================================================
# Queue B — Corner/rbac/installer_role_cannot_record_inspection
# ===========================================================================

def test_installer_role_cannot_record_inspection(api):
    """PRD §2.1: "A request whose role is not permitted on the target endpoint is
    rejected with `ERR_FORBIDDEN` (HTTP 403)." PRD §4 lists record-result under the
    Inspector role — the role header, not the person, gates the endpoint.

    Design: Corner/rbac/installer_role_cannot_record_inspection
    """
    ctx = create_install_complete_project()
    inspector = create_technician(name="Quinn Inspector", certification="QEI")
    insp = get_success_data(api.create_inspection(
        factories.create_inspection_payload(ctx["unit"]["id"], inspector["id"],
                                            project_id=ctx["project"]["id"]), COORD))
    get_success_data(api.set_clock({"to_iso8601": "2026-08-12T10:05:00Z"}, ADMIN))
    # Same technician id, but presented under the Installer role.
    resp = api.record_inspection_result(
        insp["id"], {"result": "PASSED"}, make_installer_headers(inspector["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    insp = get_success_data(api.get_inspection(insp["id"], COORD))
    assert insp["status"] == "SCHEDULED"


# ===========================================================================
# Queue B — Corner/rbac/gets_readable_by_all_roles
# ===========================================================================

def test_gets_readable_by_all_roles(api):
    """PRD §4: "GET endpoints are readable by all nine roles."

    Design: Corner/rbac/gets_readable_by_all_roles
    """
    ctx = create_project_draft()
    projects, meta = validate_paginated(
        api.list_projects(make_homeowner_headers("u-own-1")))
    assert meta["total_count"] == 1
    project = validate_success(api.get_project(ctx["project"]["id"], OFFICER))
    assert project["status"] == "DRAFT"


# ===========================================================================
# Queue B — Corner/cross_cutting_layers/occ_project_version_conflict
# ===========================================================================

def test_occ_project_version_conflict(api):
    """PRD §2.6: "If the project's current `version` has advanced beyond that value
    since the client's last read, the update is rejected with
    `ERR_STALE_PROJECT_VERSION` (HTTP 412), so that a coordinator holding a stale view
    cannot silently overwrite a selection another writer has legitimately superseded."

    Design: Corner/cross_cutting_layers/occ_project_version_conflict
    """
    ctx = create_project_draft()
    project = ctx["project"]
    # A second catalog model that fits the default survey (12/96 minimums met by the
    # default 12/96 measurements), so selection is valid and DRAFT -> QUOTED.
    model = get_success_data(api.create_product_model(
        factories.create_product_model_payload(model_code="HYD-OCC-1"), ADMIN))
    updated = get_success_data(api.update_project(project["id"],
        factories.select_product_payload(model["id"], ctx["installer"]["id"],
                                         project["version"]), COORD))
    assert updated["version"] == 2
    assert updated["status"] == "QUOTED"
    # Replay with the pre-update version.
    resp = api.update_project(project["id"],
        factories.select_product_payload(model["id"], ctx["installer"]["id"],
                                         updated["version"] - 1), COORD)
    validate_error(resp, ApiErrorId.ERR_STALE_PROJECT_VERSION)
    project = get_success_data(api.get_project(project["id"], COORD))
    assert project["version"] == 2, "rejected PATCH does not increment"


# ===========================================================================
# Queue B — Corner/cross_cutting_layers/occ_contract_tier_stale_conflict
# ===========================================================================

def test_occ_contract_tier_stale_conflict(api):
    """PRD §2.6: "A tier change against a `ServiceContract` — the contract `PATCH` —
    likewise requires `expected_contract_version` matching the contract's current
    `version`. A mismatch is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412)."
    PRD §3.7: "`STANDARD` carries $1,200.00 with 2 visits and 120 minutes".

    Design: Corner/cross_cutting_layers/occ_contract_tier_stale_conflict
    """
    ctx = create_install_complete_project()
    contract = get_success_data(api.create_service_contract(
        factories.create_service_contract_payload(ctx["unit"]["id"], tier="BASIC"), COORD))
    assert contract["version"] == 1
    updated = get_success_data(api.update_service_contract(contract["id"], {
        "tier": "STANDARD", "expected_contract_version": contract["version"],
    }, COORD))
    assert updated["version"] == 2
    assert updated["tier"] == "STANDARD"
    assert updated["annual_fee"] == 1200.00
    assert updated["included_visits"] == 2
    assert updated["entrapment_sla_minutes"] == 120
    resp = api.update_service_contract(contract["id"], {
        "tier": "PREMIUM", "expected_contract_version": contract["version"],
    }, COORD)
    validate_error(resp, ApiErrorId.ERR_STALE_CONTRACT_VERSION)
    contract = get_success_data(api.get_service_contract(contract["id"], COORD))
    assert contract["tier"] == "STANDARD"


# ===========================================================================
# Queue B — Corner/cross_cutting_layers/clock_default_permit_approval_timestamp
# ===========================================================================

def test_clock_default_permit_approval_timestamp(api):
    """PRD §2.4: "At startup the logical clock reads exactly `2026-08-01T00:00:00Z`;
    before any client sets it, every timestamp comparison observes that default."
    PRD §3.3: "The regulator may approve ... which sets `approved_date` to the logical
    clock and `valid_through` to 180 days later".

    Design: Corner/cross_cutting_layers/clock_default_permit_approval_timestamp
    """
    ctx = create_quoted_project()
    permit = get_success_data(api.create_permit(
        factories.create_permit_payload(ctx["project"]["id"]), COORD))
    # No clock-set calls in this test: the default logical clock applies.
    permit = get_success_data(api.approve_permit(permit["id"], REGULATOR))
    assert permit["approved_date"] == "2026-08-01T00:00:00.000Z"
    assert permit["valid_through"] == "2027-01-28T00:00:00.000Z"


# ===========================================================================
# Queue B — Corner/cross_cutting_layers/terminate_detaches_open_calls
# ===========================================================================

def test_terminate_detaches_open_calls(api):
    """PRD §3.7: "termination detaches any attached `OPEN` or `DISPATCHED` service calls
    by nulling their `contract_id`, turning them into ad-hoc calls."

    Design: Corner/cross_cutting_layers/terminate_detaches_open_calls
    """
    ctx = create_unit_with_contract(tier="STANDARD")
    call = create_dispatched_call(ctx, call_type="REPAIR")
    contract = get_success_data(api.terminate_service_contract(ctx["contract"]["id"], COORD))
    assert contract["status"] == "TERMINATED"
    call = get_success_data(api.get_service_call(call["id"], COORD))
    assert call.get("contract_id") is None
    assert call["status"] == "DISPATCHED"


# ===========================================================================
# Queue B — Corner/consistency_model/immediate_consistency_create_then_read
# ===========================================================================

def test_immediate_consistency_create_then_read(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource
    will return the created or updated resource object in the data field."

    Design: Corner/consistency_model/immediate_consistency_create_then_read
    """
    created = validate_success(api.create_property(
        factories.create_property_payload(address_line="5 Bluff Rd", state_code="OR",
                                          has_existing_shaft=True), COORD),
        expected_status=201)
    fetched = validate_success(api.get_property(created["id"], ADMIN))
    assert fetched["address_line"] == "5 Bluff Rd"
    assert fetched["state_code"] == "OR"
    assert fetched["has_existing_shaft"] is True
    assert fetched["version"] == 1


# ===========================================================================
# Queue B — Corner/errors/get_by_id_not_found_sweep
# ===========================================================================

def test_get_by_id_not_found_sweep(api):
    """PRD §2.7: "3. **Path existence** — path resource identifiers exist, validated
    left to right along the URL, each yielding its resource-specific not-found error
    (`ERR_PROPERTY_NOT_FOUND`, `ERR_SURVEY_NOT_FOUND`, `ERR_PRODUCT_MODEL_NOT_FOUND`,
    `ERR_TECHNICIAN_NOT_FOUND`, `ERR_CONTRACTOR_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`,
    `ERR_PERMIT_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`,
    `ERR_INSPECTION_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`,
    `ERR_SERVICE_CALL_NOT_FOUND`, `ERR_GRANT_PROGRAM_NOT_FOUND`,
    `ERR_GRANT_APPLICATION_NOT_FOUND`, `ERR_CHANGE_ORDER_NOT_FOUND`; all HTTP 404)."

    Design: Corner/errors/get_by_id_not_found_sweep
    """
    cases = [
        (api.get_survey, ApiErrorId.ERR_SURVEY_NOT_FOUND),
        (api.get_product_model, ApiErrorId.ERR_PRODUCT_MODEL_NOT_FOUND),
        (api.get_technician, ApiErrorId.ERR_TECHNICIAN_NOT_FOUND),
        (api.get_contractor, ApiErrorId.ERR_CONTRACTOR_NOT_FOUND),
        (api.get_permit, ApiErrorId.ERR_PERMIT_NOT_FOUND),
        (api.get_work_order, ApiErrorId.ERR_WORK_ORDER_NOT_FOUND),
        (api.get_inspection, ApiErrorId.ERR_INSPECTION_NOT_FOUND),
        (api.get_certificate, ApiErrorId.ERR_CERTIFICATE_NOT_FOUND),
        (api.get_service_contract, ApiErrorId.ERR_CONTRACT_NOT_FOUND),
        (api.get_service_call, ApiErrorId.ERR_SERVICE_CALL_NOT_FOUND),
        (api.get_grant_program, ApiErrorId.ERR_GRANT_PROGRAM_NOT_FOUND),
        (api.get_grant_application, ApiErrorId.ERR_GRANT_APPLICATION_NOT_FOUND),
        (api.get_change_order, ApiErrorId.ERR_CHANGE_ORDER_NOT_FOUND),
    ]
    for getter, expected in cases:
        resp = getter(NON_EXISTENT_UUID, COORD)
        validate_error(resp, expected)
        assert resp.status_code == 404


# ===========================================================================
# Queue B — Corner/errors/deactivate_inspector_with_scheduled_inspection_rejected
# ===========================================================================

def test_deactivate_inspector_with_scheduled_inspection_rejected(api):
    """PRD §2.8: "deactivation itself is refused with `ERR_TECHNICIAN_HAS_OPEN_CALLS`
    while the technician still has service calls in `OPEN`, `DISPATCHED`, or `ON_SITE`,
    and with `ERR_TECHNICIAN_HAS_OPEN_INSPECTIONS` while inspections remain
    `SCHEDULED`."

    Design: Corner/errors/deactivate_inspector_with_scheduled_inspection_rejected
    """
    ctx = create_install_complete_project()
    inspector = create_technician(name="Quinn Inspector", certification="QEI")
    get_success_data(api.create_inspection(
        factories.create_inspection_payload(
            ctx["unit"]["id"], inspector["id"],
            scheduled_start="2026-08-13T10:00:00Z", scheduled_end="2026-08-13T11:00:00Z",
            project_id=ctx["project"]["id"]), COORD))
    resp = api.deactivate_technician(inspector["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_TECHNICIAN_HAS_OPEN_INSPECTIONS)
    tech = get_success_data(api.get_technician(inspector["id"], ADMIN))
    assert tech["status"] == "ACTIVE"


# ===========================================================================
# Queue B — Corner/errors/unassigned_technician_cannot_arrive
# ===========================================================================

def test_unassigned_technician_cannot_arrive(api):
    """PRD §3.7: "Arrival is recorded by the dispatched technician
    (`ERR_NOT_ASSIGNED_TECHNICIAN`)".

    Design: Corner/errors/unassigned_technician_cannot_arrive
    """
    ctx = create_registered_project()
    other = create_technician(name="Al Alt", certification="CET", region="south")
    call = create_dispatched_call(ctx, call_type="REPAIR")
    resp = api.arrive_service_call(call["id"], make_installer_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_ASSIGNED_TECHNICIAN)
    call = get_success_data(api.get_service_call(call["id"], COORD))
    assert call["status"] == "DISPATCHED"


# ===========================================================================
# Queue B — Corner/errors/non_assigned_contractor_cannot_complete_work
# ===========================================================================

def test_non_assigned_contractor_cannot_complete_work(api):
    """PRD §3.4: "The contractor — only the contractor whose `id` matches the work
    order's `contractor_id`, with anyone else refused `ERR_NOT_ASSIGNED_CONTRACTOR` —
    reports completion with an `actual_cost`".

    Design: Corner/errors/non_assigned_contractor_cannot_complete_work
    """
    from test_helpers import create_contractor
    ctx = create_quoted_project(
        model_overrides={"model_code": "HYD-200", "min_pit_depth_inches": 16,
                         "min_overhead_clearance_inches": 100, "capacity_lbs": 950,
                         "base_price": 30000.00, "install_labor_price": 9500.00},
        prop_overrides={"address_line": "7 Hill Ct", "state_code": "WA"},
        contractor=True)
    other_gc = create_contractor(company_name="OtherCo")
    permit = get_success_data(api.create_permit(
        factories.create_permit_payload(ctx["project"]["id"], ahj_name="Tacoma AHJ"), COORD))
    get_success_data(api.approve_permit(permit["id"], REGULATOR))
    wo = get_success_data(api.create_work_order(
        factories.create_work_order_payload(ctx["project"]["id"], ctx["contractor"]["id"],
                                            scope_description="Deepen pit"), COORD))
    get_success_data(api.release_work_order(wo["id"], COORD))
    from test_helpers import make_contractor_headers
    resp = api.complete_work_order(wo["id"], {"actual_cost": 3100.00},
                                   make_contractor_headers(other_gc["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_ASSIGNED_CONTRACTOR)
    wo = get_success_data(api.get_work_order(wo["id"], COORD))
    assert wo["status"] == "RELEASED"


# ===========================================================================
# Queue B — Corner/errors/structural_selection_without_contractor_rejected
# ===========================================================================

def test_structural_selection_without_contractor_rejected(api):
    """PRD §3.2: "When either shortfall is positive, `requires_structural` is set to
    true and a `contractor_id` must be supplied (`ERR_CONTRACTOR_REQUIRED`)".

    Design: Corner/errors/structural_selection_without_contractor_rejected
    """
    ctx = create_project_draft(
        prop_overrides={"address_line": "7 Hill Ct", "state_code": "WA"})
    model = get_success_data(api.create_product_model(
        factories.create_product_model_payload(
            model_code="HYD-200", min_pit_depth_inches=16,
            min_overhead_clearance_inches=100, capacity_lbs=950,
            base_price=30000.00, install_labor_price=9500.00), ADMIN))
    resp = api.update_project(ctx["project"]["id"],
        factories.select_product_payload(model["id"], ctx["installer"]["id"],
                                         ctx["project"]["version"]), COORD)
    validate_error(resp, ApiErrorId.ERR_CONTRACTOR_REQUIRED)
    project = get_success_data(api.get_project(ctx["project"]["id"], COORD))
    assert project["status"] == "DRAFT"


# ===========================================================================
# Queue B — Corner/errors/complete_work_on_draft_rejected
# ===========================================================================

def test_complete_work_on_draft_rejected(api):
    """PRD §3.4: "The contractor ... reports completion with an `actual_cost`, moving
    the order from `RELEASED` to `WORK_COMPLETE`" and "operating on an order in the
    wrong state yields `ERR_WORK_ORDER_STATE_FORBIDS`."

    Design: Corner/errors/complete_work_on_draft_rejected
    """
    from test_helpers import make_contractor_headers
    ctx = create_quoted_project(
        model_overrides={"model_code": "HYD-200", "min_pit_depth_inches": 16,
                         "min_overhead_clearance_inches": 100, "capacity_lbs": 950,
                         "base_price": 30000.00, "install_labor_price": 9500.00},
        prop_overrides={"address_line": "7 Hill Ct", "state_code": "WA"},
        contractor=True)
    permit = get_success_data(api.create_permit(
        factories.create_permit_payload(ctx["project"]["id"], ahj_name="Tacoma AHJ"), COORD))
    get_success_data(api.approve_permit(permit["id"], REGULATOR))
    wo = get_success_data(api.create_work_order(
        factories.create_work_order_payload(ctx["project"]["id"], ctx["contractor"]["id"],
                                            scope_description="Deepen pit"), COORD))
    assert wo["status"] == "DRAFT"
    resp = api.complete_work_order(wo["id"], {"actual_cost": 3100.00},
                                   make_contractor_headers(ctx["contractor"]["id"]))
    validate_error(resp, ApiErrorId.ERR_WORK_ORDER_STATE_FORBIDS)
    wo = get_success_data(api.get_work_order(wo["id"], COORD))
    assert wo["status"] == "DRAFT"
