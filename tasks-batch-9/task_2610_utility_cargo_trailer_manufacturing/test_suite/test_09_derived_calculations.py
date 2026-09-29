"""Derived calculations: VIN assembly, stock ranking, waivers and counters.

Every figure asserted here is produced by the server from stored state; the
tests supply only the inputs PRD names and then pin the arithmetic and the
ordering PRD 3.7, 3.8 and 3.9 declare.
"""

import pytest

import test_helpers as H
from test_helpers import CERT_OFFICER_2, validate_success


class TestVinAndMcoSequence:
    def test_two_labels_minted_back_to_back_draw_a_plant_wide_sequence(self, api):
        """The counter is plant-wide, so the two VINs differ only in their last digit.

        PRD 3.7: "Issuance draws a `vin_sequence` from a **plant-wide monotonic
        counter**. The counter starts at 1 and advances by one for every label
        issued."
        PRD 3.7: "The `vin` is exactly 17 characters, assembled left to right from
        nine pieces."

        Design: Corner/calculations/calc_vin_and_mco_sequence_is_plant_wide_and_composed_field_by_field
        """
        plant = H.setup_plant(api)
        first = H.unit_at_road_test_passed(plant, api, "SN-000101", H.JIG_WINDOW_1, H.LANE_WINDOW_1)
        second = H.unit_at_road_test_passed(
            plant, api, "SN-000102", H.JIG_WINDOW_2, H.LANE_WINDOW_2
        )

        label_one = validate_success(
            api.issue_label(first["unit"]["id"], H.label_payload(), headers=CERT_OFFICER_2),
            expected_status=201,
        )
        label_two = validate_success(
            api.issue_label(second["unit"]["id"], H.label_payload(), headers=CERT_OFFICER_2),
            expected_status=201,
        )

        assert label_one["vin_sequence"] == 1
        assert label_one["vin"] == H.VIN_FIRST
        H.assert_vin_composition(
            label_one["vin"], "TA", 2, braked=True, year=2026, sequence=1
        )
        H.assert_mco_number(label_one["mco_number"], 1)
        assert label_two["vin_sequence"] == 2
        assert label_two["vin"] == H.VIN_SECOND
        H.assert_mco_number(label_two["mco_number"], 2)
        assert label_one["gvwr_lbs"] == H.TA_CERTIFIED_GVWR_LBS
        assert label_one["gawr_per_axle_lbs"] == H.TA_GAWR_PER_AXLE_LBS
        assert label_one["tire_size_code"] == "ST205/75R15"
        assert label_one["status"] == H.LabelStatus.ISSUED
        assert label_one["issued_by_user_id"] == H.CERT_OFFICER_2_ID
        unit_one = H.read_unit(api, first["unit"]["id"])
        assert label_one["model_version_pinned"] == unit_one["model_version_pinned"]
        assert unit_one["vin"] == H.VIN_FIRST
        assert unit_one["build_status"] == H.BuildStatus.RELEASED_TO_STOCK
        assert H.read_unit(api, second["unit"]["id"])["vin"] == H.VIN_SECOND


