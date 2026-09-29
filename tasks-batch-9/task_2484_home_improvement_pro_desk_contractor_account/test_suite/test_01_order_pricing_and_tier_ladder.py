"""Order pricing: tier-review variants, per-unit rounding and the freight waiver."""

from test_helpers import (
    SKU_MORTAR_BAG,
    SKU_SHINGLE_BUNDLE,
    api_client,
    create_draft_order,
    create_pro_account,
    get_success_data,
    make_contractor_admin_headers,
    read_pro_account,
    setup_pro_desk,
    setup_store_with_stock,
    validate_success,
)

# --------------------------------------------------------------------------- #
# Local setup helpers (built from published endpoints only)                    #
# --------------------------------------------------------------------------- #


def _submit(order_id: str, account_id: str) -> dict:
    return validate_success(
        api_client.submit_pro_order(
            order_id, make_contractor_admin_headers(account_id)
        ),
        expected_status=200,
    )


def _read_order(order_id: str, account_id: str) -> dict:
    return validate_success(
        api_client.get_pro_order(order_id, make_contractor_admin_headers(account_id)),
        expected_status=200,
    )


def _preview(order_id: str, account_id: str) -> dict:
    return validate_success(
        api_client.get_pricing_preview(
            order_id, make_contractor_admin_headers(account_id)
        ),
        expected_status=200,
    )


def _setup_two_variant_accounts_with_orders():
    """One stocked store, a PINNED_AT_REVIEW and a ROLLING_365_INCLUSIVE account.

    Both accounts carry 4990000 cents of baseline volume, ten thousand cents
    short of the GOLD opening figure, and each holds a DRAFT will-call card
    order for 100 units of the same SKU.
    """
    store, _stocks = setup_store_with_stock([(SKU_SHINGLE_BUNDLE, 600)])
    pinned = create_pro_account(
        store["id"],
        business_name="Pinned Roofing",
        tier_review_mode="PINNED_AT_REVIEW",
        baseline_volume_cents=4_990_000,
    )
    rolling = create_pro_account(
        store["id"],
        business_name="Rolling Roofing",
        tier_review_mode="ROLLING_365_INCLUSIVE",
        baseline_volume_cents=4_990_000,
    )
    pinned_order, _ = create_draft_order(
        pinned["id"],
        store["id"],
        [(SKU_SHINGLE_BUNDLE, 100)],
        payment_method="CARD",
        delivery_mode="WILL_CALL",
    )
    rolling_order, _ = create_draft_order(
        rolling["id"],
        store["id"],
        [(SKU_SHINGLE_BUNDLE, 100)],
        payment_method="CARD",
        delivery_mode="WILL_CALL",
    )
    return store, pinned, rolling, pinned_order, rolling_order


