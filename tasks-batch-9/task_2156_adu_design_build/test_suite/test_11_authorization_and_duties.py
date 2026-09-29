"""Authentication, endpoint authorization, and segregation of duties."""
from test_helpers import (
    NON_EXISTENT_UUID, ApiErrorId, validate_success, validate_error, validate_paginated,
    change_order_payload,
    setup_intake_project, setup_permitted_project, setup_under_plan_check_project,
    setup_submitted_change_order, setup_scheduled_phase,
    register_inspector, book_inspection, record_result, price_financing_scenario,
    read_project, make_building_inspector_headers,
    DESIGN_LEAD, PLAN_CHECKER, PROJECT_MANAGER, FINANCE_ADVISOR,
)


def test_request_without_the_role_header_is_unauthenticated(api):
    """PRD §2.1: "Every request to this API — without exception, including reads — must carry
    two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the capacity
    in which they act. If either header is absent or empty, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.7: "1. **Authentication.** Presence and non-emptiness of both headers, then
    recognition of the role name — both surfacing as `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_x_user_role_header_returns_unauthenticated
    """
    response = api.raw_get(f"/adu-projects/{NON_EXISTENT_UUID}",
                           headers={"Content-Type": "application/json"})

    error = validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)
    assert error["error_id"] != ApiErrorId.ERR_PROJECT_NOT_FOUND.value, (
        "authentication is checked ahead of path existence")


def test_homeowner_may_not_decide_a_change_order(api):
    """PRD §2.1: "Segregation of duties is enforced structurally rather than by convention. A
    `Homeowner` authors change orders and may never decide one; a `ProjectManager` decides
    them and may never author one."
    PRD §2.1: "Only once the role is recognized does the service ask whether that role is
    listed for the endpoint being called; when it is not, the answer is
    `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/homeowner_cannot_decide_change_order
    """
    ctx = setup_intake_project(api)
    change_order = setup_submitted_change_order(
        api, ctx, title="Widen the doorway", scope_items=["Reframe the entry"],
        cost_delta_cents=250_000, schedule_delta_days=1)

    validate_error(
        api.decide_change_order(change_order["id"], {"decision": "APPROVE"},
                                ctx["homeowner_headers"]),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED)

    unchanged = validate_success(api.get_change_order(change_order["id"], PROJECT_MANAGER))
    assert unchanged["status"] == "SUBMITTED"
    assert unchanged["decided_by_user_id"] is None


def test_project_manager_may_not_author_a_change_order(api):
    """PRD §2.1: "Segregation of duties is enforced structurally rather than by convention. A
    `Homeowner` authors change orders and may never decide one; a `ProjectManager` decides
    them and may never author one."
    PRD §3.6: "A `Homeowner` raises a change order — a `ChangeOrder` row — against their own
    project, supplying the `expected_adu_project_version` guard, a `title` labelling the
    request, a `scope_items` array of free-text scope lines being added or removed, a
    `cost_delta_cents` figure that is signed so that negative values are credits, and a
    `schedule_delta_days` figure that is likewise signed and must lie between negative 30 and
    120 inclusive."

    Design: Corner/rbac/project_manager_cannot_author_change_order
    """
    ctx = setup_intake_project(api)

    validate_error(
        api.create_change_order(
            ctx["project"]["id"],
            change_order_payload(ctx["project"]["version"],
                                 title="Builder-initiated scope bump",
                                 scope_items=["Upgrade insulation"],
                                 cost_delta_cents=300_000, schedule_delta_days=1),
            PROJECT_MANAGER),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED)

    _, meta = validate_paginated(api.list_change_orders(
        PROJECT_MANAGER, {"adu_project_id": ctx["project"]["id"]}))
    assert meta["total_count"] == 0
    assert read_project(api, ctx["project"]["id"])["version"] == 1


def test_design_lead_may_not_record_the_plan_check_result(api):
    """PRD §2.1: "A `PlanChecker` is jurisdiction plan-check staff, recording plan-check
    outcomes and issuing the certificate of occupancy, and never touching contract money."
    PRD §2.1: "Only once the role is recognized does the service ask whether that role is
    listed for the endpoint being called; when it is not, the answer is
    `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/design_lead_cannot_record_plan_check_result
    """
    ctx = setup_under_plan_check_project(api, service_type=None)

    validate_error(
        api.record_plan_check_result(ctx["submittal"]["id"], {"outcome": "APPROVED"},
                                     DESIGN_LEAD),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED)

    unchanged = validate_success(api.get_permit_submittal(ctx["submittal"]["id"], PLAN_CHECKER))
    assert unchanged["status"] == "UNDER_PLAN_CHECK"
    assert read_project(api, ctx["project"]["id"])["status"] == "PERMITTING"