class TestAllocationSelectorRanksByStockAge:
    def test_the_selector_takes_the_trailer_that_reached_stock_first(self, api):
        """A held trailer created and labelled first still loses the ranking.

        PRD 3.8: "Candidates are then ranked on three keys in strict order:
        `released_to_stock_at` ascending first, so the oldest stock trailer is
        allocated first; `created_at` ascending as the tie-break when two trailers
        were released at the same instant; and `serial_number` in ascending
        lexicographic order as the final tie-break."

        Design: Corner/calculations/calc_selector_takes_the_oldest_stocked_unit_not_the_first_created
        """
        plant = H.setup_plant(api)
        held = H.unit_at_road_test_passed(plant, api, "SN-000101", H.JIG_WINDOW_1, H.LANE_WINDOW_1)
        early = H.unit_at_road_test_passed(
            plant, api, "SN-000102", H.JIG_WINDOW_2, H.LANE_WINDOW_2
        )
        option = H.charge_option(
            api,
            held["unit"]["id"],
            option_code="E_TRACK_KIT",
            quantity=3,
            unit_weight_lbs=20,
            unit_price_cents=6650,
            labor_hours=1.0,
        )
        H.issue_label(api, held["unit"]["id"])
        H.set_clock(api, H.CLOCK_AUG_06)
        H.issue_label(api, early["unit"]["id"])
        H.set_clock(api, H.CLOCK_AUG_07)
        H.complete_option(api, option["id"])
        order = H.place_order(api, plant["dealer"]["id"], plant["model"]["id"])

        allocated = H.allocate_order(api, order["id"], plant["dealer"]["id"])

        held_unit = H.read_unit(api, held["unit"]["id"])
        early_unit = H.read_unit(api, early["unit"]["id"])
        H.assert_instant(held_unit["released_to_stock_at"], H.CLOCK_AUG_07)
        H.assert_instant(early_unit["released_to_stock_at"], H.CLOCK_AUG_06)
        assert allocated["allocated_unit_id"] == early["unit"]["id"]
        H.assert_money(allocated["invoice_subtotal_cents"], H.ORDER1_SUBTOTAL_CENTS)
        assert allocated["volume_discount_pct"] == pytest.approx(0.00, abs=0.001)
        H.assert_money(allocated["freight_cents"], H.ORDER1_FREIGHT_CENTS)
        H.assert_money(allocated["invoice_total_cents"], H.ORDER1_TOTAL_CENTS)
        H.assert_money(allocated["floor_plan_draw_cents"], H.ORDER1_DRAW_CENTS)
        assert early_unit["build_status"] == H.BuildStatus.ALLOCATED
        assert early_unit["dealer_order_id"] == order["id"]
        assert held_unit["build_status"] == H.BuildStatus.RELEASED_TO_STOCK
        assert held_unit["dealer_order_id"] is None
        assert held_unit["curb_weight_lbs"] == 2040
        assert held_unit["payload_capacity_lbs"] == 4260


class TestWarrantyFreightWaiver:
    def test_a_parts_subtotal_of_exactly_fifty_thousand_waives_the_warranty_freight(self, api):
        """The waiver is inclusive, so a subtotal landing on 50000 pays no freight.

        PRD 3.9: "Part freight, `freight_cents`, is 0 when `parts_subtotal_cents`
        is 0, is also 0 when `parts_subtotal_cents` is 500 dollars or more — that
        is, 50000 cents or more, the freight waiver — and is otherwise a flat 45
        dollars, or 4500 cents."

        Design: Corner/calculations/calc_warranty_freight_is_waived_at_a_parts_subtotal_of_exactly_fifty_thousand
        """
        plant = H.setup_plant(api)
        staged = H.unit_shipped(plant, api)
        H.set_clock(api, H.CLOCK_SEP_01)
        claim = H.file_claim(
            api,
            staged["unit"]["id"],
            plant["dealer"]["id"],
            complaint_code="FLOORING",
            labor_hours=H.CLAIM_FLOORING_LABOR_HOURS,
            part_lines=[dict(line) for line in H.CLAIM_FLOORING_PART_LINES],
            failure_date=H.CLAIM_FAILURE_DATE_IN_WARRANTY,
        )

        approved = H.review_claim(api, claim["id"], H.ClaimDecision.APPROVE)

        H.assert_money(approved["parts_subtotal_cents"], H.CLAIM_FLOORING_PARTS_SUBTOTAL_CENTS)
        H.assert_money(approved["freight_cents"], 0)
        H.assert_money(approved["labor_cents"], H.CLAIM_FLOORING_LABOR_CENTS)
        assert approved["coverage_variant"] == H.CoverageVariant.IN_WARRANTY_FULL
        assert approved["coverage_factor"] == pytest.approx(1.00, abs=0.01)
        H.assert_money(approved["reimbursement_total_cents"], H.CLAIM_FLOORING_TOTAL_CENTS)
        assert approved["status"] == H.ClaimStatus.APPROVED
        assert approved["part_line_count"] == 1
        assert approved["shipped_line_count"] == 0
        H.assert_money(H.read_dealer(api, plant["dealer"]["id"])["warranty_receivable_cents"], 0)


