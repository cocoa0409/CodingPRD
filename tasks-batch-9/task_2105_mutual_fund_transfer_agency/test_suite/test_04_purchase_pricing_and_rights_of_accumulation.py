"""Sales-load pricing: the household basis, the breakpoint tier and the NAV variant."""

from test_helpers import (
    capture_purchase,
    money,
    only_position,
    price_trade,
    read_account,
    read_nav_record,
    read_trade,
    set_clock,
    setup_dual_channel_household,
    setup_linked_household,
    setup_provisional_pricing_scenario,
    setup_settled_purchase,
    setup_trading_desk,
    shares,
    strike_nav,
    pct,
    price,
    validate_paginated,
    validate_success,
    DEFAULT_BREAKPOINT_TIERS,
    TWO_TIER_BREAKPOINT_TIERS,
    TUESDAY,
    TEST_USERS,
)

OPERATOR = TEST_USERS["operator_headers"]
ACCOUNTANT = TEST_USERS["accountant_headers"]

CLOCK_TUESDAY = "2026-08-04T09:00:00Z"


class TestBasisVariantDivergence:
    def test_direct_household_marks_positions_to_market_for_the_qualifying_amount(self, api):
        """PRD §3.2: "Under `MARKET_VALUE_BASIS`, each such position is valued at its
        share balance multiplied by the price of its class on the valuation date in
        question, rounded to cents, and those per-position amounts are then summed; the
        price of a class on a date is the `nav_per_share` of that class's NAV record whose
        `status` is `FINAL` or `CORRECTED` and whose `valuation_date` is on or before the
        date in question, taking the greatest such `valuation_date`, and breaking a tie
        between two records sharing that date in favour of the one with the earlier
        `created_at`."
        PRD §3.5: "Step one computes `roa_qualifying_amount` as the buying account's
        `household_basis_amount` — evaluated under the household rules of §3.2 with the
        valuation date set to the order's `trade_date` — plus the order's `gross_amount`,
        and records which basis variant produced it in `roa_basis_variant`, either
        `MARKET_VALUE_BASIS` or `HISTORICAL_COST_BASIS`."
        PRD §3.5: "Step three computes `sales_load_amount` as `gross_amount` multiplied by
        that percentage, rounded half-up to two decimal places. Step four computes
        `net_invested_amount` as `gross_amount` minus `sales_load_amount`. Step five computes
        `shares_transacted` as `net_invested_amount` divided by the applied NAV, rounded
        half-up to three decimal places, and the result is positive because a purchase adds
        shares."
        PRD §3.5: "In both variants `nav_per_share_applied` records the NAV per share
        actually used."

        Design: Difficulty/dual_variant_calc/roa_basis_variant_diverges_between_direct_and_omnibus_household
        """
        setup = setup_dual_channel_household()
        assert setup["nav_tuesday"]["nav_per_share"] == price(11.0000)

        trade = capture_purchase(
            setup["direct_account"]["id"], setup["share_class"]["id"], 37000.00
        )
        priced = validate_success(api.price_trade(trade["id"], OPERATOR), 200)

        assert priced["roa_basis_variant"] == "MARKET_VALUE_BASIS"
        assert priced["roa_qualifying_amount"] == money(100030.00)
        assert priced["sales_load_pct"] == pct(0.035)
        assert priced["sales_load_amount"] == money(1295.00)
        assert priced["net_invested_amount"] == money(35705.00)
        assert priced["shares_transacted"] == shares(3245.909)
        assert priced["nav_per_share_applied"] == price(11.0000)

    def test_omnibus_household_values_positions_at_historical_cost(self, api):
        """PRD §3.2: "Under `HISTORICAL_COST_BASIS`, every qualifying position contributes
        its `cost_basis_amount` and nothing is marked to market, so appreciation never
        raises the qualifying amount and identical holdings can land in a lower breakpoint
        tier than they would in a direct account."
        PRD §3.5: "Step two selects the tier: among the class's `breakpoint_tiers`, the
        tier chosen is the one with the greatest `min_qualifying_amount` that is less than
        or equal to `roa_qualifying_amount`, and that tier's `load_pct` becomes the order's
        `sales_load_pct`."
        PRD §3.5: "Step three computes `sales_load_amount` as `gross_amount` multiplied by
        that percentage, rounded half-up to two decimal places. Step four computes
        `net_invested_amount` as `gross_amount` minus `sales_load_amount`. Step five computes
        `shares_transacted` as `net_invested_amount` divided by the applied NAV, rounded
        half-up to three decimal places, and the result is positive because a purchase adds
        shares."

        Design: Difficulty/dual_variant_calc/roa_basis_variant_diverges_between_direct_and_omnibus_household
        """
        setup = setup_dual_channel_household()

        direct_trade = capture_purchase(
            setup["direct_account"]["id"], setup["share_class"]["id"], 37000.00
        )
        direct_priced = price_trade(direct_trade["id"])

        omnibus_trade = capture_purchase(
            setup["omnibus_account"]["id"], setup["share_class"]["id"], 37000.00
        )
        omnibus_priced = validate_success(
            api.price_trade(omnibus_trade["id"], OPERATOR), 200
        )

        assert omnibus_priced["roa_basis_variant"] == "HISTORICAL_COST_BASIS"
        assert omnibus_priced["roa_qualifying_amount"] == money(97000.00)
        assert omnibus_priced["sales_load_pct"] == pct(0.045)
        assert omnibus_priced["sales_load_amount"] == money(1665.00)
        assert omnibus_priced["net_invested_amount"] == money(35335.00)
        assert omnibus_priced["shares_transacted"] == shares(3212.273)

        assert direct_priced["shares_transacted"] != shares(
            omnibus_priced["shares_transacted"]
        ), "identical dollars at an identical NAV must diverge across the two variants"