def test_plan_checker_may_not_read_a_financing_scenario(api):
    """PRD §2.1: "A `PlanChecker` is jurisdiction plan-check staff, recording plan-check
    outcomes and issuing the certificate of occupancy, and never touching contract money."
    PRD §2.1: "Only once the role is recognized does the service ask whether that role is
    listed for the endpoint being called; when it is not, the answer is
    `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/plan_checker_cannot_read_financing_scenario
    """
    ctx = setup_intake_project(api)
    scenario = price_financing_scenario(api, ctx["project"]["id"], product_type="HELOC",
                                        appraisal_approach="SALES_COMPARISON")

    validate_error(api.get_financing_scenario(scenario["id"], PLAN_CHECKER),
                   ApiErrorId.ERR_ROLE_NOT_PERMITTED)

    allowed = validate_success(api.get_financing_scenario(scenario["id"], FINANCE_ADVISOR))
    assert allowed["as_completed_value_cents"] == 89_000_000


def test_inspector_may_not_record_a_result_on_another_inspectors_slot(api):
    """PRD §2.1: "When `X-User-Role` is `BuildingInspector`, `X-User-ID` is the `id` of the
    acting `Inspector`; recording a result on an appointment whose `inspector_id` is some
    other inspector is rejected with `ERR_NOT_ASSIGNED_INSPECTOR` (HTTP 403)."
    PRD §3.8: "Recording an outcome is reserved to the `BuildingInspector` the slot was booked
    to."

    Design: Corner/rbac/inspector_cannot_record_result_on_unassigned_appointment
    """
    ctx = setup_permitted_project(api)
    booked_to = register_inspector(api, ctx["jurisdiction"]["id"], full_name="R. Okafor")
    other = register_inspector(api, ctx["jurisdiction"]["id"], full_name="S. Nakamura")
    phase = setup_scheduled_phase(api, ctx, "2026-09-01", "2026-09-05")
    appointment = book_inspection(api, phase["id"], booked_to["id"])

    validate_error(
        api.record_inspection_result(
            appointment["id"], {"outcome": "PASS", "result_notes": "Looks fine to me"},
            make_building_inspector_headers(other["id"])),
        ApiErrorId.ERR_NOT_ASSIGNED_INSPECTOR)

    unchanged = validate_success(
        api.get_inspection_appointment(appointment["id"], PROJECT_MANAGER))
    assert unchanged["status"] == "SCHEDULED"
    assert unchanged["recorded_by_inspector_id"] is None


def test_inspector_who_signed_an_earlier_result_may_not_sign_the_final(api):
    """PRD §3.8: "Segregation of duties applies to one branch specifically. When the
    `inspection_type` being recorded is `FINAL`, the service first checks whether any other
    appointment on the same `adu_project_id` already carries a `recorded_by_inspector_id`
    equal to the acting `X-User-ID`; if one does, the request is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The inspector who signed the framing cannot also
    sign the final."
    PRD §3.8: "Appointment listings may be narrowed by `adu_project_id`,
    `construction_phase_id`, `inspector_id`, `recorded_by_inspector_id`, `slot_date`, and
    `status`."

    Design: Corner/rbac/final_inspection_by_prior_recording_inspector_rejected
    """
    ctx = setup_permitted_project(api)
    inspector = register_inspector(api, ctx["jurisdiction"]["id"], full_name="R. Okafor")
    phase = setup_scheduled_phase(api, ctx, "2026-09-01", "2026-09-05")
    foundation = book_inspection(api, phase["id"], inspector["id"],
                                 inspection_type="FOUNDATION", slot_date="2026-09-02",
                                 slot_start="2026-09-02T09:00:00Z",
                                 slot_end="2026-09-02T10:00:00Z")
    record_result(api, foundation["id"], inspector["id"], "PASS", "Rebar and forms verified")
    final = book_inspection(api, phase["id"], inspector["id"], inspection_type="FINAL",
                            slot_date="2026-09-04", slot_start="2026-09-04T09:00:00Z",
                            slot_end="2026-09-04T10:00:00Z")

    validate_error(
        api.record_inspection_result(final["id"], {"outcome": "PASS", "result_notes": "Final"},
                                     make_building_inspector_headers(inspector["id"])),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    unchanged = validate_success(api.get_inspection_appointment(final["id"], PROJECT_MANAGER))
    assert unchanged["status"] == "SCHEDULED"
    assert unchanged["recorded_by_inspector_id"] is None

    signed = validate_success(api.get_inspection_appointment(foundation["id"], PROJECT_MANAGER))
    assert signed["recorded_by_inspector_id"] == inspector["id"]

    _, meta = validate_paginated(api.list_inspection_appointments(
        PROJECT_MANAGER, {"recorded_by_inspector_id": inspector["id"],
                          "adu_project_id": ctx["project"]["id"]}))
    assert meta["total_count"] == 1
