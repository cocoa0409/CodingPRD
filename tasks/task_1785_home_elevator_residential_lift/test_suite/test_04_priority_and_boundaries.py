"""Validation priority pairs, numeric boundaries, and resource window overlaps
(PRD §2.7, §3.1, §3.4, §3.5, §3.7, §3.8)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    create_contractor,
    create_grant_application_payload,
    create_grant_program,
    create_grant_program_payload,
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
)

COORD = TEST_USERS["coordinator_headers"]
ADMIN = TEST_USERS["dealer_admin_headers"]
REGULATOR = TEST_USERS["regulator_headers"]
OFFICER = TEST_USERS["grant_officer_headers"]


# ===========================================================================
# Queue A — priority_pair_validation_conflict / grant_create_state_beats_fiscal
# ===========================================================================

class TestGrantCreateStateBeatsFiscal:
    def test_state_error_reported_over_income_cap(self, api):
        """PRD §2.7: "Every endpoint applies its guard checks in a fixed priority order,
        and when several checks could fail on the same request the earliest one wins."
        PRD §2.7: "11. **Fiscal gates, always last** — money gates are evaluated after
        every other class: household income at submission (`ERR_INCOME_ABOVE_CAP`, 402),
        verified income at approval (`ERR_VERIFIED_INCOME_INELIGIBLE`, 402), and pool
        availability at approval (`ERR_GRANT_POOL_EXHAUSTED`, 402)."

        Design: Difficulty/priority_pair_validation_conflict/grant_create_state_beats_fiscal
        """
        ctx = create_project_draft()  # DRAFT: no product selected
        program = create_grant_program()
        resp = api.create_grant_application(
            create_grant_application_payload(
                ctx["project"]["id"], program["id"], household_income=70000.00),
            make_homeowner_headers(ctx["prop"]["owner_user_id"]))
        validate_error(resp, ApiErrorId.ERR_PROJECT_STATE_FORBIDS)
        assert resp.json()["data"]["error_id"] != "ERR_INCOME_ABOVE_CAP"

    def test_rejected_submission_creates_no_application(self, api):
        """PRD §3.8: "A homeowner applies by naming the `project_id`, the `program_id`,
        and declaring `household_income`. Submission requires the clock to fall within
        the program's inclusive application window (`ERR_APPLICATION_WINDOW_CLOSED`),
        the program to be `OPEN` (`ERR_PROGRAM_NOT_OPEN`), the project's `project_type`
        to appear in the program's `eligible_project_types`
        (`ERR_PROJECT_TYPE_INELIGIBLE`), the declared income to be no greater than
        `income_cap` (`ERR_INCOME_ABOVE_CAP`), the project to be in one of `QUOTED`,
        `PERMIT_IN_PROGRESS`, `PERMIT_APPROVED`, `STRUCTURAL_IN_PROGRESS`,
        `READY_FOR_INSTALL`, or `INSTALL_SCHEDULED` (`ERR_PROJECT_STATE_FORBIDS`), and
        no existing `SUBMITTED` or `APPROVED` application for the same project and
        program pair (`ERR_DUPLICATE_APPLICATION`)."

        Design: Difficulty/priority_pair_validation_conflict/grant_create_state_beats_fiscal
        """
        ctx = create_project_draft()
        program = create_grant_program()
        resp = api.create_grant_application(
            create_grant_application_payload(
                ctx["project"]["id"], program["id"], household_income=70000.00),
            make_homeowner_headers(ctx["prop"]["owner_user_id"]))
        validate_error(resp, ApiErrorId.ERR_PROJECT_STATE_FORBIDS)
        apps, _meta = validate_paginated(api.list_grant_applications(
            COORD, params={"project_id": ctx["project"]["id"]}))
        assert apps == []


# ===========================================================================
# Queue A — priority_pair_validation_conflict / inspection_create_safety_beats_temporal
# ===========================================================================

class TestInspectionCreateSafetyBeatsTemporal:
    def _setup_install_complete(self, api):
        from test_helpers import create_install_complete_project
        return create_install_complete_project()

    def test_certification_error_reported_over_date_range(self, api):
        """PRD §2.7: "6. **Certification** — the referenced technician holds the
        certification the operation demands: CET (or `CET_AND_QEI`) to install or to be
        dispatched on `REPAIR` and `ENTRAPMENT` calls, QEI (or `CET_AND_QEI`) to perform
        inspections; otherwise `ERR_TECHNICIAN_NOT_CERTIFIED` (HTTP 403)." and item 10
        lists the temporal gates after it.

        Design: Difficulty/priority_pair_validation_conflict/inspection_create_safety_beats_temporal
        """
        ctx = self._setup_install_complete(api)
        # Installer holds CET only (no QEI); the window is also inverted.
        resp = api.create_inspection(
            factories.create_inspection_payload(
                ctx["unit"]["id"], ctx["installer"]["id"],
                scheduled_start="2026-08-13T10:00:00Z", scheduled_end="2026-08-13T09:00:00Z",
                project_id=ctx["project"]["id"]), COORD)
        validate_error(resp, ApiErrorId.ERR_TECHNICIAN_NOT_CERTIFIED)
        assert resp.json()["data"]["error_id"] != "ERR_INVALID_DATE_RANGE"

    def test_rejected_inspection_creates_no_row(self, api):
        """PRD §3.5: "the inspector must hold QEI-level certification
        (`ERR_TECHNICIAN_NOT_CERTIFIED`) and must differ from the project's lead
        installer (`ERR_INSPECTOR_NOT_INDEPENDENT`)."

        Design: Difficulty/priority_pair_validation_conflict/inspection_create_safety_beats_temporal
        """
        ctx = self._setup_install_complete(api)
        resp = api.create_inspection(
            factories.create_inspection_payload(
                ctx["unit"]["id"], ctx["installer"]["id"],
                scheduled_start="2026-08-13T10:00:00Z", scheduled_end="2026-08-13T09:00:00Z",
                project_id=ctx["project"]["id"]), COORD)
        validate_error(resp, ApiErrorId.ERR_TECHNICIAN_NOT_CERTIFIED)
        inspections, _meta = validate_paginated(
            api.list_inspections(COORD, params={"unit_id": ctx["unit"]["id"]}))
        assert inspections == []


# ===========================================================================
# Queue A — priority_pair_validation_conflict / work_order_create_existence_beats_referential
# ===========================================================================

class TestWorkOrderCreateExistenceBeatsReferential:
    def _suspended_contractor(self, api):
        gc = create_contractor()
        get_success_data(api.suspend_contractor(gc["id"], ADMIN))
        return gc

    def test_not_found_reported_over_suspended_contractor(self, api):
        """PRD §2.7: "Every endpoint applies its guard checks in a fixed priority order,
        and when several checks could fail on the same request the earliest one wins."
        PRD §2.7: "4. **Body well-formedness and body references** — required fields are
        present, types and enum members are valid, and no unknown fields appear,
        yielding `ERR_INVALID_REQUEST` (HTTP 400); only after that are the body's
        foreign-key references (`property_id`, `survey_id`, `product_model_id`,
        technician ids, `contractor_id`, `project_id`, `unit_id`, `program_id`,
        `modernize_unit_id`) resolved, each to the same not-found set."

        Design: Difficulty/priority_pair_validation_conflict/work_order_create_existence_beats_referential
        """
        gc = self._suspended_contractor(api)
        resp = api.create_work_order(
            factories.create_work_order_payload(NON_EXISTENT_UUID, gc["id"],
                                                scope_description="Pit deepening",
                                                estimated_cost=5000.00), COORD)
        validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_FOUND)
        assert resp.json()["data"]["error_id"] != "ERR_CONTRACTOR_NOT_ACTIVE"

    def test_not_found_is_http_404(self, api):
        """PRD §2.7 item 4: "only after that are the body's foreign-key references
        (`property_id`, `survey_id`, `product_model_id`, technician ids,
        `contractor_id`, `project_id`, `unit_id`, `program_id`, `modernize_unit_id`)
        resolved, each to the same not-found set."

        Design: Difficulty/priority_pair_validation_conflict/work_order_create_existence_beats_referential
        """
        gc = self._suspended_contractor(api)
        resp = api.create_work_order(
            factories.create_work_order_payload(NON_EXISTENT_UUID, gc["id"]), COORD)
        error = validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_FOUND)
        assert resp.status_code == 404
        assert error["error_id"] == "ERR_PROJECT_NOT_FOUND"


# ===========================================================================
# Queue A — boundary_precision_check / pit_depth_exact_equality_fits
# ===========================================================================

class TestPitDepthExactEqualityFits:
    def test_exact_minimum_measurements_are_feasible(self, api):
        """PRD §3.1: "A model **fits directly** when both shortfalls are exactly zero;
        it **fits correctably** when each shortfall is at most 12 inches, the maximum
        correctable shortfall. The verdict is `FEASIBLE` when at least one active model
        fits directly".

        Design: Difficulty/boundary_precision_check/pit_depth_exact_equality_fits
        """
        ctx = create_quoted_project()  # survey 12/96 exactly meets the model minimums
        survey = get_success_data(api.get_survey(ctx["survey"]["id"], COORD))
        assert survey["feasibility_verdict"] == "FEASIBLE"

    def test_zero_shortfall_requires_no_structural(self, api):
        """PRD §3.2: "When `requires_structural` is true, the `structural_estimate` is a
        base structural fee of $1,500.00 plus $250.00 per inch of pit shortfall plus
        $150.00 per inch of overhead shortfall; when no shortfall exists, the estimate
        is zero."

        Design: Difficulty/boundary_precision_check/pit_depth_exact_equality_fits
        """
        ctx = create_quoted_project()
        project = ctx["project"]
        assert project["requires_structural"] is False
        assert project["structural_estimate"] == 0
        assert project["contract_price"] == 33000.00


# ===========================================================================
# Queue A — boundary_precision_check / income_cap_exact_equality_allowed
# ===========================================================================

class TestIncomeCapExactEqualityAllowed:
    def _setup(self, api):
        ctx = create_quoted_project()
        prog_a = create_grant_program(program_name="ProgA", funder_name="Fund A")
        prog_b = create_grant_program(program_name="ProgB", funder_name="Fund B")
        return ctx, prog_a, prog_b

    def test_income_exactly_at_cap_is_eligible(self, api):
        """PRD §3.8: "the declared income to be no greater than `income_cap`
        (`ERR_INCOME_ABOVE_CAP`)".

        Design: Difficulty/boundary_precision_check/income_cap_exact_equality_allowed
        """
        ctx, prog_a, _prog_b = self._setup(api)
        app = get_success_data(api.create_grant_application(
            create_grant_application_payload(ctx["project"]["id"], prog_a["id"],
                                             household_income=60000.00),
            make_homeowner_headers(ctx["prop"]["owner_user_id"])))
        assert app["status"] == "SUBMITTED"

    def test_income_one_cent_over_cap_rejected(self, api):
        """PRD §3.8: "the declared income to be no greater than `income_cap`
        (`ERR_INCOME_ABOVE_CAP`)".

        Design: Difficulty/boundary_precision_check/income_cap_exact_equality_allowed
        """
        ctx, prog_a, prog_b = self._setup(api)
        owner = make_homeowner_headers(ctx["prop"]["owner_user_id"])
        get_success_data(api.create_grant_application(
            create_grant_application_payload(ctx["project"]["id"], prog_a["id"],
                                             household_income=60000.00), owner))
        resp = api.create_grant_application(
            create_grant_application_payload(ctx["project"]["id"], prog_b["id"],
                                             household_income=60000.01), owner)
        validate_error(resp, ApiErrorId.ERR_INCOME_ABOVE_CAP)
        apps, _meta = validate_paginated(
            api.list_grant_applications(COORD, params={"project_id": ctx["project"]["id"]}))
        assert len(apps) == 1


# ===========================================================================
# Queue A — boundary_precision_check / sla_arrival_exact_equality_not_breached
# ===========================================================================

class TestSlaArrivalExactEqualityNotBreached:
    def _setup(self, api):
        ctx = create_unit_with_contract(tier="PREMIUM")
        get_success_data(api.set_clock({"to_iso8601": "2026-09-10T17:30:00Z"}, ADMIN))
        call = create_service_call(ctx, call_type="ENTRAPMENT")
        call = get_success_data(api.dispatch_service_call(
            call["id"], {"technician_id": ctx["installer"]["id"]}, COORD))
        get_success_data(api.set_clock({"to_iso8601": "2026-09-10T18:30:00Z"}, ADMIN))
        return ctx, call

    def test_sla_deadline_is_reported_plus_tier_minutes(self, api):
        """PRD §3.7: "for an `ENTRAPMENT` call the `sla_deadline` is set to `reported_at`
        plus the attached contract's entrapment SLA minutes — or 240 minutes when no
        contract is attached."  PRD §3.7: "`PREMIUM` carries $2,400.00 with 4 visits and
        60 minutes."

        Design: Difficulty/boundary_precision_check/sla_arrival_exact_equality_not_breached
        """
        _ctx, call = self._setup(api)
        assert call["sla_deadline"] == "2026-09-10T18:30:00.000Z"

    def test_arrival_exactly_at_deadline_is_compliant(self, api):
        """PRD §3.7: "for an entrapment call, `sla_breached` is computed here as true
        exactly when the elapsed minutes from `reported_at` to `arrived_at` are strictly
        greater than the SLA minutes — arrival exactly at the deadline is compliant."

        Design: Difficulty/boundary_precision_check/sla_arrival_exact_equality_not_breached
        """
        ctx, call = self._setup(api)
        call = get_success_data(api.arrive_service_call(
            call["id"], make_installer_headers(ctx["installer"]["id"])))
        assert call["sla_breached"] is False
        assert call["status"] == "ON_SITE"


# ===========================================================================
# Queue A — resource_temporal_overlap / contractor_window_pure_overlap
# ===========================================================================

class TestContractorWindowPureOverlap:
    def _setup_two_work_orders(self, api):
        """Two PERMIT_APPROVED structural projects sharing one contractor; WO1 RELEASED
        on [08-10, 08-20); WO2 DRAFT on [08-15, 08-25)."""
        gc = create_contractor(license_state_code="CA")
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
                prop_overrides={"address_line": address, "state_code": "CA"},
                contractor=True)
            # Re-select with the shared contractor.
            project = get_success_data(api.get_project(ctx["project"]["id"], COORD))
            ctx["project"] = get_success_data(api.update_project(project["id"], {
                "product_model_id": ctx["model"]["id"],
                "lead_installer_technician_id": ctx["installer"]["id"],
                "contractor_id": gc["id"],
                "expected_project_version": project["version"],
            }, COORD))
            permit = get_success_data(api.create_permit(
                factories.create_permit_payload(ctx["project"]["id"]), COORD))
            get_success_data(api.approve_permit(permit["id"], REGULATOR))
            ctx["contractor"] = gc
            ctxs.append(ctx)
        wo1 = get_success_data(api.create_work_order(
            factories.create_work_order_payload(
                ctxs[0]["project"]["id"], gc["id"], scope_description="Pit deepening P1",
                scheduled_start_date="2026-08-10T08:00:00Z",
                scheduled_end_date="2026-08-20T17:00:00Z"), COORD))
        wo1 = get_success_data(api.release_work_order(wo1["id"], COORD))
        wo2 = get_success_data(api.create_work_order(
            factories.create_work_order_payload(
                ctxs[1]["project"]["id"], gc["id"], scope_description="Pit deepening P2",
                scheduled_start_date="2026-08-15T08:00:00Z",
                scheduled_end_date="2026-08-25T17:00:00Z"), COORD))
        return gc, wo1, wo2

    def test_pure_overlap_rejected(self, api):
        """PRD §3.4: "Release requires the contractor to be `ACTIVE`
        (`ERR_CONTRACTOR_NOT_ACTIVE`) and checks window overlap against that
        contractor's other released or work-complete orders: the windows are treated as
        half-open intervals, so a conflict exists exactly when the new window's start is
        before an existing window's end **and** the existing window's start is before
        the new window's end; pure adjacency — one window's end equal to the other's
        start — is allowed. A true overlap is rejected with
        `ERR_CONTRACTOR_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/contractor_window_pure_overlap
        """
        _gc, wo1, wo2 = self._setup_two_work_orders(api)
        resp = api.release_work_order(wo2["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_CONTRACTOR_WINDOW_OVERLAP)
        wo2 = get_success_data(api.get_work_order(wo2["id"], COORD))
        assert wo2["status"] == "DRAFT"

    def test_rejected_release_leaves_existing_order_untouched(self, api):
        """PRD §3.4: "Release moves the work order from `DRAFT` to `RELEASED` and the
        project from `PERMIT_APPROVED` to `STRUCTURAL_IN_PROGRESS`." — a rejected
        release performs neither mutation.

        Design: Difficulty/resource_temporal_overlap/contractor_window_pure_overlap
        """
        _gc, wo1, wo2 = self._setup_two_work_orders(api)
        resp = api.release_work_order(wo2["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_CONTRACTOR_WINDOW_OVERLAP)
        wo1 = get_success_data(api.get_work_order(wo1["id"], COORD))
        assert wo1["status"] == "RELEASED"


# ===========================================================================
# Queue A — resource_temporal_overlap / inspector_buffered_overlap
# ===========================================================================

class TestInspectorBufferedOverlap:
    def _setup_first_annual(self, api):
        ctx = create_registered_project()
        first = get_success_data(api.create_inspection(
            factories.create_inspection_payload(
                ctx["unit"]["id"], ctx["inspector"]["id"], inspection_type="ANNUAL",
                scheduled_start="2026-09-02T09:00:00Z",
                scheduled_end="2026-09-02T10:00:00Z"), COORD))
        return ctx, first

    def test_thirty_minute_gap_rejected(self, api):
        """PRD §3.5: "Scheduling also enforces a buffered-conflict rule: a new
        inspection window may not begin within 45 minutes of another `SCHEDULED`
        inspection for the same inspector — adjacency without a full 45-minute gap is
        rejected with `ERR_INSPECTOR_BUFFER_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/inspector_buffered_overlap
        """
        ctx, first = self._setup_first_annual(api)
        resp = api.create_inspection(
            factories.create_inspection_payload(
                ctx["unit"]["id"], ctx["inspector"]["id"], inspection_type="ANNUAL",
                scheduled_start="2026-09-02T10:30:00Z",
                scheduled_end="2026-09-02T11:30:00Z"), COORD)
        validate_error(resp, ApiErrorId.ERR_INSPECTOR_BUFFER_CONFLICT)
        first = get_success_data(api.get_inspection(first["id"], COORD))
        assert first["status"] == "SCHEDULED"

    def test_rejected_conflict_leaves_single_scheduled_inspection(self, api):
        """PRD §3.5: "a new inspection window may not begin within 45 minutes of another
        `SCHEDULED` inspection for the same inspector — adjacency without a full
        45-minute gap is rejected with `ERR_INSPECTOR_BUFFER_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/inspector_buffered_overlap
        """
        ctx, _first = self._setup_first_annual(api)
        resp = api.create_inspection(
            factories.create_inspection_payload(
                ctx["unit"]["id"], ctx["inspector"]["id"], inspection_type="ANNUAL",
                scheduled_start="2026-09-02T10:30:00Z",
                scheduled_end="2026-09-02T11:30:00Z"), COORD)
        validate_error(resp, ApiErrorId.ERR_INSPECTOR_BUFFER_CONFLICT)
        inspections, _meta = validate_paginated(api.list_inspections(
            COORD, params={"inspector_technician_id": ctx["inspector"]["id"],
                           "status": "SCHEDULED"}))
        assert len(inspections) == 1