class TestPricingVariantSelection:
    def test_a_preliminary_strike_prices_the_order_provisionally(self, api):
        """PRD §3.5: "When the record is still `PRELIMINARY`, the order prices against the
        preliminary strike, `pricing_variant` is set to `PRELIMINARY_NAV`, and the order
        moves `RECEIVED → PRICED_PROVISIONAL`; provisional pricing touches no position and
        settlement remains blocked."
        PRD §3.5: "Step five computes `shares_transacted` as `net_invested_amount` divided
        by the applied NAV, rounded half-up to three decimal places, and the result is
        positive because a purchase adds shares."

        Design: Difficulty/dual_variant_calc/trade_pricing_variant_provisional_versus_final_share_quantity
        """
        setup = setup_provisional_pricing_scenario()
        assert setup["nav_tuesday"]["nav_per_share"] == price(11.0000)
        assert setup["nav_tuesday"]["status"] == "PRELIMINARY"

        trade = capture_purchase(
            setup["buyer_account"]["id"], setup["share_class"]["id"], 20000.00
        )
        priced = validate_success(api.price_trade(trade["id"], OPERATOR), 200)

        assert priced["pricing_variant"] == "PRELIMINARY_NAV"
        assert priced["execution_status"] == "PRICED_PROVISIONAL"
        assert priced["settlement_status"] == "UNSETTLED"
        assert priced["nav_per_share_applied"] == price(11.0000)
        assert priced["sales_load_amount"] == money(1150.00)
        assert priced["shares_transacted"] == shares(1713.636)

    def test_repricing_after_a_revised_final_strike_overwrites_the_share_quantity(self, api):
        """PRD §3.3: "A record that is still `PRELIMINARY` may be re-struck any number of
        times before it is finalized, leaving it `PRELIMINARY` — the
        `PRELIMINARY → PRELIMINARY` self-transition."
        PRD §3.5: "When the record is `FINAL` or `CORRECTED`, the order prices against the
        final strike, `pricing_variant` is set to `FINAL_NAV`, and the order moves
        either `RECEIVED → PRICED_FINAL` directly or `PRICED_PROVISIONAL → PRICED_FINAL` if
        it had been priced provisionally before; every priced field is recomputed against the final
        NAV, so `shares_transacted` may well differ from the provisional quantity, and it is
        the final quantity that reaches the ledger."

        Design: Difficulty/dual_variant_calc/trade_pricing_variant_provisional_versus_final_share_quantity
        """
        setup = setup_provisional_pricing_scenario()
        trade = capture_purchase(
            setup["buyer_account"]["id"], setup["share_class"]["id"], 20000.00
        )
        provisional = price_trade(trade["id"])
        assert provisional["shares_transacted"] == shares(1713.636)

        reposted = validate_success(
            api.repost_nav_record(
                setup["nav_tuesday"]["id"], {"total_net_assets": 64176.00}, ACCOUNTANT
            ),
            200,
        )
        assert reposted["nav_per_share"] == price(11.2000)
        validate_success(
            api.finalize_nav_record(setup["nav_tuesday"]["id"], ACCOUNTANT), 200
        )

        final = validate_success(api.price_trade(trade["id"], OPERATOR), 200)
        assert final["pricing_variant"] == "FINAL_NAV"
        assert final["execution_status"] == "PRICED_FINAL"
        assert final["settlement_status"] == "UNSETTLED"
        assert final["nav_per_share_applied"] == price(11.2000)
        assert final["shares_transacted"] == shares(1683.036)
        assert final["sales_load_amount"] == money(1150.00)


