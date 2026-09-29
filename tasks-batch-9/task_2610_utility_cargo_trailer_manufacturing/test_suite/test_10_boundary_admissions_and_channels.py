"""Inclusive boundaries that must be admitted, and the read/write channels.

PRD 2.9 declares every threshold inclusive unless the text says otherwise, so
each boundary here is exercised on its accepted side. The floor-plan
administration endpoint and the reverse-lookup sub-resource reads follow.
"""

import pytest

import test_helpers as H
from test_helpers import (
    ASSEMBLY_TECH,
    SALES_ADMIN,
    WELD_SUPERVISOR,
    validate_paginated,
    validate_success,
)


class TestInclusiveClaimAndBudgetBoundaries:
    def test_labor_hours_landing_exactly_on_the_flat_rate_ceiling_are_accepted(self, api):
        """An AXLE claim at 4.375 hours sits on the ceiling and is admitted verbatim.

        PRD 3.9: "The comparison is inclusive: hours landing exactly on the
        ceiling are accepted, and hours above it are refused with
        `ERR_LABOR_HOURS_EXCEED_FLAT_RATE`."

        Design: Corner/validations/validation_labor_hours_exactly_at_the_flat_rate_ceiling_is_accepted
        """
        ceiling = H.FLAT_RATE_HOURS["AXLE"] * H.FLAT_RATE_CEILING_MULTIPLIER
        plant = H.setup_plant(api)
        staged = H.unit_shipped(plant, api)
        H.set_clock(api, H.CLOCK_SEP_01)

        response = api.create_claim(
            H.claim_payload(
                staged["unit"]["id"],
                plant["dealer"]["id"],
                complaint_code="AXLE",
                labor_hours=ceiling,
            ),
            headers=SALES_ADMIN,
        )

        claim = validate_success(response, expected_status=201)
        assert claim["labor_hours"] == pytest.approx(ceiling, abs=0.001)
        assert claim["status"] == H.ClaimStatus.SUBMITTED
        assert claim["complaint_code"] == "AXLE"
        assert claim["part_line_count"] == 2
        assert claim["shipped_line_count"] == 0
        assert claim["info_request_round"] == 0
        H.assert_no_money_computed(claim)

    def test_an_option_that_consumes_the_whole_budget_leaves_payload_at_zero(self, api):
        """A 4320 lb option lands payload on the floor and is still admitted.

        PRD 3.5: "The admission rule follows directly: an install is refused when
        charging it would drive `payload_capacity_lbs` below zero, and a
        `payload_capacity_lbs` of exactly zero is admissible — a trailer may be
        loaded to precisely its rating and no further."

        Design: Corner/validations/validation_option_that_zeroes_the_payload_capacity_is_admitted
        """
        plant = H.setup_plant(api)
        staged = H.unit_at_frame_welded(plant, api)
        assert staged["unit"]["payload_capacity_lbs"] == H.TA_PAYLOAD_CAPACITY_LBS

        response = api.create_option_install(
            staged["unit"]["id"],
            H.option_payload(
                option_code="SPECIALTY_FLOORING",
                quantity=1,
                unit_weight_lbs=H.TA_PAYLOAD_CAPACITY_LBS,
                unit_price_cents=199900,
                labor_hours=4.0,
            ),
            headers=ASSEMBLY_TECH,
        )

        option = validate_success(response, expected_status=201)
        assert option["status"] == H.OptionStatus.PENDING
        assert option["total_weight_lbs"] == H.TA_PAYLOAD_CAPACITY_LBS
        H.assert_money(option["total_price_cents"], 199900)
        unit = H.read_unit(api, staged["unit"]["id"])
        assert unit["curb_weight_lbs"] == H.TA_CERTIFIED_GVWR_LBS
        assert unit["payload_capacity_lbs"] == H.MIN_PAYLOAD_CAPACITY_LBS
        H.assert_weight_budget_balances(unit)
        H.assert_unit_dimensions(
            unit, H.BuildStatus.FRAME_WELDED, H.ComplianceStatus.NOT_VERIFIED
        )


class TestInclusiveFloorPlanAdmission:
    def test_a_draw_landing_exactly_on_the_limit_is_admitted_at_zero_headroom(self, api):
        """A limit of exactly 521460 funds the draw and leaves the dealer ACTIVE.

        PRD 3.8: "a draw landing exactly on the limit is accepted, and a breach is
        refused with `ERR_FLOOR_PLAN_LIMIT_EXCEEDED` (HTTP 402)."

        Design: Corner/validations/validation_draw_landing_exactly_on_the_floor_plan_limit_is_admitted
        """
        plant = H.setup_plant(
            api, dealer_overrides={"floor_plan_limit_cents": H.ORDER1_DRAW_CENTS}
        )
        H.unit_in_stock(plant, api)
        order = H.place_order(api, plant["dealer"]["id"], plant["model"]["id"])

        allocated = H.allocate_order(api, order["id"], plant["dealer"]["id"])

        assert allocated["status"] == H.OrderStatus.ALLOCATED
        assert allocated["floor_plan_status"] == H.FloorPlanStatus.DRAWN
        H.assert_money(allocated["invoice_total_cents"], H.ORDER1_TOTAL_CENTS)
        H.assert_money(allocated["floor_plan_draw_cents"], H.ORDER1_DRAW_CENTS)
        dealer = H.read_dealer(api, plant["dealer"]["id"])
        H.assert_floor_plan_conserved(dealer, H.ORDER1_DRAW_CENTS)
        H.assert_money(dealer["floor_plan_available_cents"], 0)
        assert dealer["status"] == H.DealerStatus.ACTIVE
        assert dealer["allocations_current_month_count"] == 1


