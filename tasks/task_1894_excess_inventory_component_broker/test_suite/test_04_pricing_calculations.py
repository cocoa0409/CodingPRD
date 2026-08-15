"""Pricing calculations: dual carrying-value bases, provisional vs final
settlement pricing, age buckets, volatility dampener, credit exposure."""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_seller, create_customer, create_bin, create_lot, create_active_listing,
    place_order, fund_order_fully, advance_order_to_delivered,
    set_clock, post_snapshot,
    setup_listed_broker_owned_scenario, setup_listed_consignment_scenario,
    setup_delivered_order,
    make_customer_headers,
    api_client,
    TEST_USERS,
    ApiErrorId,
)

BROKER = TEST_USERS["broker_ops_headers"]
FINANCE = TEST_USERS["finance_admin_headers"]


class TestCarryingValueDualBasis:
    def test_straight_line_basis_decays_with_age(self, api):
        """PRD section 3.3: "The straight-line basis,
        `carrying_value_straight_line_cents`, decays the cost of on-hand units
        over a 365-day horizon: it is the per-unit `cost_basis_per_unit_cents`
        multiplied by the on-hand unit count — `qty_available` plus
        `qty_reserved` — then multiplied by the fraction of the horizon
        remaining, which is one minus the number of whole days elapsed since
        `received_at` divided by 365, floored at zero so a lot a full year old
        or older carries nothing, with the final figure rounded half-up to a
        whole cent."

        Design: Difficulty/dual_variant_calc/lot_carrying_value_straight_line_vs_mark_to_market
        """
        seller = create_seller(name="Acme Surplus")
        storage_bin = create_bin(capacity_units=100, bin_code="BIN-A1")
        lot, _ = create_lot(
            seller, storage_bin, mpn="LM317T", quantity=10,
            ask_price_per_unit_cents=10000, agreed_unit_price_cents=10000,
            provenance_doc_url="https://docs.x.com/p1.pdf",
        )
        set_clock("2026-11-01T00:00:00Z")
        post_snapshot("LM317T", 11000, source="DISTRIBUTOR_FEED")
        set_clock("2026-11-09T00:00:00Z")

        read = validate_success(api.get_lot(lot["id"], BROKER), 200)
        # age_days = 100 -> round_half_up(10000*10*(1-100/365)) = 72603
        assert read["carrying_value_straight_line_cents"] == 72603

    def test_mark_to_market_basis_uses_latest_spot_with_haircut(self, api):
        """PRD section 3.3: "The market basis, `carrying_value_market_cents`,
        ignores age entirely: it takes the most recent market price snapshot
        for the lot's `mpn` — the snapshot with the greatest `observed_at`,
        ties broken by the greatest `created_at` — multiplies its
        `spot_price_cents` by the broker haircut of 0.85 and by the on-hand
        unit count, and rounds half-up to a whole cent; when no snapshot exists
        for the part number, the market-basis value is null. The two bases
        generally disagree, and both refresh as age advances and as new
        snapshots arrive."

        Design: Difficulty/dual_variant_calc/lot_carrying_value_straight_line_vs_mark_to_market
        """
        seller = create_seller(name="Acme Surplus")
        storage_bin = create_bin(capacity_units=100, bin_code="BIN-A1")
        lot, _ = create_lot(
            seller, storage_bin, mpn="LM317T", quantity=10,
            ask_price_per_unit_cents=10000, agreed_unit_price_cents=10000,
            provenance_doc_url="https://docs.x.com/p1.pdf",
        )
        set_clock("2026-11-01T00:00:00Z")
        post_snapshot("LM317T", 11000, source="DISTRIBUTOR_FEED")
        set_clock("2026-11-09T00:00:00Z")

        read = validate_success(api.get_lot(lot["id"], BROKER), 200)
        # round_half_up(11000 * 0.85 * 10) == 93500
        assert read["carrying_value_market_cents"] == 93500
        assert (
            read["carrying_value_market_cents"]
            != read["carrying_value_straight_line_cents"]
        ), "the two accounting bases must disagree on this lot state"


