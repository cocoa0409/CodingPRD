"""Order pricing: configured list price, tier resolution, rollup, rounding."""
from test_helpers import (
    ApiErrorId,
    assert_order_totals_invariants,
    fixtures as fx,
    validate_error,
    validate_success,
    AE,
    FINANCE,
)

TWO_TIER_CONTRACT = {
    "contract_type": "COOP",
    "pricing_tiers": [
        {"category": "SEATING", "min_qty": 1, "discount_pct": 40},
        {"category": "SEATING", "min_qty": 25, "discount_pct": 45},
    ],
    "default_discount_pct": 30,
}

ARMS_SERIES = {
    "option_catalog": [
        {"option_code": "ARMS", "price_uplift_pct": 10, "extra_lead_days": 5}
    ]
}


class TestTieredNetPrice:
    def test_contract_tiered_net_price_mode_a_volume_tier(self, api):
        """PRD section 3.4: "Each line's configured list price,
        `unit_list_price_cents`, is the series' `base_list_price_cents` scaled
        by one plus the sum of the `price_uplift_pct` values of the selected
        options divided by one hundred, rounded half-up to whole cents." and
        "The net unit price is the list unit price multiplied by one hundred
        minus the applicable discount percent, divided by one hundred, rounded
        half-up to whole cents" and "among the contract's `pricing_tiers`
        entries whose `category` equals the series' category, the applicable
        tier is the one with the largest `min_qty` that is less than or equal
        to the line's `quantity` (the comparison is inclusive, so a `min_qty`
        equal to the quantity qualifies); that tier's `discount_pct` applies."

        Design: Difficulty/combinatorial_formula/contract_tiered_net_price_mode_a
        """
        ctx = fx.setup_draft_order(
            contract_overrides=TWO_TIER_CONTRACT,
            series_overrides=ARMS_SERIES,
            line_overrides={"quantity": 25, "selected_options": ["ARMS"]},
        )
        line = ctx.line
        # 100000 x 1.10 = 110000 list; qty 25 reaches the min_qty-25 tier (45%)
        assert line["unit_list_price_cents"] == 110_000
        assert line["unit_net_price_cents"] == 60_500
        assert line["line_total_cents"] == 1_512_500

    def test_contract_tiered_net_price_mode_a_below_tier(self, api):
        """PRD section 3.4: "the applicable tier is the one with the largest
        `min_qty` that is less than or equal to the line's `quantity` (the
        comparison is inclusive, so a `min_qty` equal to the quantity
        qualifies); that tier's `discount_pct` applies." At quantity 24 the
        min_qty-25 tier is out of reach, so the 40-percent tier applies and the
        unit price is higher than for the larger order.

        Design: Difficulty/combinatorial_formula/contract_tiered_net_price_mode_a
        """
        ctx = fx.setup_draft_order(
            contract_overrides=TWO_TIER_CONTRACT,
            series_overrides=ARMS_SERIES,
            line_overrides={"quantity": 24, "selected_options": ["ARMS"]},
        )
        assert ctx.line["unit_list_price_cents"] == 110_000
        assert ctx.line["unit_net_price_cents"] == 66_000
        assert ctx.line["line_total_cents"] == 1_584_000


