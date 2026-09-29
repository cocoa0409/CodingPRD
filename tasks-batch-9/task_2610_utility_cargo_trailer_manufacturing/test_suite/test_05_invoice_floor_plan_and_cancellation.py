"""The pinned seven-step invoice, the admission ladder and exact compensation.

Covers PRD 3.8's evaluation order, the precedence of the order-state check over
the floor-plan headroom check from PRD 2.7, and the conserved floor-plan sum an
allocate-then-cancel pair owes under PRD 2.10.
"""

import pytest

import test_helpers as H
from test_helpers import SALES_ADMIN, validate_error


JIG_WINDOW_SECOND = ("2026-08-03T12:00:00Z", "2026-08-03T14:00:00Z")


class TestPinnedSevenStepInvoice:
    def test_the_first_allocation_of_the_year_is_undiscounted_and_pays_freight(self, api):
        """Tier 0 leaves the flat freight in place and draws 90 percent.

        PRD 3.8: "Step five sets `freight_cents`, which is waived to 0 whenever
        any volume tier applies — that is, whenever `volume_discount_pct` is at
        least three hundredths — and is otherwise a flat 895 dollars, or 89500
        cents; this is why freight cannot be evaluated before the tier is known."

        Design: Difficulty/combinatorial_formula/order_invoice_pinned_seven_step_evaluation_order
        """
        H.set_clock(api, H.CLOCK_DEFAULT_UTC)
        plant = H.setup_plant(api)
        first = H.unit_in_stock(plant, api, "SN-000101", H.JIG_WINDOW_1, H.LANE_WINDOW_1)
        order = H.place_order(api, plant["dealer"]["id"], plant["model"]["id"], po_ref="PO-10001")

        allocated = H.allocate_order(api, order["id"], plant["dealer"]["id"])

        assert allocated["allocated_unit_id"] == first["unit"]["id"]
        H.assert_money(allocated["invoice_subtotal_cents"], H.ORDER1_SUBTOTAL_CENTS)
        assert allocated["volume_discount_pct"] == pytest.approx(0.00, abs=0.001)
        H.assert_money(allocated["volume_discount_cents"], H.ORDER1_DISCOUNT_CENTS)
        H.assert_money(allocated["freight_cents"], H.ORDER1_FREIGHT_CENTS)
        H.assert_money(allocated["invoice_total_cents"], H.ORDER1_TOTAL_CENTS)
        H.assert_money(allocated["floor_plan_draw_cents"], H.ORDER1_DRAW_CENTS)
        assert allocated["floor_plan_status"] == H.FloorPlanStatus.DRAWN

    def test_the_second_allocation_earns_three_percent_and_waives_the_freight(self, api):
        """The tier is read from the count observed before this allocation.

        PRD 3.8: "Step three selects `volume_discount_pct` from the dealer's
        `allocations_ytd_count` **as observed before this allocation is
        counted**: when that count is 0 the rate is zero, when it is 1 the rate
        is three hundredths, and when it is 2 or more the rate is five
        hundredths."

        Design: Difficulty/combinatorial_formula/order_invoice_pinned_seven_step_evaluation_order
        """
        H.set_clock(api, H.CLOCK_DEFAULT_UTC)
        plant = H.setup_plant(api)
        first = H.unit_in_stock(plant, api, "SN-000101", H.JIG_WINDOW_1, H.LANE_WINDOW_1)
        second = H.unit_in_stock(plant, api, "SN-000102", JIG_WINDOW_SECOND, H.LANE_WINDOW_2)
        order1 = H.place_order(api, plant["dealer"]["id"], plant["model"]["id"], po_ref="PO-10001")
        order2 = H.place_order(api, plant["dealer"]["id"], plant["model"]["id"], po_ref="PO-10002")
        H.allocate_order(api, order1["id"], plant["dealer"]["id"])

        allocated = H.allocate_order(api, order2["id"], plant["dealer"]["id"])

        assert allocated["allocated_unit_id"] == second["unit"]["id"]
        H.assert_money(allocated["invoice_subtotal_cents"], H.ORDER1_SUBTOTAL_CENTS)
        assert allocated["volume_discount_pct"] == pytest.approx(H.ORDER2_DISCOUNT_PCT, abs=0.001)
        H.assert_money(allocated["volume_discount_cents"], H.ORDER2_DISCOUNT_CENTS)
        H.assert_money(allocated["freight_cents"], H.ORDER2_FREIGHT_CENTS)
        H.assert_money(allocated["invoice_total_cents"], H.ORDER2_TOTAL_CENTS)
        H.assert_money(allocated["floor_plan_draw_cents"], H.ORDER2_DRAW_CENTS)
        dealer = H.read_dealer(api, plant["dealer"]["id"])
        H.assert_floor_plan_conserved(dealer, H.TWO_ORDER_OUTSTANDING_CENTS)
        assert dealer["allocations_ytd_count"] == 2
        assert first["unit"]["serial_number"] == "SN-000101"


