"""Validation-precedence conflicts, cross-entity state gates, and temporal
overlap geometry (asset open-ray downtime vs technician closed-interval
windows).

Covers Difficulty queue rules priority_pair_validation_conflict,
cross_entity_state_dependency, and resource_temporal_overlap, plus the Corner
touching-window instance.
"""
from test_helpers import (
    fixtures as fx,
    validate_success,
    validate_error,
    validate_paginated,
    TEST_USERS,
    make_technician_headers,
)

PLANNER = TEST_USERS["planner_headers"]
MANAGER = TEST_USERS["manager_headers"]
WARRANTY = TEST_USERS["warranty_admin_headers"]


# =========================================================================
# Rule 5 — priority_pair_validation_conflict
# =========================================================================

class TestValidationPrecedence:
    def test_assign_state_check_beats_skill_gate(self, api):
        """PRD §3.10: "State validity comes next: an action whose target is not in
        a state from which the transition is defined yields ERR_INVALID_STATE.
        ... Only after all of these structural checks pass does the system
        evaluate the domain-specific business rules — skill gating, ...".
        PRD §3.5: "Assigning an UNASSIGNED order to a technician requires the
        caller to supply that technician_id."

        Design: Difficulty/priority_pair_validation_conflict/assign_state_beats_skill_state_vs_business_safety
        """
        site, asset, tech = fx.setup_site_asset_tech(
            asset_overrides={"criticality": "HIGH", "acquisition_cost_cents": 400_000},
            tech_overrides={"skill_level": "JUNIOR", "weekly_capacity_hours": 40},
        )
        # DRAFT OVERHAUL work order — never released, so assign is not defined.
        wo = fx.create_corrective_work_order(
            asset["id"], severity="OVERHAUL", estimated_labor_hours=8
        )
        validate_error(
            api.assign_work_order(wo["id"], {"technician_id": tech["id"]}, PLANNER),
            "ERR_INVALID_STATE",
        )
        after = validate_success(api.get_work_order(wo["id"], PLANNER))
        assert after["execution_status"] == "DRAFT"

    def test_assign_state_check_blocks_backlog_side_effect(self, api):
        """PRD §3.5: "A successful assign advances execution_status from
        UNASSIGNED to ASSIGNED, sets assigned_technician_id, and increases the
        technician's backlog_hours by the order's estimated_labor_hours."
        PRD §3.10: "an action whose target is not in a state from which the
        transition is defined yields ERR_INVALID_STATE."

        Design: Difficulty/priority_pair_validation_conflict/assign_state_beats_skill_state_vs_business_safety
        """
        site, asset, tech = fx.setup_site_asset_tech(
            asset_overrides={"criticality": "HIGH", "acquisition_cost_cents": 400_000},
            tech_overrides={"skill_level": "JUNIOR", "weekly_capacity_hours": 40},
        )
        wo = fx.create_corrective_work_order(
            asset["id"], severity="OVERHAUL", estimated_labor_hours=8
        )
        validate_error(
            api.assign_work_order(wo["id"], {"technician_id": tech["id"]}, PLANNER),
            "ERR_INVALID_STATE",
        )
        tech_after = validate_success(api.get_technician(tech["id"], MANAGER))
        assert tech_after["backlog_hours"] == 0, (
            "the rejected assign ran no backlog side-effect"
        )

    def test_close_state_check_beats_downtime_open_guard(self, api):
        """PRD §3.10: "State validity comes next: an action whose target is not in
        a state from which the transition is defined yields ERR_INVALID_STATE.
        ... Only after all of these structural checks pass does the system
        evaluate the domain-specific business rules".
        PRD §3.6: "Closing an order is permitted only while it is IN_PROGRESS."

        Design: Difficulty/priority_pair_validation_conflict/close_state_beats_downtime_open_state_vs_business_constraint
        """
        fx.set_clock("2026-05-10T00:00:00Z")
        site, asset, tech = fx.setup_site_asset_tech(
            asset_overrides={"criticality": "CRITICAL", "acquisition_cost_cents": 700_000},
            tech_overrides={"skill_level": "SENIOR"},
        )
        # ASSIGNED (not started) — close is not defined from ASSIGNED.
        wo = fx.setup_assigned_work_order(
            asset["id"], tech["id"], severity="MAJOR", estimated_labor_hours=4
        )
        fx.open_downtime(
            asset["id"], "MECHANICAL_FAILURE", "2026-05-10T01:00:00Z", work_order_id=wo["id"]
        )
        validate_error(
            api.close_work_order(wo["id"], {"actual_cost_cents": 5000},
                                 make_technician_headers(tech["id"])),
            "ERR_INVALID_STATE",
        )
        after = validate_success(api.get_work_order(wo["id"], PLANNER))
        assert after["execution_status"] == "ASSIGNED"

    def test_close_state_check_leaves_downtime_open(self, api):
        """PRD §3.6: "A successful close advances execution_status to CLOSED, sets
        closed_at to the current instant".
        PRD §3.10: "an action whose target is not in a state from which the
        transition is defined yields ERR_INVALID_STATE."

        Design: Difficulty/priority_pair_validation_conflict/close_state_beats_downtime_open_state_vs_business_constraint
        """
        fx.set_clock("2026-05-10T00:00:00Z")
        site, asset, tech = fx.setup_site_asset_tech(
            asset_overrides={"criticality": "CRITICAL", "acquisition_cost_cents": 700_000},
            tech_overrides={"skill_level": "SENIOR"},
        )
        wo = fx.setup_assigned_work_order(
            asset["id"], tech["id"], severity="MAJOR", estimated_labor_hours=4
        )
        dt = fx.open_downtime(
            asset["id"], "MECHANICAL_FAILURE", "2026-05-10T01:00:00Z", work_order_id=wo["id"]
        )
        validate_error(
            api.close_work_order(wo["id"], {"actual_cost_cents": 5000},
                                 make_technician_headers(tech["id"])),
            "ERR_INVALID_STATE",
        )
        dt_after = validate_success(api.get_downtime_event(dt["id"], MANAGER))
        assert dt_after["status"] == "OPEN", "no close cascade ran; downtime untouched"
        wo_after = validate_success(api.get_work_order(wo["id"], PLANNER))
        assert wo_after["closed_at"] is None


