"""Rate-decision yield computation, the publish/reject branch, and superseding.

Covers the rate_yield calculation (yield rule selection, last-room-value premium,
floor/ceiling clamp, rounding) and the RateDecision state machine's divergent
branches, all driven through the publish/reject endpoints.
"""
from test_helpers import (
    validate_success,
    validate_error,
    TEST_USERS,
    set_clock,
    setup_published_master_bar,
    create_property,
    create_room_type,
    create_rate_plan,
    create_inventory_day,
    create_yield_rule,
    create_rate_decision,
    publish_decision,
    ApiErrorId,
)

RM = TEST_USERS["revenue_manager_headers"]


class TestLastRoomPremiumDualVariant:
    def test_publish_without_scarcity_applies_no_premium(self, api):
        """PRD §3.4: "the last-room-value premium is considered: if the night's
        current `rooms_available` (per §2.7) is at or below 5 rooms, the running
        rate is multiplied by 1.20 (a 20% premium) and `last_room_premium_applied`
        is set true; otherwise no premium is applied."

        Design: Difficulty/dual_variant_calc/rate_yield_with_lrv_premium_vs_without
        """
        set_clock("2026-06-01T00:00:00Z")
        prop = create_property(name="Premier", total_rooms=110)
        rt = create_room_type(prop["id"], code="STD", name="Standard", physical_rooms=110)
        plan = create_rate_plan(
            rt["id"], rate_class="BAR", is_master_bar=True,
            base_rate=200, floor_rate=100, ceiling_rate=400,
        )
        # rooms_available = floor(100*1.0) - 50 = 50 -> no premium
        create_inventory_day(rt["id"], "2026-06-02T00:00:00Z", physical_capacity=100, transient_sold_rooms=50)
        dec = create_rate_decision(plan["id"], "2026-06-02T00:00:00Z", requested_rate=200)
        data = validate_success(api.publish_rate_decision(dec["id"], {"expected_rate_plan_version": plan["version"]}, RM))
        assert data["yielded_rate"] == 200.00, f"expected 200.00 got {data['yielded_rate']}"
        assert data["last_room_premium_applied"] is False

    def test_publish_with_scarcity_applies_premium(self, api):
        """PRD §3.4: "the last-room-value premium is considered: if the night's
        current `rooms_available` (per §2.7) is at or below 5 rooms, the running
        rate is multiplied by 1.20 (a 20% premium) and `last_room_premium_applied`
        is set true; otherwise no premium is applied."

        Design: Difficulty/dual_variant_calc/rate_yield_with_lrv_premium_vs_without
        """
        set_clock("2026-06-01T00:00:00Z")
        prop = create_property(name="Premier", total_rooms=110)
        rt = create_room_type(prop["id"], code="STD", name="Standard", physical_rooms=110)
        plan = create_rate_plan(
            rt["id"], rate_class="BAR", is_master_bar=True,
            base_rate=200, floor_rate=100, ceiling_rate=400,
        )
        # rooms_available = floor(10*1.0) - 6 = 4 (<= 5) -> premium fires: 150*1.20 = 180
        create_inventory_day(rt["id"], "2026-06-03T00:00:00Z", physical_capacity=10, transient_sold_rooms=6)
        dec = create_rate_decision(plan["id"], "2026-06-03T00:00:00Z", requested_rate=150)
        data = validate_success(api.publish_rate_decision(dec["id"], {"expected_rate_plan_version": plan["version"]}, RM))
        assert data["yielded_rate"] == 180.00, f"expected 180.00 got {data['yielded_rate']}"
        assert data["last_room_premium_applied"] is True


