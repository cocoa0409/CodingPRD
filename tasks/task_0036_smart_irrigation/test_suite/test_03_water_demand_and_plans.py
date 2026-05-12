"""Irrigation plans, water-demand model, lifecycle.

PRD references:
  - §3.2 Irrigation Plans and the Water-Demand Model
  - §2.10 Concurrency and Race Resolution (plan window overlap)
"""
from __future__ import annotations

import pytest

from test_helpers import (
    DEFAULT_NOW_ISO,
    activate_plan,
    add_days,
    add_hours,
    assert_irrigation_plan,
    create_plan,
    create_plan_payload,
    create_plot,
    create_sensor,
    create_tenant,
    create_water_quota,
    list_audit_logs,
    find_audit_entries,
    setup_full_active_scenario,
    setup_overlap_plans,
    setup_tenant_plot_quota,
    suspend_plan,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.2 — Plan creation defaults
# ===========================================================================
class TestPlanCreationDefaults:
    def test_create_plan_initial_state_draft_version_one(
        self, api, water_admin_headers,
    ):
        """PRD §3.2: 'Every plan begins in DRAFT with plan_version 1
        and a null parent_plan_id.'

        Claim: brand-new plan has status=DRAFT, plan_version=1,
        parent_plan_id=None.
        """
        tenant, plot, quota, _ = setup_tenant_plot_quota()
        ws = quota["period_start"]
        we = add_days(ws, 1)
        res = api.create_irrigation_plan(
            plot["id"],
            create_plan_payload(
                window_start=ws, window_end=we,
                source="MANUAL_OVERRIDE", planned_volume_liters=500.0,
            ),
            water_admin_headers,
        )
        plan = validate_success(res, expected_status=201)
        assert_irrigation_plan(plan)
        assert plan["status"] == "DRAFT"
        assert plan["plan_version"] == 1
        assert plan.get("parent_plan_id") is None


# ===========================================================================
# §3.2 — Crop water demand model: AUTO source
# ===========================================================================
class TestCropWaterDemand:
    def test_auto_plan_uses_stage_demand_no_sensor_data(
        self, api, water_admin_headers,
    ):
        """PRD §3.2: 'the stage base demand in liters per hectare is
        20000 for SEEDLING, 35000 for VEGETATIVE, 50000 for FLOWERING,
        45000 for FRUITING, and 25000 for MATURE; this is multiplied
        by area_hectares to obtain the base liters.'
        PRD §3.2: 'The latest valid moisture reading is the most recent
        SensorReading from a SOIL_MOISTURE sensor on the plot whose
        validity is VALID, ordered by reading_timestamp descending and
        taking the first one; if no such reading exists, the model uses
        50 as the default.'
        PRD §3.2: 'the recent rainfall is the most recent VALID
        SensorReading from a WEATHER_STATION sensor on the plot taken
        within the last 24 hours, defaulting to zero millimetres if
        none.'

        For CORN at VEGETATIVE with area=10ha and no sensor data:
          base = 35000 * 10 = 350000
          moisture_adj = max(0, (65 - 50)/100) = 0.15
          weather_adj = max(0, (1 - 0/30)) = 1.0
          planned_volume_liters = 350000 * (1 + 0.15) * 1.0 = 402500.00
        """
        tenant = create_tenant()
        plot = create_plot(
            tenant["id"], crop_type="CORN", crop_stage="VEGETATIVE",
            area_hectares=10.0,
        )
        # add at least one ONLINE sensor for downstream activation
        create_sensor(plot["id"], sensor_type="SOIL_MOISTURE")
        # cover the plan window
        create_water_quota(
            plot["id"],
            period_start=DEFAULT_NOW_ISO,
            period_end=add_days(DEFAULT_NOW_ISO, 30),
            allocated_liters=10_000_000.0,
        )
        ws = DEFAULT_NOW_ISO
        we = add_days(ws, 1)
        res = api.create_irrigation_plan(
            plot["id"],
            create_plan_payload(
                window_start=ws, window_end=we, source="AUTO",
            ),
            water_admin_headers,
        )
        plan = validate_success(res, expected_status=201)
        # base 350000 * 1.15 * 1.0 = 402500.0 (rounded half-up to 2dp)
        assert plan["planned_volume_liters"] == pytest.approx(
            402500.00, abs=0.01
        ), (
            f"Expected 402500.00 (35000*10*1.15*1.0), got "
            f"{plan['planned_volume_liters']}"
        )
        assert plan["source"] == "AUTO"

    def test_manual_override_source_takes_body_volume_verbatim(
        self, api, water_admin_headers,
    ):
        """PRD §3.2: 'When source is MANUAL_OVERRIDE, the formula is
        skipped and planned_volume_liters is taken verbatim from the
        request body'.

        Claim: source=MANUAL_OVERRIDE + body planned_volume_liters
        bypasses the formula.
        """
        tenant, plot, quota, _ = setup_tenant_plot_quota(
            crop_type="CORN", crop_stage="VEGETATIVE",
            area_hectares=10.0, allocated_liters=10_000_000.0,
        )
        ws = quota["period_start"]
        we = add_days(ws, 1)
        res = api.create_irrigation_plan(
            plot["id"],
            create_plan_payload(
                window_start=ws, window_end=we,
                source="MANUAL_OVERRIDE",
                planned_volume_liters=42.0,
            ),
            water_admin_headers,
        )
        plan = validate_success(res, expected_status=201)
        assert plan["planned_volume_liters"] == pytest.approx(42.0, abs=0.01)
        assert plan["source"] == "MANUAL_OVERRIDE"


# ===========================================================================
# §3.2 — Activation preconditions
# ===========================================================================
class TestPlanActivation:
    def test_activate_requires_at_least_one_online_sensor(
        self, api, water_admin_headers,
    ):
        """PRD §3.2: 'the plot must carry at least one Sensor whose
        status is ONLINE'.
        PRD §3.2: 'Failure of the first two preconditions yields
        ERR_PRECONDITION_NOT_MET (422)'.

        Claim: plot with zero ONLINE sensors → ERR_PRECONDITION_NOT_MET
        on activate.
        """
        tenant, plot, quota, _ = setup_tenant_plot_quota(
            allocated_liters=100000.0, add_online_sensor=False,
        )
        ws = quota["period_start"]
        we = add_days(ws, 1)
        plan = create_plan(
            plot["id"], window_start=ws, window_end=we,
            source="MANUAL_OVERRIDE", planned_volume_liters=500.0,
        )
        res = api.activate_plan(plot["id"], plan["id"], water_admin_headers)
        validate_error(res, "ERR_PRECONDITION_NOT_MET")

    def test_activate_succeeds_with_online_sensor_and_quota(
        self, api, water_admin_headers,
    ):
        """PRD §3.2: 'Activation by an Operator or WaterAdmin advances
        the plan from DRAFT to ACTIVE'.

        Claim: with all preconditions satisfied, plan flips DRAFT →
        ACTIVE.
        """
        tenant, plot, quota, _ = setup_tenant_plot_quota(
            allocated_liters=100000.0,
        )
        plan = create_plan(
            plot["id"],
            window_start=quota["period_start"],
            window_end=add_days(quota["period_start"], 1),
            source="MANUAL_OVERRIDE", planned_volume_liters=500.0,
        )
        res = api.activate_plan(plot["id"], plan["id"], water_admin_headers)
        data = validate_success(res, expected_status=200)
        assert data["status"] == "ACTIVE"

    def test_activate_overlap_rejected_409(
        self, api, water_admin_headers,
    ):
        """PRD §3.2: 'the plan's [window_start, window_end) must not
        overlap any other IrrigationPlan on the same plot whose status
        is in the set of ACTIVE or SUSPENDED'.
        PRD §3.2: 'failure of the overlap check yields
        ERR_PLAN_WINDOW_OVERLAP (409)'.

        Claim: a plan whose window overlaps an ACTIVE plan on the same
        plot → ERR_PLAN_WINDOW_OVERLAP on activation.
        """
        ctx = setup_overlap_plans(
            plan1_offset_hours_from_period_start=24,
            plan1_duration_hours=24,
        )
        # plan1 covers [period_start+24h, period_start+48h).
        # Create a plan2 [period_start+36h, period_start+60h) — overlap.
        period_start = ctx["quota"]["period_start"]
        plan2 = create_plan(
            ctx["plot"]["id"],
            window_start=add_hours(period_start, 36),
            window_end=add_hours(period_start, 60),
            source="MANUAL_OVERRIDE", planned_volume_liters=200.0,
        )
        res = api.activate_plan(
            ctx["plot"]["id"], plan2["id"], water_admin_headers,
        )
        validate_error(res, "ERR_PLAN_WINDOW_OVERLAP")


# ===========================================================================
# §3.2 — Suspension state transitions
# ===========================================================================
class TestPlanSuspendResume:
    def test_explicit_suspend_active_to_suspended(
        self, api, water_admin_headers,
    ):
        """PRD §3.2: 'A plan in ACTIVE may be suspended back to
        SUSPENDED either explicitly by an Operator or WaterAdmin'.

        Claim: POST /suspend on ACTIVE → SUSPENDED.
        """
        ctx = setup_full_active_scenario(plan_volume_liters=500.0)
        plan = ctx["plan"]
        res = api.suspend_plan(
            ctx["plot"]["id"], plan["id"], water_admin_headers,
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "SUSPENDED"

    def test_resume_suspended_to_active(
        self, api, water_admin_headers,
    ):
        """PRD §3.2: 'Resumption from SUSPENDED back to ACTIVE requires
        that the covering WaterQuota is in usage_state UNDER or
        WARNING'.

        Claim: with quota UNDER, resume flips SUSPENDED → ACTIVE.
        """
        ctx = setup_full_active_scenario(plan_volume_liters=500.0)
        suspend_plan(ctx["plot"]["id"], ctx["plan"]["id"])
        res = api.resume_plan(
            ctx["plot"]["id"], ctx["plan"]["id"], water_admin_headers,
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "ACTIVE"

    def test_resume_non_suspended_returns_invalid_state(
        self, api, water_admin_headers,
    ):
        """PRD §3.2: 'attempting to resume a plan that is not in
        SUSPENDED yields ERR_INVALID_STATE (409).'

        Claim: resume on ACTIVE plan → ERR_INVALID_STATE.
        """
        ctx = setup_full_active_scenario(plan_volume_liters=500.0)
        res = api.resume_plan(
            ctx["plot"]["id"], ctx["plan"]["id"], water_admin_headers,
        )
        validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# §3.2 — Override creates a revision (cycle ACTIVE → DRAFT)
# ===========================================================================
class TestPlanOverrideCycle:
    def test_override_flips_original_to_draft_and_creates_revision(
        self, api, water_admin_headers,
    ):
        """PRD §3.2: 'Override is a deliberate cycle from ACTIVE back
        to DRAFT: the original plan moves from ACTIVE to DRAFT, its
        quota reservation is released, a brand-new IrrigationPlan
        record is created with parent_plan_id set to the original
        plan's id, plan_version set to one greater than the original's
        plan_version, source set to MANUAL_OVERRIDE, and status set
        to DRAFT.'

        Claim: POST /override returns a NEW plan with parent_plan_id ==
        original.id, plan_version == original.plan_version + 1,
        source == MANUAL_OVERRIDE, status == DRAFT.
        """
        ctx = setup_full_active_scenario(plan_volume_liters=1000.0)
        original = ctx["plan"]
        res = api.override_plan(
            ctx["plot"]["id"], original["id"],
            {"planned_volume_liters": 600.0},
            water_admin_headers,
        )
        new_plan = validate_success(res, expected_status=201)
        assert new_plan["parent_plan_id"] == original["id"]
        assert new_plan["plan_version"] == original["plan_version"] + 1
        assert new_plan["source"] == "MANUAL_OVERRIDE"
        assert new_plan["status"] == "DRAFT"
        assert new_plan["planned_volume_liters"] == pytest.approx(
            600.0, abs=0.01
        )

    def test_override_appends_audit_log_plan_overridden(
        self, api, water_admin_headers,
    ):
        """PRD §3.2: 'an AuditLog entry with action_type of
        PLAN_OVERRIDDEN is appended.'

        Claim: an AuditLog with action_type==PLAN_OVERRIDDEN exists
        for the original plan after override.
        """
        ctx = setup_full_active_scenario(plan_volume_liters=1000.0)
        original = ctx["plan"]
        api.override_plan(
            ctx["plot"]["id"], original["id"],
            {"planned_volume_liters": 600.0},
            water_admin_headers,
        )
        entries = list_audit_logs(
            params={"action_type": "PLAN_OVERRIDDEN", "limit": 100}
        )
        matched = find_audit_entries(
            entries, action_type="PLAN_OVERRIDDEN",
            subject_id=original["id"],
        )
        assert len(matched) >= 1, (
            "Expected PLAN_OVERRIDDEN audit entry referencing original "
            "plan id"
        )


# ===========================================================================
# §3.2 — Cancel a DRAFT plan
# ===========================================================================
class TestPlanCancel:
    def test_delete_draft_plan_returns_204(
        self, api, water_admin_headers,
    ):
        """PRD §3.2: 'cancelling a DRAFT plan with the delete
        operation moves it to CANCELLED.'
        PRD §4: 'the cancellation of a DRAFT IrrigationPlan returns
        HTTP 204.'

        Claim: DELETE on a DRAFT plan returns 204.
        """
        tenant, plot, quota, _ = setup_tenant_plot_quota(
            allocated_liters=100000.0,
        )
        plan = create_plan(
            plot["id"],
            window_start=quota["period_start"],
            window_end=add_days(quota["period_start"], 1),
            source="MANUAL_OVERRIDE", planned_volume_liters=500.0,
        )
        res = api.cancel_plan(plot["id"], plan["id"], water_admin_headers)
        # 204 is the expected status; body may be empty.
        assert res.status_code == 204, (
            f"PRD §4: 'cancellation of a DRAFT IrrigationPlan returns "
            f"HTTP 204.' Got {res.status_code}"
        )

    def test_delete_active_plan_returns_invalid_state(
        self, api, water_admin_headers,
    ):
        """PRD §1.4 (validation §5): IrrigationPlan operations require
        plan in expected status.
        PRD §3.2: cancel via delete is for DRAFT only ('cancelling a
        DRAFT plan with the delete operation moves it to CANCELLED').

        Claim: DELETE on an ACTIVE plan → ERR_INVALID_STATE.
        """
        ctx = setup_full_active_scenario(plan_volume_liters=500.0)
        res = api.cancel_plan(
            ctx["plot"]["id"], ctx["plan"]["id"], water_admin_headers,
        )
        validate_error(res, "ERR_INVALID_STATE")