class TestDealerScopeSatisfied:
    def test_a_dealer_filing_against_its_own_id_passes_the_ownership_check(self, api):
        """The entity-backed identity matches the body dealer_id, so the claim opens.

        PRD 2.1: "Concretely, a `Dealer` caller must supply its own `id` as the
        body `dealer_id` when placing a dealer order or filing a warranty claim;
        when cancelling a dealer order, the order's own `dealer_id` must equal
        `X-User-ID`; when answering an information request on a claim, the claim's
        `dealer_id` must equal `X-User-ID`; when reading a single dealer record,
        the dealer identifier in the path must equal `X-User-ID`; and when listing
        dealer orders or warranty claims, the `dealer_id` filter must be supplied
        and must equal `X-User-ID`."

        Design: Corner/validations/validation_dealer_scope_passes_when_the_dealer_files_against_its_own_id
        """
        plant = H.setup_plant(api)
        dealer_id = plant["dealer"]["id"]
        staged = H.unit_shipped(plant, api)
        H.set_clock(api, H.CLOCK_SEP_01)

        response = api.create_claim(
            H.claim_payload(staged["unit"]["id"], dealer_id),
            headers=H.make_dealer_headers(dealer_id),
        )

        claim = validate_success(response, expected_status=201)
        assert claim["dealer_id"] == dealer_id
        assert claim["unit_id"] == staged["unit"]["id"]
        assert claim["status"] == H.ClaimStatus.SUBMITTED
        assert claim["part_line_count"] == 2
        H.assert_no_money_computed(claim)


class TestFloorPlanAdministration:
    def test_a_payoff_repays_the_child_order_and_leaves_the_sale_untouched(self, api):
        """The order stays ALLOCATED while its draw leaves the conserved sum.

        PRD 3.8: "A `PAYOFF` names the `order_id` of a drawn order and moves that
        order's `floor_plan_status` from `DRAWN` to `REPAID`, which removes its
        `floor_plan_draw_cents` from the conserved sum so that the dealer's
        `floor_plan_outstanding_cents` drops by exactly that amount — delivery
        never repays a floor plan, only a payoff does."

        Design: Corner/endpoints/endpoint_payoff_adjustment_removes_the_draw_from_the_conserved_sum
        """
        plant = H.setup_plant(api)
        staged = H.order_allocated(plant, api)

        response = api.adjust_floor_plan(
            plant["dealer"]["id"],
            H.adjustment_payload(
                "PAYOFF",
                H.ORDER1_DRAW_CENTS,
                order_id=staged["order"]["id"],
                note="dealer paid off the unit",
            ),
            headers=SALES_ADMIN,
        )

        dealer = validate_success(response)
        order = H.read_order(api, staged["order"]["id"])
        assert order["floor_plan_status"] == H.FloorPlanStatus.REPAID
        assert order["status"] == H.OrderStatus.ALLOCATED
        H.assert_money(order["floor_plan_draw_cents"], H.ORDER1_DRAW_CENTS)
        H.assert_floor_plan_conserved(dealer, 0)
        H.assert_money(dealer["floor_plan_limit_cents"], H.DEALER_FLOOR_PLAN_LIMIT_CENTS)
        H.assert_money(dealer["floor_plan_available_cents"], H.DEALER_FLOOR_PLAN_LIMIT_CENTS)
        assert dealer["status"] == H.DealerStatus.ACTIVE
        assert dealer["allocations_current_month_count"] == 1
        unit = H.read_unit(api, staged["unit"]["id"])
        assert unit["build_status"] == H.BuildStatus.ALLOCATED
        assert unit["dealer_order_id"] == staged["order"]["id"]

    def test_a_limit_decrease_below_the_outstanding_balance_derives_a_credit_hold(self, api):
        """The hold is derived from the resulting arithmetic, not requested.

        PRD 3.8: "A decrease that leaves `floor_plan_outstanding_cents` above the
        new `floor_plan_limit_cents` additionally sets the dealer's `status` to
        `CREDIT_HOLD` as a derived consequence."

        Design: Corner/endpoints/endpoint_limit_decrease_below_outstanding_derives_a_credit_hold
        """
        plant = H.setup_plant(api)
        staged = H.order_allocated(plant, api)

        dealer = H.adjust_floor_plan(
            api,
            plant["dealer"]["id"],
            "LIMIT_DECREASE",
            H.DEALER_FLOOR_PLAN_LIMIT_CENTS - H.SQUEEZED_LIMIT_CENTS,
            note="credit line reduced by the floor plan lender",
        )

        H.assert_money(dealer["floor_plan_limit_cents"], H.SQUEEZED_LIMIT_CENTS)
        H.assert_floor_plan_conserved(dealer, H.ORDER1_DRAW_CENTS)
        H.assert_money(dealer["floor_plan_available_cents"], H.SQUEEZED_HEADROOM_CENTS)
        assert dealer["status"] == H.DealerStatus.CREDIT_HOLD
        order = H.read_order(api, staged["order"]["id"])
        assert order["floor_plan_status"] == H.FloorPlanStatus.DRAWN
        H.assert_money(order["floor_plan_draw_cents"], H.ORDER1_DRAW_CENTS)
        assert order["status"] == H.OrderStatus.ALLOCATED

    def test_a_credit_release_sets_the_dealer_active_while_headroom_stays_negative(self, api):
        """The release overrides the status without re-deriving it from the balances.

        PRD 3.8: "A `CREDIT_HOLD` sets the dealer's `status` to `CREDIT_HOLD`
        directly and a `CREDIT_RELEASE` sets it back to `ACTIVE`."

        Design: Corner/endpoints/endpoint_credit_release_restores_an_active_dealer_without_moving_balances
        """
        plant = H.setup_plant(api)
        staged = H.order_allocated(plant, api)
        held = H.adjust_floor_plan(
            api,
            plant["dealer"]["id"],
            "LIMIT_DECREASE",
            H.DEALER_FLOOR_PLAN_LIMIT_CENTS - H.SQUEEZED_LIMIT_CENTS,
            note="floor plan maintenance",
        )
        assert held["status"] == H.DealerStatus.CREDIT_HOLD

        dealer = H.adjust_floor_plan(
            api, plant["dealer"]["id"], "CREDIT_RELEASE", 0, note="lender waiver on file"
        )

        assert dealer["status"] == H.DealerStatus.ACTIVE
        H.assert_money(dealer["floor_plan_limit_cents"], H.SQUEEZED_LIMIT_CENTS)
        H.assert_floor_plan_conserved(dealer, H.ORDER1_DRAW_CENTS)
        H.assert_money(dealer["floor_plan_available_cents"], H.SQUEEZED_HEADROOM_CENTS)
        assert H.read_order(api, staged["order"]["id"])["floor_plan_status"] == (
            H.FloorPlanStatus.DRAWN
        )


