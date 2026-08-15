"""Project and permit pipeline state machines (PRD §3.3–§3.5): corrections cycle,
structural fork/join, parallel unit dimensions, invalid and terminal transitions."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_acceptance_passed_project,
    create_completed_survey,
    create_contractor,
    create_install_complete_project,
    create_project_draft,
    create_project_payload,
    create_quoted_project,
    create_registered_project,
    create_technician,
    factories,
    get_success_data,
    make_contractor_headers,
    make_inspector_headers,
    make_installer_headers,
    make_surveyor_headers,
    validate_error,
    validate_paginated,
)

COORD = TEST_USERS["coordinator_headers"]
ADMIN = TEST_USERS["dealer_admin_headers"]
REGULATOR = TEST_USERS["regulator_headers"]


def _permit_in_progress(api, ctx):
    permit = get_success_data(api.create_permit(
        factories.create_permit_payload(ctx["project"]["id"]), COORD))
    return permit


# ===========================================================================
# Queue A — non_linear_state_machine / permit_corrections_cycle
# ===========================================================================

class TestPermitCorrectionsCycle:
    def test_correction_cycle_increments_revision_count_each_loop(self, api):
        """PRD §3.3: "From there a `Regulator` may request corrections, moving it to
        `CORRECTIONS_REQUIRED` and incrementing `revision_count` (which starts at 0) by
        1, with `correction_notes` captured from the request. The coordinator resubmits,
        returning the application to `UNDER_REVIEW`; the cycle can repeat."

        Design: Difficulty/non_linear_state_machine/permit_corrections_cycle
        """
        ctx = create_quoted_project()
        permit = _permit_in_progress(api, ctx)
        permit = get_success_data(api.request_corrections(
            permit["id"], {"correction_notes": "Add pit ladder detail"}, REGULATOR))
        assert permit["status"] == "CORRECTIONS_REQUIRED" and permit["revision_count"] == 1
        permit = get_success_data(api.resubmit_permit(permit["id"], COORD))
        assert permit["status"] == "UNDER_REVIEW"
        permit = get_success_data(api.request_corrections(
            permit["id"], {"correction_notes": "Add load calc"}, REGULATOR))
        assert permit["revision_count"] == 2
        permit = get_success_data(api.resubmit_permit(permit["id"], COORD))
        assert permit["status"] == "UNDER_REVIEW" and permit["revision_count"] == 2

    def test_approval_after_cycles_sets_validity_and_auto_advances_project(self, api):
        """PRD §3.3: "The regulator may approve — permitted only while the project is in
        `PERMIT_IN_PROGRESS`, else `ERR_PROJECT_STATE_FORBIDS` — which sets
        `approved_date` to the logical clock and `valid_through` to 180 days later,
        moves the application to `APPROVED`, advances the project from
        `PERMIT_IN_PROGRESS` to `PERMIT_APPROVED`, and, when the project requires no
        structural work, auto-advances it further to `READY_FOR_INSTALL`."

        Design: Difficulty/non_linear_state_machine/permit_corrections_cycle
        """
        ctx = create_quoted_project()
        permit = _permit_in_progress(api, ctx)
        get_success_data(api.request_corrections(
            permit["id"], {"correction_notes": "Add pit ladder detail"}, REGULATOR))
        get_success_data(api.resubmit_permit(permit["id"], COORD))
        get_success_data(api.request_corrections(
            permit["id"], {"correction_notes": "Add load calc"}, REGULATOR))
        get_success_data(api.resubmit_permit(permit["id"], COORD))
        get_success_data(api.set_clock({"to_iso8601": "2026-08-05T00:00:00Z"}, ADMIN))
        permit = get_success_data(api.approve_permit(permit["id"], REGULATOR))
        assert permit["status"] == "APPROVED"
        assert permit["revision_count"] == 2
        assert permit["approved_date"] == "2026-08-05T00:00:00.000Z"
        assert permit["valid_through"] == "2027-02-01T00:00:00.000Z"  # approved + 180 days
        project = get_success_data(api.get_project(ctx["project"]["id"], COORD))
        assert project["status"] == "READY_FOR_INSTALL"


# ===========================================================================
# Queue A — non_linear_state_machine / unit_parallel_dimensions
# ===========================================================================

class TestUnitParallelDimensions:
    def test_modernization_moves_equipment_axis_only(self, api):
        """PRD §3.2: "Creating a modernization project immediately moves the target
        unit's equipment status from `IN_SERVICE` or `OUT_OF_SERVICE` to
        `UNDER_MODERNIZATION`".

        Design: Difficulty/non_linear_state_machine/unit_parallel_dimensions
        """
        ctx = create_registered_project()
        project2 = get_success_data(api.create_project(
            create_project_payload(ctx["prop"]["id"], ctx["survey"]["id"],
                                   project_type="MODERNIZATION",
                                   modernize_unit_id=ctx["unit"]["id"]), COORD))
        unit = get_success_data(api.get_unit(ctx["unit"]["id"], COORD))
        assert unit["equipment_status"] == "UNDER_MODERNIZATION"
        assert unit["registration_status"] == "REGISTERED"
        assert project2["status"] == "DRAFT"
        assert project2["project_type"] == "MODERNIZATION"

    def test_modernization_project_references_target_unit(self, api):
        """PRD §3.2: "A project is born when a coordinator creates one from a completed
        survey, supplying `property_id`, `survey_id`, a `project_type` of
        `NEW_INSTALLATION` or `MODERNIZATION`, and — only for a modernization —
        `modernize_unit_id` naming the existing unit to be replaced".

        Design: Difficulty/non_linear_state_machine/unit_parallel_dimensions
        """
        ctx = create_registered_project()
        project2 = get_success_data(api.create_project(
            create_project_payload(ctx["prop"]["id"], ctx["survey"]["id"],
                                   project_type="MODERNIZATION",
                                   modernize_unit_id=ctx["unit"]["id"]), COORD))
        assert project2["modernize_unit_id"] == ctx["unit"]["id"]
        unit = get_success_data(api.get_unit(ctx["unit"]["id"], COORD))
        assert unit["equipment_status"] == "UNDER_MODERNIZATION"
        assert unit["registration_status"] == "REGISTERED"


# ===========================================================================
# Queue A — non_linear_state_machine / project_structural_fork_join
# ===========================================================================

class TestProjectStructuralForkJoin:
    def _two_projects(self, api):
        """Project A no-structural (HYD-100 fits), Project B structural (HYD-200, 4/4)."""
        ctx_a = create_quoted_project(prop_overrides={"address_line": "1 Pine St"})
        ctx_b = create_quoted_project(
            model_overrides={"model_code": "HYD-200", "min_pit_depth_inches": 16,
                             "min_overhead_clearance_inches": 100, "capacity_lbs": 950,
                             "base_price": 30000.00, "install_labor_price": 9500.00},
            prop_overrides={"address_line": "2 Oak Ave"},
            contractor=True)
        return ctx_a, ctx_b

    def test_no_structural_branch_auto_joins_ready_for_install(self, api):
        """PRD §3.3: "The regulator may approve — permitted only while the project is in
        `PERMIT_IN_PROGRESS`, else `ERR_PROJECT_STATE_FORBIDS` — which sets
        `approved_date` to the logical clock and `valid_through` to 180 days later,
        moves the application to `APPROVED`, advances the project from
        `PERMIT_IN_PROGRESS` to `PERMIT_APPROVED`, and, when the project requires no
        structural work, auto-advances it further to `READY_FOR_INSTALL`."

        Design: Difficulty/non_linear_state_machine/project_structural_fork_join
        """
        ctx_a, _ctx_b = self._two_projects(api)
        permit = _permit_in_progress(api, ctx_a)
        get_success_data(api.approve_permit(permit["id"], REGULATOR))
        project = get_success_data(api.get_project(ctx_a["project"]["id"], COORD))
        assert project["status"] == "READY_FOR_INSTALL"

    def test_structural_branch_blocks_scheduling_until_work_verified(self, api):
        """PRD §3.4: "The coordinator then verifies: verification moves the order from
        `WORK_COMPLETE` to `VERIFIED`, advances the project from
        `STRUCTURAL_IN_PROGRESS` to `READY_FOR_INSTALL`, and computes the project's
        `structural_adjustment` as the reconciliation between actual and estimated
        structural cost."
        PRD §3.4: "if the actual cost comes in at or under the estimate, the adjustment
        is the full signed difference, crediting the homeowner the entire underrun."

        Design: Difficulty/non_linear_state_machine/project_structural_fork_join
        """
        _ctx_a, ctx_b = self._two_projects(api)
        permit_b = _permit_in_progress(api, ctx_b)
        get_success_data(api.approve_permit(permit_b["id"], REGULATOR))
        project_b = get_success_data(api.get_project(ctx_b["project"]["id"], COORD))
        assert project_b["status"] == "PERMIT_APPROVED"
        # Scheduling is rejected before the structural branch completes.
        resp = api.schedule_installation(
            project_b["id"], factories.schedule_installation_payload(), COORD)
        validate_error(resp, ApiErrorId.ERR_PROJECT_STATE_FORBIDS)
        # Structural branch: release -> complete-work (underrun) -> verify.
        wo = get_success_data(api.create_work_order(
            factories.create_work_order_payload(project_b["id"], ctx_b["contractor"]["id"],
                                                estimated_cost=3100.00), COORD))
        get_success_data(api.release_work_order(wo["id"], COORD))
        get_success_data(api.complete_work_order(
            wo["id"], {"actual_cost": 3000.00},
            make_contractor_headers(ctx_b["contractor"]["id"])))
        get_success_data(api.verify_work_order(wo["id"], COORD))
        project_b = get_success_data(api.get_project(project_b["id"], COORD))
        assert project_b["status"] == "READY_FOR_INSTALL"
        # actual 3000.00 vs estimate 3100.00: full underrun credit -100.00.
        assert project_b["structural_adjustment"] == -100.00


# ===========================================================================
# Queue B — Corner/state_machines/project_initial_state_is_draft
# ===========================================================================

def test_project_initial_state_is_draft(api):
    """PRD §3.2: "A new project starts in `DRAFT`."
    PRD §2.5: "The `version` starts at 1 on creation and increments by 1 on every
    mutation of the resource".
    PRD §3.8: "when nothing is committed it is `UNFUNDED`."

    Design: Corner/state_machines/project_initial_state_is_draft
    """
    prop, _surveyor, survey = create_completed_survey()
    project = get_success_data(api.create_project(
        create_project_payload(prop["id"], survey["id"]), COORD))
    assert project["status"] == "DRAFT"
    assert project["version"] == 1
    assert project.get("product_model_id") is None
    assert project["funding_posture"] == "UNFUNDED"


# ===========================================================================
# Queue B — Corner/state_machines/unit_born_installed_and_unregistered
# ===========================================================================

def test_unit_born_installed_and_unregistered(api):
    """PRD §3.5: "Completion moves the project from `INSTALL_SCHEDULED` to
    `INSTALL_COMPLETE` and creates the `ElevatorUnit`: `property_id` and
    `product_model_id` are copied from the project, `project_id` points back to the
    installing project, `serial_number` comes from the input, `install_date` is the
    logical clock timestamp, `equipment_status` starts at `INSTALLED`, and
    `registration_status` starts at `UNREGISTERED`."

    Design: Corner/state_machines/unit_born_installed_and_unregistered
    """
    ctx = create_install_complete_project(serial_number="SN-100")
    unit = ctx["unit"]
    assert unit["equipment_status"] == "INSTALLED"
    assert unit["registration_status"] == "UNREGISTERED"
    assert unit["install_date"] == "2026-08-12T09:00:00.000Z"
    assert unit["serial_number"] == "SN-100"


# ===========================================================================
# Queue B — Corner/state_machines/cancel_already_cancelled_project_rejected
# ===========================================================================

def test_cancel_already_cancelled_project_rejected(api):
    """PRD §3.8: "A coordinator may cancel a project in any state except `CLOSED`,
    `CANCELLED`, or `REGISTERED` — a registered project can never be cancelled, and the
    attempt yields `ERR_PROJECT_STATE_FORBIDS`."

    Design: Corner/state_machines/cancel_already_cancelled_project_rejected
    """
    ctx = create_project_draft()
    get_success_data(api.cancel_project(ctx["project"]["id"], COORD))
    resp = api.cancel_project(ctx["project"]["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_PROJECT_STATE_FORBIDS)
    project = get_success_data(api.get_project(ctx["project"]["id"], COORD))
    assert project["status"] == "CANCELLED"


# ===========================================================================
# Queue B — Corner/state_machines/closed_project_lockdown
# ===========================================================================

def test_closed_project_lockdown(api):
    """PRD §3.8: "A coordinator may cancel a project in any state except `CLOSED`,
    `CANCELLED`, or `REGISTERED` — a registered project can never be cancelled, and the
    attempt yields `ERR_PROJECT_STATE_FORBIDS`."
    PRD §3.2: "Product selection is a scope update performed by the coordinator and is
    the OCC-guarded write described in §2.6: the request must carry
    `expected_project_version` alongside any of `product_model_id`,
    `lead_installer_technician_id`, and `contractor_id`. The first valid selection moves
    the project from `DRAFT` to `QUOTED`; a further selection while the project is still
    in `DRAFT` or `QUOTED` legitimately supersedes the prior one".

    Design: Corner/state_machines/closed_project_lockdown
    """
    ctx = create_registered_project()
    project = get_success_data(api.close_project(ctx["project"]["id"], COORD))
    assert project["status"] == "CLOSED"
    assert project["final_invoice"] == 33000.00
    resp = api.update_project(project["id"], {
        "product_model_id": ctx["model"]["id"],
        "expected_project_version": project["version"],
    }, COORD)
    validate_error(resp, ApiErrorId.ERR_PROJECT_STATE_FORBIDS)
    resp = api.cancel_project(project["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_PROJECT_STATE_FORBIDS)
    project = get_success_data(api.get_project(project["id"], COORD))
    assert project["status"] == "CLOSED"


# ===========================================================================
# Queue B — Corner/state_machines/survey_double_complete_rejected
# ===========================================================================

def test_survey_double_complete_rejected(api):
    """PRD §3.1: "Completing or cancelling a survey that has already left `SCHEDULED` is
    refused with `ERR_SURVEY_STATE_FORBIDS`."

    Design: Corner/state_machines/survey_double_complete_rejected
    """
    prop, surveyor, survey = create_completed_survey()
    resp = api.complete_survey(
        survey["id"],
        factories.complete_survey_payload(measured_pit_depth_inches=20,
                                          measured_overhead_clearance_inches=120,
                                          floors_served=3),
        make_surveyor_headers(surveyor["id"]))
    validate_error(resp, ApiErrorId.ERR_SURVEY_STATE_FORBIDS)
    survey = get_success_data(api.get_survey(survey["id"], COORD))
    assert survey["measured_pit_depth_inches"] == 12
    assert survey["feasibility_verdict"] == "FEASIBLE"


# ===========================================================================
# Queue B — Corner/state_machines/permit_resubmit_from_under_review_rejected
# ===========================================================================

def test_permit_resubmit_from_under_review_rejected(api):
    """PRD §3.3: "Operating on a permit that is not in the state an action requires
    yields `ERR_PERMIT_STATE_FORBIDS`."

    Design: Corner/state_machines/permit_resubmit_from_under_review_rejected
    """
    ctx = create_quoted_project()
    permit = _permit_in_progress(api, ctx)
    resp = api.resubmit_permit(permit["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_PERMIT_STATE_FORBIDS)
    permit = get_success_data(api.get_permit(permit["id"], COORD))
    assert permit["status"] == "UNDER_REVIEW"
    assert permit["revision_count"] == 0


# ===========================================================================
# Queue B — Corner/state_machines/work_order_rework_loop
# ===========================================================================

def test_work_order_rework_loop(api):
    """PRD §3.4: "Verification may instead be rejected with a `rejection_reason`, which
    loops the order back from `WORK_COMPLETE` to `RELEASED` for rework and clears
    `actual_cost` back to null."
    PRD §3.4: "if the actual cost comes in at or under the estimate, the adjustment is
    the full signed difference, crediting the homeowner the entire underrun. When a
    project requires no structural work, or no verified work order exists, the
    adjustment is zero."

    Design: Corner/state_machines/work_order_rework_loop
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
    wo = get_success_data(api.create_work_order(
        factories.create_work_order_payload(ctx["project"]["id"], ctx["contractor"]["id"],
                                            scope_description="Deepen pit 4 in",
                                            estimated_cost=3100.00), COORD))
    get_success_data(api.release_work_order(wo["id"], COORD))
    get_success_data(api.complete_work_order(
        wo["id"], {"actual_cost": 3000.00}, make_contractor_headers(ctx["contractor"]["id"])))
    wo = get_success_data(api.reject_work_order_verification(
        wo["id"], {"rejection_reason": "Pit depth still short"}, COORD))
    assert wo["status"] == "RELEASED"
    assert wo.get("actual_cost") is None, "rejection clears actual_cost"
    get_success_data(api.complete_work_order(
        wo["id"], {"actual_cost": 3100.00}, make_contractor_headers(ctx["contractor"]["id"])))
    wo = get_success_data(api.verify_work_order(wo["id"], COORD))
    assert wo["status"] == "VERIFIED"
    project = get_success_data(api.get_project(ctx["project"]["id"], COORD))
    assert project["status"] == "READY_FOR_INSTALL"
    assert project["structural_adjustment"] == 0.00


