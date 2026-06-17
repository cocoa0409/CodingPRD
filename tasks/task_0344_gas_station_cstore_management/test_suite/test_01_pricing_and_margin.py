"""Fuel pricing, loyalty accrual, store totals, and fuel-margin reporting.

Covers Queue A difficulty rules dual_variant_calc and combinatorial_formula, plus
the calculations-section corner instances that PRD prose uniquely determines.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, get_success_data,
    make_manager_headers, make_cashier_headers,
    factories as f,
)
from test_helpers import factories  # noqa: F401
import test_helpers.fixtures as fx

MANAGER = make_manager_headers()
CASHIER = make_cashier_headers("cash1")


def _margin(api, station_id, cost_basis="WAC",
            window_start="2026-06-01T00:00:00Z", window_end="2026-06-02T00:00:00Z"):
    resp = api.create_margin_report(
        f.create_margin_report_payload(station_id, window_start, window_end, cost_basis=cost_basis),
        MANAGER)
    return validate_success(resp, 201)


def _build_premium_wac_scenario(api):
    """One PREMIUM grade @419, tank with two POSTED deliveries (5000@280, 3000@300)
    giving WAC 287.5, and two SETTLED GOLD CARD fuel sales (12 + 10 gal = 22 gal).
    Clock set to 2026-06-01 so sales fall in the report window. Returns station id."""
    station = fx.create_station()
    fx.set_clock(station["id"], "2026-06-01T00:00:00Z")
    grade = fx.create_grade(station["id"], code="PREMIUM", octane=93, price_cents=419)
    tank = fx.create_tank(station["id"], grade["id"], capacity_gallons=10000,
                          reorder_point_gallons=1500)
    pump = fx.create_pump(station["id"], tank["id"], number=1)
    fx.create_and_post_delivery(station["id"], tank["id"], net_gallons=5000, unit_cost_cents=280)
    fx.create_and_post_delivery(station["id"], tank["id"], net_gallons=3000, unit_cost_cents=300)
    shift = fx.open_shift(station["id"], opening_float_cents=20000)
    member = fx.seed_gold_member(station["id"], shift["id"], name="Gold Member")
    fx.authorize_capture_settle_fuel(station["id"], pump["id"], shift["id"], gallons=12,
                                     tender="CARD", loyalty_account_id=member["id"])
    fx.authorize_capture_settle_fuel(station["id"], pump["id"], shift["id"], gallons=10,
                                     tender="CARD", loyalty_account_id=member["id"])
    return station["id"]


class TestMarginVariants:
    def test_margin_wac_vs_replacement_cogs_diverge(self, api):
        """PRD §3.10: "under `WAC` it is the grade's `weighted_avg_cost_cents` — the
        chronological weighted-average wet-stock cost accumulated across all posted
        deliveries; under `REPLACEMENT` it is the unit cost of the most recent posted
        delivery to a tank of that grade (the forward-looking replacement cost, ignoring
        older lots), selecting the latest by effective time with `created_at` ascending
        as the tie-break."
        PRD §3.10: "Each grade's cost of goods is that grade's total gallons multiplied
        by its chosen per-gallon cost, rounded half-up to whole cents; `cogs_cents` is the
        sum of those per-grade figures (rounding is applied per grade and then the rounded
        grade figures are summed)."

        Design: Difficulty/dual_variant_calc/margin_wac_vs_replacement_diverge
        """
        station_id = _build_premium_wac_scenario(api)

        wac = _margin(api, station_id, cost_basis="WAC")
        rep = _margin(api, station_id, cost_basis="REPLACEMENT")

        # WAC = (5000*280 + 3000*300)/8000 = 287.5; round(22*287.5) = 6325
        assert wac["revenue_cents"] == 9108, f"got {wac['revenue_cents']}"
        assert wac["cogs_cents"] == 6325, f"got {wac['cogs_cents']}"
        assert wac["margin_cents"] == 2783, f"got {wac['margin_cents']}"
        # REPLACEMENT = last posted lot 300; round(22*300) = 6600
        assert rep["cogs_cents"] == 6600, f"got {rep['cogs_cents']}"
        assert rep["margin_cents"] == 2508, f"got {rep['margin_cents']}"
        assert wac["cogs_cents"] != rep["cogs_cents"]

    def test_margin_cogs_round_per_grade_then_sum(self, api):
        """PRD §3.10: "Each grade's cost of goods is that grade's total gallons multiplied
        by its chosen per-gallon cost, rounded half-up to whole cents; `cogs_cents` is the
        sum of those per-grade figures (rounding is applied per grade and then the rounded
        grade figures are summed)."
        PRD §3.10: "the report computes `gallons_sold` as the sum of `gallons`"

        Design: Difficulty/combinatorial_formula/margin_round_per_grade_then_sum_mode_b
        """
        station_id = _build_premium_wac_scenario(api)
        wac = _margin(api, station_id, cost_basis="WAC")
        # One grade, 22 gal at WAC 287.5 -> round(22*287.5) = round(6325.0) = 6325
        assert wac["cogs_cents"] == 6325, f"got {wac['cogs_cents']}"
        assert wac["gallons_sold"] == 22, f"got {wac['gallons_sold']}"

    def test_margin_excludes_reversed_transactions(self, api):
        """PRD §3.10: "The window predicate selects the fuel transactions whose `created_at`
        is greater than or equal to `window_start` and strictly less than `window_end`,
        restricted to those whose `settlement_status` is `SETTLED` (reversed transactions
        are excluded)."

        Design: Corner/calculations/margin_report_excludes_reversed_transactions
        """
        station = fx.create_station()
        fx.set_clock(station["id"], "2026-06-01T00:00:00Z")
        grade = fx.create_grade(station["id"], code="REGULAR", price_cents=419)
        tank = fx.create_tank(station["id"], grade["id"])
        pump = fx.create_pump(station["id"], tank["id"], number=1)
        fx.create_and_post_delivery(station["id"], tank["id"], net_gallons=5000, unit_cost_cents=280)
        shift = fx.open_shift(station["id"])
        fx.authorize_capture_settle_fuel(station["id"], pump["id"], shift["id"], gallons=12, tender="CARD")
        t2 = fx.authorize_fuel(station["id"], pump["id"], shift["id"], gallons=10, tender="CARD")
        fx.capture_fuel(t2["id"])
        fx.settle_fuel(t2["id"], shift["id"])
        get_success_data(api.reverse_fuel_transaction(t2["id"], CASHIER))

        rep = _margin(api, station["id"], cost_basis="WAC")
        # The distinguishing claim: the REVERSED 10gal sale is excluded from the window.
        assert rep["gallons_sold"] == 12, f"REVERSED 10gal must be excluded, got {rep['gallons_sold']}"
        # Guest (no loyalty) at base 419, no discount -> revenue = round(12*419) = 5028.
        assert rep["revenue_cents"] == 5028, f"got {rep['revenue_cents']}"

    def test_margin_pct_zero_when_no_revenue(self, api):
        """PRD §3.10: "The `margin_pct` is the margin divided by revenue, multiplied by 100,
        rounded half-up to two decimal places; when `revenue_cents` is 0 the margin
        percentage is 0."

        Design: Corner/calculations/margin_pct_zero_when_no_revenue
        """
        station = fx.create_station()
        rep = _margin(api, station["id"], cost_basis="WAC")
        assert rep["revenue_cents"] == 0
        assert rep["gallons_sold"] == 0
        assert rep["margin_pct"] == 0


class TestLoyaltyAccrual:
    def test_fuel_vs_store_accrual_diverge(self, api):
        """PRD §3.7: "ten points for each gallon of fuel (the whole-number floor of the
        dispensed gallons multiplied by 10 points per gallon), plus two points for each
        whole dollar of store subtotal (the whole-number floor of the store subtotal in
        cents divided by 100, multiplied by 2 points per dollar). For a fuel settlement only
        the gallon term contributes and the store term is 0; for a store settlement only the
        dollar term contributes and the gallon term is 0."
        PRD §3.7: "The awarded points are added to both `point_balance` and `lifetime_points`"

        Design: Difficulty/dual_variant_calc/loyalty_fuel_vs_store_accrual_diverge
        """
        station = fx.create_station()
        fx.set_clock(station["id"], "2026-06-01T00:00:00Z")
        grade = fx.create_grade(station["id"], code="REGULAR", price_cents=419)
        tank = fx.create_tank(station["id"], grade["id"])
        pump = fx.create_pump(station["id"], tank["id"], number=1)
        fx.create_and_post_delivery(station["id"], tank["id"], net_gallons=5000, unit_cost_cents=280)
        member = fx.enroll_member(station["id"], name="Bronze Member")
        shift = fx.open_shift(station["id"])

        # Fuel settle: BRONZE, 12 gal -> floor(12*10)=120 base, *1.0 = 120
        fx.authorize_capture_settle_fuel(station["id"], pump["id"], shift["id"], gallons=12,
                                         tender="CARD", loyalty_account_id=member["id"])
        after_fuel = get_success_data(api.get_loyalty_account(member["id"], CASHIER))
        assert after_fuel["lifetime_points"] == 120, f"got {after_fuel['lifetime_points']}"

        # Store settle: BRONZE, subtotal 1550 -> floor(1550/100)*2 = 30 base, *1.0 = 30
        snk = f.line_item(sku="SNK", name="Snacks", category="GROCERY",
                          unit_price_cents=1550, qty=1, taxable=True)
        get_success_data(api.create_store_transaction(
            f.create_store_transaction_payload(station["id"], shift["id"],
                                               line_items=[snk], tender="CARD",
                                               loyalty_account_id=member["id"]), CASHIER))
        after_store = get_success_data(api.get_loyalty_account(member["id"], CASHIER))
        assert after_store["lifetime_points"] == 150, f"got {after_store['lifetime_points']}"
        assert after_store["lifetime_points"] - 120 == 30, "store accrual must be 30 (dollar term only)"


class TestFuelPumpPrice:
    def test_gold_tier_discount_min_cap_applied(self, api):
        """PRD §3.7: "The tier discount in cents per gallon is 0 for `BRONZE`, 3 for
        `SILVER`, and 5 for `GOLD`, and a guest with no loyalty account gets 0. The applied
        `discount_cents_per_gal` is the smaller of the tier discount and the maximum allowed
        discount of 10 cents per gallon."
        PRD §3.6: "`net_price_cents_per_gal` is the base price minus the discount; and
        `total_cents` is the gallons multiplied by the net per-gallon price, rounded half-up
        to whole cents."

        Design: Difficulty/combinatorial_formula/pump_price_tiered_min_cap_mode_a
        """
        station = fx.create_station()
        grade = fx.create_grade(station["id"], code="REGULAR", price_cents=419)
        tank = fx.create_tank(station["id"], grade["id"])
        pump = fx.create_pump(station["id"], tank["id"], number=1)
        fx.create_and_post_delivery(station["id"], tank["id"], net_gallons=5000, unit_cost_cents=280)
        shift = fx.open_shift(station["id"])
        member = fx.seed_gold_member(station["id"], shift["id"], name="Gold")
        assert member["tier"] == "GOLD"

        txn = fx.authorize_fuel(station["id"], pump["id"], shift["id"], gallons=12,
                                tender="CARD", loyalty_account_id=member["id"])
        # GOLD min(5,10)=5; net 419-5=414; round(12*414)=4968
        assert txn["discount_cents_per_gal"] == 5, f"got {txn['discount_cents_per_gal']}"
        assert txn["net_price_cents_per_gal"] == 414, f"got {txn['net_price_cents_per_gal']}"
        assert txn["total_cents"] == 4968, f"got {txn['total_cents']}"

    def test_bronze_member_no_fuel_discount(self, api):
        """PRD §3.7: "The tier discount in cents per gallon is 0 for `BRONZE`, 3 for
        `SILVER`, and 5 for `GOLD`, and a guest with no loyalty account gets 0."
        PRD §3.6: "`total_cents` is the gallons multiplied by the net per-gallon price,
        rounded half-up to whole cents."

        Design: Corner/calculations/bronze_member_no_fuel_discount_default
        """
        station = fx.create_station()
        grade = fx.create_grade(station["id"], code="REGULAR", price_cents=419)
        tank = fx.create_tank(station["id"], grade["id"])
        pump = fx.create_pump(station["id"], tank["id"], number=1)
        fx.create_and_post_delivery(station["id"], tank["id"], net_gallons=5000, unit_cost_cents=280)
        member = fx.enroll_member(station["id"], name="Bronze")
        shift = fx.open_shift(station["id"])

        txn = fx.authorize_fuel(station["id"], pump["id"], shift["id"], gallons=12,
                                tender="CARD", loyalty_account_id=member["id"])
        # BRONZE discount 0; round(12*419) = 5028
        assert txn["discount_cents_per_gal"] == 0
        assert txn["total_cents"] == 5028, f"got {txn['total_cents']}"


class TestStoreAndCarWashPricing:
    def test_store_total_mixed_taxable_sum_then_round(self, api):
        """PRD §3.8: "The `tax_cents` is computed once on the taxable subtotal — the sum of
        `unit_price_cents` times `qty` over only the line items whose `taxable` flag is true —
        multiplied by the station's `tax_rate_bp` divided by 10000, with that single product
        rounded half-up to whole cents (tax is summed first, then rounded once). The
        `total_cents` is the subtotal plus the tax."

        Design: Corner/calculations/store_total_mixed_taxable_sum_then_round
        """
        station = fx.create_station()
        shift = fx.open_shift(station["id"])
        items = [
            f.line_item(sku="A", name="Taxable", category="GROCERY",
                        unit_price_cents=500, qty=2, taxable=True),
            f.line_item(sku="B", name="Exempt", category="GROCERY",
                        unit_price_cents=275, qty=2, taxable=False),
        ]
        st = validate_success(api.create_store_transaction(
            f.create_store_transaction_payload(station["id"], shift["id"],
                                               line_items=items, tender="CARD"), CASHIER), 201)
        # subtotal 1000+550=1550; taxable 1000; round(1000*825/10000)=round(82.5)=83; total 1633
        assert st["subtotal_cents"] == 1550
        assert st["tax_cents"] == 83, f"got {st['tax_cents']}"
        assert st["total_cents"] == 1633, f"got {st['total_cents']}"

    def test_car_wash_deluxe_gold_discount(self, api):
        """PRD §3.9: "A purchased code is priced from the package list — 800 cents for
        `BASIC`, 1200 for `DELUXE`, 1600 for `SUPREME` — reduced by the loyalty wash discount
        for the member's tier, which is 0% for `BRONZE`, 10% for `SILVER`, and 20% for `GOLD`
        (0% with no loyalty account); the list price multiplied by one minus that discount
        fraction is rounded half-up to whole cents and stored as `price_cents`."

        Design: Corner/calculations/car_wash_price_deluxe_gold_discount
        """
        station = fx.create_station()
        fx.set_clock(station["id"], "2026-06-01T00:00:00Z")
        shift = fx.open_shift(station["id"])
        member = fx.seed_gold_member(station["id"], shift["id"], name="Gold")
        assert member["tier"] == "GOLD"
        code = validate_success(api.create_car_wash_code(
            f.create_car_wash_code_payload(station["id"], package="DELUXE",
                                           loyalty_account_id=member["id"]), CASHIER), 201)
        # round(1200*(1-0.20)) = 960
        assert code["price_cents"] == 960, f"got {code['price_cents']}"
        assert code["status"] == "ISSUED"