class TestNonlinearYieldFormula:
    def test_rule_then_premium_then_ceiling_clamp(self, api):
        """PRD §3.4: "If a rule is chosen, the running rate becomes the
        `requested_rate` multiplied by the quantity one plus that rule's
        `adjustment_pct`; if no rule is eligible, the running rate stays equal to
        the `requested_rate`."
        PRD §3.4: "the running rate is clamped into the plan's band — taken as no
        less than `floor_rate` and no more than `ceiling_rate`, with the floor
        applied first and the ceiling applied as the upper bound — and only then
        rounded half-up to 2 decimal places to yield the final `yielded_rate`."

        Design: Difficulty/combinatorial_formula/rate_yield_nonlinear_rule_then_premium_then_clamp
        """
        set_clock("2026-06-01T00:00:00Z")
        prop = create_property(name="Apex", total_rooms=20)
        rt = create_room_type(prop["id"], code="STE", name="Suite", physical_rooms=20)
        create_yield_rule(prop["id"], 0.90, 0.50, 1, name="PeakSurge", enabled=True)
        plan = create_rate_plan(
            rt["id"], rate_class="BAR", is_master_bar=True,
            base_rate=300, floor_rate=100, ceiling_rate=400,
        )
        # sold 18 -> forecast round(27)=27 capped at ceiling floor(20)=20 -> occ 1.0 (rule eligible)
        # rooms_available = 20 - 18 = 2 (premium). 300*1.5=450, *1.20=540, clamp to ceiling 400.
        create_inventory_day(rt["id"], "2026-06-04T00:00:00Z", physical_capacity=20, transient_sold_rooms=18)
        dec = create_rate_decision(plan["id"], "2026-06-04T00:00:00Z", requested_rate=300)
        data = validate_success(api.publish_rate_decision(dec["id"], {"expected_rate_plan_version": plan["version"]}, RM))
        assert data["yielded_rate"] == 400.00, f"expected ceiling clamp 400.00 got {data['yielded_rate']}"
        assert data["last_room_premium_applied"] is True

    def test_nonlinear_formula_records_applied_rule_and_published_rate(self, api):
        """PRD §3.4: "The decision records the single `applied_yield_rule_id` that
        fired (or null if none), and its `last_room_premium_applied` flag."
        PRD §3.4: "The decision's `yielded_rate` becomes the plan's
        `published_rate`, and the plan's `version` increments by 1."

        Design: Difficulty/combinatorial_formula/rate_yield_nonlinear_rule_then_premium_then_clamp
        """
        set_clock("2026-06-01T00:00:00Z")
        prop = create_property(name="Apex2", total_rooms=20)
        rt = create_room_type(prop["id"], code="STE", name="Suite", physical_rooms=20)
        create_yield_rule(prop["id"], 0.90, 0.50, 1, name="PeakSurge", enabled=True)
        plan = create_rate_plan(
            rt["id"], rate_class="BAR", is_master_bar=True,
            base_rate=300, floor_rate=100, ceiling_rate=400,
        )
        create_inventory_day(rt["id"], "2026-06-04T00:00:00Z", physical_capacity=20, transient_sold_rooms=18)
        dec = create_rate_decision(plan["id"], "2026-06-04T00:00:00Z", requested_rate=300)
        data = validate_success(api.publish_rate_decision(dec["id"], {"expected_rate_plan_version": plan["version"]}, RM))
        # The eligible rule fired, so applied_yield_rule_id must be recorded (non-null).
        assert data["applied_yield_rule_id"] is not None
        plan_after = validate_success(api.get_rate_plan(plan["id"], RM))
        assert plan_after["published_rate"] == 400.00, (
            f"published_rate must equal the clamped yielded_rate, got {plan_after['published_rate']}"
        )


