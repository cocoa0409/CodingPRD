"""Lot recall, near-expiry, expiry, dispose, and the cascades they trigger."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    create_recall_payload, create_clock_advance_payload,
    create_pick_complete_payload,
    create_warehouse, create_bin, create_lot, putaway_lot_units,
    setup_warehouse_with_inventory, create_allocated_order,
    setup_released_wave_for_order, get_pick_tasks_for_order,
    setup_picking_pick_task, get_inventory_row,
    sum_inventory_qty_for_lot,
    TEST_USERS, NEAR_EXPIRY_DAYS,
    RECALL_WEIGHT, ABNORMAL_EVENT_WEIGHT,
    assert_posture_consistent_with_score,
)


class TestRecall:
    def test_recall_active_lot_to_recalled(self, api, manager_headers, staff_headers):
        """PRD §3.9: "A WarehouseManager may recall an ACTIVE or NEAR_EXPIRY
        lot, supplying a recall_reason chosen from SUPPLIER_RECALL,
        SAFETY_ISSUE, or EXPIRY_BATCH. ... Recalling moves the lot to
        RECALLED and writes recalled_at = clock_now and recall_reason from
        the body."

        Claim: /recall on ACTIVE lot moves it to RECALLED with recalled_at
        and recall_reason populated.
        """
        wh = create_warehouse(advance_clock_to="2025-03-15T00:00:00.000Z")
        lot = create_lot(wh["id"])
        recalled = validate_success(api.recall_lot(
            wh["id"], lot["id"],
            create_recall_payload("SAFETY_ISSUE"),
            manager_headers), 200)
        assert recalled["status"] == "RECALLED"
        assert recalled["recall_reason"] == "SAFETY_ISSUE"
        assert recalled.get("recalled_at") is not None

    def test_recall_increments_recall_count_and_recomputes_posture(self, api, manager_headers):
        """PRD §3.9: "The warehouse's recall_count_open is incremented by 1
        and risk_score and posture are recomputed from the new counters."
        PRD §3.1: "100 points per lot in recall_count_open"

        Claim: each recall increments recall_count_open by 1 and adds 100
        points to risk_score; posture follows.
        """
        wh = create_warehouse()
        before = validate_success(api.get_warehouse(wh["id"], manager_headers), 200)
        lot = create_lot(wh["id"])
        validate_success(api.recall_lot(
            wh["id"], lot["id"], create_recall_payload("SUPPLIER_RECALL"),
            manager_headers), 200)
        after = validate_success(api.get_warehouse(wh["id"], manager_headers), 200)
        assert after["recall_count_open"] == before["recall_count_open"] + 1
        # +100 points
        assert after["risk_score"] >= before["risk_score"] + 100 - 0.01
        assert_posture_consistent_with_score(after)

    def test_recall_disposed_lot_invalid_state(self, api, manager_headers, staff_headers):
        """PRD §3.9: "A recall on any other status is rejected with
        ERR_INVALID_STATE."

        Claim: recalling a non-ACTIVE/non-NEAR_EXPIRY lot → ERR_INVALID_STATE.
        Setup: take a lot to DISPOSED first (via recall + dispose), then
        attempt recall on DISPOSED.
        """
        wh = create_warehouse()
        lot = create_lot(wh["id"])
        validate_success(api.recall_lot(
            wh["id"], lot["id"], create_recall_payload("SAFETY_ISSUE"),
            manager_headers), 200)
        validate_success(api.dispose_lot(
            wh["id"], lot["id"], staff_headers), 200)
        # Now try to recall again — DISPOSED is not allowed
        validate_error(api.recall_lot(
            wh["id"], lot["id"], create_recall_payload("SAFETY_ISSUE"),
            manager_headers), "ERR_INVALID_STATE")


class TestRecallCascade:
    def test_recall_cascades_to_picking_tasks_and_order(self, api, staff_headers, manager_headers):
        """PRD §3.9: "The cascade is broader than expiry: every pick task
        that references the lot in either CREATED or PICKING is moved to
        FAILED, each affected pick task's Inventory.reserved_units is
        decreased by its planned_units, and each affected order then rolls
        up to SHORT_PICKED (with the corresponding abnormal_event_count_24h
        increment) once its remaining pick tasks are terminal."

        # difficulty: transitive_cascade/lot_recall_cascade_depth_4
        Claim: recall on a lot whose only pick task is PICKING cascades
        all 4 hops:
          Lot → RECALLED;
          PickTask → FAILED;
          Order → SHORT_PICKED;
          abnormal_event_count_24h += 1; reserved_units released.
        """
        wh, b, lot, order, wave, pt = setup_picking_pick_task(order_qty=10, sku="PEN")
        before = validate_success(api.get_warehouse(wh["id"], manager_headers), 200)
        # Recall
        validate_success(api.recall_lot(
            wh["id"], lot["id"], create_recall_payload("SAFETY_ISSUE"),
            manager_headers), 200)
        # Hop 1
        lot_after = validate_success(api.get_lot(wh["id"], lot["id"], staff_headers), 200)
        assert lot_after["status"] == "RECALLED"
        # Hop 2
        pt_after = validate_success(api.get_pick_task(wh["id"], pt["id"], staff_headers), 200)
        assert pt_after["status"] == "FAILED"
        # Hop 3
        order_after = validate_success(api.get_order(wh["id"], order["id"], staff_headers), 200)
        assert order_after["status"] == "SHORT_PICKED"
        # Hop 4
        wh_after = validate_success(api.get_warehouse(wh["id"], manager_headers), 200)
        assert wh_after["abnormal_event_count_24h"] == before["abnormal_event_count_24h"] + 1
        assert wh_after["recall_count_open"] == before["recall_count_open"] + 1
        # Reservations released
        inv_after = get_inventory_row(wh["id"], b["id"], lot["id"])
        assert inv_after["reserved_units"] == 0


class TestNearExpiryAndExpiry:
    def test_near_expiry_at_30_days_inclusive(self, api, manager_headers, staff_headers):
        """PRD §3.9: "When that value is at most 30, the lot transitions to
        NEAR_EXPIRY (the threshold is inclusive, so a lot exactly 30 days
        from expiry is NEAR_EXPIRY)."

        # difficulty: boundary_precision_check/near_expiry_days_inclusive_boundary
        Claim: a lot exactly 30 days from expiry transitions to NEAR_EXPIRY
        on /_clock/advance.
        """
        wh = create_warehouse(advance_clock_to=False)  # at epoch
        # Create lot that will be exactly 30 days from expiry on advance
        lot = create_lot(
            wh["id"],
            lot_code="LOT_30D",
            manufacture_date="1970-01-01T00:00:00.000Z",
            expiry_date="2025-01-31T00:00:00.000Z",
        )
        # Advance to 2025-01-01 → expiry is exactly 30 days away
        validate_success(api.advance_clock(
            create_clock_advance_payload(wh["id"], "2025-01-01T00:00:00.000Z"),
            manager_headers), 200)
        lot_after = validate_success(api.get_lot(wh["id"], lot["id"], staff_headers), 200)
        assert lot_after["status"] == "NEAR_EXPIRY"

    def test_lot_31_days_from_expiry_remains_active(self, api, manager_headers, staff_headers):
        """PRD §3.9: "Otherwise the lot remains ACTIVE." (i.e., when
        days_to_expiry > 30)

        # difficulty: boundary_precision_check/near_expiry_days_inclusive_boundary
        Claim: a lot 31 days from expiry remains ACTIVE.
        """
        wh = create_warehouse(advance_clock_to=False)
        lot = create_lot(
            wh["id"],
            lot_code="LOT_31D",
            manufacture_date="1970-01-01T00:00:00.000Z",
            expiry_date="2025-02-01T00:00:00.000Z",
        )
        validate_success(api.advance_clock(
            create_clock_advance_payload(wh["id"], "2025-01-01T00:00:00.000Z"),
            manager_headers), 200)
        lot_after = validate_success(api.get_lot(wh["id"], lot["id"], staff_headers), 200)
        assert lot_after["status"] == "ACTIVE"

    def test_expired_lot_moves_to_expired_when_clock_passes_expiry(self, api, manager_headers, staff_headers):
        """PRD §3.9: "When that value is strictly less than 0, the lot
        transitions directly to EXPIRED (skipping NEAR_EXPIRY if the clock
        leapt past expiry)."

        Claim: clock advances past expiry → lot status becomes EXPIRED.
        """
        wh = create_warehouse(advance_clock_to=False)
        lot = create_lot(
            wh["id"],
            lot_code="LOT_EXP",
            manufacture_date="1970-01-01T00:00:00.000Z",
            expiry_date="2024-06-01T00:00:00.000Z",
        )
        validate_success(api.advance_clock(
            create_clock_advance_payload(wh["id"], "2025-01-01T00:00:00.000Z"),
            manager_headers), 200)
        lot_after = validate_success(api.get_lot(wh["id"], lot["id"], staff_headers), 200)
        assert lot_after["status"] == "EXPIRED"


class TestDispose:
    def test_dispose_recalled_lot(self, api, manager_headers, staff_headers):
        """PRD §3.9: "A floor staff caller may dispose a lot whose status
        is EXPIRED, RECALLED, or QUARANTINED, taking it to the terminal
        DISPOSED. ... On a successful dispose, every inventory row for
        the lot has its qty_units set to 0, every affected bin recomputes
        used_volume_cm3, used_weight_g, remaining_volume_cm3, and
        remaining_weight_g, and — when the lot was leaving RECALLED —
        recall_count_open is decreased by 1 and risk_score and posture
        are recomputed."

        # difficulty: compensating_invariant/qty_units_invariant_putaway_then_dispose
        Claim: putaway 50 units then recall+dispose returns total qty_units
        to 0; recall_count_open is decremented.
        """
        wh, b, lot = setup_warehouse_with_inventory(units=50, sku="PEN")
        before_total = sum_inventory_qty_for_lot(wh["id"], lot["id"])
        assert before_total == 50
        # Recall
        validate_success(api.recall_lot(
            wh["id"], lot["id"], create_recall_payload("SUPPLIER_RECALL"),
            manager_headers), 200)
        wh_after_recall = validate_success(api.get_warehouse(wh["id"], manager_headers), 200)
        recall_count_after_recall = wh_after_recall["recall_count_open"]
        # Dispose
        disposed = validate_success(api.dispose_lot(
            wh["id"], lot["id"], staff_headers), 200)
        assert disposed["status"] == "DISPOSED"
        after_total = sum_inventory_qty_for_lot(wh["id"], lot["id"])
        assert after_total == 0
        # Bin recomputed
        bin_after = validate_success(api.get_bin(wh["id"], b["id"], staff_headers), 200)
        assert bin_after["used_volume_cm3"] == 0
        assert bin_after["used_weight_g"] == 0
        # Recall count decremented
        wh_final = validate_success(api.get_warehouse(wh["id"], manager_headers), 200)
        assert wh_final["recall_count_open"] == recall_count_after_recall - 1

    def test_dispose_blocked_by_open_pick_tasks(self, api, manager_headers, staff_headers):
        """PRD §2.6 rule 18: "Disposing a lot is rejected with
        ERR_LOT_HAS_OPEN_PICKS while at least one pick task referencing
        the lot is in CREATED or PICKING."

        Claim: dispose on a lot with open CREATED pick tasks → ERR_LOT_HAS_OPEN_PICKS.
        Note: PRD §3.9 requires the lot be EXPIRED, RECALLED, or QUARANTINED
        before dispose. We also need an open CREATED pick task referencing
        the lot. After recall, all CREATED/PICKING pick tasks are cascaded
        to FAILED, so a CREATED pick task can't survive recall. We therefore
        use QUARANTINED which doesn't cascade pick task failures.
        """
        wh = create_warehouse(advance_clock_to="2025-01-01T00:00:00.000Z")
        # Need a RETURNS bin for quarantine
        ret_bin = create_bin(wh["id"], bin_code="RTN", zone="RETURNS",
                            capacity_volume_cm3=100000, capacity_weight_g=100000)
        amb_bin = create_bin(wh["id"], bin_code="AMB1", zone="AMBIENT",
                            capacity_volume_cm3=100000, capacity_weight_g=100000)
        # Lot category AMBIENT — putaway goes to amb_bin
        lot = create_lot(wh["id"], sku="PEN", category="AMBIENT")
        putaway_lot_units(wh["id"], lot["id"], 30)
        # Allocate an order so a CREATED pick task exists
        order = create_allocated_order(wh["id"], sku="PEN", qty_units=10,
                                       order_number="ORD-DISP")
        pts = get_pick_tasks_for_order(wh["id"], order["id"])
        assert pts[0]["status"] == "CREATED"
        # Take the lot to QUARANTINED via inbound shipment failure path
        # Create a separate FAILED shipment of the same lot, quarantine it → lot QUARANTINED
        from test_helpers import (create_inbound_shipment_payload,
                                  create_complete_inspection_payload)
        sh = validate_success(api.create_inbound_shipment(
            wh["id"], create_inbound_shipment_payload(lot["id"], 20, asn_number="ASN-Q"),
            staff_headers), 201)
        validate_success(api.start_inspection(wh["id"], sh["id"], staff_headers), 200)
        # FAIL: defects=1, sample=8 → 0.125 > 0.025
        validate_success(api.complete_inspection(
            wh["id"], sh["id"],
            create_complete_inspection_payload(lot["id"], 20, 1),
            staff_headers), 200)
        validate_success(api.quarantine_inbound_shipment(
            wh["id"], sh["id"], staff_headers), 200)
        # Lot now QUARANTINED. Try to dispose — should fail because pt is still CREATED.
        validate_error(api.dispose_lot(
            wh["id"], lot["id"], staff_headers), "ERR_LOT_HAS_OPEN_PICKS")


class TestDisposeForbiddenStates:
    def test_dispose_active_lot_invalid_state(self, api, staff_headers):
        """PRD §3.9: "A floor staff caller may dispose a lot whose status
        is EXPIRED, RECALLED, or QUARANTINED"

        Claim: dispose on ACTIVE lot → ERR_INVALID_STATE.
        """
        wh = create_warehouse()
        lot = create_lot(wh["id"])
        # ACTIVE → not allowed for dispose
        validate_error(api.dispose_lot(
            wh["id"], lot["id"], staff_headers), "ERR_INVALID_STATE")