class TestOrderStateBeatsFloorPlanHeadroom:
    def test_allocating_a_cancelled_order_reports_the_state_not_the_credit_line(self, api):
        """A cancelled order on a starved credit line still reports the state error.

        PRD 2.7: "The rule that fires masks every later rule completely, so a
        request that trips step 3 never reveals whether it would also have tripped
        step 20."

        Design: Difficulty/priority_pair_validation_conflict/order_state_check_beats_floor_plan_limit_check
        """
        H.set_clock(api, H.CLOCK_DEFAULT_UTC)
        plant = H.setup_plant(api, dealer_overrides={"floor_plan_limit_cents": 100000})
        H.unit_in_stock(plant, api, "SN-000101", H.JIG_WINDOW_1, H.LANE_WINDOW_1)
        order_a = H.place_order(api, plant["dealer"]["id"], plant["model"]["id"], po_ref="PO-10001")
        H.place_order(api, plant["dealer"]["id"], plant["model"]["id"], po_ref="PO-10002")
        H.cancel_order(api, order_a["id"], cancellation_reason="dealer withdrew")
        dealer_version = H.read_dealer(api, plant["dealer"]["id"])["version"]

        response = api.allocate_order(
            order_a["id"], H.allocation_payload(dealer_version), headers=SALES_ADMIN
        )

        validate_error(response, H.ERR_ORDER_STATE_INVALID)
        assert H.read_order(api, order_a["id"])["status"] == H.OrderStatus.CANCELLED

    def test_a_pending_order_that_overshoots_the_limit_reports_the_headroom_breach(self, api):
        """With the state check satisfied the floor-plan rule finally fires.

        PRD 3.8: "a draw landing exactly on the limit is accepted, and a breach is
        refused with `ERR_FLOOR_PLAN_LIMIT_EXCEEDED` (HTTP 402)."

        Design: Difficulty/priority_pair_validation_conflict/order_state_check_beats_floor_plan_limit_check
        """
        H.set_clock(api, H.CLOCK_DEFAULT_UTC)
        plant = H.setup_plant(api, dealer_overrides={"floor_plan_limit_cents": 100000})
        staged = H.unit_in_stock(plant, api, "SN-000101", H.JIG_WINDOW_1, H.LANE_WINDOW_1)
        order_a = H.place_order(api, plant["dealer"]["id"], plant["model"]["id"], po_ref="PO-10001")
        order_b = H.place_order(api, plant["dealer"]["id"], plant["model"]["id"], po_ref="PO-10002")
        H.cancel_order(api, order_a["id"], cancellation_reason="dealer withdrew")
        dealer_version = H.read_dealer(api, plant["dealer"]["id"])["version"]

        response = api.allocate_order(
            order_b["id"], H.allocation_payload(dealer_version), headers=SALES_ADMIN
        )

        validate_error(response, H.ERR_FLOOR_PLAN_LIMIT_EXCEEDED)
        order_b_after = H.read_order(api, order_b["id"])
        assert order_b_after["status"] == H.OrderStatus.PENDING
        assert order_b_after["floor_plan_status"] == H.FloorPlanStatus.NONE
        dealer = H.read_dealer(api, plant["dealer"]["id"])
        H.assert_floor_plan_conserved(dealer, 0)
        H.assert_money(dealer["floor_plan_available_cents"], 100000)
        assert dealer["allocations_current_month_count"] == 0
        assert (
            H.read_unit(api, staged["unit"]["id"])["build_status"]
            == H.BuildStatus.RELEASED_TO_STOCK
        )