class TestReverseLookupReadChannels:
    def test_each_sub_resource_read_applies_its_own_default_visibility(self, api):
        """A removed option hides by default, appears under include_removed.

        PRD 3.5: "A trailer's option lines are readable as a list which excludes
        `REMOVED` lines unless the request sets `include_removed` to true, and a
        single line is readable on its own with its extended weight and price."

        Design: Corner/endpoints/endpoint_reverse_lookup_reads_scope_children_and_hide_removed_lines
        """
        plant = H.setup_plant(api)
        staged = H.unit_at_road_test_passed(plant, api)
        unit_id = staged["unit"]["id"]
        kept = H.charge_option(
            api,
            unit_id,
            option_code="SIDE_CABINET_PKG",
            quantity=2,
            unit_weight_lbs=45,
            unit_price_cents=34500,
            labor_hours=2.0,
        )
        dropped = H.charge_option(
            api,
            unit_id,
            option_code="REAR_RAMP_GATE",
            quantity=1,
            unit_weight_lbs=210,
            unit_price_cents=89900,
            labor_hours=1.5,
        )
        H.remove_option(api, dropped["id"], removal_reason="dealer dropped the ramp gate")
        H.issue_label(api, unit_id)

        visible, _meta = validate_paginated(
            api.list_option_installs(unit_id, headers=ASSEMBLY_TECH)
        )
        including, _meta2 = validate_paginated(
            api.list_option_installs(
                unit_id, params={"include_removed": "true"}, headers=ASSEMBLY_TECH
            )
        )

        assert [row["id"] for row in visible] == [kept["id"]]
        assert visible[0]["status"] == H.OptionStatus.PENDING
        assert len(including) == 2
        removed = [row for row in including if row["id"] == dropped["id"]][0]
        assert removed["status"] == H.OptionStatus.REMOVED
        assert removed["total_weight_lbs"] == 210
        H.assert_money(removed["total_price_cents"], 89900)
        reservations, _meta3 = validate_paginated(
            api.list_unit_jig_reservations(unit_id, headers=WELD_SUPERVISOR)
        )
        assert len(reservations) == 1
        assert reservations[0]["status"] == H.ReservationStatus.CONSUMED
        assert reservations[0]["duration_minutes"] == 120
        labels, _meta4 = validate_paginated(api.list_labels(unit_id, headers=SALES_ADMIN))
        assert len(labels) == 1
        assert labels[0]["status"] == H.LabelStatus.ISSUED
        assert labels[0]["vin"] == H.VIN_FIRST
        unit = H.read_unit(api, unit_id)
        assert unit["curb_weight_lbs"] == 2070
        assert unit["payload_capacity_lbs"] == 4230
        assert unit["build_status"] == H.BuildStatus.LABELED
        assert unit["released_to_stock_at"] is None