class TestYieldThresholdBoundary:
    def test_rule_fires_at_exact_threshold(self, api):
        """PRD §3.4: "among the property's enabled rules whose
        `occupancy_threshold_pct` is less than or equal to that basis occupancy,
        it chooses the one with the highest `occupancy_threshold_pct`; ties are
        broken by the lower `priority` value, and any remaining tie by the earlier
        `created_at`."

        Design: Difficulty/boundary_precision_check/yield_rule_fires_at_exact_threshold_inclusive
        """
        set_clock("2026-06-01T00:00:00Z")
        prop = create_property(name="BoundaryA", total_rooms=100)
        rt = create_room_type(prop["id"], code="STD", name="Standard", physical_rooms=100)
        create_yield_rule(prop["id"], 0.75, 0.10, 1, name="AtThreshold", enabled=True)
        plan = create_rate_plan(
            rt["id"], rate_class="BAR", is_master_bar=True,
            base_rate=200, floor_rate=100, ceiling_rate=400,
        )
        # sold 50 -> forecast round(75)=75 capped 100 -> occ 0.75 (== threshold, inclusive >=)
        create_inventory_day(rt["id"], "2026-06-12T00:00:00Z", physical_capacity=100, transient_sold_rooms=50)
        dec = create_rate_decision(plan["id"], "2026-06-12T00:00:00Z", requested_rate=200)
        data = validate_success(api.publish_rate_decision(dec["id"], {"expected_rate_plan_version": plan["version"]}, RM))
        assert data["yielded_rate"] == 220.00, f"expected 220.00 got {data['yielded_rate']}"
        assert data["applied_yield_rule_id"] is not None

    def test_rule_at_exact_threshold_without_premium(self, api):
        """PRD §3.4: "the last-room-value premium is considered: if the night's
        current `rooms_available` (per §2.7) is at or below 5 rooms, the running
        rate is multiplied by 1.20 (a 20% premium) and `last_room_premium_applied`
        is set true; otherwise no premium is applied."

        Design: Difficulty/boundary_precision_check/yield_rule_fires_at_exact_threshold_inclusive
        """
        set_clock("2026-06-01T00:00:00Z")
        prop = create_property(name="BoundaryA2", total_rooms=100)
        rt = create_room_type(prop["id"], code="STD", name="Standard", physical_rooms=100)
        create_yield_rule(prop["id"], 0.75, 0.10, 1, name="AtThreshold", enabled=True)
        plan = create_rate_plan(
            rt["id"], rate_class="BAR", is_master_bar=True,
            base_rate=200, floor_rate=100, ceiling_rate=400,
        )
        # rooms_available = floor(100) - 50 = 50 (> 5) -> no premium, so 200*1.10 stays 220.
        create_inventory_day(rt["id"], "2026-06-12T00:00:00Z", physical_capacity=100, transient_sold_rooms=50)
        dec = create_rate_decision(plan["id"], "2026-06-12T00:00:00Z", requested_rate=200)
        data = validate_success(api.publish_rate_decision(dec["id"], {"expected_rate_plan_version": plan["version"]}, RM))
        assert data["last_room_premium_applied"] is False
        assert data["yielded_rate"] == 220.00, f"expected 220.00 got {data['yielded_rate']}"

    def test_rule_does_not_fire_below_threshold(self, api):
        """PRD §3.4: "If a rule is chosen, the running rate becomes the
        `requested_rate` multiplied by the quantity one plus that rule's
        `adjustment_pct`; if no rule is eligible, the running rate stays equal to
        the `requested_rate`."

        Design: Corner/cross_cutting_complexity_layers/rate_threshold_no_rule_eligible_below_threshold
        """
        set_clock("2026-06-01T00:00:00Z")
        prop = create_property(name="BelowThr", total_rooms=100)
        rt = create_room_type(prop["id"], code="STD", name="Standard", physical_rooms=100)
        create_yield_rule(prop["id"], 0.75, 0.10, 1, name="Thr75", enabled=True)
        plan = create_rate_plan(
            rt["id"], rate_class="BAR", is_master_bar=True,
            base_rate=200, floor_rate=100, ceiling_rate=400,
        )
        # sold 49 -> forecast round(73.5)=74 -> occ 0.74 < 0.75 -> no rule
        create_inventory_day(rt["id"], "2026-06-06T00:00:00Z", physical_capacity=100, transient_sold_rooms=49)
        dec = create_rate_decision(plan["id"], "2026-06-06T00:00:00Z", requested_rate=200)
        data = validate_success(api.publish_rate_decision(dec["id"], {"expected_rate_plan_version": plan["version"]}, RM))
        assert data["yielded_rate"] == 200.00, f"expected 200.00 got {data['yielded_rate']}"
        assert data["applied_yield_rule_id"] is None

    def test_tie_break_chooses_highest_threshold_rule(self, api):
        """PRD §3.4: "among the property's enabled rules whose
        `occupancy_threshold_pct` is less than or equal to that basis occupancy,
        it chooses the one with the highest `occupancy_threshold_pct`; ties are
        broken by the lower `priority` value, and any remaining tie by the earlier
        `created_at`."

        Design: Corner/calculations/yield_rule_tie_break_highest_threshold_then_priority
        """
        set_clock("2026-06-01T00:00:00Z")
        prop = create_property(name="TieRule", total_rooms=100)
        rt = create_room_type(prop["id"], code="STD", name="Standard", physical_rooms=100)
        create_yield_rule(prop["id"], 0.50, 0.05, 1, name="Low", enabled=True)
        create_yield_rule(prop["id"], 0.80, 0.30, 2, name="High", enabled=True)
        plan = create_rate_plan(
            rt["id"], rate_class="BAR", is_master_bar=True,
            base_rate=200, floor_rate=100, ceiling_rate=400,
        )
        # sold 53 -> forecast round(79.5)=80 -> occ 0.80; both eligible, higher threshold (0.80) wins
        create_inventory_day(rt["id"], "2026-06-06T00:00:00Z", physical_capacity=100, transient_sold_rooms=53)
        dec = create_rate_decision(plan["id"], "2026-06-06T00:00:00Z", requested_rate=200)
        data = validate_success(api.publish_rate_decision(dec["id"], {"expected_rate_plan_version": plan["version"]}, RM))
        assert data["yielded_rate"] == 260.00, f"expected 260.00 (200*1.30) got {data['yielded_rate']}"