class TestPerLineRounding:
    ODD_CONTRACT = {
        "contract_type": "NEGOTIATED",
        "pricing_tiers": [{"category": "SEATING", "min_qty": 1, "discount_pct": 45}],
    }
    ODD_SERIES = {"series_code": "SC-ODD", "base_list_price_cents": 10_101,
                  "base_lead_time_days": 14}

    def test_per_line_rounding_mode_b_unit_price(self, api):
        """PRD section 2.5: "per-unit rounding precedes extension: the net unit
        price of an order line is rounded half-up to whole cents" — 10101 at a
        45-percent discount is 5555.55 before rounding, so the unit price is
        5556.

        Design: Difficulty/combinatorial_formula/per_line_rounding_mode_b
        """
        ctx = fx.setup_draft_order(
            contract_overrides=self.ODD_CONTRACT,
            series_overrides=self.ODD_SERIES,
            line_overrides={"quantity": 3},
        )
        assert ctx.line["unit_net_price_cents"] == 5_556

    def test_per_line_rounding_mode_b_extension_preserved_at_submit(self, api):
        """PRD section 2.5: "so `line_total_cents` is the rounded
        `unit_net_price_cents` times `quantity`" — 5556 x 3 = 16668 (the
        extend-then-round order would give 16667).
        PRD section 3.4: "On a successful submit the order captures
        `pinned_contract_version` from the contract's current `version` and
        `pinned_plan_version` from the plan's `approved_version`; all line
        pricing is recomputed" — the pinned rounding order still holds after
        submit.

        Design: Difficulty/combinatorial_formula/per_line_rounding_mode_b
        """
        ctx = fx.setup_draft_order(
            contract_overrides=self.ODD_CONTRACT,
            series_overrides=self.ODD_SERIES,
            line_overrides={"quantity": 3},
        )
        assert ctx.line["line_total_cents"] == 16_668
        validate_success(api.submit_order(ctx.order["id"], AE))
        line_after = validate_success(api.get_order_line(ctx.line["id"], AE))
        assert line_after["unit_net_price_cents"] == 5_556
        assert line_after["line_total_cents"] == 16_668


class TestOrderRollupPinnedEvaluation:
    ROLLUP_CONTRACT = {
        "pricing_tiers": [
            {"category": "SEATING", "min_qty": 1, "discount_pct": 40},
            {"category": "SEATING", "min_qty": 25, "discount_pct": 45},
            {"category": "TABLES", "min_qty": 1, "discount_pct": 35},
        ],
        "default_discount_pct": 30,
    }

    def _setup(self):
        """Order: 25x SEATING @110000 list + 12x TABLES @200000 list; customer
        holds 1225000 credit (10 items, grade A, appraised 1500000)."""
        ctx = fx.setup_draft_order(
            contract_overrides=self.ROLLUP_CONTRACT,
            series_overrides=ARMS_SERIES,
            line_overrides={"quantity": 25, "selected_options": ["ARMS"]},
        )
        tables = fx.create_series(
            ctx.dealership["id"],
            {
                "manufacturer": "MILLERKNOLL",
                "category": "TABLES",
                "series_code": "MK-TB",
                "base_list_price_cents": 200_000,
                "base_lead_time_days": 20,
            },
        )
        ctx.tables_line = fx.add_line(
            ctx.order["id"], tables["id"], {"quantity": 12}
        )
        ctx.lot = fx.setup_customer_credit(
            ctx.customer["id"], appraised_value_cents=1_500_000,
            condition_grade="A", item_count=10,
        )
        return ctx

    def test_order_rollup_pinned_evaluation_mode_c_totals(self, api):
        """PRD section 3.4: "Fourth, the install fee band is chosen from
        `total_list_cents`: when the list total reaches or exceeds fifty
        thousand dollars (5,000,000 cents) the fee percentage is 8; otherwise it
        is 12. Fifth, `install_fee_cents` is the fee percentage applied to
        `total_net_cents`, rounded half-up to whole cents." — list total
        5150000 selects the 8-percent band even though it is the NET total the
        fee is applied to.

        Design: Difficulty/combinatorial_formula/order_rollup_pinned_evaluation_mode_c
        """
        ctx = self._setup()
        order = validate_success(api.submit_order(ctx.order["id"], AE))
        assert order["total_list_cents"] == 5_150_000   # 2750000 + 2400000
        assert order["total_net_cents"] == 3_072_500    # 1512500 + 1560000
        assert order["install_fee_cents"] == 245_800    # 8% of net, not 12%
        assert order["grand_total_cents"] == 3_318_300
        assert_order_totals_invariants(order)

    def test_order_rollup_pinned_evaluation_mode_c_credit_cap(self, api):
        """PRD section 3.4: "Sixth, the credit cap is computed as the floor of
        the sum of `total_net_cents` and `install_fee_cents` multiplied by the
        dealership's `credit_cap_pct` and divided by one hundred."
        PRD section 3.8: "the resulting `credit_applied_cents` must not exceed
        the order's credit cap — the floor of (`total_net_cents` plus
        `install_fee_cents`) times the dealership's `credit_cap_pct` divided by
        one hundred — else `ERR_CREDIT_CAP_EXCEEDED`".

        Design: Difficulty/combinatorial_formula/order_rollup_pinned_evaluation_mode_c
        """
        ctx = self._setup()
        validate_success(api.submit_order(ctx.order["id"], AE))
        # Cap is floor(3318300 x 25%) = 829575; balance is 1225000.
        resp = api.apply_credit(ctx.order["id"], {"amount_cents": 900_000}, FINANCE)
        validate_error(resp, ApiErrorId.ERR_CREDIT_CAP_EXCEEDED)
        order = validate_success(
            api.apply_credit(ctx.order["id"], {"amount_cents": 829_575}, FINANCE)
        )
        assert order["credit_applied_cents"] == 829_575
        assert order["grand_total_cents"] == 2_488_725
        assert_order_totals_invariants(order)
        customer = validate_success(api.get_customer(ctx.customer["id"], FINANCE))
        assert customer["liquidation_credit_balance_cents"] == 395_425