class TestProvisionalVsFinalSettlement:
    def _scenario(self, api):
        sc = setup_listed_consignment_scenario(
            mpn="STM32F103", quantity=10, agreed_unit_price_cents=8000,
            asking_price_per_unit_cents=10000, broker_fee_bps=1500,
            credit_limit_cents=200000, urgency_tier="CRITICAL",
        )
        order = place_order(sc["customer"], sc["listing"], quantity=10)
        delivered = advance_order_to_delivered(sc["customer"], order)
        set_clock("2026-10-10T00:00:00Z")
        post_snapshot("STM32F103", 8000, source="TRADE_DESK")
        set_clock("2026-10-20T00:00:00Z")
        post_snapshot("STM32F103", 11000, source="TRADE_DESK")
        set_clock("2026-11-04T00:00:00Z")
        return sc, delivered

    def test_provisional_price_captures_urgency_premium(self, api):
        """PRD section 3.6: "The customer's urgency tier sets a premium over
        the listing's asking price: zero percent for `STANDARD`, ten percent
        for `PRIORITY`, and twenty-five percent for `CRITICAL`. The
        `provisional_unit_price_cents` is the listing's
        `asking_price_per_unit_cents` increased by that premium, rounded
        half-up to a whole cent; `provisional_total_cents` is that unit price
        multiplied by the `quantity`; and `required_escrow_cents` equals the
        provisional total, because the broker demands one hundred percent of
        the provisional price in escrow before any work begins."

        Design: Difficulty/dual_variant_calc/order_price_provisional_vs_final_settlement
        """
        sc, delivered = self._scenario(api)
        assert delivered["provisional_unit_price_cents"] == 12500, (
            "round_half_up(10000 * 1.25) for a CRITICAL customer"
        )
        assert delivered["provisional_total_cents"] == 125000
        assert delivered["required_escrow_cents"] == 125000

    def test_final_price_applies_age_and_volatility_discounts(self, api):
        """PRD section 3.7: "The `final_unit_price_cents` is the provisional
        unit price reduced by the age discount and then by the volatility
        dampener, with a single round half-up to whole cents at that
        unit-price step; `final_total_cents` is the final unit price
        multiplied by the quantity; and `customer_refund_cents` is
        `provisional_total_cents` minus `final_total_cents`."

        Design: Difficulty/dual_variant_calc/order_price_provisional_vs_final_settlement
        """
        sc, delivered = self._scenario(api)
        settled = validate_success(
            api.settle_sales_order(delivered["id"], FINANCE), 200
        )
        # age 95 -> 5% discount; volatility (11000-8000)/8000 = 0.375 > 0.20 -> 3%.
        # round_half_up(12500 * 0.95 * 0.97) = round_half_up(11518.75) = 11519
        assert settled["final_unit_price_cents"] == 11519
        assert settled["final_total_cents"] == 115190
        assert settled["customer_refund_cents"] == 9810
        assert settled["final_unit_price_cents"] != settled["provisional_unit_price_cents"]


