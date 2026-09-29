"""Multi-term money formulas whose term order and rounding placement are pinned.

Each rule here composes three or more branch tables and would land on a
different integer if any single step were reordered, re-rounded or keyed off the
wrong intermediate.
"""

from test_helpers import (
    FINANCE,
    accept_attribution_for_review,
    api_client,
    assert_instant,
    assert_refund_ledger_identity,
    create_model,
    file_attribution_claim,
    get_success_data,
    read_order,
    request_comfort_exchange,
    resolve_attribution_payload,
    set_clock,
    setup_delivered_order,
    setup_partner_channel_order,
    setup_return_lifecycle,
)

PRORATED_BUNDLE = {
    "code": "SLEEP-KIT-PRO",
    "unwind_policy": "DEDUCT_PRORATED",
    "accessory_retail_cents": 12340,
    "percent_off_bps": 1000,
    "gift_card_cents": 7701,
    "requires_accessory_return": False,
}


class TestBundleUnwindRoundsEachComponentBeforeSumming:
    """A prorated three-gift bundle unwound after 45 of 100 trial nights."""

    def test_each_component_is_rounded_to_whole_cents_before_the_three_are_added(self):
        """PRD §3.8: "Otherwise three components are evaluated in a fixed order and — this matters — **each is rounded to whole cents before they are added**; summing the three exact fractions and rounding once at the end produces a different and incorrect figure."

        With 55 of 100 nights unearned the accessory term is 12340 * 55/100 =
        6787, the discount reallocation is 12000 * 12340 / (12340 + 120000) =
        1119 and the gift card is 7701 * 55/100 = 4235.55 which rounds up to
        4236; the three whole-cent terms sum to 12142, whereas summing the exact
        fractions first would round to 12141.

        Design: Difficulty/combinatorial_formula/bundle_unwind_three_components_rounded_individually_before_summing
        """
        scenario = setup_return_lifecycle(
            stage="INSPECTED", bundle_overrides=PRORATED_BUNDLE
        )
        case = scenario["return_case"]

        assert case["bundle_unwind_cents"] == 12142, (
            "the three components must be rounded individually (6787 + 1119 + "
            f"4236) before summing, got {case['bundle_unwind_cents']}"
        )
        assert case["damage_offset_cents"] == 0, (
            "a grade A unsoiled unit retains nothing, got "
            f"{case['damage_offset_cents']}"
        )

    def test_the_unwind_and_the_usage_proration_both_reduce_the_provisional_refund(self):
        """PRD §3.8: "`provisional_refund_cents` is `gross_refundable_cents` less that provisional proration, less `bundle_unwind_cents`, less `damage_offset_cents`, and at inspection `proration_deduction_cents` holds the provisional figure."

        The 1000-bps promotion discounts the 120000-cent quote by 12000, so the
        principal is 108000; 45 nights of usage prorate 108000 * 45 * 2500 /
        (100 * 10000) = 12150, and 108000 - 12150 - 12142 - 0 = 83708.

        Design: Difficulty/combinatorial_formula/bundle_unwind_three_components_rounded_individually_before_summing
        """
        scenario = setup_return_lifecycle(
            stage="INSPECTED", bundle_overrides=PRORATED_BUNDLE
        )
        case = scenario["return_case"]

        assert case["nights_used"] == 45
        assert case["proration_deduction_cents"] == 12150
        assert case["provisional_refund_cents"] == 83708, (
            "108000 - 12150 - 12142 - 0 = 83708, got "
            f"{case['provisional_refund_cents']}"
        )