class TestTierDefaultAndCancelledLines:
    def test_tier_default_when_no_category_match(self, api):
        """PRD section 3.4: "When no tier in the line's category has a
        `min_qty` at or below the quantity, the contract's
        `default_discount_pct` applies instead." A STORAGE line under a
        SEATING-only tier schedule prices at the 30-percent default.

        Design: Corner/calculations/tier_default_when_no_category_match
        """
        ctx = fx.setup_draft_order(
            series_overrides={
                "category": "STORAGE",
                "series_code": "SC-ST",
                "base_lead_time_days": 21,
            },
            line_overrides={"quantity": 2},
        )
        assert ctx.line["unit_net_price_cents"] == 70_000
        assert ctx.line["line_total_cents"] == 140_000

    def test_order_totals_exclude_cancelled_lines(self, api):
        """PRD section 3.4: "First, `total_list_cents` is the sum of each
        non-`CANCELLED` line's `unit_list_price_cents` times its `quantity`."
        and "cancelling it moves the line to `CANCELLED` and recomputes the
        order totals excluding that line."

        Design: Corner/calculations/order_totals_exclude_cancelled_lines
        """
        ctx = fx.setup_draft_order(line_overrides={"quantity": 1})
        second = fx.add_line(ctx.order["id"], ctx.series["id"], {"quantity": 1})
        cancelled = validate_success(api.cancel_order_line(second["id"], AE))
        assert cancelled["status"] == "CANCELLED"
        order = validate_success(api.submit_order(ctx.order["id"], AE))
        assert order["total_list_cents"] == 100_000
        assert order["total_net_cents"] == 60_000
        assert order["install_fee_cents"] == 7_200   # 12% band: list < 5000000
        assert order["grand_total_cents"] == 67_200

    def test_immediate_consistency_submit_response(self, api):
        """PRD section 2.2: "Unless otherwise noted, operations that create or
        modify a resource will return the created or updated resource object in
        the data field." — the submit response itself carries the recomputed
        totals, and a later read returns the same values.
        PRD section 3.4: "order totals are recomputed per the rollup below".

        Design: Corner/consistency_model/immediate_consistency_submit_response
        """
        ctx = fx.setup_draft_order(line_overrides={"quantity": 1})
        order = validate_success(api.submit_order(ctx.order["id"], AE))
        assert order["total_net_cents"] == 60_000
        assert order["install_fee_cents"] == 7_200
        assert order["grand_total_cents"] == 67_200
        reread = validate_success(api.get_project_order(order["id"], AE))
        assert reread["total_net_cents"] == order["total_net_cents"]
        assert reread["install_fee_cents"] == order["install_fee_cents"]
        assert reread["grand_total_cents"] == order["grand_total_cents"]

    def test_unknown_option_code_rejected(self, api):
        """PRD section 3.4: "a `selected_options` array of option codes drawn
        from that series' option catalog; an option code that does not appear
        in the catalog is rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/validations/unknown_option_code_rejected
        """
        ctx = fx.setup_draft_order(series_overrides=ARMS_SERIES)
        resp = api.create_order_line(
            {
                "order_id": ctx.order["id"],
                "series_id": ctx.series["id"],
                "quantity": 1,
                "selected_options": ["NOPE"],
            },
            AE,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