# =========================================================================
# Rule 7 — cross_entity_state_dependency
# =========================================================================

class TestCrossEntityStateGates:
    def test_warranty_approve_requires_work_order_closed(self, api):
        """PRD §3.9: "Approval requires the claim to be SUBMITTED, the referenced
        work order to be CLOSED, the work order's closed_at to fall strictly
        before the asset's warranty_expires_at (otherwise ERR_WARRANTY_EXPIRED),
        and the asset not to be RETIRED."

        Design: Difficulty/cross_entity_state_dependency/warranty_approve_requires_work_order_closed
        """
        fx.set_clock("2026-02-01T00:00:00Z")
        site, asset, tech = fx.setup_site_asset_tech(
            asset_overrides={"criticality": "HIGH", "acquisition_cost_cents": 600_000,
                             "warranty_expires_at": "2027-01-01T00:00:00Z"},
            tech_overrides={"skill_level": "SENIOR"},
        )
        # Work order is IN_PROGRESS, not yet closed.
        wo = fx.setup_in_progress_work_order(
            asset["id"], tech["id"], severity="MAJOR", estimated_labor_hours=4
        )
        claim = fx.submit_claim(asset["id"], wo["id"], "REPAIR")
        validate_error(
            api.approve_claim(claim["id"], {"decision_reason": "early"}, WARRANTY),
            "ERR_INVALID_STATE",
        )
        after = validate_success(api.get_warranty_claim(claim["id"], WARRANTY))
        assert after["status"] == "SUBMITTED"

    def test_warranty_approve_on_open_wo_does_not_link_claim(self, api):
        """PRD §3.9: "Approval ... links the work order by setting its
        warranty_claim_id to this claim".
        PRD §3.9: "Approval requires the claim to be SUBMITTED, the referenced
        work order to be CLOSED".

        Design: Difficulty/cross_entity_state_dependency/warranty_approve_requires_work_order_closed
        """
        fx.set_clock("2026-02-01T00:00:00Z")
        site, asset, tech = fx.setup_site_asset_tech(
            asset_overrides={"criticality": "HIGH", "acquisition_cost_cents": 600_000,
                             "warranty_expires_at": "2027-01-01T00:00:00Z"},
            tech_overrides={"skill_level": "SENIOR"},
        )
        wo = fx.setup_in_progress_work_order(
            asset["id"], tech["id"], severity="MAJOR", estimated_labor_hours=4
        )
        claim = fx.submit_claim(asset["id"], wo["id"], "REPAIR")
        validate_error(
            api.approve_claim(claim["id"], {"decision_reason": "early"}, WARRANTY),
            "ERR_INVALID_STATE",
        )
        wo_after = validate_success(api.get_work_order(wo["id"], PLANNER))
        assert wo_after["warranty_claim_id"] is None, "no link created by the rejected approve"

    def test_retire_blocked_by_open_downtime(self, api):
        """PRD §3.2: "Retirement is permitted only when the asset is OPERATIONAL —
        an asset that is DOWN, or that has any work order in UNASSIGNED,
        ASSIGNED, IN_PROGRESS, or ON_HOLD, is considered busy and the attempt is
        rejected with ERR_ASSET_BUSY."

        Design: Difficulty/cross_entity_state_dependency/asset_retire_blocked_by_open_downtime
        """
        fx.set_clock("2026-05-20T00:00:00Z")
        site, asset = fx.setup_site_and_asset(
            asset_overrides={"criticality": "MEDIUM", "acquisition_cost_cents": 800_000}
        )
        fx.open_downtime(asset["id"], "ELECTRICAL_FAILURE", "2026-05-20T01:00:00Z")
        current = validate_success(api.get_asset(asset["id"], MANAGER))
        validate_error(
            api.retire_asset(asset["id"], {"expected_asset_version": current["version"]}, MANAGER),
            "ERR_ASSET_BUSY",
        )
        after = validate_success(api.get_asset(asset["id"], MANAGER))
        assert after["status"] == "DOWN", "asset remains DOWN, not RETIRED"

    def test_retire_blocked_does_not_deactivate_schedules(self, api):
        """PRD §3.2: "A successful retire moves the asset to the terminal RETIRED
        status, increments its version, and cascades by setting active to false
        on every PM schedule of that asset".
        PRD §3.2: "an asset that is DOWN ... is considered busy and the attempt
        is rejected with ERR_ASSET_BUSY."

        Design: Difficulty/cross_entity_state_dependency/asset_retire_blocked_by_open_downtime
        """
        fx.set_clock("2026-05-20T00:00:00Z")
        site, asset = fx.setup_site_and_asset(
            asset_overrides={"criticality": "MEDIUM", "acquisition_cost_cents": 800_000}
        )
        sched = fx.create_pm_schedule(
            asset["id"], "CALENDAR", calendar_interval_days=30,
            estimated_labor_hours=2, severity="ROUTINE",
        )
        fx.open_downtime(asset["id"], "ELECTRICAL_FAILURE", "2026-05-20T01:00:00Z")
        current = validate_success(api.get_asset(asset["id"], MANAGER))
        validate_error(
            api.retire_asset(asset["id"], {"expected_asset_version": current["version"]}, MANAGER),
            "ERR_ASSET_BUSY",
        )
        sched_after = validate_success(api.get_pm_schedule(sched["id"], PLANNER))
        assert sched_after["active"] is True, "rejected retire ran no deactivation cascade"