class TestPublishRejectBranch:
    def test_publish_branch_sets_rate_reject_branch_does_not(self, api):
        """PRD §3.4: "The decision's `yielded_rate` becomes the plan's
        `published_rate`, and the plan's `version` increments by 1."
        PRD §3.4: "Rejection is allowed only from `DRAFT` (otherwise
        `ERR_INVALID_STATE`); the decision's `yielded_rate` stays null, the plan's
        `published_rate` is left unchanged, and there is no channel sync and no KPI
        recompute."

        Design: Difficulty/non_linear_state_machine/rate_decision_branching_publish_vs_reject
        """
        set_clock("2026-06-01T00:00:00Z")
        prop = create_property(name="Branch", total_rooms=40)
        rt = create_room_type(prop["id"], code="KING", name="King", physical_rooms=40)
        plan = create_rate_plan(
            rt["id"], rate_class="BAR", is_master_bar=True,
            base_rate=200, floor_rate=100, ceiling_rate=400,
        )
        create_inventory_day(rt["id"], "2026-06-07T00:00:00Z", physical_capacity=40, transient_sold_rooms=10)
        dec_pub = create_rate_decision(plan["id"], "2026-06-07T00:00:00Z", requested_rate=200)
        dec_rej = create_rate_decision(plan["id"], "2026-06-07T00:00:00Z", requested_rate=250)

        pub = validate_success(api.publish_rate_decision(dec_pub["id"], {"expected_rate_plan_version": plan["version"]}, RM))
        assert pub["status"] == "PUBLISHED" and pub["yielded_rate"] == 200.00

        rej = validate_success(api.reject_rate_decision(dec_rej["id"], {"reject_reason": "off strategy"}, RM))
        assert rej["status"] == "REJECTED" and rej["yielded_rate"] is None

        plan_after = validate_success(api.get_rate_plan(plan["id"], RM))
        assert plan_after["published_rate"] == 200.00, (
            f"published_rate must come from the published decision, got {plan_after['published_rate']}"
        )

    def test_reject_branch_leaves_published_rate_null(self, api):
        """PRD §3.4: "Rejecting a `DRAFT` decision (`DRAFT → REJECTED`), also a
        `RevenueManager` action, is the divergent branch."
        PRD §3.4: "the decision's `yielded_rate` stays null, the plan's
        `published_rate` is left unchanged, and there is no channel sync and no KPI
        recompute."

        Design: Difficulty/non_linear_state_machine/rate_decision_branching_publish_vs_reject
        """
        set_clock("2026-06-01T00:00:00Z")
        prop = create_property(name="BranchRej", total_rooms=40)
        rt = create_room_type(prop["id"], code="KING", name="King", physical_rooms=40)
        plan = create_rate_plan(
            rt["id"], rate_class="BAR", is_master_bar=True,
            base_rate=200, floor_rate=100, ceiling_rate=400,
        )
        create_inventory_day(rt["id"], "2026-06-07T00:00:00Z", physical_capacity=40, transient_sold_rooms=10)
        dec = create_rate_decision(plan["id"], "2026-06-07T00:00:00Z", requested_rate=250)
        rej = validate_success(api.reject_rate_decision(dec["id"], {"reject_reason": "off strategy"}, RM))
        assert rej["status"] == "REJECTED" and rej["yielded_rate"] is None
        plan_after = validate_success(api.get_rate_plan(plan["id"], RM))
        assert plan_after["published_rate"] is None, (
            f"reject must leave published_rate unchanged (null), got {plan_after['published_rate']}"
        )

    def test_new_decision_is_draft_with_null_yield(self, api):
        """PRD §3.4: "A decision is born in `DRAFT` with its `yielded_rate` null
        and its `version` 1."

        Design: Corner/state_machines/new_rate_decision_initial_state_is_draft
        """
        prop = create_property(name="InitS", total_rooms=40)
        rt = create_room_type(prop["id"], code="KING", name="King", physical_rooms=40)
        plan = create_rate_plan(
            rt["id"], rate_class="BAR", is_master_bar=True,
            base_rate=200, floor_rate=100, ceiling_rate=400,
        )
        dec = validate_success(
            api.create_rate_decision(
                {"rate_plan_id": plan["id"], "stay_date": "2026-06-05T00:00:00Z", "requested_rate": 200}, RM
            ),
            expected_status=201,
        )
        assert dec["status"] == "DRAFT" and dec["yielded_rate"] is None

    def test_publish_already_published_decision_rejected(self, api):
        """PRD §3.4: "Before any pricing is computed, the publish is gated: the
        decision must be in `DRAFT` state, otherwise `ERR_INVALID_STATE`."

        Design: Corner/state_machines/publish_already_published_decision_returns_invalid_state
        """
        set_clock("2026-06-01T00:00:00Z")
        ctx = setup_published_master_bar(
            "2026-06-05T00:00:00Z", requested_rate=200,
            prop_overrides={"name": "DblPub", "total_rooms": 40},
            rt_overrides={"code": "KING", "name": "King", "physical_rooms": 40},
            inv_overrides={"physical_capacity": 40, "transient_sold_rooms": 5},
        )
        dec = ctx["decision"]
        plan_v = ctx["rate_plan"]["version"]
        resp = api.publish_rate_decision(dec["id"], {"expected_rate_plan_version": plan_v}, RM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestSupersedeInvariant:
    def test_second_publish_supersedes_first_single_effective_rate(self, api):
        """PRD §3.4: "any prior decision still `PUBLISHED` for the same plan and
        `stay_date` is moved `PUBLISHED → SUPERSEDED`, since it no longer drives
        the plan's `published_rate`."

        Design: Difficulty/compensating_invariant/supersede_keeps_single_effective_published_rate
        """
        set_clock("2026-06-01T00:00:00Z")
        prop = create_property(name="InvariantB", total_rooms=50)
        rt = create_room_type(prop["id"], code="STD", name="Standard", physical_rooms=50)
        plan = create_rate_plan(
            rt["id"], rate_class="BAR", is_master_bar=True,
            base_rate=200, floor_rate=100, ceiling_rate=400,
        )
        create_inventory_day(rt["id"], "2026-06-20T00:00:00Z", physical_capacity=50, transient_sold_rooms=10)
        dec1 = create_rate_decision(plan["id"], "2026-06-20T00:00:00Z", requested_rate=200)
        publish_decision(dec1["id"], plan["version"])
        plan_v1 = validate_success(api.get_rate_plan(plan["id"], RM))["version"]
        dec2 = create_rate_decision(plan["id"], "2026-06-20T00:00:00Z", requested_rate=250)
        p2 = validate_success(api.publish_rate_decision(dec2["id"], {"expected_rate_plan_version": plan_v1}, RM))
        assert p2["status"] == "PUBLISHED" and p2["yielded_rate"] == 250.00

        first_after = validate_success(api.get_rate_decision(dec1["id"], RM))
        assert first_after["status"] == "SUPERSEDED", (
            f"prior published decision must be demoted, got {first_after['status']}"
        )
        plan_after = validate_success(api.get_rate_plan(plan["id"], RM))
        assert plan_after["published_rate"] == 250.00, (
            f"published_rate must equal the single effective decision, got {plan_after['published_rate']}"
        )

    def test_newest_publish_drives_published_rate_not_stale_value(self, api):
        """PRD §3.4: "any prior decision still `PUBLISHED` for the same plan and
        `stay_date` is moved `PUBLISHED → SUPERSEDED`, since it no longer drives
        the plan's `published_rate`."
        PRD §3.4: "The decision's `yielded_rate` becomes the plan's
        `published_rate`, and the plan's `version` increments by 1."

        Design: Difficulty/compensating_invariant/supersede_keeps_single_effective_published_rate
        """
        set_clock("2026-06-01T00:00:00Z")
        prop = create_property(name="InvariantB2", total_rooms=50)
        rt = create_room_type(prop["id"], code="STD", name="Standard", physical_rooms=50)
        plan = create_rate_plan(
            rt["id"], rate_class="BAR", is_master_bar=True,
            base_rate=200, floor_rate=100, ceiling_rate=400,
        )
        create_inventory_day(rt["id"], "2026-06-20T00:00:00Z", physical_capacity=50, transient_sold_rooms=10)
        dec1 = create_rate_decision(plan["id"], "2026-06-20T00:00:00Z", requested_rate=200)
        publish_decision(dec1["id"], plan["version"])
        plan_v1 = validate_success(api.get_rate_plan(plan["id"], RM))["version"]
        dec2 = create_rate_decision(plan["id"], "2026-06-20T00:00:00Z", requested_rate=250)
        published2 = validate_success(api.publish_rate_decision(dec2["id"], {"expected_rate_plan_version": plan_v1}, RM))
        # The newly published decision is the single effective one.
        assert published2["status"] == "PUBLISHED"
        plan_after = validate_success(api.get_rate_plan(plan["id"], RM))
        assert plan_after["published_rate"] == published2["yielded_rate"] == 250.00, (
            f"published_rate must track the newest publish, got {plan_after['published_rate']}"
        )

    def test_publish_response_carries_computed_rate_immediately(self, api):
        """PRD §3.4: "When those gates pass, the system computes the decision's
        `yielded_rate` in a strictly pinned order."
        PRD §3.4: "Publishing a `DRAFT` decision (`DRAFT → PUBLISHED`) is the
        system's most consequential operation and is restricted to a
        `RevenueManager`."

        Design: Corner/consistency_model/immediate_publish_visible_in_same_response
        """
        set_clock("2026-06-01T00:00:00Z")
        prop = create_property(name="Immediate", total_rooms=50)
        rt = create_room_type(prop["id"], code="STD", name="Standard", physical_rooms=50)
        plan = create_rate_plan(
            rt["id"], rate_class="BAR", is_master_bar=True,
            base_rate=200, floor_rate=100, ceiling_rate=400,
        )
        create_inventory_day(rt["id"], "2026-06-06T00:00:00Z", physical_capacity=50, transient_sold_rooms=10)
        dec = create_rate_decision(plan["id"], "2026-06-06T00:00:00Z", requested_rate=200)
        data = validate_success(api.publish_rate_decision(dec["id"], {"expected_rate_plan_version": plan["version"]}, RM))
        assert data["status"] == "PUBLISHED" and data["yielded_rate"] == 200.00
