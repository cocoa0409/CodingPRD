"""Supplementary tests so every difficulty-design instance has at least TWO
dedicated tests (per §2.1.A coverage rule).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    create_recall_payload, create_clock_advance_payload,
    create_pick_complete_payload, create_pack_payload,
    create_order_payload, create_wave_payload,
    create_cycle_count_payload, create_submit_count_payload,
    create_inbound_shipment_payload,
    create_complete_inspection_payload,
    create_warehouse, create_bin, create_lot, putaway_lot_units,
    setup_warehouse_with_inventory, setup_warehouse_with_recalls,
    create_allocated_order, setup_released_wave_for_order,
    get_pick_tasks_for_order, setup_picking_pick_task,
    setup_cycle_count_in_state, get_inventory_row,
    sum_inventory_qty_for_lot,
    TEST_USERS, NON_EXISTENT_UUID,
    STAFF_USER_ID, AUDITOR_USER_ID,
    make_staff_headers, make_auditor_headers,
)


# =============================================================================
# transitive_cascade/lot_recall_cascade_depth_4 — second test
# =============================================================================

class TestRecallCascadeUpdatesRiskScore:
    def test_recall_recomputes_risk_score(self, api, manager_headers, staff_headers):
        """PRD §3.9: "The warehouse's recall_count_open is incremented by 1
        and risk_score and posture are recomputed from the new counters."

        # difficulty: transitive_cascade/lot_recall_cascade_depth_4
        Claim: a recall (additional cascade leg) recomputes risk_score; the
        new score reflects 100 points per recall plus 10 per abnormal event.
        """
        wh, b, lot, order, wave, pt = setup_picking_pick_task(order_qty=10, sku="PEN")
        before = validate_success(api.get_warehouse(wh["id"], manager_headers), 200)
        validate_success(api.recall_lot(
            wh["id"], lot["id"], create_recall_payload("SAFETY_ISSUE"),
            manager_headers), 200)
        after = validate_success(api.get_warehouse(wh["id"], manager_headers), 200)
        # +100 for recall, +10 for abnormal_event (short_picked rollup)
        # = 110 points more than before
        assert after["risk_score"] == pytest.approx(before["risk_score"] + 110, abs=0.01)


# =============================================================================
# transitive_cascade/cycle_count_adjust_cascade_depth_3 — second test
# =============================================================================

class TestCycleCountAdjustCascadeShrinkage:
    def test_adjust_increments_warehouse_shrinkage(self, api, manager_headers):
        """PRD §3.8: "shrinkage_value_30d_cents on the warehouse is increased
        by the cycle count's variance_value_cents (so long as the approval
        falls within the rolling 30-day window)."

        # difficulty: transitive_cascade/cycle_count_adjust_cascade_depth_3
        Claim: approving an ADJUSTED cycle count cascades into the warehouse's
        shrinkage_value_30d_cents counter.
        """
        wh = create_warehouse(advance_clock_to="2025-01-01T00:00:00.000Z")
        b = create_bin(wh["id"], bin_code="BCC2", zone="AMBIENT",
                      capacity_volume_cm3=10000, capacity_weight_g=10000)
        lot = create_lot(wh["id"], sku="PEN", category="AMBIENT",
                        unit_volume_cm3=20, unit_weight_g=10, unit_value_cents=200)
        putaway_lot_units(wh["id"], lot["id"], 50)
        before = validate_success(api.get_warehouse(wh["id"], manager_headers), 200)
        # variance: counted 40, book 50, variance_units = -10, value = 10*200 = 2000 cents
        cc = setup_cycle_count_in_state(
            wh["id"], b["id"], lot["id"], "ADJUSTED",
            counted_qty_offset=-10,
            submitter_user_id="cc-staff-2",
            approver_user_id="cc-aud-2",
        )
        assert cc["status"] == "ADJUSTED"
        assert cc["variance_value_cents"] == 2000
        after = validate_success(api.get_warehouse(wh["id"], manager_headers), 200)
        assert after["shrinkage_value_30d_cents"] == before["shrinkage_value_30d_cents"] + 2000


# =============================================================================
# resource_temporal_overlap/wave_per_warehouse_singleton_exclusion — second test
# =============================================================================

class TestWaveSingletonAllowsAdditionalPlannedWaves:
    def test_multiple_planned_waves_allowed_until_release(self, api, staff_headers):
        """PRD §3.5: "Releasing the wave from PLANNED to RELEASED enforces
        two preconditions: first, no other wave on the same warehouse may
        be in RELEASED or IN_PROGRESS"
        Note: the rule gates only the release transition — multiple PLANNED
        waves are permitted.

        # difficulty: resource_temporal_overlap/wave_per_warehouse_singleton_exclusion
        Claim: PLANNED wave creation is unconstrained — many PLANNED waves
        may coexist on the same warehouse.
        """
        wh, b, lot = setup_warehouse_with_inventory(units=100, sku="PEN")
        orders = []
        for i in range(3):
            o = create_allocated_order(
                wh["id"], sku="PEN", qty_units=5,
                order_number=f"ORD-PL-{i}",
            )
            orders.append(o)
        waves = []
        for i, o in enumerate(orders):
            w = validate_success(api.create_wave(
                wh["id"],
                create_wave_payload([o["id"]], wave_code=f"PLW-{i}"),
                staff_headers), 201)
            assert w["status"] == "PLANNED"
            waves.append(w)
        assert len(waves) == 3


# =============================================================================
# priority_pair_validation_conflict/state_vs_business_safety_pick_start — second
# =============================================================================

class TestStateBeforeLotPickabilityAlreadyTerminal:
    def test_pick_start_on_already_picked_when_lot_recalled(self, api, staff_headers, manager_headers):
        """PRD §2.6 priority rules 5 and 6: state-eligibility (priority 5)
        is evaluated before lot-pickability (priority 6).

        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_pick_start
        Claim: when a pick task is already in PICKED state and its lot is
        then RECALLED, restarting it returns ERR_INVALID_STATE (state takes
        priority over lot-pickability).
        """
        wh, b, lot, order, wave, pt = setup_picking_pick_task(order_qty=5)
        # Complete pt
        validate_success(api.complete_pick_task(
            wh["id"], pt["id"], create_pick_complete_payload(5),
            staff_headers), 200)
        # Recall the lot — but lot is RECALLED only after the pick task
        # already terminated, so cascade doesn't change pt's status.
        # Wait — lot recall's cascade only touches CREATED/PICKING tasks, not PICKED.
        # So pt remains PICKED after recall.
        validate_success(api.recall_lot(
            wh["id"], lot["id"], create_recall_payload("SAFETY_ISSUE"),
            manager_headers), 200)
        pt_after = validate_success(api.get_pick_task(wh["id"], pt["id"], staff_headers), 200)
        assert pt_after["status"] == "PICKED"  # unchanged
        # Try to start it (PICKED → PICKING is invalid; lot is RECALLED).
        # State check (priority 5) wins → ERR_INVALID_STATE.
        validate_error(api.start_pick_task(
            wh["id"], pt["id"], staff_headers), "ERR_INVALID_STATE")


# =============================================================================
# priority_pair_validation_conflict/capacity_vs_safety_order_allocate — second
# =============================================================================

class TestCapacityWinsOverPostureWithRealInventory:
    def test_partial_inventory_shortage_in_frozen_warehouse(self, api, staff_headers, manager_headers):
        """PRD §2.6 priority rules 13 and 14: capacity (priority 13) is
        evaluated before posture (priority 14).

        # difficulty: priority_pair_validation_conflict/capacity_vs_safety_order_allocate
        Claim: in a FROZEN-posture warehouse with partial inventory of the
        SKU, a request that exceeds available stock fails with
        ERR_INSUFFICIENT_INVENTORY (priority 13), not ERR_POSTURE_FROZEN
        (priority 14).
        """
        wh = setup_warehouse_with_recalls(num_recalls=3)
        assert wh["posture"] == "FROZEN"
        # Now stock 5 units of GOOD_SKU
        b = create_bin(wh["id"], bin_code="GS-BIN",
                      capacity_volume_cm3=100000, capacity_weight_g=100000)
        lot = create_lot(wh["id"], sku="GOOD_SKU", category="AMBIENT")
        putaway_lot_units(wh["id"], lot["id"], 5)
        # Order requesting 10 units — only 5 available, so ERR_INSUFFICIENT_INVENTORY wins
        order = validate_success(api.create_order(
            wh["id"],
            create_order_payload(
                requested_lines=[{"sku": "GOOD_SKU", "qty_units": 10}],
                order_number="ORD-PRI-2", carrier="UPS"),
            staff_headers), 201)
        validate_error(api.allocate_order(
            wh["id"], order["id"], staff_headers), "ERR_INSUFFICIENT_INVENTORY")


# =============================================================================
# non_linear_state_machine/order_short_picked_to_allocated_cycle — second
# =============================================================================

class TestReplanRetainsAuditTrail:
    def test_replan_preserves_terminal_short_picked_pick_task(self, api, staff_headers):
        """PRD §3.6: "The terminal pick tasks from the previous round are
        retained for audit"

        # difficulty: non_linear_state_machine/order_short_picked_to_allocated_cycle
        Claim: after replan of a SHORT_PICKED order, the original
        SHORT_PICKED pick task survives in the order's pick_tasks list.
        """
        wh, b, lot, order, wave, pt = setup_picking_pick_task(order_qty=20)
        validate_success(api.complete_pick_task(
            wh["id"], pt["id"], create_pick_complete_payload(8),
            staff_headers), 200)
        # Capture original pick task id
        original_id = pt["id"]
        # Replan
        replanned = validate_success(api.replan_order(
            wh["id"], order["id"], staff_headers), 200)
        assert replanned["status"] == "ALLOCATED"
        # Re-check pick tasks
        pts_after = get_pick_tasks_for_order(wh["id"], order["id"])
        ids = {pt2["id"]: pt2 for pt2 in pts_after}
        assert original_id in ids, "Original SHORT_PICKED pick task should be retained"
        assert ids[original_id]["status"] == "SHORT_PICKED"
        # New CREATED pick task with planned_units = 12 (residual)
        new_pts = [pt for pt in pts_after if pt["status"] == "CREATED"]
        assert len(new_pts) >= 1
        assert sum(pt["planned_units"] for pt in new_pts) == 12


# =============================================================================
# cross_entity_state_dependency/pick_task_depends_on_bin_status — second
# =============================================================================

class TestPickStartReleasedAfterBinUnfreeze:
    def test_pick_start_succeeds_after_cycle_count_dispute(self, api, staff_headers, manager_headers):
        """PRD §3.8: dispute "leaves inventory unchanged, and unfreezes the bin."
        PRD §3.6: "the source bin's status must be ACTIVE (otherwise ERR_BIN_FROZEN)"

        # difficulty: cross_entity_state_dependency/pick_task_depends_on_bin_status
        Claim: once the cycle count's dispute unfreezes the source bin,
        the pick task can be started — the cross-entity dependency on
        bin status fully tracks bin state changes.
        """
        wh, b, lot = setup_warehouse_with_inventory(units=30, sku="PEN")
        # Allocate
        order = create_allocated_order(wh["id"], sku="PEN", qty_units=10)
        wave = setup_released_wave_for_order(wh["id"], order["id"])
        pt = get_pick_tasks_for_order(wh["id"], order["id"])[0]
        # Schedule cycle count to freeze
        cc = validate_success(api.create_cycle_count(
            wh["id"], create_cycle_count_payload(b["id"], lot["id"]),
            staff_headers), 201)
        # Pick start should fail
        validate_error(api.start_pick_task(
            wh["id"], pt["id"], staff_headers), "ERR_BIN_FROZEN")
        # Submit a count with variance, then DISPUTE to unfreeze
        validate_success(api.start_cycle_count(wh["id"], cc["id"], staff_headers), 200)
        validate_success(api.submit_cycle_count(
            wh["id"], cc["id"], create_submit_count_payload(25),  # variance
            staff_headers), 200)
        validate_success(api.dispute_cycle_count(
            wh["id"], cc["id"], staff_headers), 200)
        # Bin should now be ACTIVE
        bin_after = validate_success(api.get_bin(wh["id"], b["id"], staff_headers), 200)
        assert bin_after["status"] == "ACTIVE"
        # Pick start now succeeds
        pt_started = validate_success(api.start_pick_task(
            wh["id"], pt["id"], staff_headers), 200)
        assert pt_started["status"] == "PICKING"


# =============================================================================
# cross_entity_state_dependency/order_allocate_depends_on_warehouse_posture — second
# =============================================================================

class TestOrderAllocatePostureRestrictedAllowed:
    def test_allocate_succeeds_when_posture_restricted(self, api, staff_headers, manager_headers):
        """PRD §3.4: "the warehouse posture must be OPEN or RESTRICTED
        (otherwise ERR_POSTURE_FROZEN)"

        # difficulty: cross_entity_state_dependency/order_allocate_depends_on_warehouse_posture
        Claim: with warehouse posture RESTRICTED (score in (100, 200]),
        allocate is permitted — only FROZEN gates allocation.
        Setup: 2 recalls × 100 = 200 → posture RESTRICTED.
        """
        wh = create_warehouse()
        # Create 2 recalls
        for i in range(2):
            lot_i = create_lot(wh["id"], lot_code=f"PR_{i}", sku=f"PR_{i}")
            validate_success(api.recall_lot(
                wh["id"], lot_i["id"], create_recall_payload("SAFETY_ISSUE"),
                manager_headers), 200)
        wh_after = validate_success(api.get_warehouse(wh["id"], manager_headers), 200)
        assert wh_after["posture"] == "RESTRICTED"
        # Now stock and allocate
        b = create_bin(wh["id"], bin_code="OK-BIN",
                      capacity_volume_cm3=100000, capacity_weight_g=100000)
        good_lot = create_lot(wh["id"], sku="GOOD", category="AMBIENT", lot_code="L_GOOD")
        putaway_lot_units(wh["id"], good_lot["id"], 30)
        order = validate_success(api.create_order(
            wh["id"],
            create_order_payload(
                requested_lines=[{"sku": "GOOD", "qty_units": 5}],
                order_number="ORD-RESTR", carrier="UPS"),
            staff_headers), 201)
        allocated = validate_success(api.allocate_order(
            wh["id"], order["id"], staff_headers), 200)
        assert allocated["status"] == "ALLOCATED"


# =============================================================================
# compensating_invariant/qty_units_invariant_putaway_then_dispose — second
# =============================================================================

class TestQtyInvariantBinUsedRecomputed:
    def test_dispose_recomputes_bin_used_to_zero(self, api, manager_headers, staff_headers):
        """PRD §3.9: "On a successful dispose, every inventory row for the
        lot has its qty_units set to 0, every affected bin recomputes
        used_volume_cm3, used_weight_g, remaining_volume_cm3, and
        remaining_weight_g"

        # difficulty: compensating_invariant/qty_units_invariant_putaway_then_dispose
        Claim: after dispose, bin.used_volume_cm3 and used_weight_g for
        the only-occupied bin recompute back to 0; remaining_volume_cm3
        equals capacity_volume_cm3.
        """
        wh, b, lot = setup_warehouse_with_inventory(
            units=20, sku="PEN", unit_volume_cm3=20, unit_weight_g=5)
        bin_pre = validate_success(api.get_bin(wh["id"], b["id"], staff_headers), 200)
        assert bin_pre["used_volume_cm3"] == 20 * 20
        assert bin_pre["used_weight_g"] == 20 * 5
        # Recall + dispose
        validate_success(api.recall_lot(
            wh["id"], lot["id"], create_recall_payload("SUPPLIER_RECALL"),
            manager_headers), 200)
        validate_success(api.dispose_lot(wh["id"], lot["id"], staff_headers), 200)
        bin_post = validate_success(api.get_bin(wh["id"], b["id"], staff_headers), 200)
        assert bin_post["used_volume_cm3"] == 0
        assert bin_post["used_weight_g"] == 0
        assert bin_post["remaining_volume_cm3"] == bin_post["capacity_volume_cm3"]
        assert bin_post["remaining_weight_g"] == bin_post["capacity_weight_g"]


# =============================================================================
# combinatorial_formula/risk_score_three_weighted_inputs_mode_a — second
# =============================================================================

class TestRiskScoreShrinkageContribution:
    def test_risk_score_includes_shrinkage(self, api, manager_headers):
        """PRD §3.1: "The risk_score is the sum of three rolling components:
        one point for every dollar of shrinkage_value_30d_cents (i.e.,
        the integer cents counter divided by 100), plus 10 points per
        event in abnormal_event_count_24h, plus 100 points per lot in
        recall_count_open."

        # difficulty: combinatorial_formula/risk_score_three_weighted_inputs_mode_a
        Claim: shrinkage contributes 1 point per dollar; specifically,
        shrinkage 5000 cents = 50 dollars = 50 points (in addition to
        the +10 per abnormal event from the variance submission).
        """
        wh = create_warehouse(advance_clock_to="2025-01-01T00:00:00.000Z")
        b = create_bin(wh["id"], bin_code="RS-B",
                      capacity_volume_cm3=10000, capacity_weight_g=10000)
        lot = create_lot(wh["id"], sku="PEN", category="AMBIENT",
                        unit_volume_cm3=20, unit_weight_g=5,
                        unit_value_cents=500)  # cents per unit
        putaway_lot_units(wh["id"], lot["id"], 100)
        # Variance: counted 90, book 100, variance_units = -10
        # variance_value_cents = 10 * 500 = 5000 (= $50 → 50 risk-score points)
        before = validate_success(api.get_warehouse(wh["id"], manager_headers), 200)
        cc = setup_cycle_count_in_state(
            wh["id"], b["id"], lot["id"], "ADJUSTED",
            counted_qty_offset=-10,
            submitter_user_id="rs-staff",
            approver_user_id="rs-aud",
        )
        assert cc["variance_value_cents"] == 5000
        after = validate_success(api.get_warehouse(wh["id"], manager_headers), 200)
        # +1 abnormal event (from variance submission, +10 score),
        # +5000 cents shrinkage (+50 score from $50)
        # = +60 to risk_score
        assert after["abnormal_event_count_24h"] == before["abnormal_event_count_24h"] + 1
        assert after["shrinkage_value_30d_cents"] == before["shrinkage_value_30d_cents"] + 5000
        assert after["risk_score"] == pytest.approx(before["risk_score"] + 60.0, abs=0.01)


# =============================================================================
# combinatorial_formula/carton_count_sum_then_ceil_mode_b — second
# =============================================================================

class TestCartonCountFinalSumThenCeil:
    def test_final_carton_count_uses_sum_then_ceil(self, api, staff_headers, manager_headers):
        """PRD §3.7: "the total volume is the sum over PICKED pick tasks of
        picked_units times that pick task's lot unit_volume_cm3"
        and "the count by taking the maximum of three values: cartons-by-volume
        (the order's total volume divided by 50000, rounded up to a whole
        carton), cartons-by-weight (the order's total weight divided by
        20000, rounded up to a whole carton), and the floor of one carton"

        # difficulty: combinatorial_formula/carton_count_sum_then_ceil_mode_b
        Claim: final_carton_count is computed sum-then-ceil. With 4 picked
        units of volume 30000 each (total = 120000 cm3),
        final_carton_count = ceil(120000 / 50000) = 3.
        """
        wh = create_warehouse()
        b = create_bin(wh["id"], bin_code="FCC-B",
                      capacity_volume_cm3=200000, capacity_weight_g=50000)
        lot = create_lot(wh["id"], sku="PEN", category="AMBIENT",
                        unit_volume_cm3=30000, unit_weight_g=100, unit_value_cents=100,
                        lot_code="LFCC")
        putaway_lot_units(wh["id"], lot["id"], 4)
        order = create_allocated_order(wh["id"], sku="PEN", qty_units=4,
                                       order_number="ORD-FCC", pick_strategy="FEFO")
        wave = setup_released_wave_for_order(wh["id"], order["id"])
        pts = get_pick_tasks_for_order(wh["id"], order["id"])
        for pt in pts:
            validate_success(api.start_pick_task(wh["id"], pt["id"], staff_headers), 200)
            validate_success(api.complete_pick_task(
                wh["id"], pt["id"], create_pick_complete_payload(pt["planned_units"]),
                staff_headers), 200)
        packed = validate_success(api.pack_order(
            wh["id"], order["id"], create_pack_payload(), staff_headers), 200)
        # 4 * 30000 = 120000 cm3 → ceil(120000/50000) = 3
        # 4 * 100 = 400 g → ceil(400/20000) = 1
        # max(3, 1, 1) = 3
        assert packed["final_carton_count"] == 3