# =========================================================================
# Rule 8 — resource_temporal_overlap
# =========================================================================

class TestTemporalOverlap:
    def test_asset_second_open_downtime_rejected(self, api):
        """PRD §3.8: "Because an asset cannot have two concurrently open
        downtimes, logging a new open event whose interval would overlap an
        existing open downtime on the same asset is rejected with
        ERR_DOWNTIME_OVERLAP."

        Design: Difficulty/resource_temporal_overlap/asset_downtime_open_ray_overlap
        """
        fx.set_clock("2026-05-25T00:00:00Z")
        site, asset = fx.setup_site_and_asset(
            asset_overrides={"criticality": "HIGH", "acquisition_cost_cents": 350_000}
        )
        fx.open_downtime(asset["id"], "MECHANICAL_FAILURE", "2026-05-25T01:00:00Z")
        validate_error(
            api.create_downtime_event(
                asset["id"],
                {"reason_code": "ELECTRICAL_FAILURE", "started_at": "2026-05-25T05:00:00Z"},
                TEST_USERS["technician_headers"],
            ),
            "ERR_DOWNTIME_OVERLAP",
        )
        data, meta = validate_paginated(api.list_asset_downtime_events(asset["id"], MANAGER))
        assert meta["total_count"] == 1, "the overlapping second downtime was not created"

    def test_asset_second_open_downtime_started_earlier_rejected(self, api):
        """PRD §3.8: "Because an asset cannot have two concurrently open
        downtimes, logging a new open event whose interval would overlap an
        existing open downtime on the same asset is rejected with
        ERR_DOWNTIME_OVERLAP."

        Design: Difficulty/resource_temporal_overlap/asset_downtime_open_ray_overlap
        """
        fx.set_clock("2026-05-25T00:00:00Z")
        site, asset = fx.setup_site_and_asset(
            asset_overrides={"criticality": "HIGH", "acquisition_cost_cents": 350_000}
        )
        fx.open_downtime(asset["id"], "MECHANICAL_FAILURE", "2026-05-25T05:00:00Z")
        # A second OPEN downtime starting earlier still overlaps the open-ended ray.
        validate_error(
            api.create_downtime_event(
                asset["id"],
                {"reason_code": "ELECTRICAL_FAILURE", "started_at": "2026-05-25T01:00:00Z"},
                TEST_USERS["technician_headers"],
            ),
            "ERR_DOWNTIME_OVERLAP",
        )

    def test_technician_window_strict_overlap_rejected(self, api):
        """PRD §3.5: "Booking is rejected with ERR_TECH_DOUBLE_BOOKED when the new
        window overlaps any window already booked on another non-terminal work
        order (one whose execution status is not CLOSED or CANCELLED) for the
        same assigned technician."

        Design: Difficulty/resource_temporal_overlap/technician_window_closed_interval_overlap
        """
        fx.set_clock("2026-06-02T00:00:00Z")
        site = fx.create_site()
        tech = fx.create_technician(skill_level="SENIOR")
        asset1 = fx.create_asset(site["id"], name="Asset S1", criticality="MEDIUM",
                                 acquisition_cost_cents=100_000)
        asset2 = fx.create_asset(site["id"], name="Asset S2", criticality="MEDIUM",
                                 acquisition_cost_cents=100_000)
        wo1 = fx.setup_assigned_work_order(
            asset1["id"], tech["id"], severity="MAJOR", estimated_labor_hours=2
        )
        validate_success(
            api.schedule_window(
                wo1["id"],
                {"scheduled_start": "2026-06-02T09:00:00Z",
                 "scheduled_end": "2026-06-02T11:00:00Z"},
                PLANNER,
            )
        )
        wo2 = fx.setup_assigned_work_order(
            asset2["id"], tech["id"], severity="MAJOR", estimated_labor_hours=2
        )
        validate_error(
            api.schedule_window(
                wo2["id"],
                {"scheduled_start": "2026-06-02T10:00:00Z",
                 "scheduled_end": "2026-06-02T12:00:00Z"},
                PLANNER,
            ),
            "ERR_TECH_DOUBLE_BOOKED",
        )
        after = validate_success(api.get_work_order(wo2["id"], PLANNER))
        assert after["scheduled_start"] is None, "window not booked"

    def test_technician_window_left_overlap_rejected(self, api):
        """PRD §3.5: "any positive-length overlap does. Booking is rejected with
        ERR_TECH_DOUBLE_BOOKED when the new window overlaps any window already
        booked on another non-terminal work order ... for the same assigned
        technician."

        Design: Difficulty/resource_temporal_overlap/technician_window_closed_interval_overlap
        """
        fx.set_clock("2026-06-02T00:00:00Z")
        site = fx.create_site()
        tech = fx.create_technician(skill_level="SENIOR")
        asset1 = fx.create_asset(site["id"], name="Asset L1", acquisition_cost_cents=100)
        asset2 = fx.create_asset(site["id"], name="Asset L2", acquisition_cost_cents=100)
        wo1 = fx.setup_assigned_work_order(
            asset1["id"], tech["id"], severity="MAJOR", estimated_labor_hours=2
        )
        validate_success(
            api.schedule_window(
                wo1["id"],
                {"scheduled_start": "2026-06-02T09:00:00Z",
                 "scheduled_end": "2026-06-02T11:00:00Z"},
                PLANNER,
            )
        )
        wo2 = fx.setup_assigned_work_order(
            asset2["id"], tech["id"], severity="MAJOR", estimated_labor_hours=2
        )
        # New window 08:00-09:30 overlaps the existing 09:00-11:00 from the left.
        validate_error(
            api.schedule_window(
                wo2["id"],
                {"scheduled_start": "2026-06-02T08:00:00Z",
                 "scheduled_end": "2026-06-02T09:30:00Z"},
                PLANNER,
            ),
            "ERR_TECH_DOUBLE_BOOKED",
        )


