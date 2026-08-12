"""Seat pricing (pinned two-stage rounding), demand tiers, and seat conservation."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_seat_conservation,
    create_performance,
    get_performance,
    get_seat_inventory,
    list_performance_inventories,
    setup_net_share_performance,
    setup_on_sale_performance,
    validate_error,
    validate_success,
)

BOM = TEST_USERS["box_office_manager_headers"]
ANY = TEST_USERS["any_headers"]


class TestSeatPricingRounding:
    def test_seat_price_pinned_rounding_literals(self, api):
        """PRD §3.8: "The two roundings are pinned: computing the price with a single rounding over the combined product yields a different cent value for odd bases — a base of 10050 cents in `BALCONY` at a ratio of 0.6 prices at 15076 cents under the pinned order, but 15075 under the naive single rounding — and only the pinned result is conformant."
        PRD §3.8: "A price quote is available for any inventory: given an optional `quantity`, it reports the `unit_price_cents`, the `demand_multiplier` currently in force, whether the group discount applied as `group_discount_applied`, and the `total_price_cents`, all evaluated at the current sold ratio without counting the quoted seats."

        BALCONY 10 seats @ 10,050 with 6 sold (ratio 0.6): unit1 =
        round_half_up(10050*1.25) = 12,563; unit = round_half_up(12563*1.2) = 15,076.

        Design: Difficulty/combinatorial_formula/seat_price_nested_rounding_order
        """
        scenario = setup_on_sale_performance(
            sections=[{"section": "BALCONY", "total_seats": 10, "base_price_cents": 10_050}]
        )
        inventory = scenario["inventories"][0]
        resp = api.purchase_seats(inventory["id"], 6, BOM)
        validate_success(resp, 200)

        resp = api.get_price_quote(inventory["id"], ANY, quantity=10)
        quote = validate_success(resp, 200)
        assert quote["unit_price_cents"] == 15_076, (
            "pinned order: round_half_up(10050*1.25)=12563 then round_half_up(12563*1.2)=15076"
        )
        assert quote["demand_multiplier"] == 1.2, "sold_ratio 0.6 in [0.5, 0.8)"
        assert quote["group_discount_applied"] is True, "quantity 10 >= 10"
        assert quote["total_price_cents"] == 135_684, "round_half_up(15076*10*0.9)"

    def test_seat_purchase_revenue_at_prepurchase_price(self, api):
        """PRD §3.8: "Purchasing requires `ON_SALE` and sufficient availability under the same two errors; it charges the total at the pre-purchase demand ratio, then increases `seats_sold` by the `quantity`, adds the charged total to the performance's `realized_revenue_cents`, recomputes the inventory's `current_price_cents` at the new ratio, and propagates upward — the production's `season_revenue_cents` is recomputed, and with it the `accrued_revenue_share_cents` of every `RATIFIED` net-revenue share of the production."
        PRD §3.8: "A purchase charges the `current_price_cents` times the quantity, multiplied by 0.9 as a group discount when the quantity is at least 10 and by 1.0 otherwise, with the total rounded half up to whole cents."

        The six-seat purchase was charged at ratio 0 (unit 12,563, no group
        discount): realized revenue 75,378; the inventory then reprices to 15,076.

        Design: Difficulty/combinatorial_formula/seat_price_nested_rounding_order
        """
        scenario = setup_on_sale_performance(
            sections=[{"section": "BALCONY", "total_seats": 10, "base_price_cents": 10_050}]
        )
        performance = scenario["performance"]
        inventory = scenario["inventories"][0]
        resp = api.purchase_seats(inventory["id"], 6, BOM)
        after = validate_success(resp, 200)
        assert after["seats_sold"] == 6
        assert after["current_price_cents"] == 15_076, "repriced at the new 0.6 ratio"

        performance_after = get_performance(performance["id"])
        assert performance_after["realized_revenue_cents"] == 75_378, (
            "6 * 12563 at the pre-purchase ratio 0, no group discount"
        )


class TestDemandTierBoundary:
    def test_demand_tier_boundary_at_half_ratio(self, api):
        """PRD §3.8: "Second, the sold ratio — `seats_sold` divided by `total_seats`, measured before the seats of the purchase currently being charged are counted — selects a demand multiplier: 1.0 while the ratio is below 0.5, 1.2 once the ratio reaches 0.5 but stays below 0.8, and 1.5 once the ratio reaches 0.8."

        STALLS 10 @ 10,000: at 4/10 sold the price is 10,000 (ratio 0.4 < 0.5);
        the fifth seat is charged at 10,000, and after it the ratio is exactly
        0.5 so the price becomes 12,000 (boundary inclusive).

        Design: Corner/calculations/demand_tier_boundary_at_half_ratio
        """
        scenario = setup_on_sale_performance(
            sections=[{"section": "STALLS", "total_seats": 10, "base_price_cents": 10_000}]
        )
        inventory = scenario["inventories"][0]

        resp = api.purchase_seats(inventory["id"], 4, BOM)
        after_4 = validate_success(resp, 200)
        assert after_4["current_price_cents"] == 10_000, "ratio 0.4 < 0.5 -> multiplier 1.0"

        resp = api.purchase_seats(inventory["id"], 1, BOM)
        after_5 = validate_success(resp, 200)
        assert after_5["current_price_cents"] == 12_000, (
            "ratio exactly 0.5 reaches the 1.2 tier (boundary inclusive)"
        )

        performance_after = get_performance(scenario["performance"]["id"])
        assert performance_after["realized_revenue_cents"] == 50_000, (
            "the fifth seat itself was charged at the pre-purchase price 10,000"
        )


class TestSeatExhaustionBoundary:
    def test_purchase_exact_available_then_over_rejected(self, api):
        """PRD §3.8: "Purchasing requires `ON_SALE` and sufficient availability under the same two errors; it charges the total at the pre-purchase demand ratio, then increases `seats_sold` by the `quantity`..."
        PRD §3.8: "Holding seats moves them from available to held and requires the performance's sales dimension to be `ON_SALE` — else `ERR_SALES_NOT_OPEN` — and the requested `quantity` not to exceed availability, else `ERR_INSUFFICIENT_SEATS`."

        STALLS 10 @ 10,000: buying exactly the 10 available seats succeeds
        (group discount at quantity 10: 10*10000*0.9 = 90,000), and the next
        purchase of a single seat fails with zero availability.

        Design: Difficulty/boundary_precision_check/seat_purchase_exact_available_then_over
        """
        scenario = setup_on_sale_performance(
            sections=[{"section": "STALLS", "total_seats": 10, "base_price_cents": 10_000}]
        )
        performance = scenario["performance"]
        inventory = scenario["inventories"][0]

        resp = api.purchase_seats(inventory["id"], 10, BOM)
        after = validate_success(resp, 200)
        assert after["seats_sold"] == 10, "quantity == available is allowed"

        resp = api.purchase_seats(inventory["id"], 1, BOM)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_SEATS)

        performance_after = get_performance(performance["id"])
        assert performance_after["realized_revenue_cents"] == 90_000, (
            "10 seats * 10,000 * 0.9 group discount at quantity >= 10"
        )

    def test_purchase_to_zero_after_holds_then_over_rejected(self, api):
        """PRD §3.8: "The box office moves seats between three buckets, where availability is always `total_seats` minus `seats_held` minus `seats_sold`. Holding seats moves them from available to held and requires the performance's sales dimension to be `ON_SALE` — else `ERR_SALES_NOT_OPEN` — and the requested `quantity` not to exceed availability, else `ERR_INSUFFICIENT_SEATS`."

        STALLS 20 @ 10,000: hold 6 (available 14), purchase 14 (exactly the
        remaining availability; group discount applies), then any further
        purchase fails.

        Design: Difficulty/boundary_precision_check/seat_purchase_exact_available_then_over
        """
        scenario = setup_on_sale_performance(
            sections=[{"section": "STALLS", "total_seats": 20, "base_price_cents": 10_000}]
        )
        inventory = scenario["inventories"][0]

        resp = api.hold_seats(inventory["id"], 6, BOM)
        after_hold = validate_success(resp, 200)
        assert after_hold["seats_held"] == 6

        resp = api.purchase_seats(inventory["id"], 14, BOM)
        after_purchase = validate_success(resp, 200)
        assert after_purchase["seats_sold"] == 14
        assert_seat_conservation(after_purchase)
        available = 20 - 6 - 14
        assert available == 0

        resp = api.purchase_seats(inventory["id"], 1, BOM)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_SEATS)
        resp = api.hold_seats(inventory["id"], 1, BOM)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_SEATS)


class TestSeatConservation:
    def test_seat_conservation_hold_release_purchase_sequence(self, api):
        """PRD §3.8: "The box office moves seats between three buckets, where availability is always `total_seats` minus `seats_held` minus `seats_sold`."
        PRD §3.8: "Releasing seats moves them from held back to available and requires only that the `quantity` not exceed `seats_held`, else `ERR_INSUFFICIENT_SEATS`; a release is not gated on the sales dimension."

        STALLS 20 @ 10,000: hold 7, hold 3, release 4, purchase 5 — held 6,
        sold 5, available 9, invariant 6 + 5 + 9 == 20; revenue 5 * 10,000
        (ratio 0, no group discount).

        Design: Difficulty/compensating_invariant/seat_conservation_hold_release
        """
        scenario = setup_on_sale_performance(
            sections=[{"section": "STALLS", "total_seats": 20, "base_price_cents": 10_000}]
        )
        inventory = scenario["inventories"][0]

        validate_success(api.hold_seats(inventory["id"], 7, BOM), 200)
        validate_success(api.hold_seats(inventory["id"], 3, BOM), 200)
        validate_success(api.release_seats(inventory["id"], 4, BOM), 200)
        resp = api.purchase_seats(inventory["id"], 5, BOM)
        after = validate_success(resp, 200)

        assert after["seats_held"] == 6, "7 + 3 - 4"
        assert after["seats_sold"] == 5
        available = assert_seat_conservation(after)
        assert available == 9, "6 held + 5 sold + 9 available == 20 total"

        performance_after = get_performance(scenario["performance"]["id"])
        assert performance_after["realized_revenue_cents"] == 50_000, (
            "5 * 10,000 at ratio 0, no group discount"
        )

    def test_seat_conservation_hold_then_full_release_restores(self, api):
        """PRD §3.8: "Releasing seats moves them from held back to available and requires only that the `quantity` not exceed `seats_held`, else `ERR_INSUFFICIENT_SEATS`; a release is not gated on the sales dimension."
        PRD §3.8: "The box office moves seats between three buckets, where availability is always `total_seats` minus `seats_held` minus `seats_sold`."

        The compensating pair hold 5 / release 5 returns the inventory to
        held 0, sold 0, available 20 — the conserved seat count is unchanged.

        Design: Difficulty/compensating_invariant/seat_conservation_hold_release
        """
        scenario = setup_on_sale_performance(
            sections=[{"section": "STALLS", "total_seats": 20, "base_price_cents": 10_000}]
        )
        inventory = scenario["inventories"][0]

        validate_success(api.hold_seats(inventory["id"], 5, BOM), 200)
        resp = api.release_seats(inventory["id"], 5, BOM)
        after = validate_success(resp, 200)
        assert after["seats_held"] == 0
        assert after["seats_sold"] == 0
        available = assert_seat_conservation(after)
        assert available == 20, "hold then full release restores all availability"

        performance_after = get_performance(scenario["performance"]["id"])
        assert performance_after["realized_revenue_cents"] == 0


class TestSalesGate:
    def test_hold_before_on_sale_rejected(self, api):
        """PRD §3.8: "Holding seats moves them from available to held and requires the performance's sales dimension to be `ON_SALE` — else `ERR_SALES_NOT_OPEN` — and the requested `quantity` not to exceed availability, else `ERR_INSUFFICIENT_SEATS`."

        Design: Corner/endpoints/hold_before_on_sale_rejected
        """
        scenario = setup_on_sale_performance(
            sections=[{"section": "STALLS", "total_seats": 10, "base_price_cents": 10_000}]
        )
        # Recreate a fresh performance whose sales were never opened.
        production = scenario["production"]
        performance = create_performance(
            production["id"], "2026-07-02T19:00:00Z", "2026-07-02T22:00:00Z",
            sections=[{"section": "STALLS", "total_seats": 10, "base_price_cents": 10_000}],
        )
        inventory = list_performance_inventories(performance["id"])[0]

        resp = api.hold_seats(inventory["id"], 2, BOM)
        validate_error(resp, ApiErrorId.ERR_SALES_NOT_OPEN)


class TestDerivedFieldReconciliation:
    def test_derived_fields_reconciled_on_purchase(self, api):
        """PRD §3.8: "Purchasing requires `ON_SALE` and sufficient availability under the same two errors; it charges the total at the pre-purchase demand ratio, then increases `seats_sold` by the `quantity`, adds the charged total to the performance's `realized_revenue_cents`, recomputes the inventory's `current_price_cents` at the new ratio, and propagates upward — the production's `season_revenue_cents` is recomputed, and with it the `accrued_revenue_share_cents` of every `RATIFIED` net-revenue share of the production."
        PRD §3.8: "The production's season revenue is, at all times, the sum of `realized_revenue_cents` over its performances whose lifecycle is not `CANCELLED`."

        Purchase of 10 STALLS @ 20,000 (ratio 0; group discount at quantity 10):
        performance revenue 180,000; season revenue 0 -> 180,000; the RATIFIED
        40% net share's accrual 0 -> 72,000.

        Design: Corner/cross_cutting_layers/derived_fields_reconciled_on_purchase
        """
        scenario = setup_net_share_performance(share_percentage=40)
        performance = scenario["performance"]
        production = scenario["production"]
        share = scenario["share"]
        inventory = scenario["inventory"]

        validate_success(api.purchase_seats(inventory["id"], 10, BOM), 200)

        performance_after = get_performance(performance["id"])
        assert performance_after["realized_revenue_cents"] == 180_000, (
            "10 * 20,000 * 0.9 group discount"
        )
        production_after = validate_success(api.get_production(production["id"], ANY), 200)
        assert production_after["season_revenue_cents"] == 180_000
        share_after = validate_success(api.get_co_production_share(share["id"], ANY), 200)
        assert share_after["accrued_revenue_share_cents"] == 72_000, (
            "round_half_up(0.40 * 180,000)"
        )
