"""Cafe ordering: per-line rounding order, redemption caps, post-redemption
earning, allergen-vs-fiscal precedence, kitchen state machine, and the
loyalty ledger view (PRD §2.8, §3.6, §3.9)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    get_success_data, ApiErrorId,
    set_clock, reset_clock, run_ops_as_admin,
    setup_cafe_guardian, create_menu_item, place_order, serve_order,
    order_line, seed_points, register_guardian, guardian_headers, add_child,
    make_staff, staff_headers, get_guardian_fresh, assert_loyalty_transaction,
)
from test_helpers import api_client


class TestPerLineRounding:
    def test_cafe_total_per_line_then_sum_rounding(self, api):
        """PRD §3.6: "Pricing pins its rounding order — per line first, then
        sum, never sum-then-round. Each line's total is the `unit_price_cents`
        multiplied by the `quantity` and by one minus the guardian's plan
        `cafe_discount_pct` (zero when membership is not `ACTIVE`), rounded
        half-up to whole cents; the order's `subtotal_cents` is the sum of
        those rounded line totals."

        PLUS 10% member: 3x425 -> round(1275*0.9)=1148; 1x255 ->
        round(255*0.9)=230; subtotal 1378 (sum-then-round would give 1377).
        Redeem 500 (cap floor(1378/2)=689 not hit) -> total 878.

        Design: Difficulty/combinatorial_formula/cafe_total_per_line_then_sum_rounding
        """
        ctx = setup_cafe_guardian(email="g4@x.com", with_plan=True,
                                  seed_point_amount=600)
        muffin = create_menu_item("Muffin", 255, allergen_tags=["WHEAT", "EGG"])
        order = place_order(ctx["guardian"],
                            [order_line(ctx["latte"]["id"], 3),
                             order_line(muffin["id"], 1)],
                            points_to_redeem=500)
        assert order["subtotal_cents"] == 1378
        assert order["points_redeemed"] == 500
        assert order["total_cents"] == 878

    def test_cafe_total_single_units_still_round_per_line(self, api):
        """PRD §3.6: "Pricing pins its rounding order — per line first, then
        sum, never sum-then-round."

        PLUS 10% member, one Latte and one Muffin: round(425*0.9)=383 plus
        round(255*0.9)=230 gives 613; sum-then-round of 680*0.9 would give
        612. The per-line rule pins 613.

        Design: Difficulty/combinatorial_formula/cafe_total_per_line_then_sum_rounding
        """
        ctx = setup_cafe_guardian(email="g4b@x.com", with_plan=True)
        muffin = create_menu_item("Muffin", 255, allergen_tags=["WHEAT", "EGG"])
        order = place_order(ctx["guardian"],
                            [order_line(ctx["latte"]["id"], 1),
                             order_line(muffin["id"], 1)])
        assert order["subtotal_cents"] == 613
        assert order["total_cents"] == 613  # no redemption requested


class TestEarnOnPostRedemptionTotal:
    def test_points_earned_on_post_redemption_total(self, api):
        """PRD §3.9: "At the café, the order totals are computed first,
        redemption is applied second, and only then are points earned — on the
        post-redemption `total_cents` — as one point per whole 100 cents
        (floor division) multiplied by the guardian's tier multiplier: 1 for
        `BRONZE`, 2 for `SILVER`, 3 for `GOLD`, read at the moment of
        earning."

        Subtotal 1378, redeemed 500, total 878 -> floor(878/100)*1 = 8 points
        (the pre-redemption reading floor(1378/100) = 13 would be wrong).

        Design: Difficulty/combinatorial_formula/loyalty_earn_on_post_redemption_total
        """
        ctx = setup_cafe_guardian(email="g5@x.com", with_plan=True,
                                  seed_point_amount=600)
        muffin = create_menu_item("Muffin", 255, allergen_tags=["WHEAT", "EGG"])
        order = place_order(ctx["guardian"],
                            [order_line(ctx["latte"]["id"], 3),
                             order_line(muffin["id"], 1)],
                            points_to_redeem=500)
        served = serve_order(order, ctx["cafe_headers"])
        assert served["points_earned"] == 8
        assert served["status"] == "SERVED"

        g = get_guardian_fresh(ctx["guardian"]["id"], ctx["g_headers"])
        assert g["points_balance"] == 108  # 600 - 500 + 8

    def test_silver_tier_multiplier_applied_at_serve_time(self, api):
        """PRD §3.9: "one point per whole 100 cents (floor division)
        multiplied by the guardian's tier multiplier: 1 for `BRONZE`, 2 for
        `SILVER`, 3 for `GOLD`, read at the moment of earning."

        A guardian whose tier has been recomputed to SILVER (1,000 lifetime
        points) earns floor(425/100) * 2 = 8 points on a 425-cent order.

        Design: Difficulty/combinatorial_formula/loyalty_earn_on_post_redemption_total
        """
        ctx = setup_cafe_guardian(email="g5s@x.com", seed_point_amount=1000)
        run_ops_as_admin()  # recompute tiers from lifetime_points
        g = get_guardian_fresh(ctx["guardian"]["id"], ctx["g_headers"])
        assert g["loyalty_tier"] == "SILVER"

        order = place_order(ctx["guardian"], [order_line(ctx["latte"]["id"], 1)])
        served = serve_order(order, ctx["cafe_headers"])
        assert served["points_earned"] == 8  # floor(425/100) * 2


class TestAllergenSafetyPrecedence:
    def test_cafe_allergen_safety_beats_points_fiscal(self, api):
        """PRD §2.8: "the earliest failing tier determines the error."
        PRD §2.8: "Fifth, business safety: waiver validity, grip-sock
        resolvability, child age, allergen intersection, lost-child gates,
        and child-reunion requirements."
        PRD §2.8: "Eighth, fiscal and quota checks: reservation quota, slot
        capacity, membership and credit sufficiency, and points redemption
        limits."
        PRD §3.6: "no order line's `allergen_tags` may intersect the union of
        the listed children's `allergies`, and a conflict is rejected with
        `ERR_ALLERGEN_CONFLICT` (HTTP 422)".

        An order that both conflicts with a listed child's MILK allergy and
        requests more points than the zero balance must report the safety
        error, not the fiscal one.

        Design: Difficulty/priority_pair_validation_conflict/cafe_allergen_safety_beats_points_fiscal
        """
        ctx = setup_cafe_guardian(email="g10@x.com")  # zero points
        child = add_child(ctx["guardian"], birth_date="2020-01-15",
                          allergies=["MILK"])
        res = api.create_cafe_order(
            {"guardian_id": ctx["guardian"]["id"],
             "lines": [order_line(ctx["latte"]["id"], 1)],  # tagged MILK
             "child_ids": [child["id"]],
             "points_to_redeem": 99999},
            ctx["g_headers"])
        validate_error(res, ApiErrorId.ERR_ALLERGEN_CONFLICT,
                       expected_status=422)

        data, meta = validate_paginated(api.list_guardian_cafe_orders(
            ctx["guardian"]["id"], ctx["g_headers"]))
        assert meta["total_count"] == 0, "no order may be persisted"

    def test_allergen_conflict_beats_redemption_cap_fiscal(self, api):
        """PRD §2.8: "the earliest failing tier determines the error."
        PRD §2.8: "Fifth, business safety: waiver validity, grip-sock
        resolvability, child age, allergen intersection, lost-child gates,
        and child-reunion requirements."
        PRD §2.8: "Eighth, fiscal and quota checks: reservation quota, slot
        capacity, membership and credit sufficiency, and points redemption
        limits."
        PRD §3.6: "a conflict is rejected with `ERR_ALLERGEN_CONFLICT`
        (HTTP 422)".

        With a sufficient points balance but a redemption request above the
        half-subtotal cap AND an allergen conflict, the safety-tier error
        still wins.

        Design: Difficulty/priority_pair_validation_conflict/cafe_allergen_safety_beats_points_fiscal
        """
        ctx = setup_cafe_guardian(email="g10b@x.com", seed_point_amount=500)
        child = add_child(ctx["guardian"], birth_date="2020-01-15",
                          allergies=["MILK"])
        res = api.create_cafe_order(
            {"guardian_id": ctx["guardian"]["id"],
             "lines": [order_line(ctx["latte"]["id"], 1)],  # tagged MILK
             "child_ids": [child["id"]],
             "points_to_redeem": 300},  # over cap floor(425/2)=212
            ctx["g_headers"])
        validate_error(res, ApiErrorId.ERR_ALLERGEN_CONFLICT,
                       expected_status=422)


class TestKitchenStateMachine:
    def test_cafe_order_serve_before_preparing_rejected(self, api):
        """PRD §3.6: "Kitchen workflow is simple: `CafeStaff` (or a `Manager`)
        moves an order from `PLACED` to `PREPARING`, then from `PREPARING` to
        `SERVED`."
        PRD §2.8: "the target resource must be in a valid from-state for the
        requested transition, yielding `ERR_INVALID_STATE` (HTTP 409)".

        Design: Corner/state_machines/cafe_order_serve_before_preparing_rejected
        """
        ctx = setup_cafe_guardian(email="gm@x.com")
        order = place_order(ctx["guardian"], [order_line(ctx["latte"]["id"], 1)])
        res = api.serve_cafe_order(order["id"], ctx["cafe_headers"])
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        fresh = get_success_data(
            api.get_cafe_order(order["id"], ctx["cafe_headers"]))
        assert fresh["status"] == "PLACED"


class TestRedemptionCap:
    def test_redeem_above_cap_returns_redemption_cap_exceeded(self, api):
        """PRD §3.6: "the requested `points_to_redeem` (default 0) may not
        exceed the guardian's `points_balance`, else `ERR_INSUFFICIENT_POINTS`
        (HTTP 402), and may not exceed half of the `subtotal_cents` rounded
        down, else `ERR_REDEMPTION_CAP_EXCEEDED` (HTTP 422)."

        Balance 500 covers the request, but subtotal 425 caps redemption at
        floor(425/2) = 212, so redeeming 300 hits the cap.

        Design: Corner/validations/redeem_above_cap_returns_redemption_cap_exceeded
        """
        ctx = setup_cafe_guardian(email="gw2@x.com", seed_point_amount=500)
        res = api.create_cafe_order(
            {"guardian_id": ctx["guardian"]["id"],
             "lines": [order_line(ctx["latte"]["id"], 1)],
             "child_ids": [], "points_to_redeem": 300},
            ctx["g_headers"])
        validate_error(res, ApiErrorId.ERR_REDEMPTION_CAP_EXCEEDED,
                       expected_status=422)


class TestLoyaltyLedgerView:
    def test_guardian_loyalty_ledger_reverse_lists_transactions(self, api):
        """PRD §3.9: "The loyalty ledger is an append-only series of
        `LoyaltyTransaction` entries per guardian, each with a `kind` of
        `EARN`, `REDEEM`, `REVERSAL`, or `ADJUSTMENT`, a signed `points`
        value" and "a `balance_after` snapshot of the guardian's
        `points_balance` immediately after the entry."
        PRD §2.3: "Unless otherwise specified, every list endpoint returns
        resources sorted by their creation timestamp in ascending order."

        A +50 ADJUSTMENT followed by a served 425-cent order (EARN +4 at
        BRONZE) lists two entries in creation order, the last with
        balance_after 54.

        Design: Corner/endpoints/guardian_loyalty_ledger_reverse_lists_transactions
        """
        ctx = setup_cafe_guardian(email="gz2@x.com", seed_point_amount=50)
        order = place_order(ctx["guardian"], [order_line(ctx["latte"]["id"], 1)])
        served = serve_order(order, ctx["cafe_headers"])
        assert served["points_earned"] == 4  # floor(425/100) * 1

        data, meta = validate_paginated(api.list_loyalty_ledger(
            ctx["guardian"]["id"], ctx["g_headers"]))
        assert meta["total_count"] == 2
        for entry in data:
            assert_loyalty_transaction(entry)
        assert data[0]["kind"] == "ADJUSTMENT" and data[0]["points"] == 50
        assert data[1]["kind"] == "EARN" and data[1]["points"] == 4
        assert data[1]["balance_after"] == 54