# ===========================================================================
# Queue B — Corner/state_machines/certificate_renewal_due_sweep
# ===========================================================================

def test_certificate_renewal_due_sweep(api):
    """PRD §2.4: "Second, any certificate in `ACTIVE` whose `expiration_date` is thirty
    days or fewer in the future transitions to `RENEWAL_DUE`".

    Design: Corner/state_machines/certificate_renewal_due_sweep
    """
    ctx = create_registered_project()
    cert = ctx["certificate"]
    assert cert["expiration_date"] == "2027-08-12T10:05:00.000Z"
    get_success_data(api.set_clock({"to_iso8601": "2027-07-20T00:00:00Z"}, ADMIN))
    cert = get_success_data(api.get_certificate(cert["id"], COORD))
    assert cert["status"] == "RENEWAL_DUE"
    assert cert["expiration_date"] == "2027-08-12T10:05:00.000Z"
    unit = get_success_data(api.get_unit(ctx["unit"]["id"], COORD))
    assert unit["equipment_status"] == "IN_SERVICE"
    assert unit["registration_status"] == "REGISTERED"


# ===========================================================================
# Queue B — Corner/state_machines/certificate_expiry_sweep_out_of_service
# ===========================================================================

def test_certificate_expiry_sweep_out_of_service(api):
    """PRD §3.6: "Expiry lapses the unit — `registration_status` from `REGISTERED` to
    `LAPSED` — and forces the equipment out of service — `equipment_status` from
    `IN_SERVICE` to `OUT_OF_SERVICE` — which in turn cascade-cancels the unit's `OPEN`
    or `DISPATCHED` service calls with their consumed visits restored."

    Design: Corner/state_machines/certificate_expiry_sweep_out_of_service
    """
    ctx = create_registered_project()
    get_success_data(api.set_clock({"to_iso8601": "2027-08-13T00:00:00Z"}, ADMIN))
    cert = get_success_data(api.get_certificate(ctx["certificate"]["id"], COORD))
    assert cert["status"] == "EXPIRED"
    unit = get_success_data(api.get_unit(ctx["unit"]["id"], COORD))
    assert unit["registration_status"] == "LAPSED"
    assert unit["equipment_status"] == "OUT_OF_SERVICE"