class TestCancellationCompensation:
    def test_cancelling_an_allocated_order_returns_the_conserved_sum_to_zero(self, api):
        """The draw leaves the sum while the invoice fields stay on the row.

        PRD 3.8: "The order's invoice fields and its `floor_plan_draw_cents` are
        retained on the row for audit; changing `floor_plan_status` is what
        removes them from the conserved sum, and an allocate-then-cancel pair must
        therefore leave `floor_plan_outstanding_cents` identical to its
        pre-allocation value."

        Design: Difficulty/compensating_invariant/order_cancellation_restores_the_floor_plan_sum_exactly
        """
        H.set_clock(api, H.CLOCK_DEFAULT_UTC)
        plant = H.setup_plant(api)
        staged = H.order_allocated(plant, api)

        cancelled = H.cancel_order(
            api,
            staged["order"]["id"],
            cancellation_reason="dealer cancelled the stocking order",
        )

        assert cancelled["status"] == H.OrderStatus.CANCELLED
        assert cancelled["allocated_unit_id"] is None
        assert cancelled["floor_plan_status"] == H.FloorPlanStatus.RELEASED
        H.assert_money(cancelled["floor_plan_draw_cents"], H.ORDER1_DRAW_CENTS)
        H.assert_money(cancelled["invoice_total_cents"], H.ORDER1_TOTAL_CENTS)
        dealer = H.read_dealer(api, plant["dealer"]["id"])
        H.assert_floor_plan_conserved(dealer, 0)
        H.assert_money(dealer["floor_plan_available_cents"], H.DEALER_FLOOR_PLAN_LIMIT_CENTS)
        assert dealer["allocations_current_month_count"] == 0
        assert dealer["allocations_ytd_count"] == 0
        assert (
            H.read_unit(api, staged["unit"]["id"])["build_status"]
            == H.BuildStatus.RELEASED_TO_STOCK
        )

    def test_the_released_trailer_keeps_its_original_stock_age_and_its_label(self, api):
        """The reversal does not rewrite released_to_stock_at and leaves the VIN.

        PRD 3.8: "the trailer's `released_to_stock_at` is deliberately **not**
        rewritten, so it keeps its original stock age and its original place in
        the allocation ranking."

        Design: Difficulty/compensating_invariant/order_cancellation_restores_the_floor_plan_sum_exactly
        """
        H.set_clock(api, H.CLOCK_DEFAULT_UTC)
        plant = H.setup_plant(api)
        staged = H.unit_in_stock(plant, api)
        stocked_at = staged["unit"]["released_to_stock_at"]
        vin_before = staged["unit"]["vin"]
        staged = H.order_allocated(plant, api, staged=staged)

        H.cancel_order(api, staged["order"]["id"])

        after = H.read_unit(api, staged["unit"]["id"])
        assert after["build_status"] == H.BuildStatus.RELEASED_TO_STOCK
        assert after["dealer_order_id"] is None
        assert after["released_to_stock_at"] == stocked_at
        assert after["vin"] == vin_before
        labels, _meta = H.validate_paginated(
            api.list_labels(staged["unit"]["id"], headers=SALES_ADMIN)
        )
        assert len(labels) == 1
        assert labels[0]["status"] == H.LabelStatus.ISSUED
