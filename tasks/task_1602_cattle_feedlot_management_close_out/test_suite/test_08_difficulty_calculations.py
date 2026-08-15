"""Deep calculation tests: dual-variant cost-of-gain and grid pricing, feed-call
quantity branch/clamp interaction, pinned allocation rounding order, pinned
invoice evaluation order, and boundary-precision caps."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assign_pen,
    assign_ration,
    confirm_close_out,
    create_draft_close_out,
    create_hedge,
    create_lot,
    create_owner,
    create_pen,
    create_ration,
    get_lot,
    get_pen,
    list_lot_close_outs,
    list_lot_invoices,
    market_lot,
    market_ship_and_draft_close_out,
    post_first_feed_call,
    post_next_feed_call,
    set_clock,
    setup_commingled_pen,
    setup_full_cost_lifecycle,
    ship_lot,
    validate_error,
)

FYM = TEST_USERS["feedyard_manager_headers"]
RM = TEST_USERS["risk_manager_headers"]

# Nine carcass records matching a 9-head shipment: 3 PRIME/YG2 at 510 lbs,
# 4 CHOICE/YG3 at 495 lbs, 2 SELECT/YG4 at 477 lbs.
NINE_HEAD_CARCASSES = (
    [{"hot_carcass_weight_lbs": 510, "quality_grade": "PRIME", "yield_grade": 2}] * 3
    + [{"hot_carcass_weight_lbs": 495, "quality_grade": "CHOICE", "yield_grade": 3}] * 4
    + [{"hot_carcass_weight_lbs": 477, "quality_grade": "SELECT", "yield_grade": 4}] * 2
)

TWO_HEAD_CARCASSES = [
    {"hot_carcass_weight_lbs": 763, "quality_grade": "CHOICE", "yield_grade": 2},
    {"hot_carcass_weight_lbs": 812, "quality_grade": "SELECT", "yield_grade": 4},
]


class TestCostOfGainDualVariant:
    """Provisional (forward-looking ADG projection, yardage to the current
    clock date) vs final (actual pay weights at close-out, yardage to the ship
    date) cost of gain over identical cost data."""

    def _build_full_cost_lot(self):
        ws = setup_full_cost_lifecycle(owner_name="O-100", pen_code="A-01",
                                       ration_name="R1-START", lot_number="L-100")
        return ws

    def test_provisional_cog_uses_projected_gain(self, api):
        """PRD §3.7: "Its cost pool is the purchase cost plus feed, provisional
        yardage over the window from arrival up to but not including the current
        logical date, health, and death-loss costs; its projected gain is the
        lot's `head_count_current` multiplied by the whole days on feed (the
        current logical date minus the arrival date, in whole days) and by an
        assumed average daily gain of 3.4 pounds per head per day; the pool
        divided by that gain, expressed in hundredweight and rounded half up to
        two decimal places, is the provisional value"

        Design: Difficulty/dual_variant_calc/cog_provisional_vs_final_diverge
        """
        ws = self._build_full_cost_lot()
        prov = ws["lot"]["provisional_cog_cents_per_cwt"]
        assert prov == pytest.approx(2530392.16, abs=0.01), (
            "Provisional variant: pool 1548600c / projected gain 0.612 cwt "
            "(9 head x 2 days on feed x 3.4 lbs)"
        )

    def test_final_cog_uses_actual_pay_weights(self, api):
        """PRD §3.7: "`final_cog_cents_per_cwt` divides that pool by the lot's
        gained hundredweight, where the gained weight is the `out_weight_total_lbs`
        minus the in-weight attributable to shipped head (`in_weight_total_lbs`
        multiplied by `head_shipped` and divided by `head_count_in`, so dead-head
        in-weight is excluded), the whole difference divided by one hundred"
        PRD §3.7: "Under `PER_CARCASS`, each record's value is its
        `hot_carcass_weight_lbs` divided by one hundred and multiplied by the
        base price plus that record's two adjustments, with each per-record line
        rounded half up to two decimal places first, and `total_grid_value_cents`
        is the sum of those rounded lines."

        Design: Difficulty/dual_variant_calc/cog_provisional_vs_final_diverge
        """
        ws = self._build_full_cost_lot()
        prov = ws["lot"]["provisional_cog_cents_per_cwt"]
        market_ship_and_draft_close_out(ws, "2026-08-03", 7200,
                                        grid_base_price_cents_per_cwt=19000)
        close_out = confirm_close_out(ws["close_out"]["id"], NINE_HEAD_CARCASSES)

        assert close_out["total_cost_cents"] == 1548600, (
            "1400000 purchase + 2000 feed + 855 yardage (19 head-days x 45c) "
            "+ 5000 health + 140745 death loss"
        )
        assert close_out["final_cog_cents_per_cwt"] == pytest.approx(
            172066.67, abs=0.01), (
            "Final variant: pool 1548600c / actual gain 9.0 cwt "
            "(7200 out - 7000 x 9/10 shipped-head in-weight)"
        )
        assert close_out["final_cog_cents_per_cwt"] != pytest.approx(
            prov, abs=0.01), (
            "Identical cost accumulators, two pinned variants, different results"
        )
        assert close_out["total_grid_value_cents"] == pytest.approx(
            833328.0, abs=0.01), (
            "3 x 5.10 cwt x 20400 + 4 x 4.95 cwt x 19000 + 2 x 4.77 cwt x 15200"
        )
        assert close_out["net_result_cents"] == pytest.approx(-715272.0, abs=0.01), (
            "grid value 833328 + hedge P&L 0 - total cost 1548600"
        )


class TestGridValueDualVariant:
    """PER_CARCASS rounds each carcass line to cents then sums; LOT_AVERAGE
    rounds weight-averaged adjustments then applies once."""

    def _build_two_closeouts(self, api):
        set_clock("2026-08-02T00:00:00Z")
        owner = create_owner(owner_name="O-200", billing_email="o200@x.com")
        lot = create_lot(owner["id"], lot_number="L-200", sex_class="HEIFER",
                         head_count_in=2, in_weight_total_lbs=1400,
                         purchase_cost_cents=280000)
        lot = market_lot(lot["id"])
        lot = ship_lot(lot["id"], "2026-08-02", 1500)
        co1 = create_draft_close_out(lot["id"], lot["version"],
                                     pricing_basis="PER_CARCASS",
                                     grid_base_price_cents_per_cwt=18537)
        co1 = confirm_close_out(co1["id"], TWO_HEAD_CARCASSES)
        lot_now = get_lot(lot["id"])
        co2 = create_draft_close_out(lot["id"], lot_now["version"],
                                     pricing_basis="LOT_AVERAGE",
                                     grid_base_price_cents_per_cwt=18537)
        co2 = confirm_close_out(co2["id"], TWO_HEAD_CARCASSES)
        return lot, co1, co2

    def test_per_carcass_rounds_each_line_then_sums(self, api):
        """PRD §3.7: "Under `PER_CARCASS`, each record's value is its
        `hot_carcass_weight_lbs` divided by one hundred and multiplied by the
        base price plus that record's two adjustments, with each per-record line
        rounded half up to two decimal places first, and `total_grid_value_cents`
        is the sum of those rounded lines."
        PRD §3.7: "any prior `CONFIRMED` close-out for the same lot becomes
        `SUPERSEDED`"

        Design: Difficulty/dual_variant_calc/grid_value_per_carcass_vs_lot_average_diverge
        """
        lot, co1, co2 = self._build_two_closeouts(api)
        assert co1["total_grid_value_cents"] == pytest.approx(262627.75, abs=0.01), (
            "7.63 cwt x (18537+0+200) + 8.12 cwt x (18537-1800-2000), each line "
            "rounded to cents first"
        )
        statuses = {co["id"]: co["status"] for co in list_lot_close_outs(lot["id"])}
        assert statuses[co1["id"]] == "SUPERSEDED"
        assert statuses[co2["id"]] == "CONFIRMED"

    def test_lot_average_rounds_adjustments_then_applies_once(self, api):
        """PRD §3.7: "Under `LOT_AVERAGE`, a weight-averaged quality adjustment
        is computed as the sum of each record's quality premium multiplied by its
        carcass weight, divided by the total carcass weight and rounded half up
        to two decimal places; the yield adjustment is averaged the same way; the
        average price is the base plus the two averaged adjustments; and
        `total_grid_value_cents` is the total carcass weight divided by one
        hundred and multiplied by that average price, rounded half up to two
        decimal places as a single final rounding."

        Design: Difficulty/dual_variant_calc/grid_value_per_carcass_vs_lot_average_diverge
        """
        _, co1, co2 = self._build_two_closeouts(api)
        assert co2["total_grid_value_cents"] == pytest.approx(262627.79, abs=0.01), (
            "avg_qp -928.00, avg_yd -934.22 -> avg price 16674.78; "
            "15.75 cwt x 16674.78 = 262627.785 -> round half up"
        )
        assert co2["total_grid_value_cents"] != pytest.approx(
            co1["total_grid_value_cents"], abs=0.01), (
            "Identical carcass data and base price; the pinned pricing_basis "
            "variant alone changes the result"
        )


class TestFeedCallQuantityEngine:
    """Bunk-score branch deltas, the [8.0, 30.0] clamp, and per-head rounding
    composed with live occupancy and ration cost."""

    def _build_two_pen_setup(self):
        owner = create_owner(owner_name="O-300", billing_email="o300@x.com")
        pen1 = create_pen(pen_code="B-01", capacity_head=200)
        pen2 = create_pen(pen_code="B-02", capacity_head=100)
        ration = create_ration(ration_name="R-GROW", step_level=1,
                               cost_per_ton_cents=20000)
        lot1 = create_lot(owner["id"], lot_number="L-301", head_count_in=100,
                          in_weight_total_lbs=70000, purchase_cost_cents=14000000)
        lot2 = create_lot(owner["id"], lot_number="L-302", head_count_in=50,
                          in_weight_total_lbs=35000, purchase_cost_cents=7000000)
        assign_pen(pen1["id"], lot1["id"], 100)
        assign_pen(pen2["id"], lot2["id"], 50)
        assign_ration(lot1["id"], ration["id"], end_date="2026-08-10")
        assign_ration(lot2["id"], ration["id"], end_date="2026-08-10")
        post_first_feed_call(pen1["id"], "2026-08-01", 24.0)
        post_first_feed_call(pen2["id"], "2026-08-01", 29.8)
        return {"pen1": pen1, "pen2": pen2, "lot1": lot1, "lot2": lot2}

    def test_bunk_score_branch_and_clamp_on_call_outputs(self, api):
        """PRD §3.3: "a score of 0 adds three quarters of a pound per head ... The
        adjusted figure is clamped to a floor of 8.0 pounds and a ceiling of 30.0
        pounds per head, and the result is rounded half up to the nearest tenth
        of a pound to become the call's `qty_lbs_per_head`. The call's
        `total_qty_lbs` is the per-head quantity multiplied by the pen's
        `current_occupancy_head`, rounded half up to a whole pound, and its
        `total_cost_cents` is that total divided by two thousand (converting
        pounds to tons) and multiplied by the ration's `cost_per_ton_cents`,
        rounded half up to a whole cent."

        Design: Difficulty/combinatorial_formula/feed_call_bunk_score_branch_and_clamp
        """
        ws = self._build_two_pen_setup()
        call1 = post_next_feed_call(ws["pen1"]["id"], "2026-08-02", 0)
        assert call1["qty_lbs_per_head"] == pytest.approx(24.8, abs=1e-9), (
            "24.0 + 0.75 = 24.75 rounds half up to 24.8"
        )
        assert call1["total_qty_lbs"] == 2480
        assert call1["total_cost_cents"] == 24800, "2480 / 2000 x 20000"

        call2 = post_next_feed_call(ws["pen2"]["id"], "2026-08-02", 0)
        assert call2["qty_lbs_per_head"] == pytest.approx(30.0, abs=1e-9), (
            "29.8 + 0.75 = 30.55 hits the 30.0 ceiling clamp branch"
        )
        assert call2["total_qty_lbs"] == 1500
        assert call2["total_cost_cents"] == 15000

    def test_feed_cost_accumulates_to_lots(self, api):
        """PRD §3.3: "Each assignment's share is added to its lot's
        `total_feed_cost_cents`, and each affected lot's `version` increments."

        Design: Difficulty/combinatorial_formula/feed_call_bunk_score_branch_and_clamp
        """
        ws = self._build_two_pen_setup()
        post_next_feed_call(ws["pen1"]["id"], "2026-08-02", 0)
        post_next_feed_call(ws["pen2"]["id"], "2026-08-02", 0)
        assert get_lot(ws["lot1"]["id"])["total_feed_cost_cents"] == 48800, (
            "24000 from the 2026-08-01 baseline call + 24800 from the bunk-0 call"
        )
        assert get_lot(ws["lot2"]["id"])["total_feed_cost_cents"] == 29900, (
            "14900 + 15000"
        )


class TestFeedAllocationRoundingOrder:
    """Non-final shares round to whole cents first; the latest-created
    assignment takes the residual."""

    def _build_three_lot_pen(self):
        return setup_commingled_pen(
            pen_code="C-01", ration_name="R-FIN",
            ration_cost_per_ton_cents=19998, owner_name="O-400",
            lot_specs=[
                {"lot_number": "L-401", "head_count_in": 20,
                 "in_weight_total_lbs": 14000, "purchase_cost_cents": 2800000},
                {"lot_number": "L-402", "head_count_in": 30,
                 "in_weight_total_lbs": 21000, "purchase_cost_cents": 4200000},
                {"lot_number": "L-403", "head_count_in": 50,
                 "in_weight_total_lbs": 35000, "purchase_cost_cents": 7000000},
            ],
        )

    def test_allocation_total_and_conservation(self, api):
        """PRD §3.3: "Rounding each share independently and summing is forbidden,
        because it can drift from the true total; the pinned order is round every
        non-final share first, then assign the residual."

        Design: Difficulty/combinatorial_formula/feed_cost_allocation_rounding_order
        """
        ws = self._build_three_lot_pen()
        call = post_first_feed_call(ws["pen"]["id"], "2026-08-01", 10.0)
        assert call["total_cost_cents"] == 9999, "1000 lbs / 2000 x 19998"
        total = sum(get_lot(lot["id"])["total_feed_cost_cents"]
                    for lot in ws["lots"])
        assert total == 9999, "The pinned rounding order conserves the total"

    def test_residual_goes_to_latest_created_assignment(self, api):
        """PRD §3.3: "Every assignment except the last in that order receives a
        share of the total proportional to its head, rounded half up to whole
        cents; the last-created assignment receives the residual — the total
        minus the sum of the prior rounded shares."

        Design: Difficulty/combinatorial_formula/feed_cost_allocation_rounding_order
        """
        ws = self._build_three_lot_pen()
        post_first_feed_call(ws["pen"]["id"], "2026-08-01", 10.0)
        fa = get_lot(ws["lots"][0]["id"])["total_feed_cost_cents"]
        fb = get_lot(ws["lots"][1]["id"])["total_feed_cost_cents"]
        fc = get_lot(ws["lots"][2]["id"])["total_feed_cost_cents"]
        assert fa == 2000, "round_half_up(9999 x 20/100) = round_half_up(1999.8)"
        assert fb == 3000, "round_half_up(9999 x 30/100) = round_half_up(2999.7)"
        assert fc == 4999, (
            "Residual 9999 - 5000, NOT round_half_up(4999.5) = 5000; independent "
            "per-share rounding would drift to 10000"
        )


class TestInvoiceEvaluationOrder:
    """The invoice's death-loss line reads accruals only through the loss date;
    the insurance recovery is netted last."""

    def _confirm_full_cost_lot(self):
        ws = setup_full_cost_lifecycle(owner_name="O-500", pen_code="A-02",
                                       ration_name="R1-500", lot_number="L-500")
        market_ship_and_draft_close_out(ws, "2026-08-03", 7200,
                                        grid_base_price_cents_per_cwt=19000)
        confirm_close_out(ws["close_out"]["id"], NINE_HEAD_CARCASSES)
        invoice = list_lot_invoices(ws["lot"]["id"])[0]
        return ws, invoice

    def test_feed_yardage_and_health_lines(self, api):
        """PRD §3.7: "The invoice's feed line `feed_cents` is the lot's
        `total_feed_cost_cents` at that moment ... For the final variant the
        window runs from `arrival_date` up to but not including the ship date;
        `yardage_cents` is the resulting head-days multiplied by the yardage rate
        of 45 cents per head-day. The health line `health_cents` is
        `total_health_cost_cents` at confirm"
        PRD §3.7: "each day-segment contributing its head count (after applying
        death allocations with a loss date on or before the segment start, since
        a death reduces the count for dates from its loss date onward, not for
        earlier dates)"

        Design: Difficulty/combinatorial_formula/invoice_evaluation_order_death_charge_uses_pre_loss_accrual
        """
        _, invoice = self._confirm_full_cost_lot()
        assert invoice["feed_cents"] == 2000, "Step (1): feed at confirm"
        assert invoice["health_cents"] == 5000, "Step (3): health at confirm"
        assert invoice["yardage_head_days"] == 19, (
            "10 head on 2026-08-01 + 9 head on 2026-08-02 (the 2026-08-02 death "
            "reduces the count from that date forward)"
        )
        assert invoice["yardage_cents"] == 855, "19 head-days x 45 cents"

    def test_death_charge_pre_loss_accrual_and_credit_last(self, api):
        """PRD §3.7: "the death-loss line `death_loss_cents` is
        `total_death_loss_cents` — each loss already pinned at its own loss date,
        never repriced from invoice totals. The invoice's `insurance_credit_cents`
        is the smaller of the lot's `insurance_credit_pending_cents` and the sum
        of the four charge lines, and that credit is then subtracted from the
        pending balance; `total_cents` is the feed, yardage, health, and
        death-loss lines summed, minus the insurance credit. This pinned
        evaluation order — feed, then yardage, then health, then death loss, then
        the credit — is what breaks the apparent circularity among the lines."

        Design: Difficulty/combinatorial_formula/invoice_evaluation_order_death_charge_uses_pre_loss_accrual
        """
        _, invoice = self._confirm_full_cost_lot()
        assert invoice["death_loss_cents"] == 140745, (
            "Step (4): 140000 in-cost/head + 745 pre-loss accrual/head "
            "((2000 feed + 450 yardage + 5000 health) / 10 head); evaluating "
            "against final costs would wrongly give 140786"
        )
        assert invoice["insurance_credit_cents"] == 140745, (
            "Step (5): the PAID recovery is netted last, after the death charge "
            "is fixed"
        )
        assert invoice["total_cents"] == 7855, (
            "2000 + 855 + 5000 + 140745 - 140745"
        )


class TestHedgeCoverageBoundary:
    """Marketable-cwt cap: exactly 100% coverage is allowed; one more contract
    is rejected."""

    def _build_coverage_lot(self):
        owner = create_owner(owner_name="O-801", billing_email="o801@x.com")
        return create_lot(owner["id"], lot_number="L-801", head_count_in=80,
                          in_weight_total_lbs=80000, purchase_cost_cents=9600000)

    def test_hedge_coverage_exactly_full_allowed(self, api):
        """PRD §3.6: "the candidate position plus every `OPEN` position on the
        lot must not exceed that marketable figure; exceeding it is an
        `ERR_HEDGE_OVER_COVERED` (HTTP 422), while landing exactly on the cap is
        allowed."

        Design: Difficulty/boundary_precision_check/hedge_coverage_exactly_full_allowed
        """
        lot = self._build_coverage_lot()
        hedge = create_hedge(lot["id"], lot["version"], quantity_contracts=3,
                             entry_price_cents_per_cwt=19000)
        assert hedge["status"] == "OPEN", (
            "3 contracts x 400 cwt = 1200 <= 1200 marketable: exact 100% "
            "coverage is allowed"
        )

    def test_hedge_coverage_one_contract_over_rejected(self, api):
        """PRD §3.6: "The lot's marketable hundredweight is computed by
        multiplying the lot's `head_count_current` by its `in_weight_total_lbs`,
        multiplying by three, and dividing by the product of `head_count_in` and
        two hundred — equivalently, the current head times the average in-weight
        per head times a factor of one and a half, expressed in hundredweight —
        rounded half up to a whole hundredweight. Each live-cattle contract
        covers 400 hundredweight, so the candidate position plus every `OPEN`
        position on the lot must not exceed that marketable figure; exceeding it
        is an `ERR_HEDGE_OVER_COVERED` (HTTP 422)"

        Design: Difficulty/boundary_precision_check/hedge_coverage_exactly_full_allowed
        """
        lot = self._build_coverage_lot()
        create_hedge(lot["id"], lot["version"], quantity_contracts=3,
                     entry_price_cents_per_cwt=19000)
        fresh_version = get_lot(lot["id"])["version"]
        resp = api.create_hedge(
            {"lot_id": lot["id"], "contract_month": "2026-12",
             "quantity_contracts": 1, "entry_price_cents_per_cwt": 19000,
             "expected_lot_version": fresh_version},
            RM,
        )
        validate_error(resp, ApiErrorId.ERR_HEDGE_OVER_COVERED)


class TestPenCapacityBoundary:
    """Summed head over overlapping compatible assignments vs pen capacity:
    exactly at the cap is allowed; one head over is rejected."""

    def _build_capacity_setup(self):
        owner = create_owner(owner_name="O-802", billing_email="o802@x.com")
        pen = create_pen(pen_code="F-01", capacity_head=10)
        ration = create_ration(ration_name="R-F802", step_level=1,
                               cost_per_ton_cents=20000)
        specs = [("L-802", 6, 4200, 840000), ("L-803", 4, 2800, 560000),
                 ("L-804", 1, 700, 140000)]
        lots = [create_lot(owner["id"], lot_number=num, head_count_in=head,
                           in_weight_total_lbs=w, purchase_cost_cents=cost,
                           commingle_allowed=True)
                for num, head, w, cost in specs]
        for lot in lots:
            assign_ration(lot["id"], ration["id"], end_date="2026-09-01")
        return pen, lots

    def test_pen_capacity_exactly_at_limit_allowed(self, api):
        """PRD §3.2: "Capacity is enforced day by day: the summed head over
        overlapping compatible assignments must not exceed the pen's
        `capacity_head` on any day of the overlap, or the request fails with
        `ERR_PEN_CAPACITY_EXCEEDED` (HTTP 409)."
        PRD §2.9: "A pen's `current_occupancy_head` is always the sum of
        `head_count` over that pen's `ACTIVE` pen assignments"

        Design: Difficulty/boundary_precision_check/pen_capacity_exactly_at_limit_allowed
        """
        pen, lots = self._build_capacity_setup()
        assign_pen(pen["id"], lots[0]["id"], 6)
        assign_pen(pen["id"], lots[1]["id"], 4)
        assert get_pen(pen["id"])["current_occupancy_head"] == 10, (
            "6 + 4 == 10 == capacity: exactly-at-limit is allowed"
        )

    def test_pen_capacity_one_head_over_rejected(self, api):
        """PRD §3.2: "Capacity is enforced day by day: the summed head over
        overlapping compatible assignments must not exceed the pen's
        `capacity_head` on any day of the overlap, or the request fails with
        `ERR_PEN_CAPACITY_EXCEEDED` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/pen_capacity_exactly_at_limit_allowed
        """
        pen, lots = self._build_capacity_setup()
        assign_pen(pen["id"], lots[0]["id"], 6)
        assign_pen(pen["id"], lots[1]["id"], 4)
        resp = api.create_assignment(
            {"pen_id": pen["id"], "lot_id": lots[2]["id"], "head_count": 1,
             "start_date": "2026-08-01"},
            FYM,
        )
        validate_error(resp, ApiErrorId.ERR_PEN_CAPACITY_EXCEEDED)
        assert get_pen(pen["id"])["current_occupancy_head"] == 10, (
            "The rejected assignment adds nothing to occupancy"
        )