# ===========================================================================
# Queue B — Corner/state_machines/inspection_record_before_window_rejected
# ===========================================================================

def test_inspection_record_before_window_rejected(api):
    """PRD §3.5: "Only the assigned inspector records the result
    (`ERR_NOT_ASSIGNED_INSPECTOR`), and not before `scheduled_start`
    (`ERR_INSPECTION_NOT_STARTED`)."

    Design: Corner/state_machines/inspection_record_before_window_rejected
    """
    ctx = create_install_complete_project()
    inspector = create_technician(name="Quinn Inspector", certification="QEI")
    insp = get_success_data(api.create_inspection(
        factories.create_inspection_payload(ctx["unit"]["id"], inspector["id"],
                                            project_id=ctx["project"]["id"]), COORD))
    # Clock is already 2026-08-12T09:00 from setup; window starts 10:00.
    resp = api.record_inspection_result(
        insp["id"], {"result": "PASSED"}, make_inspector_headers(inspector["id"]))
    validate_error(resp, ApiErrorId.ERR_INSPECTION_NOT_STARTED)
    insp = get_success_data(api.get_inspection(insp["id"], COORD))
    assert insp["status"] == "SCHEDULED"


# ===========================================================================
# Queue B — Corner/state_machines/failed_inspection_requires_deficiency_codes
# ===========================================================================

