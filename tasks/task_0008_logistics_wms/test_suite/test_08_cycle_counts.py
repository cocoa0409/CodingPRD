"""Cycle counts: schedule (freeze bin), submit, approve (segregation of duties),
dispute, and warehouse-level shrinkage roll-up."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    create_cycle_count_payload, create_submit_count_payload,
    create_warehouse, create_bin, create_lot, putaway_lot_units,
    setup_warehouse_with_inventory, get_inventory_row,
    setup_cycle_count_in_state,
    TEST_USERS, NON_EXISTENT_UUID,
    STAFF_USER_ID, STAFF_USER_ID_ALT,
    AUDITOR_USER_ID, AUDITOR_USER_ID_ALT,
    make_staff_headers, make_auditor_headers,
)


class TestScheduleCycleCount:
    def test_schedule_cycle_count_freezes_bin(self, api, staff_headers, manager_headers):
        """PRD §3.8: "Scheduling a cycle count creates the entity in status
        SCHEDULED, captures book_qty as a snapshot of the current
        Inventory.qty_units for that pair, sets scheduled_at to the
        warehouse's clock_now, and freezes the bin: the bin's status flips
        from ACTIVE to FROZEN and frozen_by_cycle_count_id is set to the
        new cycle-count id."

        Claim: POST /cycle_counts → SCHEDULED + bin FROZEN with frozen_by_cycle_count_id.
        """
        wh, b, lot = setup_warehouse_with_inventory(units=30, sku="PEN")
        cc = validate_success(api.create_cycle_count(
            wh["id"], create_cycle_count_payload(b["id"], lot["id"]),
            staff_headers), 201)
        assert cc["status"] == "SCHEDULED"
        assert cc["book_qty"] == 30
        bin_after = validate_success(api.get_bin(wh["id"], b["id"], staff_headers), 200)
        assert bin_after["status"] == "FROZEN"
        assert bin_after["frozen_by_cycle_count_id"] == cc["id"]

    def test_schedule_cycle_count_on_frozen_bin_rejected(self, api, staff_headers, manager_headers):
        """PRD §2.9: "Two callers attempting to schedule a cycle count on
        the same (bin_id, lot_id) pair simultaneously serialize on
        Bin.frozen_by_cycle_count_id: at most one cycle count can hold a
        bin's freeze at a time, and the second caller is rejected with
        ERR_BIN_FROZEN and HTTP status 409."

        # difficulty: resource_temporal_overlap/bin_freeze_per_bin_closed_open_interval
        Claim: a second cycle count scheduled on the same bin while the
        first is open → ERR_BIN_FROZEN.
        """
        wh, b, lot = setup_warehouse_with_inventory(units=30, sku="PEN")
        validate_success(api.create_cycle_count(
            wh["id"], create_cycle_count_payload(b["id"], lot["id"]),
            staff_headers), 201)
        # Second attempt
        validate_error(api.create_cycle_count(
            wh["id"], create_cycle_count_payload(b["id"], lot["id"]),
            staff_headers), "ERR_BIN_FROZEN")

    def test_schedule_cycle_count_on_different_bins_allowed(self, api, staff_headers, manager_headers):
        """PRD §2.9: same sentence as above — "at most one cycle count can
        hold a bin's freeze at a time". This is per-bin scope.

        # difficulty: resource_temporal_overlap/bin_freeze_per_bin_closed_open_interval
        Claim: scheduling cycle counts on two different bins concurrently is
        allowed (the freeze is per-bin, not warehouse-wide).
        """
        wh = create_warehouse()
        bin_a = create_bin(wh["id"], bin_code="BIN-A", zone="AMBIENT",
                          capacity_volume_cm3=100000, capacity_weight_g=100000)
        bin_b = create_bin(wh["id"], bin_code="BIN-B", zone="AMBIENT",
                          capacity_volume_cm3=100000, capacity_weight_g=100000)
        lot = create_lot(wh["id"], sku="PEN", category="AMBIENT")
        putaway_lot_units(wh["id"], lot["id"], 30)
        # Some inventory will be in bin_a (by DISTANCE_OPTIMIZED or whichever was picked).
        # We need to know which bin holds the inventory; use list_inventory.
        from test_helpers import get_inventory_row
        inv_a = get_inventory_row(wh["id"], bin_a["id"], lot["id"])
        inv_b = get_inventory_row(wh["id"], bin_b["id"], lot["id"])
        # The lot is in exactly one bin; schedule cycle count on that bin first
        present_bin = bin_a if (inv_a and inv_a["qty_units"] > 0) else bin_b
        absent_bin = bin_b if present_bin == bin_a else bin_a
        # Schedule on present_bin
        validate_success(api.create_cycle_count(
            wh["id"], create_cycle_count_payload(present_bin["id"], lot["id"]),
            staff_headers), 201)
        # Schedule on absent_bin — different bin should succeed
        # The lot has 0 there → book_qty=0; that's fine
        cc2 = validate_success(api.create_cycle_count(
            wh["id"], create_cycle_count_payload(absent_bin["id"], lot["id"]),
            staff_headers), 201)
        assert cc2["status"] == "SCHEDULED"


class TestSubmitCount:
    def test_submit_count_match_to_reconciled(self, api, staff_headers):
        """PRD §3.8: "When counted_qty equals book_qty, the cycle count
        moves from COUNTING to RECONCILED: variance_units and
        variance_value_cents are both 0, the system records the caller's
        X-User-ID as submitted_by_user_id, and the bin is unfrozen —
        status returns to ACTIVE and frozen_by_cycle_count_id is cleared."

        Claim: counted_qty == book_qty → RECONCILED, variance fields 0,
        bin unfrozen.
        """
        wh, b, lot = setup_warehouse_with_inventory(units=30, sku="PEN")
        cc = validate_success(api.create_cycle_count(
            wh["id"], create_cycle_count_payload(b["id"], lot["id"]),
            staff_headers), 201)
        validate_success(api.start_cycle_count(wh["id"], cc["id"], staff_headers), 200)
        result = validate_success(api.submit_cycle_count(
            wh["id"], cc["id"], create_submit_count_payload(30),
            staff_headers), 200)
        assert result["status"] == "RECONCILED"
        assert result["variance_units"] == 0
        assert result["variance_value_cents"] == 0
        bin_after = validate_success(api.get_bin(wh["id"], b["id"], staff_headers), 200)
        assert bin_after["status"] == "ACTIVE"
        assert bin_after["frozen_by_cycle_count_id"] is None

    def test_submit_count_mismatch_to_variance_found(self, api, staff_headers, manager_headers):
        """PRD §3.8: "When counted_qty differs from book_qty, the cycle
        count moves from COUNTING to VARIANCE_FOUND: variance_units is
        computed as counted_qty minus book_qty (a signed integer),
        variance_value_cents is computed as the absolute value of
        variance_units multiplied by the lot's unit_value_cents and
        rounded half-up to integer cents, the system records
        submitted_by_user_id, and abnormal_event_count_24h on the
        warehouse is increased by 1. The bin remains frozen pending audit."

        Claim: counted_qty != book_qty → VARIANCE_FOUND with computed
        variance fields; abnormal counter incremented; bin still FROZEN.
        """
        wh, b, lot = setup_warehouse_with_inventory(
            units=100, sku="PEN", unit_value_cents=100)
        before = validate_success(api.get_warehouse(wh["id"], manager_headers), 200)
        cc = validate_success(api.create_cycle_count(
            wh["id"], create_cycle_count_payload(b["id"], lot["id"]),
            staff_headers), 201)
        validate_success(api.start_cycle_count(wh["id"], cc["id"], staff_headers), 200)
        result = validate_success(api.submit_cycle_count(
            wh["id"], cc["id"], create_submit_count_payload(95),  # variance: -5
            staff_headers), 200)
        assert result["status"] == "VARIANCE_FOUND"
        assert result["variance_units"] == -5
        # |-5| * 100 = 500 cents
        assert result["variance_value_cents"] == 500
        bin_after = validate_success(api.get_bin(wh["id"], b["id"], staff_headers), 200)
        assert bin_after["status"] == "FROZEN"  # still frozen pending audit
        after = validate_success(api.get_warehouse(wh["id"], manager_headers), 200)
        assert after["abnormal_event_count_24h"] == before["abnormal_event_count_24h"] + 1

    def test_submit_count_negative_invalid_input(self, api, staff_headers):
        """PRD §3.8: "Submission of the count carries a counted_qty that
        must be a non-negative integer (negative values are rejected with
        ERR_INVALID_INPUT)."

        Claim: counted_qty < 0 → ERR_INVALID_INPUT.
        """
        wh, b, lot = setup_warehouse_with_inventory(units=30, sku="PEN")
        cc = validate_success(api.create_cycle_count(
            wh["id"], create_cycle_count_payload(b["id"], lot["id"]),
            staff_headers), 201)
        validate_success(api.start_cycle_count(wh["id"], cc["id"], staff_headers), 200)
        validate_error(api.submit_cycle_count(
            wh["id"], cc["id"], create_submit_count_payload(-1),
            staff_headers), "ERR_INVALID_INPUT")


class TestApproveAdjustment:
    def test_approve_adjustment_writes_inventory_and_shrinkage(self, api, manager_headers):
        """PRD §3.8: "On approval the cycle count moves from VARIANCE_FOUND
        to ADJUSTED: Inventory.qty_units for the (bin_id, lot_id) pair is
        overwritten with counted_qty; the bin recomputes used_volume_cm3
        and used_weight_g; approved_by_user_id is set to the approver's
        X-User-ID and approved_at is set to clock_now; the bin is unfrozen;
        and shrinkage_value_30d_cents on the warehouse is increased by
        the cycle count's variance_value_cents (so long as the approval
        falls within the rolling 30-day window)."

        # difficulty: transitive_cascade/cycle_count_adjust_cascade_depth_3
        Claim: approve on VARIANCE_FOUND → ADJUSTED; Inventory.qty_units
        overwritten; bin used_volume/weight recomputed; warehouse shrinkage
        increased; bin unfrozen.
        """
        # Use distinct user-ids so SoD passes
        wh = create_warehouse(advance_clock_to="2025-01-01T00:00:00.000Z")
        b = create_bin(wh["id"], bin_code="BCC", zone="AMBIENT",
                      capacity_volume_cm3=10000, capacity_weight_g=10000)
        lot = create_lot(wh["id"], sku="PEN", category="AMBIENT",
                        unit_volume_cm3=20, unit_weight_g=10, unit_value_cents=100)
        putaway_lot_units(wh["id"], lot["id"], 100)
        # Schedule + start + submit (counted=95) by USER_S1
        staff_s1 = make_staff_headers(STAFF_USER_ID)
        cc = validate_success(api.create_cycle_count(
            wh["id"], create_cycle_count_payload(b["id"], lot["id"]),
            staff_s1), 201)
        validate_success(api.start_cycle_count(wh["id"], cc["id"], staff_s1), 200)
        cc_var = validate_success(api.submit_cycle_count(
            wh["id"], cc["id"], create_submit_count_payload(95),
            staff_s1), 200)
        assert cc_var["status"] == "VARIANCE_FOUND"
        assert cc_var["submitted_by_user_id"] == STAFF_USER_ID
        # Approve as different user
        auditor_a1 = make_auditor_headers(AUDITOR_USER_ID)
        result = validate_success(api.approve_cycle_count(
            wh["id"], cc["id"], auditor_a1), 200)
        assert result["status"] == "ADJUSTED"
        assert result["approved_by_user_id"] == AUDITOR_USER_ID
        # Inventory updated
        inv_after = get_inventory_row(wh["id"], b["id"], lot["id"])
        assert inv_after["qty_units"] == 95
        # Bin recomputed
        bin_after = validate_success(api.get_bin(wh["id"], b["id"], manager_headers), 200)
        assert bin_after["used_volume_cm3"] == 95 * 20
        assert bin_after["used_weight_g"] == 95 * 10
        assert bin_after["status"] == "ACTIVE"
        assert bin_after["frozen_by_cycle_count_id"] is None
        # Warehouse shrinkage
        wh_after = validate_success(api.get_warehouse(wh["id"], manager_headers), 200)
        assert wh_after["shrinkage_value_30d_cents"] == 500  # |−5| * 100 cents

    def test_approve_segregation_of_duties_rejected(self, api, manager_headers):
        """PRD §3.8: "Approval is exclusive to the Auditor role and enforces
        segregation of duties: the approver's X-User-ID must differ from
        the cycle count's submitted_by_user_id, otherwise the response is
        ERR_SEGREGATION_OF_DUTIES."

        Claim: when the approver's X-User-ID equals the submitted_by_user_id,
        approve → ERR_SEGREGATION_OF_DUTIES (403).
        """
        # Setup: same user submits and tries to approve.
        # Note: submission can be made by an Auditor too; PRD §4 lists
        # /cycle_counts/{id}/submit_count as accessible to staff and auditor.
        wh, b, lot = setup_warehouse_with_inventory(units=30, sku="PEN")
        # Submit as auditor with id A1; then try to approve as same auditor
        same_id = "shared-auditor-id"
        auditor_self = make_auditor_headers(same_id)
        cc = validate_success(api.create_cycle_count(
            wh["id"], create_cycle_count_payload(b["id"], lot["id"]),
            auditor_self), 201)
        validate_success(api.start_cycle_count(wh["id"], cc["id"], auditor_self), 200)
        validate_success(api.submit_cycle_count(
            wh["id"], cc["id"], create_submit_count_payload(25),  # variance
            auditor_self), 200)
        # Now approve as the SAME user → SoD violation
        validate_error(api.approve_cycle_count(
            wh["id"], cc["id"], auditor_self), "ERR_SEGREGATION_OF_DUTIES")

    def test_approve_only_by_auditor_role(self, api, staff_headers):
        """PRD §3.8: "Approval is exclusive to the Auditor role"
        PRD §2.1: ERR_FORBIDDEN for unauthorized role.

        Claim: a staff caller (not Auditor) trying to approve_adjustment
        → ERR_FORBIDDEN.
        """
        wh, b, lot = setup_warehouse_with_inventory(units=30, sku="PEN")
        # Submit by staff
        cc = validate_success(api.create_cycle_count(
            wh["id"], create_cycle_count_payload(b["id"], lot["id"]),
            staff_headers), 201)
        validate_success(api.start_cycle_count(wh["id"], cc["id"], staff_headers), 200)
        validate_success(api.submit_cycle_count(
            wh["id"], cc["id"], create_submit_count_payload(25),
            staff_headers), 200)
        # Approve by ANOTHER staff (not auditor)
        from test_helpers import make_staff_headers
        other_staff = make_staff_headers("staff-other-id")
        validate_error(api.approve_cycle_count(
            wh["id"], cc["id"], other_staff), "ERR_FORBIDDEN")


class TestDispute:
    def test_dispute_variance_to_disputed_inventory_unchanged(self, api, staff_headers):
        """PRD §3.8: "Disputing a VARIANCE_FOUND cycle count is open to
        staff or auditors, moves the cycle count to DISPUTED, leaves
        inventory unchanged, and unfreezes the bin."

        Claim: dispute on VARIANCE_FOUND → DISPUTED; Inventory unchanged;
        bin unfrozen.
        """
        wh, b, lot = setup_warehouse_with_inventory(
            units=100, sku="PEN", unit_value_cents=100)
        cc = validate_success(api.create_cycle_count(
            wh["id"], create_cycle_count_payload(b["id"], lot["id"]),
            staff_headers), 201)
        validate_success(api.start_cycle_count(wh["id"], cc["id"], staff_headers), 200)
        validate_success(api.submit_cycle_count(
            wh["id"], cc["id"], create_submit_count_payload(80),  # variance -20
            staff_headers), 200)
        result = validate_success(api.dispute_cycle_count(
            wh["id"], cc["id"], staff_headers), 200)
        assert result["status"] == "DISPUTED"
        # Inventory unchanged
        inv_after = get_inventory_row(wh["id"], b["id"], lot["id"])
        assert inv_after["qty_units"] == 100
        # Bin unfrozen
        bin_after = validate_success(api.get_bin(wh["id"], b["id"], staff_headers), 200)
        assert bin_after["status"] == "ACTIVE"