class TestDemoProgramBypassesTheFloorPlan:
    def test_a_demo_allocation_draws_nothing_on_a_starved_credit_line(self, api):
        """A 1000 cent limit cannot fund the invoice, yet a DEMO allocation is admitted.

        PRD 3.8: "`DEMO` orders draw zero and skip the floor-plan check entirely."

        Design: Corner/calculations/calc_demo_program_draws_zero_and_bypasses_the_floor_plan_admission
        """
        plant = H.setup_plant(api, dealer_overrides={"floor_plan_limit_cents": 1000})
        staged = H.unit_in_stock(plant, api)
        order = H.place_order(
            api, plant["dealer"]["id"], plant["model"]["id"], stocking_program="DEMO"
        )

        allocated = H.allocate_order(api, order["id"], plant["dealer"]["id"])

        assert allocated["status"] == H.OrderStatus.ALLOCATED
        assert allocated["allocated_unit_id"] == staged["unit"]["id"]
        H.assert_money(allocated["invoice_subtotal_cents"], H.ORDER1_SUBTOTAL_CENTS)
        H.assert_money(allocated["volume_discount_cents"], H.ORDER1_DISCOUNT_CENTS)
        H.assert_money(allocated["freight_cents"], H.ORDER1_FREIGHT_CENTS)
        H.assert_money(allocated["invoice_total_cents"], H.ORDER1_TOTAL_CENTS)
        H.assert_money(allocated["floor_plan_draw_cents"], 0)
        assert allocated["floor_plan_status"] == H.FloorPlanStatus.NONE
        dealer = H.read_dealer(api, plant["dealer"]["id"])
        H.assert_floor_plan_conserved(dealer, 0)
        H.assert_money(dealer["floor_plan_available_cents"], 1000)
        assert dealer["status"] == H.DealerStatus.ACTIVE
        assert dealer["allocations_current_month_count"] == 1
        assert dealer["allocations_ytd_count"] == 1
        assert H.read_unit(api, staged["unit"]["id"])["build_status"] == H.BuildStatus.ALLOCATED


class TestAllocationCounterWindows:
    def test_the_month_counter_restarts_in_september_while_the_year_counter_carries(self, api):
        """A quota of one per month admits a September allocation after an August one.

        PRD 3.8: "The two allocation counters count only orders whose `status` is
        `ALLOCATED` or `DELIVERED` and whose `allocated_at` falls inside the
        logical clock's current UTC calendar month and calendar year respectively;
        cancelled orders are excluded from both even though `allocated_at` remains
        on the row."

        Design: Corner/calculations/calc_month_counter_resets_in_september_while_the_year_counter_carries
        """
        plant = H.setup_plant(api, dealer_overrides={"allocation_quota_per_month": 1})
        H.unit_in_stock(plant, api, "SN-000101", H.JIG_WINDOW_1, H.LANE_WINDOW_1)
        second = H.unit_in_stock(plant, api, "SN-000102", H.JIG_WINDOW_2, H.LANE_WINDOW_2)
        august = H.place_order(api, plant["dealer"]["id"], plant["model"]["id"], po_ref="PO-10001")
        september = H.place_order(
            api, plant["dealer"]["id"], plant["model"]["id"], po_ref="PO-10002"
        )
        H.allocate_order(api, august["id"], plant["dealer"]["id"])
        H.set_clock(api, H.CLOCK_SEP_02)

        allocated = H.allocate_order(api, september["id"], plant["dealer"]["id"])

        assert allocated["status"] == H.OrderStatus.ALLOCATED
        assert allocated["allocated_unit_id"] == second["unit"]["id"]
        H.assert_instant(allocated["allocated_at"], H.CLOCK_SEP_02)
        assert allocated["volume_discount_pct"] == pytest.approx(
            H.ORDER2_DISCOUNT_PCT, abs=0.001
        )
        H.assert_money(allocated["volume_discount_cents"], H.ORDER2_DISCOUNT_CENTS)
        H.assert_money(allocated["freight_cents"], H.ORDER2_FREIGHT_CENTS)
        H.assert_money(allocated["invoice_total_cents"], H.ORDER2_TOTAL_CENTS)
        H.assert_money(allocated["floor_plan_draw_cents"], H.ORDER2_DRAW_CENTS)
        dealer = H.read_dealer(api, plant["dealer"]["id"])
        assert dealer["allocations_current_month_count"] == 1
        assert dealer["allocations_ytd_count"] == 2
        H.assert_floor_plan_conserved(dealer, H.TWO_ORDER_OUTSTANDING_CENTS)
        H.assert_money(dealer["floor_plan_available_cents"], H.TWO_ORDER_AVAILABLE_CENTS)
        august_after = H.read_order(api, august["id"])
        assert august_after["volume_discount_pct"] == pytest.approx(0.00, abs=0.001)
        H.assert_money(august_after["freight_cents"], H.ORDER1_FREIGHT_CENTS)