class TestTouchingWindowAllowed:
    def test_touching_endpoints_window_accepted(self, api):
        """PRD §3.5: "The window is treated as the half-open interval from
        scheduled_start up to but not including scheduled_end: two windows that
        merely touch at an endpoint do not overlap, but any positive-length
        overlap does."

        Design: Corner/cross_cutting_complexity_layers/scheduled_window_touching_endpoints_allowed
        """
        fx.set_clock("2026-06-02T00:00:00Z")
        site = fx.create_site()
        tech = fx.create_technician(skill_level="SENIOR")
        asset1 = fx.create_asset(site["id"], name="Asset TW1", acquisition_cost_cents=100)
        asset2 = fx.create_asset(site["id"], name="Asset TW2", acquisition_cost_cents=100)
        wo1 = fx.setup_assigned_work_order(
            asset1["id"], tech["id"], severity="MAJOR", estimated_labor_hours=2
        )
        validate_success(
            api.schedule_window(
                wo1["id"],
                {"scheduled_start": "2026-06-02T09:00:00Z",
                 "scheduled_end": "2026-06-02T11:00:00Z"},
                PLANNER,
            )
        )
        wo2 = fx.setup_assigned_work_order(
            asset2["id"], tech["id"], severity="MAJOR", estimated_labor_hours=2
        )
        booked = validate_success(
            api.schedule_window(
                wo2["id"],
                {"scheduled_start": "2026-06-02T11:00:00Z",
                 "scheduled_end": "2026-06-02T13:00:00Z"},
                PLANNER,
            )
        )
        assert booked["scheduled_start"].startswith("2026-06-02T11:00:00"), (
            "a window starting exactly when the first ends does not overlap"
        )
