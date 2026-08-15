"""Order completion cascade and coupling stock accounting
(PRD §3.2, §3.5): final pricing, stock decrement, asset installation,
and reservation reconciliation."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_instant_equal,
    build_assembly_order,
    cancel_assembly_order,
    create_assembly_order,
    create_coupling,
    create_customer,
    create_equipment_asset,
    create_reel,
    complete_assembly_order,
    confirm_assembly_order,
    get_coupling,
    record_pressure_test,
    tag_assembly_order,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCompletionCascade:
    def _setup_tagged_order_on_asset(self):
        cust = create_customer(name="CascadeCo", inspection_interval_days=60)
        asset = create_equipment_asset(cust["id"], asset_tag="PR-01",
                                       machine_type="press")
        reel = create_reel(hose_sku="PARK-387-8K", hose_diameter_in=0.5,
                           working_pressure_psi=3000, price_per_meter_cents=800,
                           initial_length_mm=50000)
        coup = create_coupling(coupling_sku="1CA43-8-8K", size_in=0.5,
                               unit_price_cents=1200, initial_on_hand_qty=10)
        order = create_assembly_order(
            cust["id"], reel["id"],
            equipment_asset_id=asset["id"],
            cut_length_mm=5000, required_working_pressure_psi=2000,
            crimp_diameter_spec_mm=25.0, estimated_labor_minutes=30,
            lines=[{"coupling_id": coup["id"], "quantity": 2}])
        confirm_assembly_order(order["id"])
        build_assembly_order(order["id"], measured_crimp_diameter_mm=25.1,
                             actual_labor_minutes=40)
        record_pressure_test(order["id"], test_pressure_psi=4000, result="PASSED")
        tag_assembly_order(order["id"], "TAG-CASC1")
        return cust, asset, reel, coup, order

    def test_completion_sets_final_price_and_ships_couplings(self, api):
        """PRD §3.5: "The moment of completion computes `final_total_cents` using the formula of §3.3 with `actual_labor_minutes` in place of the estimate, and the pinned rounding order applies unchanged. For each line, the coupling's `on_hand_qty` is decremented by the line's `quantity`, and the order's reservations are released so `reserved_qty` and `available_qty` recompute across the catalog."

        Order COMPLETED with final 4000 + 2400 + 6000 = 12400; coupling goes
        on_hand 10 -> 8 and reserved 2 -> 0.

        Design: Difficulty/transitive_cascade/order_completion_cascade_depth3
        """
        cust, asset, reel, coup, order = self._setup_tagged_order_on_asset()
        coup_mid = get_coupling(coup["id"])
        assert coup_mid["reserved_qty"] == 2, "reservation held while CONFIRMED+"

        completed = complete_assembly_order(order["id"])
        assert completed["status"] == "COMPLETED"
        assert completed["final_total_cents"] == 12400

        coup_after = get_coupling(coup["id"])
        assert coup_after["on_hand_qty"] == 8
        assert coup_after["reserved_qty"] == 0
        assert coup_after["available_qty"] == 8

    def test_completion_stamps_asset_and_recomputes_customer_scores(self, api):
        """PRD §3.5: "When the order names an `equipment_asset_id`, that asset must still be `ACTIVE` — completing onto a decommissioned machine is rejected with `ERR_ASSET_NOT_ACTIVE` — and completion then stamps the asset's `installed_assembly_order_id` with this order, overwrites its `installed_at` with the current logical clock, recomputes its `next_due_date` and `compliance_posture`, and finally recomputes the customer's `compliance_score_strict`, `compliance_score_projected`, and `program_status`."
        PRD §2.5: "Before the clock has ever been set, it reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time on its own."
        PRD §3.7: "An asset's `next_due_date` is its base date plus the customer's `inspection_interval_days`, where the base is `last_passed_inspection_at` when a pass exists and `installed_at` otherwise; when neither exists, the date is null."

        Install at the 2026-08-01 logical clock with a 60-day interval ->
        next_due_date 2026-09-30, posture COMPLIANT, strict score 100.00.

        Design: Difficulty/transitive_cascade/order_completion_cascade_depth3
        """
        cust, asset, reel, coup, order = self._setup_tagged_order_on_asset()
        complete_assembly_order(order["id"])

        asset_after = validate_success(
            api.get_equipment_asset(asset["id"],
                                    TEST_USERS["shop_manager_headers"]), 200)
        assert asset_after["installed_assembly_order_id"] == order["id"]
        assert_instant_equal(asset_after["installed_at"], "2026-08-01T00:00:00Z")
        assert_instant_equal(asset_after["next_due_date"], "2026-09-30T00:00:00Z")
        assert asset_after["compliance_posture"] == "COMPLIANT"

        cust_after = validate_success(
            api.get_customer(cust["id"], TEST_USERS["shop_manager_headers"]), 200)
        assert cust_after["compliance_score_strict"] == pytest.approx(100.00, abs=0.005)


class TestCouplingUnitConservation:
    def _setup(self, api):
        cust = create_customer(name="UnitCo")
        reel = create_reel(hose_sku="PARK-387-8U", hose_diameter_in=0.5,
                           working_pressure_psi=3000, price_per_meter_cents=800,
                           initial_length_mm=50000)
        coup = create_coupling(coupling_sku="1CA43-8-8U", size_in=0.5,
                               unit_price_cents=1200, initial_on_hand_qty=10)
        receipt = api.create_coupling_receipt(coup["id"], {"quantity": 5},
                                              TEST_USERS["shop_manager_headers"])
        validate_success(receipt, 200)

        def make_order(qty):
            order = create_assembly_order(
                cust["id"], reel["id"], cut_length_mm=1000,
                required_working_pressure_psi=2000, crimp_diameter_spec_mm=25.0,
                estimated_labor_minutes=10,
                lines=[{"coupling_id": coup["id"], "quantity": qty}])
            confirm_assembly_order(order["id"])
            return order

        o1 = make_order(3)
        o2 = make_order(4)
        return cust, reel, coup, o1, o2

    def test_reservation_holds_then_completion_ships_units(self, api):
        """PRD §3.2: "Stock visibility runs through two derived counters: `reserved_qty` is the sum of line quantities across every assembly order currently in `CONFIRMED`, `BUILT`, `TEST_PASSED`, `TEST_FAILED`, `REWORK`, or `TAGGED` status, and `available_qty` is what remains of `on_hand_qty` after reservations are subtracted."
        PRD §3.5: "The moment of completion computes `final_total_cents` using the formula of §3.3 with `actual_labor_minutes` in place of the estimate, and the pinned rounding order applies unchanged. For each line, the coupling's `on_hand_qty` is decremented by the line's `quantity`, and the order's reservations are released so `reserved_qty` and `available_qty` recompute across the catalog."

        10 initial + 5 receipt = 15 on hand; O1 qty 3 + O2 qty 4 reserved -> 7;
        completing O1 ships 3 (on_hand 12) while O2's 4 stay reserved.

        Design: Difficulty/compensating_invariant/coupling_unit_conservation
        """
        cust, reel, coup, o1, o2 = self._setup(api)
        coup_mid = get_coupling(coup["id"])
        assert coup_mid["on_hand_qty"] == 15
        assert coup_mid["reserved_qty"] == 7
        assert coup_mid["available_qty"] == 8

        build_assembly_order(o1["id"], measured_crimp_diameter_mm=25.0,
                             actual_labor_minutes=10)
        record_pressure_test(o1["id"], test_pressure_psi=4000, result="PASSED")
        tag_assembly_order(o1["id"], "TAG-UNIT1")
        complete_assembly_order(o1["id"])

        coup_after = get_coupling(coup["id"])
        assert coup_after["on_hand_qty"] == 12
        assert coup_after["reserved_qty"] == 4, "O2's reservation survives O1 completing"
        assert coup_after["available_qty"] == 8

    def test_conservation_holds_after_cancel_releases_reservation(self, api):
        """PRD §3.5: "From `CONFIRMED`, the reel is made whole: its `remaining_length_mm` is credited back the cut length plus the order's `scrap_charged_mm`, its `scrap_length_mm` is reduced by that same scrapped amount, its status is recomputed — so even a `DEPLETED` reel can climb back to `LOW` or `AVAILABLE` — and every coupling reservation is released."
        PRD §3.2: "Additional stock arrives through receipts, each of which adds its `quantity` to `on_hand_qty`."

        After O1 completes (3 shipped) and O2 cancels (reservation of 4 released):
        on_hand 12 + shipped 3 == 15 received; reserved 0; available 12.

        Design: Difficulty/compensating_invariant/coupling_unit_conservation
        """
        cust, reel, coup, o1, o2 = self._setup(api)
        build_assembly_order(o1["id"], measured_crimp_diameter_mm=25.0,
                             actual_labor_minutes=10)
        record_pressure_test(o1["id"], test_pressure_psi=4000, result="PASSED")
        tag_assembly_order(o1["id"], "TAG-UNIT1")
        complete_assembly_order(o1["id"])

        cancel_assembly_order(o2["id"])

        coup_final = get_coupling(coup["id"])
        assert coup_final["on_hand_qty"] == 12
        assert coup_final["reserved_qty"] == 0
        assert coup_final["available_qty"] == 12
        assert coup_final["on_hand_qty"] + 3 == 15, (
            "on_hand + shipped must equal total received (10 initial + 5 receipt)")


class TestReservedQtyReconciliation:
    def test_reserved_qty_reconciles_on_confirm_and_cancel(self, api):
        """PRD §3.2: "Stock visibility runs through two derived counters: `reserved_qty` is the sum of line quantities across every assembly order currently in `CONFIRMED`, `BUILT`, `TEST_PASSED`, `TEST_FAILED`, `REWORK`, or `TAGGED` status, and `available_qty` is what remains of `on_hand_qty` after reservations are subtracted."
        PRD §3.5: "From `CONFIRMED`, the reel is made whole: its `remaining_length_mm` is credited back the cut length plus the order's `scrap_charged_mm`, its `scrap_length_mm` is reduced by that same scrapped amount, its status is recomputed — so even a `DEPLETED` reel can climb back to `LOW` or `AVAILABLE` — and every coupling reservation is released."

        reserved_qty tracks the lifecycle exactly: 0 -> 3 at confirm, back to 0
        at cancel; available_qty mirrors it (8 -> 5 -> 8).

        Design: Corner/cross_cutting_layers/reserved_qty_reconciles_on_confirm_and_cancel
        """
        cust = create_customer(name="ReconCo")
        reel = create_reel(hose_sku="PARK-387-8RC", hose_diameter_in=0.5,
                           working_pressure_psi=3000, price_per_meter_cents=800,
                           initial_length_mm=50000)
        coup = create_coupling(coupling_sku="1CA43-8-8R", size_in=0.5,
                               unit_price_cents=1200, initial_on_hand_qty=8)
        order = create_assembly_order(
            cust["id"], reel["id"], cut_length_mm=1000,
            required_working_pressure_psi=2000, crimp_diameter_spec_mm=25.0,
            estimated_labor_minutes=10,
            lines=[{"coupling_id": coup["id"], "quantity": 3}])

        confirm_assembly_order(order["id"])
        mid = get_coupling(coup["id"])
        assert mid["reserved_qty"] == 3
        assert mid["available_qty"] == 5

        cancel_assembly_order(order["id"])
        after = get_coupling(coup["id"])
        assert after["reserved_qty"] == 0
        assert after["available_qty"] == 8
        assert after["on_hand_qty"] == 8


class TestCouplingReceiptAndAvailability:
    def test_coupling_computed_available_after_receipt(self, api):
        """PRD §3.2: "Additional stock arrives through receipts, each of which adds its `quantity` to `on_hand_qty`."
        PRD §3.2: "Stock visibility runs through two derived counters: `reserved_qty` is the sum of line quantities across every assembly order currently in `CONFIRMED`, `BUILT`, `TEST_PASSED`, `TEST_FAILED`, `REWORK`, or `TAGGED` status, and `available_qty` is what remains of `on_hand_qty` after reservations are subtracted."

        Receipt of 6 onto an initial 4 with no reservations -> on_hand 10,
        reserved 0, available 10.

        Design: Corner/entities/coupling_computed_available_after_receipt
        """
        coup = create_coupling(coupling_sku="1CA43-8-8A", size_in=0.5,
                               unit_price_cents=1200, initial_on_hand_qty=4)
        res = api.create_coupling_receipt(coup["id"], {"quantity": 6},
                                          TEST_USERS["shop_manager_headers"])
        updated = validate_success(res, 200)
        assert updated["on_hand_qty"] == 10
        assert updated["reserved_qty"] == 0
        assert updated["available_qty"] == 10


class TestCouplingStockAtConfirm:
    def test_insufficient_coupling_stock_at_confirm(self, api):
        """PRD §3.3: "Sixth and last, every line's `quantity` must fit within its coupling's `available_qty` at confirm time, or the confirm fails with `ERR_INSUFFICIENT_COUPLING_STOCK`."

        Line quantity 5 exceeds available 2 -> ERR_INSUFFICIENT_COUPLING_STOCK (422);
        no partial reservation is taken.

        Design: Corner/validations/insufficient_coupling_stock_at_confirm
        """
        cust = create_customer(name="StockCo")
        reel = create_reel(hose_sku="PARK-387-8ST", hose_diameter_in=0.5,
                           working_pressure_psi=3000, price_per_meter_cents=800,
                           initial_length_mm=50000)
        coup = create_coupling(coupling_sku="1CA43-8-8S", size_in=0.5,
                               unit_price_cents=1200, initial_on_hand_qty=2)
        order = create_assembly_order(
            cust["id"], reel["id"], cut_length_mm=1000,
            required_working_pressure_psi=2000, crimp_diameter_spec_mm=25.0,
            estimated_labor_minutes=10,
            lines=[{"coupling_id": coup["id"], "quantity": 5}])

        res = api.confirm_assembly_order(order["id"], {},
                                         TEST_USERS["counter_sales_headers"])
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_COUPLING_STOCK,
                       expected_status=422)

        assert get_coupling(coup["id"])["reserved_qty"] == 0
        after = validate_success(
            api.get_assembly_order(order["id"],
                                   TEST_USERS["counter_sales_headers"]), 200)
        assert after["status"] == "DRAFT"


class TestCouplingLinesReverseReachability:
    def test_coupling_lines_reverse_reachable(self, api):
        """PRD §3.2: "Counter staff can read a coupling together with both derived counters, and can list the order lines referencing a given coupling to see exactly where its stock is committed."
        PRD §3.3: "Every line snapshots the coupling's current `unit_price_cents` at the moment of creation, and each `line_total_cents` is the quantity multiplied by that snapshot — exact integer cents, no rounding required."

        The line for the DRAFT order is listed with quantity 3, snapshot
        unit_price_cents 1200, line_total_cents 3600.

        Design: Corner/endpoints/coupling_lines_reverse_reachable
        """
        cust = create_customer(name="LineCo")
        reel = create_reel(hose_sku="PARK-387-8L", hose_diameter_in=0.5,
                           working_pressure_psi=3000, price_per_meter_cents=800,
                           initial_length_mm=50000)
        coup = create_coupling(coupling_sku="1CA43-8-8L", size_in=0.5,
                               unit_price_cents=1200, initial_on_hand_qty=10)
        order = create_assembly_order(
            cust["id"], reel["id"], cut_length_mm=1000,
            required_working_pressure_psi=2000, crimp_diameter_spec_mm=25.0,
            estimated_labor_minutes=10,
            lines=[{"coupling_id": coup["id"], "quantity": 3}])

        res = api.list_coupling_assembly_lines(
            coup["id"], TEST_USERS["shop_manager_headers"])
        data, _meta = validate_paginated(res)
        assert len(data) == 1
        line = data[0]
        assert line["assembly_order_id"] == order["id"]
        assert line["coupling_id"] == coup["id"]
        assert line["quantity"] == 3
        assert line["unit_price_cents"] == 1200
        assert line["line_total_cents"] == 3600