def test_failed_inspection_requires_deficiency_codes(api):
    """PRD §3.5: "a failing result moves it to `FAILED` and requires a non-empty
    `deficiency_codes` array (`ERR_DEFICIENCY_CODES_REQUIRED`)."

    Design: Corner/state_machines/failed_inspection_requires_deficiency_codes
    """
    ctx = create_registered_project()
    inspector = ctx["inspector"]
    insp = get_success_data(api.create_inspection(
        factories.create_inspection_payload(
            ctx["unit"]["id"], inspector["id"], inspection_type="ANNUAL",
            scheduled_start="2026-09-02T09:00:00Z", scheduled_end="2026-09-02T10:00:00Z"),
        COORD))
    get_success_data(api.set_clock({"to_iso8601": "2026-09-02T09:05:00Z"}, ADMIN))
    resp = api.record_inspection_result(
        insp["id"], {"result": "FAILED"}, make_inspector_headers(inspector["id"]))
    validate_error(resp, ApiErrorId.ERR_DEFICIENCY_CODES_REQUIRED)
    insp = get_success_data(api.get_inspection(insp["id"], COORD))
    assert insp["status"] == "SCHEDULED"
    cert = get_success_data(api.get_certificate(ctx["certificate"]["id"], COORD))
    assert cert["status"] == "ACTIVE"