class TestTierReviewModeDivergenceOnOrderPricing:
    def test_order_pricing_diverges_between_pinned_and_rolling_tier_review_modes(self):
        """PRD §3.2: "Under `PINNED_AT_REVIEW`, order pricing uses the `tier_code` and `tier_discount_pct` already persisted on the account by the most recent tier review; the order being priced never influences its own tier, so an order that would by itself carry the account over a rung's opening volume is still priced at the old rung."

        PRD §3.2: "Under `ROLLING_365_INCLUSIVE`, order pricing first adds the order's own `list_subtotal_cents` — the undiscounted line total, chosen precisely so the computation cannot be circular — to the persisted `trailing_volume_cents`, and matches the ladder against that sum instead."

        PRD §3.2: "For identical stored data the two variants can therefore select different rungs and produce different `subtotal_cents`, `discount_cents`, `tax_cents` and `total_cents` for the same order."

        PRD §3.2: "The rung actually used to price an order is recorded on the order as `tier_code_applied`."

        Design: Difficulty/dual_variant_calc/tier_variant_divergence_pinned_vs_rolling_on_order_pricing
        """
        (
            _store,
            pinned,
            rolling,
            pinned_order,
            rolling_order,
        ) = _setup_two_variant_accounts_with_orders()

        pinned_submitted = _submit(pinned_order["id"], pinned["id"])
        rolling_submitted = _submit(rolling_order["id"], rolling["id"])

        assert pinned_submitted["tier_code_applied"] == "MEMBER"
        assert pinned_submitted["subtotal_cents"] == 199900
        assert pinned_submitted["discount_cents"] == 0
        assert pinned_submitted["tax_cents"] == 16492
        assert pinned_submitted["total_cents"] == 216392

        assert rolling_submitted["tier_code_applied"] == "GOLD"
        assert rolling_submitted["subtotal_cents"] == 189900
        assert rolling_submitted["discount_cents"] == 10000
        assert rolling_submitted["tax_cents"] == 15667
        assert rolling_submitted["total_cents"] == 205567

    def test_pricing_an_order_under_either_variant_leaves_the_persisted_tier_alone(self):
        """PRD §3.2: "Four events in total constitute a tier review: creating the account, booking a trailing-volume correction, invoicing an order, and crediting a return."

        PRD §3.2: "Under `PINNED_AT_REVIEW`, order pricing uses the `tier_code` and `tier_discount_pct` already persisted on the account by the most recent tier review; the order being priced never influences its own tier, so an order that would by itself carry the account over a rung's opening volume is still priced at the old rung."

        Design: Difficulty/dual_variant_calc/tier_variant_divergence_pinned_vs_rolling_on_order_pricing
        """
        (
            _store,
            pinned,
            rolling,
            pinned_order,
            rolling_order,
        ) = _setup_two_variant_accounts_with_orders()

        _submit(pinned_order["id"], pinned["id"])
        _submit(rolling_order["id"], rolling["id"])

        assert read_pro_account(pinned["id"])["tier_code"] == "MEMBER"
        assert read_pro_account(rolling["id"])["tier_code"] == "MEMBER"


class TestPerUnitRoundingBeforeMultiply:
    def test_tier_discount_rounds_at_the_unit_price_before_the_quantity_multiply(self):
        """PRD §3.6: "The discount is applied to the *unit* price and rounded there; only then is the rounded unit price multiplied by the quantity."

        PRD §3.6: "Consider a line with a `list_unit_price_cents` of 1999, a tier discount of 8 percent, and a `qty_units` of 7."

        PRD §3.6: "The discounted unit price is 1839.08 cents, which rounds half up to 1839, and the line subtotal is therefore 12873 cents."

        PRD §3.6: "The rung actually used to price an order is recorded on the order as `tier_code_applied`."

        Design: Difficulty/combinatorial_formula/per_unit_rounding_pinned_before_multiply_mode_b
        """
        scenario = setup_pro_desk(
            tier_code="PLATINUM",
            skus=[(SKU_SHINGLE_BUNDLE, 600)],
            account_overrides={
                "business_name": "Platinum Builders",
                "tier_review_mode": "PINNED_AT_REVIEW",
                "baseline_volume_cents": 20_000_000,
            },
        )
        account = scenario["account"]
        order, order_lines = create_draft_order(
            account["id"],
            scenario["store"]["id"],
            [(SKU_SHINGLE_BUNDLE, 7)],
            payment_method="CARD",
            delivery_mode="WILL_CALL",
        )

        submitted = _submit(order["id"], account["id"])

        assert submitted["tier_code_applied"] == "PLATINUM"

        line = get_success_data(
            api_client.get_order_line(
                order_lines[0]["id"], make_contractor_admin_headers(account["id"])
            )
        )
        assert line["effective_unit_price_cents"] == 1839
        assert line["line_subtotal_cents"] == 12873

    def test_order_subtotal_takes_the_rounded_unit_product_not_the_line_level_discount(
        self,
    ):
        """PRD §3.6: "The alternative reading — multiply the list price by the quantity to get 13993, apply the 8 percent discount to the line to get 12873.56, and round that — yields 12874."

        PRD §3.6: "Implementations must produce 12873."

        PRD §3.6: "The order's `subtotal_cents` is the sum of the lines' `line_subtotal_cents`; its `list_subtotal_cents` is the sum over lines of `list_unit_price_cents` multiplied by `qty_units`; and its `discount_cents` is `list_subtotal_cents` less `subtotal_cents`."

        PRD §3.6: "Finally, `total_cents` is the sum of `subtotal_cents`, `freight_surcharge_cents`, `lift_gate_fee_cents` and `tax_cents`."

        Design: Difficulty/combinatorial_formula/per_unit_rounding_pinned_before_multiply_mode_b
        """
        scenario = setup_pro_desk(
            tier_code="PLATINUM",
            skus=[(SKU_SHINGLE_BUNDLE, 600)],
            account_overrides={
                "business_name": "Platinum Builders",
                "tier_review_mode": "PINNED_AT_REVIEW",
                "baseline_volume_cents": 20_000_000,
            },
        )
        account = scenario["account"]
        order, _order_lines = create_draft_order(
            account["id"],
            scenario["store"]["id"],
            [(SKU_SHINGLE_BUNDLE, 7)],
            payment_method="CARD",
            delivery_mode="WILL_CALL",
        )

        submitted = _submit(order["id"], account["id"])

        assert submitted["list_subtotal_cents"] == 13993
        assert submitted["subtotal_cents"] == 12873
        assert submitted["subtotal_cents"] != 12874
        assert submitted["discount_cents"] == 1120
        assert submitted["tax_cents"] == 1062
        assert submitted["total_cents"] == 13935