class TestExchangeTierCreditIsKeyedOnTheRawDifference:
    """A 19000-cent trade up whose post-fee difference crosses the next tier band."""

    def _requested_exchange(self):
        medium = create_model(
            sku="MDL-Q-MED-X", firmness="MEDIUM", size="QUEEN", list_price_cents=120000
        )
        firm = create_model(
            sku="MDL-Q-FIRM-X", firmness="FIRM", size="QUEEN", list_price_cents=139000
        )
        scenario = setup_delivered_order(
            model=medium,
            customer_overrides={"email": "cf2@example.com", "household_hash": "HH-CF2"},
        )
        set_clock("2026-08-22T00:00:00Z")
        exchange = request_comfort_exchange(
            scenario["order"]["id"], firm["id"], headers=scenario["customer_headers"]
        )
        return exchange

    def test_the_tier_rate_reads_the_raw_difference_not_the_post_fee_difference(self):
        """PRD §3.5: "Fourth, the loyalty tier is chosen from the absolute value of `raw_price_difference_cents`: below 20000 cents the tier credit rate is zero basis points; from 20000 cents up to but not including 50000 cents it is 250 basis points; at 50000 cents and above it is 500 basis points."

        The raw gap between the 139000-cent target and the 120000-cent original
        is 19000, which is below the first band, so the tier credit is zero;
        keying the tier on the 28900-cent post-fee figure instead would award
        250 basis points of the 120000-cent principal.

        Design: Difficulty/combinatorial_formula/exchange_tier_credit_keyed_on_raw_difference_not_post_fee_difference
        """
        exchange = self._requested_exchange()

        assert exchange["raw_price_difference_cents"] == 19000
        assert exchange["tier_credit_cents"] == 0, (
            "a 19000-cent raw difference earns no tier credit, got "
            f"{exchange['tier_credit_cents']}"
        )

    def test_the_first_exchange_in_a_chain_settles_as_a_charge_to_the_customer(self):
        """PRD §3.5: "Sixth, `price_difference_cents` is `raw_price_difference_cents` plus `exchange_fee_cents` less `tier_credit_cents`."

        A first exchange carries `sequence_number` 1 and the base 9900-cent
        handling fee, so the settlement is 19000 + 9900 - 0 = 28900 cents owed
        by the customer and the request opens at REQUESTED.

        Design: Difficulty/combinatorial_formula/exchange_tier_credit_keyed_on_raw_difference_not_post_fee_difference
        """
        exchange = self._requested_exchange()

        assert exchange["sequence_number"] == 1
        assert exchange["exchange_fee_cents"] == 9900
        assert exchange["price_difference_cents"] == 28900, (
            "19000 + 9900 - 0 = 28900, got " f"{exchange['price_difference_cents']}"
        )
        assert exchange["settlement_direction"] == "CHARGE_CUSTOMER"
        assert exchange["status"] == "REQUESTED"


class TestPriceMatchCreditIsCappedUnderTheAdvertisedPolicy:
    """A 20000-cent competitor gap against a MATCH_TO_ADVERTISED partner."""

    def _approved_price_match(self):
        scenario = setup_partner_channel_order(
            partner_overrides={
                "name": "Sleep Barn CA",
                "commission_bps": 500,
                "price_match_policy": "MATCH_TO_ADVERTISED",
                "attribution_window_days": 30,
            },
            model_overrides={"sku": "MDL-Q-MED-P", "list_price_cents": 120000},
            customer_overrides={"email": "cf3@example.com", "household_hash": "HH-CF3"},
        )
        set_clock("2026-08-10T00:00:00Z")
        claim = file_attribution_claim(
            scenario["partner"],
            scenario["order"]["id"],
            "PRICE_MATCH",
            evidence_url_count=2,
            competitor_price_cents=100000,
        )
        accept_attribution_for_review(claim["id"])
        resolved = get_success_data(
            api_client.resolve_attribution_claim(
                claim["id"], resolve_attribution_payload("APPROVE"), FINANCE
            )
        )
        scenario["claim"] = resolved
        return scenario

    def test_the_advertised_policy_caps_the_credit_at_ten_percent_of_the_gross_price(self):
        """PRD §3.10: "Under a `MATCH_TO_ADVERTISED` policy the credit is whichever is smaller of the raw gap and a cap of 1000 basis points of the order's `gross_price_cents` — ten percent — that cap being rounded to the nearest whole cent with ties away from zero."

        The raw gap between the 120000-cent quote and the 100000-cent competitor
        price is 20000, but the cap is 120000 * 1000 / 10000 = 12000, so the
        credit is 12000 and the commission branch stays at zero.

        Design: Difficulty/combinatorial_formula/price_match_credit_branch_table_capped_for_match_to_advertised
        """
        scenario = self._approved_price_match()
        claim = scenario["claim"]

        assert claim["status"] == "APPROVED"
        assert claim["price_match_credit_cents"] == 12000, (
            "the 20000-cent raw gap is capped at ten percent of 120000, got "
            f"{claim['price_match_credit_cents']}"
        )
        assert claim["commission_cents"] == 0, (
            "commission_cents stays zero on a price-match claim, got "
            f"{claim['commission_cents']}"
        )
        assert_instant(claim["resolved_at"], "2026-08-10T00:00:00Z", "resolved_at")

    def test_the_approved_credit_posts_to_the_order_without_touching_the_principal(self):
        """PRD §3.10: "Approving a price-match claim also adds the resulting `price_match_credit_cents` to the order's own `price_match_credit_cents` counter and bumps the order's `version`; the refundable principal is never touched, so `paid_amount_cents` continues to equal `refunded_total_cents` plus `outstanding_refundable_cents` plus `retained_amount_cents`."

        The order's own counter reaches 12000 while the 120000-cent principal
        remains wholly outstanding.

        Design: Difficulty/combinatorial_formula/price_match_credit_branch_table_capped_for_match_to_advertised
        """
        scenario = self._approved_price_match()
        order = read_order(scenario["order"]["id"])

        assert order["price_match_credit_cents"] == 12000
        assert order["paid_amount_cents"] == 120000
        assert order["outstanding_refundable_cents"] == 120000
        assert order["refunded_total_cents"] == 0
        assert_refund_ledger_identity(order)