class TestThreeInputTieredInteraction:
    def _scenario(self, api):
        sc = setup_listed_broker_owned_scenario(
            mpn="TL074", quantity=5, agreed_unit_price_cents=4000,
            asking_price_per_unit_cents=10000,
            credit_limit_cents=100000, urgency_tier="PRIORITY", bin_capacity=50,
        )
        order = place_order(sc["customer"], sc["listing"], quantity=1)
        delivered = advance_order_to_delivered(sc["customer"], order)
        set_clock("2027-02-17T00:00:00Z")
        return sc, delivered

    def test_provisional_price_for_priority_tier(self, api):
        """PRD section 3.6: "The customer's urgency tier sets a premium over
        the listing's asking price: zero percent for `STANDARD`, ten percent
        for `PRIORITY`, and twenty-five percent for `CRITICAL`."

        Design: Difficulty/combinatorial_formula/final_price_three_input_tiered_interaction
        """
        sc, delivered = self._scenario(api)
        # round_half_up(10000 * 1.10) == 11000
        assert delivered["provisional_unit_price_cents"] == 11000
        assert delivered["provisional_total_cents"] == 11000
        assert delivered["required_escrow_cents"] == 11000

    def test_final_price_with_stale_age_bucket_and_no_snapshots(self, api):
        """PRD section 3.7: "The age discount is driven by the number of whole
        days between the lot's `received_at` and the settlement instant,
        partial days discarded: no discount while the lot is at most 89 days
        old, five percent when the age is 90 through 179 days, and twelve
        percent at 180 days or beyond."
        PRD section 3.7: "Volatility is zero when fewer than two snapshots
        exist in that window"

        Design: Difficulty/combinatorial_formula/final_price_three_input_tiered_interaction
        """
        sc, delivered = self._scenario(api)
        settled = validate_success(
            api.settle_sales_order(delivered["id"], FINANCE), 200
        )
        # age_days = 200 -> 12% discount; no snapshots -> volatility 0.
        # round_half_up(11000 * (1-0.12) * (1-0)) == 9680
        assert settled["final_unit_price_cents"] == 9680
        assert settled["final_total_cents"] == 9680
        assert settled["customer_refund_cents"] == 1320


class TestAgeBucketBoundary:
    def _scenario(self, api):
        sc = setup_listed_broker_owned_scenario(
            mpn="BC547", quantity=4, agreed_unit_price_cents=4000,
            asking_price_per_unit_cents=5000,
            credit_limit_cents=100000, urgency_tier="STANDARD", bin_capacity=50,
        )
        order = place_order(sc["customer"], sc["listing"], quantity=2)
        delivered = advance_order_to_delivered(sc["customer"], order)
        return sc, delivered

    def test_settle_at_exactly_90_days_gets_aged_discount(self, api):
        """PRD section 3.7: "no discount while the lot is at most 89 days old,
        five percent when the age is 90 through 179 days, and twelve percent at
        180 days or beyond."

        Design: Difficulty/boundary_precision_check/age_bucket_exactly_90_days_triggers_aged_discount
        """
        sc, delivered = self._scenario(api)
        # received 2026-08-01; settle at 2026-10-30 -> exactly 90 days.
        set_clock("2026-10-30T00:00:00Z")
        settled = validate_success(
            api.settle_sales_order(delivered["id"], FINANCE), 200
        )
        # round_half_up(5000 * (1-0.05)) == 4750
        assert settled["final_unit_price_cents"] == 4750
        assert settled["final_total_cents"] == 9500
        assert settled["customer_refund_cents"] == 500

    def test_settle_at_89_days_stays_fresh(self, api):
        """PRD section 3.7: "no discount while the lot is at most 89 days old,
        five percent when the age is 90 through 179 days, and twelve percent at
        180 days or beyond."

        Design: Difficulty/boundary_precision_check/age_bucket_exactly_90_days_triggers_aged_discount
        """
        sc, delivered = self._scenario(api)
        # received 2026-08-01; settle at 2026-10-29 -> exactly 89 days.
        set_clock("2026-10-29T00:00:00Z")
        settled = validate_success(
            api.settle_sales_order(delivered["id"], FINANCE), 200
        )
        # FRESH bucket: no discount, no snapshots -> volatility 0.
        assert settled["final_unit_price_cents"] == 5000
        assert settled["final_total_cents"] == 10000
        assert settled["customer_refund_cents"] == 0