class TestBreakpointTierPinning:
    def test_the_tier_is_taken_from_the_gross_qualifying_amount(self, api):
        """PRD §3.5: "Step one computes `roa_qualifying_amount` as the buying account's
        `household_basis_amount` — evaluated under the household rules of §3.2 with the
        valuation date set to the order's `trade_date` — plus the order's `gross_amount`,
        and records which basis variant produced it in `roa_basis_variant`, either
        `MARKET_VALUE_BASIS` or `HISTORICAL_COST_BASIS`."
        PRD §3.5: "Step two selects the tier: among the class's `breakpoint_tiers`, the
        tier chosen is the one with the greatest `min_qualifying_amount` that is less than
        or equal to `roa_qualifying_amount`, and that tier's `load_pct` becomes the order's
        `sales_load_pct`."
        PRD §3.5: "Step three computes `sales_load_amount` as `gross_amount` multiplied by
        that percentage, rounded half-up to two decimal places. Step four computes
        `net_invested_amount` as `gross_amount` minus `sales_load_amount`. Step five computes
        `shares_transacted` as `net_invested_amount` divided by the applied NAV, rounded
        half-up to three decimal places, and the result is positive because a purchase adds
        shares."

        Design: Difficulty/combinatorial_formula/breakpoint_tier_resolved_on_gross_amount_before_load_is_deducted
        """
        desk = setup_trading_desk(
            tiers=DEFAULT_BREAKPOINT_TIERS,
            registration_type="TRUST",
            account_overrides={"primary_owner_name": "Borderline Trust"},
        )
        assert desk["account"]["household_basis_amount"] == money(0.00)

        trade = capture_purchase(
            desk["account"]["id"], desk["share_class"]["id"], 51000.00
        )
        priced = validate_success(api.price_trade(trade["id"], OPERATOR), 200)

        assert priced["roa_qualifying_amount"] == money(51000.00)
        assert priced["sales_load_pct"] == pct(0.045)
        assert priced["sales_load_amount"] == money(2295.00)
        assert priced["net_invested_amount"] == money(48705.00)

    def test_the_tier_is_never_re_derived_from_the_net_invested_amount(self, api):
        """PRD §3.5: "Step four computes `net_invested_amount` as `gross_amount` minus
        `sales_load_amount`."
        PRD §3.5: "The tier is selected from the qualifying amount computed in step one and
        is never recomputed against the net amount produced in step four, even though the
        net amount is smaller."

        Design: Difficulty/combinatorial_formula/breakpoint_tier_resolved_on_gross_amount_before_load_is_deducted
        """
        desk = setup_trading_desk(
            tiers=DEFAULT_BREAKPOINT_TIERS,
            registration_type="TRUST",
            account_overrides={"primary_owner_name": "Borderline Trust"},
        )
        trade = capture_purchase(
            desk["account"]["id"], desk["share_class"]["id"], 51000.00
        )
        priced = price_trade(trade["id"])

        assert priced["nav_per_share_applied"] == price(10.0000)
        assert priced["shares_transacted"] == shares(4870.500)
        assert priced["shares_transacted"] != shares(4806.750), (
            "re-deriving the tier from the 48705.00 net amount is explicitly wrong"
        )