class TestFreightWaiverKeyedOnSubtotal:
    @staticmethod
    def _setup_two_lift_gate_delivery_orders():
        scenario = setup_pro_desk(
            tier_code="GOLD",
            skus=[(SKU_SHINGLE_BUNDLE, 600)],
            account_overrides={
                "business_name": "Ridgeline Roofing",
                "tier_review_mode": "PINNED_AT_REVIEW",
                "baseline_volume_cents": 6_000_000,
            },
        )
        account = scenario["account"]
        big_order, _ = create_draft_order(
            account["id"],
            scenario["store"]["id"],
            [(SKU_SHINGLE_BUNDLE, 132)],
            payment_method="CARD",
            delivery_mode="DELIVERY",
            lift_gate_required=True,
        )
        small_order, _ = create_draft_order(
            account["id"],
            scenario["store"]["id"],
            [(SKU_SHINGLE_BUNDLE, 131)],
            payment_method="CARD",
            delivery_mode="DELIVERY",
            lift_gate_required=True,
        )
        return account, big_order, small_order

    def test_freight_waiver_reads_the_post_discount_subtotal_and_spares_the_lift_gate_fee(
        self,
    ):
        """PRD §3.6: "The waiver test is then applied to the base freight, and it is keyed on `subtotal_cents` **only** — the post-discount line total, excluding the surcharge itself, the lift-gate fee and the tax — which is precisely what makes the apparent circularity (the total needs the surcharge, the surcharge seems to need a total) well defined."

        PRD §3.6: "When a `DELIVERY` order's `subtotal_cents` reaches $2,500.00 the freight is waived to 0; the threshold is inclusive, so an order landing exactly on $2,500.00 pays no freight."

        PRD §3.6: "The lift-gate fee is next and it is **never** waived, not even on an order whose freight has been waived: `lift_gate_fee_cents` is $45.00 when the order's `delivery_mode` is `DELIVERY` and its `lift_gate_required` is true, and 0 otherwise."

        Design: Difficulty/combinatorial_formula/freight_waiver_keyed_on_pre_surcharge_subtotal_mode_c
        """
        account, big_order, small_order = self._setup_two_lift_gate_delivery_orders()

        big = _submit(big_order["id"], account["id"])
        small = _submit(small_order["id"], account["id"])

        assert big["subtotal_cents"] == 250668
        assert big["freight_surcharge_cents"] == 0
        assert big["lift_gate_fee_cents"] == 4500

        assert small["subtotal_cents"] == 248769
        assert small["freight_surcharge_cents"] == 8900
        assert small["lift_gate_fee_cents"] == 4500

    def test_smaller_delivery_order_below_the_waiver_totals_more_than_the_larger_one(
        self,
    ):
        """PRD §3.6: "Below it, `freight_surcharge_cents` is the full $89.00."

        PRD §3.6: "The tax base is the sum of `subtotal_cents`, `freight_surcharge_cents` and `lift_gate_fee_cents` — freight and the lift-gate fee are taxable."

        PRD §3.6: "Finally, `total_cents` is the sum of `subtotal_cents`, `freight_surcharge_cents`, `lift_gate_fee_cents` and `tax_cents`."

        Design: Difficulty/combinatorial_formula/freight_waiver_keyed_on_pre_surcharge_subtotal_mode_c
        """
        account, big_order, small_order = self._setup_two_lift_gate_delivery_orders()

        big = _submit(big_order["id"], account["id"])
        small = _submit(small_order["id"], account["id"])

        assert big["tax_cents"] == 21051
        assert big["total_cents"] == 276219

        assert small["tax_cents"] == 21629
        assert small["total_cents"] == 283798

        assert small["total_cents"] > big["total_cents"]