class TestVolatilityThreshold:
    def test_volatility_exactly_0_20_does_not_dampen(self, api):
        """PRD section 3.7: "Only when that ratio is strictly greater than 0.20
        does a three percent dampener apply — a ratio of exactly 0.20 triggers
        nothing."

        Design: Corner/calculations/volatility_exactly_threshold_not_dampened
        """
        sc = setup_listed_broker_owned_scenario(
            mpn="LM358", quantity=2, agreed_unit_price_cents=4000,
            asking_price_per_unit_cents=5000,
            credit_limit_cents=50000, urgency_tier="STANDARD", bin_capacity=20,
        )
        order = place_order(sc["customer"], sc["listing"], quantity=1)
        delivered = advance_order_to_delivered(sc["customer"], order)
        set_clock("2026-10-10T00:00:00Z")
        post_snapshot("LM358", 10000, source="TRADE_DESK")
        set_clock("2026-10-20T00:00:00Z")
        post_snapshot("LM358", 12000, source="TRADE_DESK")
        set_clock("2026-10-21T00:00:00Z")

        settled = validate_success(
            api.settle_sales_order(delivered["id"], FINANCE), 200
        )
        # volatility == (12000-10000)/10000 == 0.20 exactly -> dampener 0.00.
        # age 81 -> FRESH. final == provisional == 5000.
        assert settled["final_unit_price_cents"] == 5000
        assert settled["customer_refund_cents"] == 0

    def test_snapshot_older_than_30d_excluded_from_window(self, api):
        """PRD section 3.7: "The volatility dampener looks at the market over
        the trailing thirty-day window — snapshots for the lot's `mpn` whose
        `observed_at` falls strictly after the instant thirty days (2,592,000
        seconds) before settlement and at or before the settlement instant."
        PRD section 3.7: "Volatility is zero when fewer than two snapshots
        exist in that window"

        Design: Corner/calculations/volatility_window_excludes_snapshot_older_than_30d
        """
        sc = setup_listed_broker_owned_scenario(
            mpn="LM358", quantity=2, agreed_unit_price_cents=4000,
            asking_price_per_unit_cents=5000,
            credit_limit_cents=50000, urgency_tier="STANDARD", bin_capacity=20,
        )
        order = place_order(sc["customer"], sc["listing"], quantity=1)
        delivered = advance_order_to_delivered(sc["customer"], order)
        # 2026-09-21 is exactly 30 days before the 2026-10-21 settle instant:
        # strictly-after excludes it from the window.
        set_clock("2026-09-21T00:00:00Z")
        post_snapshot("LM358", 5000, source="TRADE_DESK")
        set_clock("2026-10-20T00:00:00Z")
        post_snapshot("LM358", 20000, source="TRADE_DESK")
        set_clock("2026-10-21T00:00:00Z")

        settled = validate_success(
            api.settle_sales_order(delivered["id"], FINANCE), 200
        )
        # Only the 20000 snapshot is inside (t-30d, t]; count < 2 -> vol 0.
        assert settled["final_unit_price_cents"] == 5000


class TestCreditExposureBoundary:
    def test_exact_credit_equality_admitted_and_one_cent_over_rejected(self, api):
        """PRD section 3.6: "Admission requires the existing exposure plus the
        new order's `required_escrow_cents` to be no more than
        `credit_limit_cents` — exact equality is admitted, and one cent over is
        rejected with `ERR_INSUFFICIENT_CUSTOMER_CREDIT` (402)."

        Design: Corner/calculations/customer_credit_exposure_admits_exact_equality
        """
        sc = setup_listed_broker_owned_scenario(
            mpn="IRF540", quantity=10, agreed_unit_price_cents=8000,
            asking_price_per_unit_cents=10000,
            credit_limit_cents=50000, urgency_tier="CRITICAL", bin_capacity=50,
        )
        # CRITICAL: provisional unit = round_half_up(10000*1.25) = 12500.
        # qty 4 -> required 50000 == credit limit exactly.
        order = place_order(sc["customer"], sc["listing"], quantity=4)
        assert order["required_escrow_cents"] == 50000

        customer_read = validate_success(
            api.get_customer(sc["customer"]["id"], BROKER), 200
        )
        assert customer_read["open_order_exposure_cents"] == 50000

        # qty 1 more -> 50000 + 12500 > 50000 -> rejected.
        res = api.create_sales_order(
            {"customer_id": sc["customer"]["id"],
             "listing_id": sc["listing"]["id"], "quantity": 1},
            make_customer_headers(sc["customer"]["id"]),
        )
        validate_error(
            res, ApiErrorId.ERR_INSUFFICIENT_CUSTOMER_CREDIT, expected_status=402
        )
