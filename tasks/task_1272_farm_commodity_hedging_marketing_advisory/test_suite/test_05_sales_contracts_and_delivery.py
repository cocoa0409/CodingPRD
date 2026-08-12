"""Sales contracts: windows, pricing dimension, delivery tickets, tolerance,
confirm/void compensation, and plan auto-close."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_grower_headers,
    setup_active_plan_with_buyer,
    setup_operation_with_active_plan,
    create_approved_buyer,
    create_flat_contract,
    create_confirmed_delivery,
    create_contract_payload,
    create_ticket_payload,
    record_settlement_tick,
    set_logical_clock,
)

ADVISOR = TEST_USERS["advisor_headers"]


class TestDeliveryWindows:
    def test_adjacent_window_allowed_and_intersecting_rejected(self, api):
        """PRD §2.8: "First, buyer delivery windows are half-open intervals: a
        contract's window includes `delivery_window_start` and excludes
        `delivery_window_end`. A delivery ticket whose `delivery_date` falls on
        the window start is accepted; one whose `delivery_date` falls on the
        window end is rejected with `ERR_DELIVERY_OUTSIDE_WINDOW`. Two
        contracts with the same buyer may not have overlapping windows while
        either is `OPEN` or `PARTIALLY_DELIVERED`: an overlap exists precisely
        when the new contract's start falls before the existing contract's end
        and the existing contract's start falls before the new contract's end;
        pure adjacency, where one window's end equals the other's start, is
        allowed. A violation is rejected with `ERR_DELIVERY_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/buyer_delivery_windows_half_open_adjacency
        """
        ctx = setup_active_plan_with_buyer(
            name="Window Farm", risk_profile="AGGRESSIVE", max_priced_pct=1.00
        )
        create_flat_contract(
            ctx, bushels=5000, fixed_price=4.50,
            delivery_window_start="2026-10-01", delivery_window_end="2026-11-01",
        )
        adjacent = api.create_contract(
            create_contract_payload(
                ctx["operation"]["id"], ctx["plan"]["id"], ctx["buyer"]["id"],
                bushels=5000, fixed_price=4.55,
                delivery_window_start="2026-11-01", delivery_window_end="2026-12-01",
            ),
            ADVISOR,
        )
        data = validate_success(adjacent, expected_status=201)
        assert data["fulfillment_status"] == "OPEN", "adjacency (end == start) must be accepted"
        overlapping = api.create_contract(
            create_contract_payload(
                ctx["operation"]["id"], ctx["plan"]["id"], ctx["buyer"]["id"],
                bushels=1000, fixed_price=4.60,
                delivery_window_start="2026-10-31", delivery_window_end="2026-11-30",
            ),
            ADVISOR,
        )
        validate_error(overlapping, ApiErrorId.ERR_DELIVERY_WINDOW_OVERLAP)

    def test_intersection_by_one_day_rejected(self, api):
        """PRD §2.8: "an overlap exists precisely when the new contract's start
        falls before the existing contract's end and the existing contract's
        start falls before the new contract's end; pure adjacency, where one
        window's end equals the other's start, is allowed. A violation is
        rejected with `ERR_DELIVERY_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/buyer_delivery_windows_half_open_adjacency
        """
        ctx = setup_active_plan_with_buyer(
            name="Window Farm", risk_profile="AGGRESSIVE", max_priced_pct=1.00
        )
        create_flat_contract(
            ctx, bushels=5000, fixed_price=4.50,
            delivery_window_start="2026-10-01", delivery_window_end="2026-11-01",
        )
        resp = api.create_contract(
            create_contract_payload(
                ctx["operation"]["id"], ctx["plan"]["id"], ctx["buyer"]["id"],
                bushels=1000, fixed_price=4.60,
                delivery_window_start="2026-10-31", delivery_window_end="2026-11-30",
            ),
            ADVISOR,
        )
        validate_error(resp, ApiErrorId.ERR_DELIVERY_WINDOW_OVERLAP)

    def test_delivery_date_window_end_boundaries(self, api):
        """PRD §2.8: "A delivery ticket whose `delivery_date` falls on the
        window start is accepted; one whose `delivery_date` falls on the window
        end is rejected with `ERR_DELIVERY_OUTSIDE_WINDOW`."

        Design: Corner/validations/delivery_date_window_end_boundaries
        """
        ctx = setup_active_plan_with_buyer(
            name="Win Farm", risk_profile="AGGRESSIVE", max_priced_pct=1.00
        )
        contract = create_flat_contract(
            ctx, bushels=10000, fixed_price=4.50,
            delivery_window_start="2026-10-01", delivery_window_end="2026-11-01",
        )
        grower = make_grower_headers(ctx["operation"]["id"])
        on_start = api.create_ticket(
            create_ticket_payload(contract["id"], delivery_date="2026-10-01", gross_bushels=1000, moisture_pct=15.0),
            grower,
        )
        data = validate_success(on_start, expected_status=201)
        assert data["id"], "delivery on the window start is inside [start, end) and must be accepted"
        on_end = api.create_ticket(
            create_ticket_payload(contract["id"], delivery_date="2026-11-01", gross_bushels=1000, moisture_pct=15.0),
            grower,
        )
        validate_error(on_end, ApiErrorId.ERR_DELIVERY_OUTSIDE_WINDOW)

    def test_contract_inverted_window_returns_400(self, api):
        """PRD §2.6: "Field-level schema validation runs third — missing
        required fields, invalid enum values, out-of-range values, violated
        conditional-field rules, or window inversions produce
        `ERR_VALIDATION`."

        Design: Corner/validations/contract_inverted_window_returns_400
        """
        ctx = setup_active_plan_with_buyer(
            name="InvWin Farm", risk_profile="AGGRESSIVE", max_priced_pct=1.00
        )
        resp = api.create_contract(
            create_contract_payload(
                ctx["operation"]["id"], ctx["plan"]["id"], ctx["buyer"]["id"],
                bushels=1000, fixed_price=4.50,
                delivery_window_start="2026-12-01", delivery_window_end="2026-11-01",
            ),
            ADVISOR,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_contract_exceeding_uncommitted_rejected(self, api):
        """PRD §3.7: "the contract's `bushels` must not exceed the plan's
        `uncommitted_bushels`, failing with
        `ERR_INSUFFICIENT_UNCOMMITTED_BUSHELS`".
        PRD §3.3: "`uncommitted_bushels` is the snapshot minus
        `committed_contract_bushels`."

        Design: Corner/validations/contract_exceeding_uncommitted_rejected
        """
        ctx = setup_active_plan_with_buyer(
            name="Agg Farm", risk_profile="AGGRESSIVE", max_priced_pct=1.00
        )
        resp = api.create_contract(
            create_contract_payload(
                ctx["operation"]["id"], ctx["plan"]["id"], ctx["buyer"]["id"],
                bushels=25000, fixed_price=4.50,
                delivery_window_start="2026-10-01", delivery_window_end="2026-11-01",
            ),
            ADVISOR,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_UNCOMMITTED_BUSHELS)
        plan = get_success_data(api.get_plan(ctx["plan"]["id"], ADVISOR))
        assert plan["uncommitted_bushels"] == 20000, "the failed create must not consume uncommitted bushels"


class TestPricingDimension:
    def test_fix_price_flat_and_double_fix_rejected(self, api):
        """PRD §3.7: "Calling fix-price on a `FLAT_PRICE` contract or on an
        already-`PRICED` contract is rejected with `ERR_PRICING_NOT_ALLOWED`."

        Design: Corner/endpoints/fix_price_only_on_unpriced_contract
        """
        ctx = setup_active_plan_with_buyer(
            name="FP Farm", risk_profile="AGGRESSIVE", max_priced_pct=1.00
        )
        c_flat = create_flat_contract(
            ctx, bushels=3000, fixed_price=4.50,
            delivery_window_start="2026-10-01", delivery_window_end="2026-11-01",
        )
        c_hta = get_success_data(api.create_contract(
            create_contract_payload(
                ctx["operation"]["id"], ctx["plan"]["id"], ctx["buyer"]["id"],
                contract_type="HTA", bushels=3000, contract_month="2026-12",
                fixed_price=None,
                delivery_window_start="2026-11-01", delivery_window_end="2026-12-01",
            ),
            ADVISOR,
        ))
        resp1 = api.fix_price(c_flat["id"], {"fixation_price": 4.70}, ADVISOR)
        validate_error(resp1, ApiErrorId.ERR_PRICING_NOT_ALLOWED)
        fixed = get_success_data(api.fix_price(c_hta["id"], {"fixation_price": 4.70}, ADVISOR))
        assert fixed["pricing_status"] == "PRICED"
        assert fixed["effective_price"] == pytest.approx(4.70)
        resp2 = api.fix_price(c_hta["id"], {"fixation_price": 4.80}, ADVISOR)
        validate_error(resp2, ApiErrorId.ERR_PRICING_NOT_ALLOWED)
        after = get_success_data(api.get_contract(c_hta["id"], ADVISOR))
        assert after["effective_price"] == pytest.approx(4.70), "the rejected second fix must not move the price"

    def test_fix_price_moves_pricing_dimension_only(self, api):
        """PRD §3.7: "A contract's two state dimensions evolve independently.
        On the pricing dimension, fixing the price is an advisor action on an
        `UNPRICED` `HTA` or `BASIS` contract whose fulfillment is `OPEN` or
        `PARTIALLY_DELIVERED`, carrying a `fixation_price` at two decimal
        places." and "Fixing sets `fixation_price`, moves `pricing_status` from
        `UNPRICED` to `PRICED`, computes `effective_price` — for `HTA`, the
        fixation price itself; for `BASIS`, the fixation price plus
        `basis_level` — and recomputes the plan's `priced_contract_bushels`."
        Also: "A `FLAT_PRICE` contract is created with `pricing_status` equal
        to `PRICED`; `HTA` and `BASIS` contracts start `UNPRICED`. Every
        contract starts with `fulfillment_status` equal to `OPEN`."

        Design: Difficulty/non_linear_state_machine/sales_contract_independent_pricing_fulfillment_dimensions
        """
        ctx = setup_active_plan_with_buyer(
            name="Dims Farm", risk_profile="AGGRESSIVE", max_priced_pct=1.00
        )
        c_hta = get_success_data(api.create_contract(
            create_contract_payload(
                ctx["operation"]["id"], ctx["plan"]["id"], ctx["buyer"]["id"],
                contract_type="HTA", bushels=8000, contract_month="2026-12",
                fixed_price=None,
                delivery_window_start="2026-10-01", delivery_window_end="2026-11-01",
            ),
            ADVISOR,
        ))
        assert c_hta["pricing_status"] == "UNPRICED", "HTA starts UNPRICED"
        assert c_hta["fulfillment_status"] == "OPEN", "every contract starts OPEN"
        fixed = get_success_data(api.fix_price(c_hta["id"], {"fixation_price": 4.65}, ADVISOR))
        assert fixed["pricing_status"] == "PRICED", "fix-price moves the pricing dimension"
        assert fixed["effective_price"] == pytest.approx(4.65)
        assert fixed["fulfillment_status"] == "OPEN", "pricing advanced while fulfillment stayed OPEN"

    def test_partial_confirm_moves_fulfillment_dimension_only(self, api):
        """PRD §3.7: "On the fulfillment dimension, a contract progresses from
        `OPEN` to `PARTIALLY_DELIVERED` when a confirmed ticket leaves
        delivered bushels greater than zero but below the contract quantity,
        and from either state to `DELIVERED` when confirmed deliveries reach or
        exceed the contract quantity within the tolerance of §3.8."

        Design: Difficulty/non_linear_state_machine/sales_contract_independent_pricing_fulfillment_dimensions
        """
        ctx = setup_active_plan_with_buyer(
            name="Dims Farm", risk_profile="AGGRESSIVE", max_priced_pct=1.00
        )
        c_hta = get_success_data(api.create_contract(
            create_contract_payload(
                ctx["operation"]["id"], ctx["plan"]["id"], ctx["buyer"]["id"],
                contract_type="HTA", bushels=8000, contract_month="2026-12",
                fixed_price=None,
                delivery_window_start="2026-10-01", delivery_window_end="2026-11-01",
            ),
            ADVISOR,
        ))
        get_success_data(api.fix_price(c_hta["id"], {"fixation_price": 4.65}, ADVISOR))
        create_confirmed_delivery(ctx, c_hta, delivery_date="2026-10-15", gross_bushels=3000, moisture_pct=15.0)
        after = get_success_data(api.get_contract(c_hta["id"], ADVISOR))
        assert after["fulfillment_status"] == "PARTIALLY_DELIVERED", (
            "3000 of 8000 delivered must move fulfillment to PARTIALLY_DELIVERED"
        )
        assert after["delivered_bushels"] == 3000
        assert after["pricing_status"] == "PRICED", "fulfillment advanced while pricing stayed PRICED"


class TestDeliveryTicketConfirm:
    def test_confirm_unpriced_contract_rejected(self, api):
        """PRD §3.8: "The contract's `pricing_status` must be `PRICED`,
        failing with `ERR_CONTRACT_NOT_PRICED`."

        Design: Corner/endpoints/confirm_unpriced_contract_rejected
        """
        ctx = setup_active_plan_with_buyer(
            name="Unp Farm", risk_profile="AGGRESSIVE", max_priced_pct=1.00
        )
        c_hta = get_success_data(api.create_contract(
            create_contract_payload(
                ctx["operation"]["id"], ctx["plan"]["id"], ctx["buyer"]["id"],
                contract_type="HTA", bushels=5000, contract_month="2026-12",
                fixed_price=None,
                delivery_window_start="2026-10-01", delivery_window_end="2026-11-01",
            ),
            ADVISOR,
        ))
        ticket = get_success_data(api.create_ticket(
            create_ticket_payload(c_hta["id"], delivery_date="2026-10-10", gross_bushels=1000, moisture_pct=15.0),
            make_grower_headers(ctx["operation"]["id"]),
        ))
        resp = api.confirm_ticket(ticket["id"], ADVISOR)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_PRICED)
        after = get_success_data(api.get_ticket(ticket["id"], ADVISOR))
        assert after["status"] == "RECORDED", "ticket must remain RECORDED after the rejected confirm"
        contract = get_success_data(api.get_contract(c_hta["id"], ADVISOR))
        assert contract["delivered_bushels"] == 0, "no bushels may be applied by the rejected confirm"

    def test_ticket_on_delivered_contract_rejected(self, api):
        """PRD §3.8: "Recording against a contract that is already `DELIVERED`
        is rejected with `ERR_CONTRACT_FULLY_DELIVERED`."

        Design: Corner/endpoints/ticket_on_delivered_contract_rejected
        """
        ctx = setup_active_plan_with_buyer(
            name="Full Farm", risk_profile="AGGRESSIVE", max_priced_pct=1.00
        )
        contract = create_flat_contract(
            ctx, bushels=5000, fixed_price=4.50,
            delivery_window_start="2026-10-01", delivery_window_end="2026-11-01",
        )
        create_confirmed_delivery(ctx, contract, delivery_date="2026-10-10", gross_bushels=5000, moisture_pct=15.0)
        delivered = get_success_data(api.get_contract(contract["id"], ADVISOR))
        assert delivered["fulfillment_status"] == "DELIVERED"
        resp = api.create_ticket(
            create_ticket_payload(contract["id"], delivery_date="2026-10-11", gross_bushels=100, moisture_pct=15.0),
            make_grower_headers(ctx["operation"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CONTRACT_FULLY_DELIVERED)
        after = get_success_data(api.get_contract(contract["id"], ADVISOR))
        assert after["fulfillment_status"] == "DELIVERED"
        assert after["delivered_bushels"] == 5000

    def test_over_delivery_tolerance_equality_vs_excess(self, api):
        """PRD §3.8: "And the confirmation must respect the over-delivery
        tolerance: the contract's delivered bushels after this ticket must not
        exceed the floor of the contract's `bushels` multiplied by 1.02 —
        equality is allowed — failing with `ERR_OVER_DELIVERY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/over_delivery_tolerance_equality_vs_excess
        """
        ctx = setup_active_plan_with_buyer(
            name="Tol Farm", risk_profile="AGGRESSIVE", max_priced_pct=1.00
        )
        c1 = create_flat_contract(
            ctx, bushels=10000, fixed_price=4.50,
            delivery_window_start="2026-10-01", delivery_window_end="2026-11-01",
        )
        c2 = create_flat_contract(
            ctx, bushels=10000, fixed_price=4.50,
            delivery_window_start="2026-11-01", delivery_window_end="2026-12-01",
        )
        grower = make_grower_headers(ctx["operation"]["id"])
        tk_ok = get_success_data(api.create_ticket(
            create_ticket_payload(c1["id"], delivery_date="2026-10-10", gross_bushels=10200, moisture_pct=15.0),
            grower,
        ))
        tk_over = get_success_data(api.create_ticket(
            create_ticket_payload(c2["id"], delivery_date="2026-11-10", gross_bushels=10201, moisture_pct=15.0),
            grower,
        ))
        assert tk_ok["net_bushels"] == pytest.approx(10200.0)
        confirmed = get_success_data(api.confirm_ticket(tk_ok["id"], ADVISOR))
        assert confirmed["status"] == "CONFIRMED", (
            "net 10200 == floor(10000 * 1.02) — equality at the tolerance must confirm"
        )
        contract = get_success_data(api.get_contract(c1["id"], ADVISOR))
        assert contract["fulfillment_status"] == "DELIVERED"
        assert contract["delivered_bushels"] == 10200
        resp = api.confirm_ticket(tk_over["id"], ADVISOR)
        validate_error(resp, ApiErrorId.ERR_OVER_DELIVERY_EXCEEDED)

    def test_one_bushel_over_tolerance_rejected(self, api):
        """PRD §3.8: "And the confirmation must respect the over-delivery
        tolerance: the contract's delivered bushels after this ticket must not
        exceed the floor of the contract's `bushels` multiplied by 1.02 —
        equality is allowed — failing with `ERR_OVER_DELIVERY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/over_delivery_tolerance_equality_vs_excess
        """
        ctx = setup_active_plan_with_buyer(
            name="Tol Farm", risk_profile="AGGRESSIVE", max_priced_pct=1.00
        )
        c2 = create_flat_contract(
            ctx, bushels=10000, fixed_price=4.50,
            delivery_window_start="2026-11-01", delivery_window_end="2026-12-01",
        )
        tk_over = get_success_data(api.create_ticket(
            create_ticket_payload(c2["id"], delivery_date="2026-11-10", gross_bushels=10201, moisture_pct=15.0),
            make_grower_headers(ctx["operation"]["id"]),
        ))
        assert tk_over["net_bushels"] == pytest.approx(10201.0)
        resp = api.confirm_ticket(tk_over["id"], ADVISOR)
        validate_error(resp, ApiErrorId.ERR_OVER_DELIVERY_EXCEEDED)
        contract = get_success_data(api.get_contract(c2["id"], ADVISOR))
        assert contract["delivered_bushels"] == 0, "the rejected confirm must apply nothing"
        assert contract["fulfillment_status"] == "OPEN"


class TestSettlementRounding:
    def test_shrink_and_per_line_net_bushels(self, api):
        """PRD §3.8: "At recording, the server computes the moisture shrink:
        `shrink_pct` is the greater of zero and `moisture_pct` minus 15.0,
        multiplied by 0.012 — shrink applies only above the 15.0 percent
        moisture base. The `net_bushels` are then `gross_bushels` multiplied by
        one minus `shrink_pct`, rounded to three decimal places half-up."

        Design: Difficulty/combinatorial_formula/settlement_per_line_rounding_then_sum
        """
        ctx = setup_active_plan_with_buyer(
            name="Round Farm", risk_profile="AGGRESSIVE", max_priced_pct=1.00
        )
        contract = create_flat_contract(
            ctx, bushels=19550, fixed_price=4.5551,
            delivery_window_start="2026-10-01", delivery_window_end="2026-11-01",
        )
        grower = make_grower_headers(ctx["operation"]["id"])
        t1 = get_success_data(api.create_ticket(
            create_ticket_payload(contract["id"], delivery_date="2026-10-12", gross_bushels=10000, moisture_pct=16.5),
            grower,
        ))
        t2 = get_success_data(api.create_ticket(
            create_ticket_payload(contract["id"], delivery_date="2026-10-13", gross_bushels=10000, moisture_pct=17.25),
            grower,
        ))
        assert t1["net_bushels"] == pytest.approx(9820.000, abs=1e-9), (
            f"shrink (16.5-15.0)*0.012 = 0.018 -> net 9820.000, got {t1['net_bushels']}"
        )
        assert t2["net_bushels"] == pytest.approx(9730.000, abs=1e-9), (
            f"shrink (17.25-15.0)*0.012 = 0.027 -> net 9730.000, got {t2['net_bushels']}"
        )

    def test_per_line_rounding_then_sum(self, api):
        """PRD §3.8: "On confirmation the ticket's `ticket_value_dollars` is
        computed as `net_bushels` multiplied by the contract's
        `effective_price`, rounded to two decimal places half-up, and added
        into the contract's `settled_value_dollars`. The rounding order is
        pinned: each ticket's value is rounded first, then the per-ticket
        values are summed; summing net bushels and rounding once produces
        different cents and is not used."

        Design: Difficulty/combinatorial_formula/settlement_per_line_rounding_then_sum
        """
        ctx = setup_active_plan_with_buyer(
            name="Round Farm", risk_profile="AGGRESSIVE", max_priced_pct=1.00
        )
        contract = create_flat_contract(
            ctx, bushels=19550, fixed_price=4.5551,
            delivery_window_start="2026-10-01", delivery_window_end="2026-11-01",
        )
        grower = make_grower_headers(ctx["operation"]["id"])
        t1 = get_success_data(api.create_ticket(
            create_ticket_payload(contract["id"], delivery_date="2026-10-12", gross_bushels=10000, moisture_pct=16.5),
            grower,
        ))
        t2 = get_success_data(api.create_ticket(
            create_ticket_payload(contract["id"], delivery_date="2026-10-13", gross_bushels=10000, moisture_pct=17.25),
            grower,
        ))
        c1 = get_success_data(api.confirm_ticket(t1["id"], ADVISOR))
        c2 = get_success_data(api.confirm_ticket(t2["id"], ADVISOR))
        assert c1["ticket_value_dollars"] == pytest.approx(44731.08, abs=0.005), (
            f"per-line round(9820.000 * 4.5551) must be 44731.08, got {c1['ticket_value_dollars']}"
        )
        assert c2["ticket_value_dollars"] == pytest.approx(44321.12, abs=0.005), (
            f"per-line round(9730.000 * 4.5551) must be 44321.12, got {c2['ticket_value_dollars']}"
        )
        settled = get_success_data(api.get_contract(contract["id"], ADVISOR))
        assert settled["settled_value_dollars"] == pytest.approx(89052.20, abs=0.005), (
            "pinned order yields 89052.20, NOT 89052.21 (sum-then-round); got "
            f"{settled['settled_value_dollars']}"
        )
        assert settled["delivered_bushels"] == 19550


class TestVoidCompensation:
    def test_void_confirmed_ticket_compensates_fully(self, api):
        """PRD §3.8: "Voiding a previously `CONFIRMED` ticket reverses every
        effect confirmation applied: the contract's `delivered_bushels`
        decrements by the ticket's `net_bushels`, the contract's
        `settled_value_dollars` decrements by the ticket's stored
        `ticket_value_dollars`, the agreement's `billable_bushels_accrued`
        decrements by `net_bushels`, the fulfillment state reverts —
        `DELIVERED` back to `PARTIALLY_DELIVERED`, or `PARTIALLY_DELIVERED`
        back to `OPEN`, as the resulting quantities dictate — and the plan is
        recomputed."

        Design: Corner/endpoints/void_confirmed_ticket_compensates_fully
        """
        ctx = setup_active_plan_with_buyer(
            name="Void Farm", risk_profile="AGGRESSIVE", max_priced_pct=1.00,
            agreement_overrides={"fee_type": "PER_BUSHEL", "rate_per_bushel": 0.02, "flat_annual_fee": None},
        )
        contract = create_flat_contract(
            ctx, bushels=8000, fixed_price=4.50,
            delivery_window_start="2026-10-01", delivery_window_end="2026-11-01",
        )
        ticket = create_confirmed_delivery(
            ctx, contract, delivery_date="2026-10-10", gross_bushels=4000, moisture_pct=15.0
        )
        pre = get_success_data(api.get_contract(contract["id"], ADVISOR))
        assert pre["fulfillment_status"] == "PARTIALLY_DELIVERED"
        assert pre["delivered_bushels"] == 4000
        agreement_pre = get_success_data(api.get_agreement(ctx["agreement"]["id"], ADVISOR))
        assert agreement_pre["billable_bushels_accrued"] == 4000
        voided = get_success_data(api.void_ticket(ticket["id"], ADVISOR))
        assert voided["status"] == "VOIDED"
        after = get_success_data(api.get_contract(contract["id"], ADVISOR))
        assert after["delivered_bushels"] == 0, "void must return delivered_bushels to 0"
        assert after["settled_value_dollars"] == pytest.approx(0.00), (
            "void must subtract the stored ticket value (18000.00 -> 0.00)"
        )
        assert after["fulfillment_status"] == "OPEN", "PARTIALLY_DELIVERED must revert to OPEN"
        agreement_post = get_success_data(api.get_agreement(ctx["agreement"]["id"], ADVISOR))
        assert agreement_post["billable_bushels_accrued"] == 0, (
            "billable accrual must be fully reversed — no drift after compensation"
        )


class TestPlanAutoCloseCascade:
    def test_confirm_cascade_does_not_over_fire(self, api):
        """PRD §3.3: "A plan also closes itself automatically when a
        delivery-ticket confirmation leaves the plan with `uncommitted_bushels`
        equal to zero and every sales contract on the plan `DELIVERED`; in that
        event all remaining `PENDING` price targets of the plan move to
        `CANCELLED`, and the same target cancellation applies on an explicit
        close."

        Design: Difficulty/transitive_cascade/delivery_confirm_cascade_to_plan_auto_close
        """
        ctx = setup_active_plan_with_buyer(
            name="Close Farm", risk_profile="AGGRESSIVE", max_priced_pct=1.00
        )
        plan_id = ctx["plan"]["id"]
        get_success_data(api.create_price_target(
            {"plan_id": plan_id, "contract_month": "2026-12", "target_price": 4.90, "increment_bushels": 5000}, ADVISOR))
        c1 = create_flat_contract(ctx, bushels=12000, fixed_price=4.50,
                                  delivery_window_start="2026-10-01", delivery_window_end="2026-11-01")
        create_flat_contract(ctx, bushels=8000, fixed_price=4.60,
                             delivery_window_start="2026-11-01", delivery_window_end="2026-12-01")
        create_confirmed_delivery(ctx, c1, delivery_date="2026-10-05", gross_bushels=12000, moisture_pct=15.0)
        mid = get_success_data(api.get_plan(plan_id, ADVISOR))
        assert mid["status"] == "ACTIVE", (
            "with a second contract still undelivered the cascade must not over-fire"
        )

    def test_final_confirm_auto_closes_plan_and_cancels_targets(self, api):
        """PRD §3.3: "A plan also closes itself automatically when a
        delivery-ticket confirmation leaves the plan with `uncommitted_bushels`
        equal to zero and every sales contract on the plan `DELIVERED`; in that
        event all remaining `PENDING` price targets of the plan move to
        `CANCELLED`, and the same target cancellation applies on an explicit
        close."
        PRD §3.7: "A `DELIVERED` contract stays committed to the plan — the
        plan's `committed_contract_bushels` is retained and
        `uncommitted_bushels` recomputed — and the confirmation that completes
        the last contract evaluates the plan auto-close of §3.3."

        Design: Difficulty/transitive_cascade/delivery_confirm_cascade_to_plan_auto_close
        """
        ctx = setup_active_plan_with_buyer(
            name="Close Farm", risk_profile="AGGRESSIVE", max_priced_pct=1.00
        )
        plan_id = ctx["plan"]["id"]
        target = get_success_data(api.create_price_target(
            {"plan_id": plan_id, "contract_month": "2026-12", "target_price": 4.90, "increment_bushels": 5000}, ADVISOR))
        c1 = create_flat_contract(ctx, bushels=12000, fixed_price=4.50,
                                  delivery_window_start="2026-10-01", delivery_window_end="2026-11-01")
        c2 = create_flat_contract(ctx, bushels=8000, fixed_price=4.60,
                                  delivery_window_start="2026-11-01", delivery_window_end="2026-12-01")
        create_confirmed_delivery(ctx, c1, delivery_date="2026-10-05", gross_bushels=12000, moisture_pct=15.0)
        create_confirmed_delivery(ctx, c2, delivery_date="2026-11-05", gross_bushels=8000, moisture_pct=15.0)
        c2_after = get_success_data(api.get_contract(c2["id"], ADVISOR))
        assert c2_after["fulfillment_status"] == "DELIVERED", "hop 1: confirm delivers the contract"
        plan = get_success_data(api.get_plan(plan_id, ADVISOR))
        assert plan["status"] == "CLOSED", (
            "hop 3: uncommitted == 0 with every contract DELIVERED must auto-close the plan"
        )
        assert plan["uncommitted_bushels"] == 0
        target_after = get_success_data(api.get_price_target(target["id"], ADVISOR))
        assert target_after["status"] == "CANCELLED", "hop 3 side effect: pending targets cancelled on auto-close"


class TestDefaultAndFilters:
    def test_contract_default_penalty_after_window(self, api):
        """PRD §3.7: "Default is an advisor action on an `OPEN` or
        `PARTIALLY_DELIVERED` contract once the logical clock date is past the
        `delivery_window_end` and delivered bushels fall short of the contract
        quantity. Defaulting moves the contract to `DEFAULTED`; when the
        contract is `PRICED` a `default_penalty_dollars` amount is computed as
        the undelivered balance — `bushels` minus `delivered_bushels` —
        multiplied by the greater of zero and the latest settlement price for
        the operation's `primary_commodity` minus the contract's
        `effective_price`, rounded to two decimal places half-up. The
        undelivered balance is released to the plan's `uncommitted_bushels` and
        the over-sold flag is re-evaluated."

        Design: Corner/calculations/contract_default_penalty_after_window
        """
        ctx = setup_active_plan_with_buyer(
            name="Def Farm", risk_profile="AGGRESSIVE", max_priced_pct=1.00
        )
        contract = create_flat_contract(
            ctx, bushels=10000, fixed_price=4.50,
            delivery_window_start="2026-10-01", delivery_window_end="2026-11-01",
        )
        record_settlement_tick(5.00, "2026-11-15")
        set_logical_clock("2026-12-02T00:00:00Z")
        defaulted = get_success_data(api.default_contract(contract["id"], ADVISOR))
        assert defaulted["fulfillment_status"] == "DEFAULTED"
        assert defaulted["default_penalty_dollars"] == pytest.approx(5000.00, abs=0.005), (
            "(10000 - 0) * max(0, 5.00 - 4.50) == 5000.00; got "
            f"{defaulted['default_penalty_dollars']}"
        )
        plan = get_success_data(api.get_plan(ctx["plan"]["id"], ADVISOR))
        assert plan["uncommitted_bushels"] == 20000, "the undelivered balance must be released to the plan"

    def test_list_contracts_filtered_by_buyer(self, api):
        """PRD §4: the `GET /advisory/sales-contracts` row lists contracts with
        a `buyer_id` filter among its parameters.
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."

        Design: Corner/entities/list_contracts_filtered_by_buyer
        """
        ctx = setup_operation_with_active_plan(
            name="FK Farm", risk_profile="AGGRESSIVE", max_priced_pct=1.00
        )
        b1 = create_approved_buyer(name="B1", buyer_type="ELEVATOR", credit_rating="A")
        b2 = create_approved_buyer(name="B2", buyer_type="PROCESSOR", credit_rating="B")
        c1 = get_success_data(api.create_contract(
            create_contract_payload(ctx["operation"]["id"], ctx["plan"]["id"], b1["id"],
                                    bushels=3000, fixed_price=4.50), ADVISOR))
        c2 = get_success_data(api.create_contract(
            create_contract_payload(ctx["operation"]["id"], ctx["plan"]["id"], b2["id"],
                                    bushels=2000, fixed_price=4.60), ADVISOR))
        data, _meta = validate_paginated(api.list_contracts(ADVISOR, params={"buyer_id": b1["id"]}))
        assert len(data) == 1, f"filter must return exactly one contract, got {len(data)}"
        assert data[0]["id"] == c1["id"]
        assert all(row["id"] != c2["id"] for row in data), "the other buyer's contract must be filtered out"


class TestBushelConservation:
    def test_contract_create_cancel_conserve_bushels(self, api):
        """PRD §3.3: "`committed_contract_bushels` is the sum of `bushels` over
        the plan's sales contracts whose `fulfillment_status` is `OPEN`,
        `PARTIALLY_DELIVERED`, or `DELIVERED`; a `CANCELLED` contract releases
        its full commitment and a `DEFAULTED` contract releases its undelivered
        balance. `uncommitted_bushels` is the snapshot minus
        `committed_contract_bushels`."
        PRD §3.7: "Cancellation moves an `OPEN` contract with zero delivered
        bushels to `CANCELLED`, releasing the full commitment back to the
        plan's `uncommitted_bushels`, recomputing `priced_contract_bushels`,
        and re-evaluating the operation's `over_sold_flag`, clearing it when
        undelivered committed bushels once again fit marketable production."

        Design: Difficulty/compensating_invariant/contract_create_cancel_conserve_bushels
        """
        ctx = setup_active_plan_with_buyer(
            name="Inv Farm 1", risk_profile="AGGRESSIVE", max_priced_pct=1.00
        )
        plan_id = ctx["plan"]["id"]
        before = get_success_data(api.get_plan(plan_id, ADVISOR))
        assert before["committed_contract_bushels"] == 0
        assert before["uncommitted_bushels"] == 20000, "sum equals the 20000 snapshot"
        contract = create_flat_contract(ctx, bushels=7500, fixed_price=4.50)
        after_create = get_success_data(api.get_plan(plan_id, ADVISOR))
        assert after_create["committed_contract_bushels"] == 7500
        assert after_create["uncommitted_bushels"] == 12500
        assert (
            after_create["committed_contract_bushels"] + after_create["uncommitted_bushels"] == 20000
        ), "the conserved bushel budget must hold after create"
        get_success_data(api.cancel_contract(contract["id"], make_grower_headers(ctx["operation"]["id"])))
        after_cancel = get_success_data(api.get_plan(plan_id, ADVISOR))
        assert after_cancel["committed_contract_bushels"] == 0
        assert after_cancel["uncommitted_bushels"] == 20000, (
            "forward + compensating action leaves the conserved budget unchanged"
        )

    def test_cancel_releases_full_commitment_and_repriced_counter(self, api):
        """PRD §3.7: "Cancellation moves an `OPEN` contract with zero delivered
        bushels to `CANCELLED`, releasing the full commitment back to the
        plan's `uncommitted_bushels`, recomputing `priced_contract_bushels`,
        and re-evaluating the operation's `over_sold_flag`, clearing it when
        undelivered committed bushels once again fit marketable production."
        PRD §3.3: "`committed_contract_bushels` is the sum of `bushels` over
        the plan's sales contracts whose `fulfillment_status` is `OPEN`,
        `PARTIALLY_DELIVERED`, or `DELIVERED`; a `CANCELLED` contract releases
        its full commitment and a `DEFAULTED` contract releases its undelivered
        balance."

        Design: Difficulty/compensating_invariant/contract_create_cancel_conserve_bushels
        """
        ctx = setup_active_plan_with_buyer(
            name="Inv Farm 1", risk_profile="AGGRESSIVE", max_priced_pct=1.00
        )
        plan_id = ctx["plan"]["id"]
        contract = create_flat_contract(ctx, bushels=7500, fixed_price=4.50)
        mid = get_success_data(api.get_plan(plan_id, ADVISOR))
        assert mid["priced_contract_bushels"] == 7500, "FLAT_PRICE contract counts as priced while OPEN"
        cancelled = get_success_data(
            api.cancel_contract(contract["id"], make_grower_headers(ctx["operation"]["id"]))
        )
        assert cancelled["fulfillment_status"] == "CANCELLED"
        after = get_success_data(api.get_plan(plan_id, ADVISOR))
        assert after["committed_contract_bushels"] == 0, "CANCELLED releases the full commitment"
        assert after["priced_contract_bushels"] == 0, "priced counter recomputed on cancel"
        assert after["uncommitted_bushels"] == 20000, (
            "uncommitted_bushels restored to the exact pre-create value 20000"
        )

    def test_immediate_consistency_read_after_write(self, api):
        """PRD §3.7: "A `FLAT_PRICE` contract is created with `pricing_status`
        equal to `PRICED`; `HTA` and `BASIS` contracts start `UNPRICED`. Every
        contract starts with `fulfillment_status` equal to `OPEN`. Creation
        recomputes the plan's committed, uncommitted, and priced counters."
        PRD §3.3: "`priced_contract_bushels` is the sum of `bushels` over the
        plan's contracts whose `pricing_status` is `PRICED` and whose
        `fulfillment_status` is `OPEN`, `PARTIALLY_DELIVERED`, or `DELIVERED`."

        Design: Corner/consistency_model/immediate_consistency_read_after_write
        """
        ctx = setup_active_plan_with_buyer(
            name="Cons Farm", risk_profile="AGGRESSIVE", max_priced_pct=1.00
        )
        contract = create_flat_contract(ctx, bushels=7500, fixed_price=4.50)
        assert contract["pricing_status"] == "PRICED", "FLAT_PRICE is born PRICED in the create response"
        plan = get_success_data(api.get_plan(ctx["plan"]["id"], ADVISOR))
        assert plan["committed_contract_bushels"] == 7500
        assert plan["uncommitted_bushels"] == 12500
        assert plan["priced_contract_bushels"] == 7500


class TestBuyerStateDependency:
    def test_contract_create_blocked_by_suspended_buyer(self, api):
        """PRD §3.7: "Suspending a buyer leaves existing contracts unaffected
        but causes new sales-contract creation naming that buyer to be rejected
        with `ERR_BUYER_NOT_APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/contract_create_blocked_by_suspended_buyer
        """
        ctx = setup_active_plan_with_buyer(
            name="Dep Farm 1", risk_profile="AGGRESSIVE", max_priced_pct=1.00
        )
        buyer_id = ctx["buyer"]["id"]
        get_success_data(api.suspend_buyer(buyer_id, TEST_USERS["compliance_headers"]))
        resp = api.create_contract(
            create_contract_payload(
                ctx["operation"]["id"], ctx["plan"]["id"], buyer_id,
                bushels=5000, fixed_price=4.50), ADVISOR)
        validate_error(resp, ApiErrorId.ERR_BUYER_NOT_APPROVED)

    def test_reapprove_buyer_restores_contract_creation(self, api):
        """PRD §3.7: "A `ComplianceOfficer` approves a buyer, moving it from
        `PROVISIONAL` to `APPROVED`, and may suspend an `APPROVED` buyer,
        moving it to `SUSPENDED`; approval also lifts a `SUSPENDED` buyer back
        to `APPROVED`, so the approve/suspend cycle is permitted without
        limit. Suspending a buyer leaves existing contracts unaffected but
        causes new sales-contract creation naming that buyer to be rejected
        with `ERR_BUYER_NOT_APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/contract_create_blocked_by_suspended_buyer
        """
        ctx = setup_active_plan_with_buyer(
            name="Dep Farm 1", risk_profile="AGGRESSIVE", max_priced_pct=1.00
        )
        buyer_id = ctx["buyer"]["id"]
        get_success_data(api.suspend_buyer(buyer_id, TEST_USERS["compliance_headers"]))
        reapproved = get_success_data(api.approve_buyer(buyer_id, TEST_USERS["compliance_headers"]))
        assert reapproved["status"] == "APPROVED", "the approve/suspend cycle lifts the buyer back"
        created = api.create_contract(
            create_contract_payload(
                ctx["operation"]["id"], ctx["plan"]["id"], buyer_id,
                bushels=5000, fixed_price=4.50), ADVISOR)
        data = validate_success(created, expected_status=201)
        assert data["buyer_id"] == buyer_id

    def test_buyer_suspend_preserves_existing_contract(self, api):
        """PRD §3.7: "Suspending a buyer leaves existing contracts unaffected
        but causes new sales-contract creation naming that buyer to be rejected
        with `ERR_BUYER_NOT_APPROVED`."

        Design: Corner/state_machines/buyer_suspend_preserves_existing_contract
        """
        ctx = setup_active_plan_with_buyer(
            name="Susp Farm", risk_profile="AGGRESSIVE", max_priced_pct=1.00
        )
        contract = create_flat_contract(ctx, bushels=4000, fixed_price=4.50)
        get_success_data(api.suspend_buyer(ctx["buyer"]["id"], TEST_USERS["compliance_headers"]))
        after = get_success_data(api.get_contract(contract["id"], ADVISOR))
        assert after["fulfillment_status"] == "OPEN", (
            "suspension is prospective only — the existing contract is untouched"
        )
