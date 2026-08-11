"""Dredge type selection, production estimate variants, plan review loop, and
the approval gate (PRD §2.7, §3.3)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    assert_dredge_plan,
    create_dredge_plan_payload,
    set_clock, create_project, add_permit, add_reach, add_plant, add_plan,
    submit_plan, approve_plan, activate_project, get_project,
)


def _project_with_reach_and_plant(reach_overrides=None, plant_overrides=None,
                                  project_overrides=None):
    set_clock("2026-05-10T00:00:00Z")
    project = create_project(**(project_overrides or {}))
    reach = add_reach(project["id"], **(reach_overrides or {}))
    plant = add_plant(**(plant_overrides or {}))
    return project, reach, plant


class TestProductionEstimateVariants:
    def test_production_estimate_daily_rate_variants(self, api, contractor_headers):
        """PRD §3.3: "The material factor keyed by `material_class` is 1.00 for
        `SAND`, 0.85 for `SILT`, 0.70 for `CLAY`, 0.55 for `GRAVEL`, and 0.35 for
        `ROCK`."
        PRD §3.3: "The `risk_adjusted_daily_production_cy` applies the standing
        twenty-percent weather allowance — the nominal rate multiplied by
        four-fifths — again rounded half up to 2 decimal places."

        Design: Difficulty/dual_variant_calc/production_estimate_nominal_vs_risk_adjusted
        """
        project, reach, plant = _project_with_reach_and_plant(
            plant_overrides={"plant_type": "CUTTER_SUCTION"}
        )
        res = api.create_dredge_plan(
            create_dredge_plan_payload(project["id"], plant["id"],
                                       material_class="SAND"),
            contractor_headers,
        )
        plan = validate_success(res, 201)
        assert_dredge_plan(plan)
        # 4000 x 1.00 (SAND) x 1.00 (max depth 25.0 < 30) = 4000.00 nominal.
        assert plan["nominal_daily_production_cy"] == pytest.approx(4000.00, abs=1e-4)
        # 4000.00 x 0.80 weather derate = 3200.00 risk-adjusted.
        assert plan["risk_adjusted_daily_production_cy"] == pytest.approx(3200.00, abs=1e-4)
        assert plan["risk_adjusted_daily_production_cy"] < plan["nominal_daily_production_cy"]

    def test_production_estimate_duration_variants(self, api, contractor_headers):
        """PRD §3.3: "Dividing total design quantity by each daily rate and
        rounding up to whole days yields `nominal_duration_days` and
        `risk_adjusted_duration_days`."
        PRD §3.3: "the risk-adjusted variant is strictly smaller as a daily rate
        and produces a duration that is longer than or equal to the nominal one".

        Design: Difficulty/dual_variant_calc/production_estimate_nominal_vs_risk_adjusted
        """
        project, reach, plant = _project_with_reach_and_plant(
            plant_overrides={"plant_type": "CUTTER_SUCTION"}
        )
        res = api.create_dredge_plan(
            create_dredge_plan_payload(project["id"], plant["id"],
                                       material_class="SAND"),
            contractor_headers,
        )
        plan = validate_success(res, 201)
        # ceil(40000 / 4000.00) = 10; ceil(40000 / 3200.00) = ceil(12.5) = 13.
        assert plan["nominal_duration_days"] == 10
        assert plan["risk_adjusted_duration_days"] == 13
        assert plan["risk_adjusted_duration_days"] >= plan["nominal_duration_days"]

    def test_production_estimate_depth_and_material_tiers(self, api,
                                                          contractor_headers):
        """PRD §3.3: "The depth factor comes from the deepest `required_depth_ft`
        among the project's reaches: 1.00 when that maximum is below 30 feet, 0.85
        when it is at least 30 but below 50 feet, and 0.70 when it is 50 feet or
        deeper."
        PRD §3.3: "The `nominal_daily_production_cy` is the plant's
        `rated_daily_production_cy` multiplied by the material factor and the
        depth factor, rounded half up to 2 decimal places."

        Design: Corner/calculations/production_estimate_depth_and_material_tiers
        """
        project, reach, plant = _project_with_reach_and_plant(
            reach_overrides={"required_depth_ft": 40.0},
            plant_overrides={"plant_type": "CUTTER_SUCTION"},
        )
        res = api.create_dredge_plan(
            create_dredge_plan_payload(project["id"], plant["id"],
                                       material_class="CLAY"),
            contractor_headers,
        )
        plan = validate_success(res, 201)
        # 4000 x 0.70 (CLAY) x 0.85 (30 <= 40 < 50) = 2380.00; x 0.80 = 1904.00.
        assert plan["nominal_daily_production_cy"] == pytest.approx(2380.00, abs=1e-4)
        assert plan["risk_adjusted_daily_production_cy"] == pytest.approx(1904.00, abs=1e-4)
        assert plan["nominal_duration_days"] == 17  # ceil(40000 / 2380.00)
        assert plan["risk_adjusted_duration_days"] == 22  # ceil(40000 / 1904.00)


class TestPlanReviewLoop:
    def test_plan_revision_cycle_increments(self, api, owner_headers,
                                            contractor_headers):
        """PRD §3.3: "An `OwnerEngineer` may request changes, returning it to
        `CHANGES_REQUESTED`, and the next submission — the revision cycle —
        increments `revision` and recomputes every estimate field."
        PRD §3.3: "The plan is born `DRAFT` at `revision` 1".

        Design: Corner/state_machines/plan_revision_cycle_increments
        """
        project, reach, plant = _project_with_reach_and_plant()
        plan = add_plan(project["id"], plant["id"])
        assert plan["revision"] == 1
        assert plan["status"] == "DRAFT"
        submit_plan(plan["id"])
        res = api.request_changes_dredge_plan(plan["id"], owner_headers)
        assert validate_success(res, 200)["status"] == "CHANGES_REQUESTED"
        resubmitted = validate_success(
            api.submit_dredge_plan(plan["id"], contractor_headers), 200
        )
        assert resubmitted["revision"] == 2
        assert resubmitted["status"] == "SUBMITTED"


class TestApprovalGate:
    def test_plan_approve_window_infeasible_rejected(self, api, owner_headers):
        """PRD §3.3: "Window feasibility compares the planned interval against
        the risk-adjusted estimate: the elapsed span between `planned_start_utc`
        and `planned_end_utc`, divided by twenty-four hours and rounded down to
        whole days, must be at least `risk_adjusted_duration_days`, else the
        approval fails with `ERR_PLAN_WINDOW_INFEASIBLE` (HTTP 422)."

        Design: Corner/validations/plan_approve_window_infeasible_rejected
        """
        project, reach, plant = _project_with_reach_and_plant(
            plant_overrides={"plant_type": "CUTTER_SUCTION"}
        )
        add_permit(project["id"])
        plan = add_plan(project["id"], plant["id"],
                        planned_start_utc="2026-05-10T00:00:00Z",
                        planned_end_utc="2026-05-15T00:00:00Z")
        assert plan["risk_adjusted_duration_days"] == 13  # exceeds 5-day window
        submit_plan(plan["id"])
        project = get_project(project["id"])
        res = api.approve_dredge_plan(
            plan["id"], {"expected_project_version": project["version"]},
            owner_headers,
        )
        validate_error(res, ApiErrorId.ERR_PLAN_WINDOW_INFEASIBLE,
                       expected_status=422)
        plan_after = validate_success(api.get_dredge_plan(plan["id"], owner_headers))
        assert plan_after["status"] == "SUBMITTED"

    def test_plan_approve_plant_out_of_service_rejected(self, api, owner_headers,
                                                        contractor_headers):
        """PRD §3.3: "The referenced plant must be `REGISTERED`, else
        `ERR_PLANT_UNAVAILABLE` (HTTP 409)".

        Design: Corner/validations/plan_approve_plant_out_of_service_rejected
        """
        project, reach, plant = _project_with_reach_and_plant(
            plant_overrides={"plant_type": "CUTTER_SUCTION"}
        )
        add_permit(project["id"])
        plan = add_plan(project["id"], plant["id"])
        submit_plan(plan["id"])
        # Plant goes down between submission and approval.
        validate_success(
            api.patch_plant(plant["id"], {"status": "OUT_OF_SERVICE"},
                            contractor_headers),
            200,
        )
        project = get_project(project["id"])
        res = api.approve_dredge_plan(
            plan["id"], {"expected_project_version": project["version"]},
            owner_headers,
        )
        validate_error(res, ApiErrorId.ERR_PLANT_UNAVAILABLE, expected_status=409)
        plan_after = validate_success(api.get_dredge_plan(plan["id"], owner_headers))
        assert plan_after["status"] == "SUBMITTED"


class TestPlantAssignmentWindows:
    def _two_projects_sharing_one_plant(self):
        set_clock("2026-05-10T00:00:00Z")
        p1 = create_project(name="P1")
        p2 = create_project(name="P2")
        add_permit(p1["id"], permit_number="PER-1")
        add_permit(p2["id"], permit_number="PER-2")
        add_reach(p1["id"], name="R1")
        add_reach(p2["id"], name="R2")
        plant = add_plant(contractor_ref="DGE-9", plant_type="CUTTER_SUCTION")
        plan_a = add_plan(p1["id"], plant["id"],
                          planned_start_utc="2026-05-10T00:00:00Z",
                          planned_end_utc="2026-06-01T00:00:00Z")
        submit_plan(plan_a["id"])
        plan_a = approve_plan(p1["id"], plan_a["id"])
        assert plan_a["status"] == "APPROVED"
        return p1, p2, plant, plan_a

    def test_plant_assignment_touching_endpoint_allowed(self, api, owner_headers,
                                                        contractor_headers):
        """PRD §3.3: "The new plan conflicts with another `APPROVED` plan of the
        same plant only when this plan starts strictly before the other's end and
        the other starts strictly before this plan's end; two plans touching at
        an endpoint do not conflict."
        PRD §3.3: "Assignment windows are half-open: an instant exactly on
        `planned_start_utc` is inside, one exactly on `planned_end_utc` is
        outside."

        Design: Difficulty/resource_temporal_overlap/plant_assignments_half_open_touching_allowed
        """
        p1, p2, plant, plan_a = self._two_projects_sharing_one_plant()
        # planB starts exactly at planA's exclusive end 2026-06-01: half-open
        # touching, so no conflict.
        plan_b = add_plan(p2["id"], plant["id"],
                          planned_start_utc="2026-06-01T00:00:00Z",
                          planned_end_utc="2026-07-01T00:00:00Z")
        submit_plan(plan_b["id"])
        p2_fresh = get_project(p2["id"])
        res = api.approve_dredge_plan(
            plan_b["id"], {"expected_project_version": p2_fresh["version"]},
            owner_headers,
        )
        approved_b = validate_success(res, 200)
        assert approved_b["status"] == "APPROVED"

    def test_plant_assignment_true_overlap_rejected(self, api, owner_headers,
                                                    contractor_headers):
        """PRD §3.3: "A violation is `ERR_PLANT_ASSIGNMENT_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/plant_assignments_half_open_touching_allowed
        """
        p1, p2, plant, plan_a = self._two_projects_sharing_one_plant()
        # planC [05-31, 06-15) genuinely intersects planA's [05-10, 06-01):
        # planC starts strictly before planA's end and planA starts strictly
        # before planC's end.
        plan_c = add_plan(p2["id"], plant["id"],
                          planned_start_utc="2026-05-31T00:00:00Z",
                          planned_end_utc="2026-06-15T00:00:00Z")
        submit_plan(plan_c["id"])
        p2_fresh = get_project(p2["id"])
        res = api.approve_dredge_plan(
            plan_c["id"], {"expected_project_version": p2_fresh["version"]},
            owner_headers,
        )
        validate_error(res, ApiErrorId.ERR_PLANT_ASSIGNMENT_OVERLAP,
                       expected_status=409)
        plan_c_after = validate_success(api.get_dredge_plan(plan_c["id"],
                                                            owner_headers))
        assert plan_c_after["status"] == "SUBMITTED"


class TestOptimisticConcurrencyOnApproval:
    def test_occ_stale_project_version_on_plan_approve(self, api, owner_headers):
        """PRD §2.7: "If that value does not match the Project's current
        `version` — because another writer has advanced the project since the
        client last read it — the approval is rejected with
        `ERR_STALE_PROJECT_VERSION` (HTTP 412)."
        PRD §3.3: "Approval carries a create-with-supersede side effect: whichever
        plan of the same project is currently `APPROVED` transitions to
        `SUPERSEDED`, and the project's `version` increments, which is exactly
        what the next approval's `expected_project_version` observes."

        Design: Corner/complexity_layers/occ_stale_project_version_on_plan_approve
        """
        set_clock("2026-05-10T00:00:00Z")
        project = create_project(name="P-OCC1")
        add_permit(project["id"])
        add_reach(project["id"])
        plant = add_plant(plant_type="CUTTER_SUCTION")
        plan_a = add_plan(project["id"], plant["id"])
        submit_plan(plan_a["id"])
        approve_plan(project["id"], plan_a["id"])
        # Version observed before activation; activation advances it (PRD §3.1).
        stale_version = get_project(project["id"])["version"]
        activate_project(project["id"])
        plan_b = add_plan(project["id"], plant["id"],
                          planned_start_utc="2026-07-01T00:00:00Z",
                          planned_end_utc="2026-08-31T00:00:00Z")
        submit_plan(plan_b["id"])
        res = api.approve_dredge_plan(
            plan_b["id"], {"expected_project_version": stale_version},
            owner_headers,
        )
        validate_error(res, ApiErrorId.ERR_STALE_PROJECT_VERSION,
                       expected_status=412)
        # Retry with the fresh version: succeeds, superseding planA.
        fresh_version = get_project(project["id"])["version"]
        approved = validate_success(
            api.approve_dredge_plan(
                plan_b["id"], {"expected_project_version": fresh_version},
                owner_headers,
            ),
            200,
        )
        assert approved["status"] == "APPROVED"
        plan_a_after = validate_success(api.get_dredge_plan(plan_a["id"],
                                                            owner_headers))
        assert plan_a_after["status"] == "SUPERSEDED"