class TestHouseholdAggregation:
    def test_a_linked_secondary_account_qualifies_on_the_whole_household(self, api):
        """PRD §3.2: "The household of an account is its primary account together with
        every account linked into that primary; only household members whose `status` is
        `ACTIVE` or `RESTRICTED` participate, and members in `PENDING_DOCS` or `CLOSED`
        contribute `0.00`."
        PRD §3.2: "Accounts may be listed and narrowed by `status`, by `account_channel`,
        by `state_code`, and by `linked_primary_account_id` — the last of which returns the
        household members aggregated into a given primary account."

        Design: Corner/calculations/linked_secondary_account_inherits_the_household_qualifying_amount
        """
        setup = setup_linked_household()

        trade = capture_purchase(
            setup["secondary_account"]["id"], setup["share_class"]["id"], 37000.00
        )
        priced = validate_success(api.price_trade(trade["id"], OPERATOR), 200)

        assert priced["roa_qualifying_amount"] == money(100030.00)
        assert priced["roa_basis_variant"] == "MARKET_VALUE_BASIS"
        assert priced["sales_load_pct"] == pct(0.035)
        assert priced["sales_load_amount"] == money(1295.00)
        assert priced["shares_transacted"] == shares(3245.909)

        household, meta = validate_paginated(
            api.list_shareholder_accounts(
                OPERATOR,
                params={"linked_primary_account_id": setup["primary_account"]["id"]},
            )
        )
        assert meta["total_count"] == 1
        assert household[0]["id"] == setup["secondary_account"]["id"]

    def test_household_basis_moves_on_settlement_and_not_on_a_nav_strike(self, api):
        """PRD §3.2: "The account's `household_basis_amount` is the rights-of-accumulation
        basis of that whole household, recomputed on every position change anywhere in the
        household — trade settlement, trade reversal, restatement following a NAV
        correction, distribution reinvestment and distribution reversal alike — and read
        whenever a purchase or an exchange is priced."
        PRD §3.2: "`current_roa_tier_pct`, the four-decimal sales-load percentage that the
        owning account's `household_basis_amount` currently qualifies for in this class's
        breakpoint schedule; and `market_value_amount`, the position's `shares` multiplied
        by the class's most recent priced NAV, rounded to two decimals."

        Design: Corner/cross_cutting_complexity_layers/household_basis_is_recomputed_on_settlement_not_on_nav_posting
        """
        desk = setup_settled_purchase(
            gross_amount=60000.00,
            tiers=TWO_TIER_BREAKPOINT_TIERS,
            account_overrides={"primary_owner_name": "Derek Rived"},
        )
        assert desk["account"]["household_basis_amount"] == money(57300.00)

        set_clock(CLOCK_TUESDAY)
        nav_tuesday = strike_nav(desk["share_class"]["id"], TUESDAY, 63030.00, finalize=True)
        assert nav_tuesday["nav_per_share"] == price(11.0000)

        after = read_account(desk["account"]["id"])
        assert after["household_basis_amount"] == money(57300.00), (
            "striking and finalizing a NAV is not a position change"
        )
        assert only_position(desk["account"]["id"])["current_roa_tier_pct"] == pct(0.045)
