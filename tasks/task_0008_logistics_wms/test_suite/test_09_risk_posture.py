"""Risk score, posture, and validation priority interactions across capacity/safety
boundaries."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    create_recall_payload,
    create_warehouse, create_lot, create_bin,
    setup_warehouse_with_inventory,
    setup_warehouse_with_recalls,
    create_allocated_order, create_order_payload,
    putaway_lot_units,
    TEST_USERS, RECALL_WEIGHT, ABNORMAL_EVENT_WEIGHT,
    POSTURE_FROZEN_THRESHOLD, POSTURE_RESTRICTED_THRESHOLD,
    assert_posture_consistent_with_score,
)


class TestRiskScoreCombinatorial:
    def test_risk_score_combines_three_inputs(self, api, manager_headers, staff_headers):
        """PRD §3.1: "The risk_score is the sum of three rolling components:
        one point for every dollar of shrinkage_value_30d_cents (i.e., the
        integer cents counter divided by 100), plus 10 points per event
        in abnormal_event_count_24h, plus 100 points per lot in
        recall_count_open. The raw sum is rounded half-up to two decimals
        and capped at 1000.00. The posture derives directly from the score:
        when risk_score is greater than 200 the posture is FROZEN, when
        risk_score is greater than 100 but at most 200 the posture is
        RESTRICTED, and when risk_score is at most 100 the posture is OPEN."

        # difficulty: combinatorial_formula/risk_score_three_weighted_inputs_mode_a
        Claim: with abnormal_event_count_24h=2 (from 2 failed inspections)
        and recall_count_open=1, shrinkage=0:
          raw = 0/100 + 2*10 + 1*100 = 120
          risk_score = 120; posture = RESTRICTED (120 > 100, ≤ 200).
        """
        wh = create_warehouse()
        # Create 2 failed inspections
        from test_helpers import (
            create_inbound_shipment_payload,
            create_complete_inspection_payload,
        )
        for i in range(2):
            lot_i = create_lot(wh["id"], lot_code=f"LOT_FAIL_{i}",
                              sku=f"FAIL_{i}", category="AMBIENT")
            sh = validate_success(api.create_inbound_shipment(
                wh["id"],
                create_inbound_shipment_payload(lot_i["id"], 20, asn_number=f"ASN_F_{i}"),
                staff_headers), 201)
            validate_success(api.start_inspection(wh["id"], sh["id"], staff_headers), 200)
            # Defect rate 1/8 = 0.125 > 0.025 → FAILED → abnormal++
            validate_success(api.complete_inspection(
                wh["id"], sh["id"],
                create_complete_inspection_payload(lot_i["id"], 20, 1),
                staff_headers), 200)
        # Create 1 recall
        recall_lot = create_lot(wh["id"], lot_code="LOT_RECALL_1",
                               sku="RECALL_1", category="AMBIENT")
        validate_success(api.recall_lot(
            wh["id"], recall_lot["id"], create_recall_payload("SAFETY_ISSUE"),
            manager_headers), 200)
        # Now read warehouse
        wh_after = validate_success(api.get_warehouse(wh["id"], manager_headers), 200)
        assert wh_after["abnormal_event_count_24h"] == 2
        assert wh_after["recall_count_open"] == 1
        assert wh_after["shrinkage_value_30d_cents"] == 0
        # raw = 0 + 20 + 100 = 120
        assert wh_after["risk_score"] == pytest.approx(120.00, abs=0.01)
        assert wh_after["posture"] == "RESTRICTED"

    def test_risk_score_rounded_2_decimals_and_capped(self, api, manager_headers):
        """PRD §3.1: "The raw sum is rounded half-up to two decimals and
        capped at 1000.00."
        PRD §2.8: "risk_score on warehouses is rounded to 2 decimal places
        and capped at 1000.00."

        Claim: the cap and 2-decimal precision are honored when many
        recalls would otherwise push past 1000.
        """
        # 11 recalls × 100 = 1100, capped at 1000.00
        wh = create_warehouse()
        for i in range(11):
            lot_i = create_lot(wh["id"], lot_code=f"CAP_{i}",
                              sku=f"CAP_{i}", category="AMBIENT")
            validate_success(api.recall_lot(
                wh["id"], lot_i["id"], create_recall_payload("SUPPLIER_RECALL"),
                manager_headers), 200)
        wh_after = validate_success(api.get_warehouse(wh["id"], manager_headers), 200)
        assert wh_after["risk_score"] == 1000.00
        assert wh_after["posture"] == "FROZEN"

    def test_posture_at_score_exactly_100_is_open(self, api, manager_headers):
        """PRD §3.1: "when risk_score is at most 100 the posture is OPEN"

        Claim: risk_score = 100 (not > 100) → posture OPEN.
        Setup: 1 recall (100 points) → score=100 → OPEN.
        """
        wh = create_warehouse()
        lot = create_lot(wh["id"])
        validate_success(api.recall_lot(
            wh["id"], lot["id"], create_recall_payload("SAFETY_ISSUE"),
            manager_headers), 200)
        wh_after = validate_success(api.get_warehouse(wh["id"], manager_headers), 200)
        assert wh_after["risk_score"] == 100.00
        assert wh_after["posture"] == "OPEN"

    def test_posture_at_score_exactly_200_is_restricted(self, api, manager_headers):
        """PRD §3.1: "when risk_score is greater than 100 but at most 200
        the posture is RESTRICTED"

        Claim: risk_score = 200 (not > 200) → posture RESTRICTED.
        Setup: 2 recalls × 100 = 200.
        """
        wh = create_warehouse()
        for i in range(2):
            lot_i = create_lot(wh["id"], lot_code=f"R200_{i}", sku=f"R200_{i}")
            validate_success(api.recall_lot(
                wh["id"], lot_i["id"], create_recall_payload("SAFETY_ISSUE"),
                manager_headers), 200)
        wh_after = validate_success(api.get_warehouse(wh["id"], manager_headers), 200)
        assert wh_after["risk_score"] == 200.00
        assert wh_after["posture"] == "RESTRICTED"

    def test_posture_above_200_is_frozen(self, api, manager_headers):
        """PRD §3.1: "when risk_score is greater than 200 the posture is
        FROZEN"

        Claim: risk_score > 200 → FROZEN. Setup: 3 recalls × 100 = 300.
        """
        wh = setup_warehouse_with_recalls(num_recalls=3)
        assert wh["risk_score"] == 300.00
        assert wh["posture"] == "FROZEN"


class TestValidationPriority:
    def test_insufficient_inventory_wins_over_posture_frozen(self, api, staff_headers, manager_headers):
        """PRD §2.6 priority rules 13 and 14: "Inventory sufficiency" (priority
        13, ERR_INSUFFICIENT_INVENTORY) is evaluated before "Operational
        posture gate" (priority 14, ERR_POSTURE_FROZEN).

        # difficulty: priority_pair_validation_conflict/capacity_vs_safety_order_allocate
        Claim: when both ERR_INSUFFICIENT_INVENTORY and ERR_POSTURE_FROZEN
        would fire (warehouse FROZEN AND no inventory for the SKU), the
        higher-priority ERR_INSUFFICIENT_INVENTORY is returned.
        """
        wh = setup_warehouse_with_recalls(num_recalls=3)
        assert wh["posture"] == "FROZEN"
        # No inventory for "NONEXISTENT_SKU"
        order = validate_success(api.create_order(
            wh["id"],
            create_order_payload(
                requested_lines=[{"sku": "NONEXISTENT_SKU", "qty_units": 5}],
                order_number="ORD-PRI", carrier="UPS"),
            staff_headers), 201)
        validate_error(api.allocate_order(
            wh["id"], order["id"], staff_headers), "ERR_INSUFFICIENT_INVENTORY")
        # Order remains CREATED
        order_after = validate_success(api.get_order(wh["id"], order["id"], staff_headers), 200)
        assert order_after["status"] == "CREATED"


class TestClockAdvanceAndOpsRunIndex:
    def test_clock_advance_updates_clock_now(self, api, manager_headers):
        """PRD §2.7: "an admin-only test-driving capability advances clock_now
        by request, taking a warehouse_id body parameter and a new_time
        body parameter and rewriting clock_now to the supplied new_time
        instant."

        Claim: /_clock/advance updates Warehouse.clock_now to new_time.
        """
        wh = create_warehouse(advance_clock_to=False)
        from test_helpers import create_clock_advance_payload
        wh_after = validate_success(api.advance_clock(
            create_clock_advance_payload(wh["id"], "2025-06-01T00:00:00.000Z"),
            manager_headers), 200)
        assert wh_after["clock_now"].startswith("2025-06-01")

    def test_run_ops_increments_ops_run_index(self, api, manager_headers):
        """PRD §3.1: "Each call increments ops_run_index by 1, runs the
        near-expiry scan over every lot whose status is in ACTIVE or
        NEAR_EXPIRY, automatically transitions inbound shipments whose
        every line is in PUTAWAY to CLOSED and inbound shipments whose
        every line is in QUARANTINED to CLOSED, decays
        abnormal_event_count_24h by dropping events older than 86400
        seconds before clock_now, recomputes shrinkage_value_30d_cents
        by re-summing the integer-cent variance values from cycle counts
        that are ADJUSTED and whose approved_at is within the last 30
        simulated days, and recomputes risk_score and posture from the
        refreshed counters."

        Claim: each /run_ops call increments ops_run_index by exactly 1.
        """
        wh = create_warehouse()
        before_idx = wh["ops_run_index"]
        wh1 = validate_success(api.run_ops(wh["id"], manager_headers), 200)
        assert wh1["ops_run_index"] == before_idx + 1
        wh2 = validate_success(api.run_ops(wh["id"], manager_headers), 200)
        assert wh2["ops_run_index"] == before_idx + 2

    def test_run_ops_closes_putaway_shipment(self, api, manager_headers, staff_headers):
        """PRD §3.1: "automatically transitions inbound shipments whose every
        line is in PUTAWAY to CLOSED"

        Claim: a fully-PUTAWAY shipment is closed by /run_ops.
        """
        wh, b, lot = setup_warehouse_with_inventory(units=10, sku="PEN")
        # Identify the shipment used by the fixture by looking up the warehouse's
        # shipments via... actually we don't have a list endpoint. Instead, set up
        # a fresh shipment manually so we control its id.
        from test_helpers import (
            create_inbound_shipment_payload,
            create_complete_inspection_payload,
        )
        sh = validate_success(api.create_inbound_shipment(
            wh["id"],
            create_inbound_shipment_payload(lot["id"], 5, asn_number="ASN-CLOSE"),
            staff_headers), 201)
        validate_success(api.start_inspection(wh["id"], sh["id"], staff_headers), 200)
        validate_success(api.complete_inspection(
            wh["id"], sh["id"],
            create_complete_inspection_payload(lot["id"], 5, 0),
            staff_headers), 200)
        validate_success(api.putaway_inbound_shipment(
            wh["id"], sh["id"], staff_headers), 200)
        # Pre run_ops: shipment status PUTAWAY
        sh_pre = validate_success(api.get_inbound_shipment(
            wh["id"], sh["id"], staff_headers), 200)
        assert sh_pre["status"] == "PUTAWAY"
        validate_success(api.run_ops(wh["id"], manager_headers), 200)
        sh_post = validate_success(api.get_inbound_shipment(
            wh["id"], sh["id"], staff_headers), 200)
        assert sh_post["status"] == "CLOSED"