class TestFreightWaiverExactThresholdOnPricingPreview:
    @staticmethod
    def _setup_member_delivery_orders_around_the_threshold():
        scenario = setup_pro_desk(
            tier_code="MEMBER",
            skus=[(SKU_MORTAR_BAG, 600)],
            account_overrides={
                "business_name": "Corner Handyman",
                "tier_review_mode": "PINNED_AT_REVIEW",
                "baseline_volume_cents": 0,
            },
        )
        account = scenario["account"]
        at_threshold_order, _ = create_draft_order(
            account["id"],
            scenario["store"]["id"],
            [(SKU_MORTAR_BAG, 125)],
            payment_method="CARD",
            delivery_mode="DELIVERY",
            lift_gate_required=False,
        )
        below_threshold_order, _ = create_draft_order(
            account["id"],
            scenario["store"]["id"],
            [(SKU_MORTAR_BAG, 124)],
            payment_method="CARD",
            delivery_mode="DELIVERY",
            lift_gate_required=False,
        )
        return account, at_threshold_order, below_threshold_order

    def test_pricing_preview_waives_freight_exactly_on_the_threshold_and_charges_it_one_step_below(
        self,
    ):
        """PRD §3.6: "When a `DELIVERY` order's `subtotal_cents` reaches $2,500.00 the freight is waived to 0; the threshold is inclusive, so an order landing exactly on $2,500.00 pays no freight."

        PRD §3.6: "Below it, `freight_surcharge_cents` is the full $89.00."

        PRD §3.6: "The preview reports `tier_code_applied`, `list_subtotal_cents`, `subtotal_cents`, `discount_cents`, `freight_surcharge_cents`, `lift_gate_fee_cents`, `tax_exempt_applied`, `tax_cents` and `total_cents`."

        Design: Difficulty/boundary_precision_check/freight_waiver_exact_threshold_on_pricing_preview
        """
        (
            account,
            at_threshold_order,
            below_threshold_order,
        ) = self._setup_member_delivery_orders_around_the_threshold()

        at_threshold = _preview(at_threshold_order["id"], account["id"])
        below_threshold = _preview(below_threshold_order["id"], account["id"])

        assert at_threshold["subtotal_cents"] == 250000
        assert at_threshold["freight_surcharge_cents"] == 0
        assert at_threshold["tax_cents"] == 20625
        assert at_threshold["total_cents"] == 270625

        assert below_threshold["subtotal_cents"] == 248000
        assert below_threshold["freight_surcharge_cents"] == 8900
        assert below_threshold["tax_cents"] == 21194
        assert below_threshold["total_cents"] == 278094

    def test_pricing_preview_persists_no_money_on_the_previewed_order(self):
        """PRD §3.6: "Before committing, the contractor or the desk can ask for a **read-only pricing preview**, which runs the whole pricing computation against the current clock and the current tier and persists nothing at all."

        PRD §3.6: "A new order sits at `fulfillment_status` `DRAFT` and `credit_status` `UNBILLED`, with every money field null until it is priced."

        Design: Difficulty/boundary_precision_check/freight_waiver_exact_threshold_on_pricing_preview
        """
        (
            account,
            at_threshold_order,
            _below_threshold_order,
        ) = self._setup_member_delivery_orders_around_the_threshold()

        _preview(at_threshold_order["id"], account["id"])

        stored = _read_order(at_threshold_order["id"], account["id"])
        assert stored["fulfillment_status"] == "DRAFT"
        assert stored["credit_status"] == "UNBILLED"
        assert stored["total_cents"] is None
        assert stored["subtotal_cents"] is None
        assert stored["freight_surcharge_cents"] is None
