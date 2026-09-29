"""Non-separable arithmetic: density band x correction factor x water cap on a receipt,
per-component cent rounding on an uplift line, and rebate-before-admin-fee on an invoice."""
import pytest

from test_helpers import validate_success, fixtures as fx


class TestReceiptVolumeCombination:
    def test_heavy_density_band_boundary_with_capped_water_deduction(self, api):
        """PRD §3.2: "**First**, a thermal expansion coefficient is selected by density band from
        the certificate density: 0.000850 when the certificate density is at least 800.0 kilograms
        per cubic metre, otherwise 0.000900 when it is at least 780.0, otherwise 0.000950."
        PRD §3.2: "**Fifth**, the water deduction cap is one half of one percent of the *governing
        gross* — not of the corrected volume — rounded half up to two decimals, and the deduction
        actually applied is the smaller of the measured water volume and that cap."
        PRD §3.2: "**Sixth**, `net_volume_liters` is the corrected volume less the applied
        deduction, rounded half up to two decimals again."

        Design: Difficulty/combinatorial_formula/receipt_density_band_vcf_and_water_cap_interaction
        """
        env = fx.setup_fuel_farm(permit_overrides={"max_daily_throughput_liters": 400000.0})
        tank = fx.register_tank(env["farm"]["id"], capacity_liters=5_000_000.0,
                                safe_fill_liters=4_000_000.0, density_kg_per_m3=800.0,
                                opening_volume_liters=0.0)
        receipt = fx.record_receipt(
            tank["id"], delivery_mode="PIPELINE", supplier_name="Refinery Two",
            meter_ticket_gross_liters=30500.0, tank_opening_gauge_liters=0.0,
            tank_closing_gauge_liters=30000.0, temperature_c=35.0,
            certificate_density_kg_per_m3=800.0, measured_water_liters=500.0)

        assert receipt["governing_gross_liters"] == pytest.approx(30000.00, abs=0.005)
        assert receipt["advisory_gross_liters"] == pytest.approx(30500.00, abs=0.005)
        assert receipt["net_volume_liters"] == pytest.approx(29340.00, abs=0.005), \
            "density exactly 800.0 selects 0.000850 and the 500 L of water is capped at 150.00 L"
        assert receipt["advisory_net_volume_liters"] == pytest.approx(29829.00, abs=0.005)
        assert receipt["status"] == "RECORDED"

    def test_density_just_below_the_boundary_selects_the_lighter_coefficient(self, api):
        """PRD §3.2: "**First**, a thermal expansion coefficient is selected by density band from
        the certificate density: 0.000850 when the certificate density is at least 800.0 kilograms
        per cubic metre, otherwise 0.000900 when it is at least 780.0, otherwise 0.000950."
        PRD §3.2: "**Fourth**, the corrected volume is the governing gross multiplied by the
        correction factor, rounded half up to two decimals."

        Design: Difficulty/combinatorial_formula/receipt_density_band_vcf_and_water_cap_interaction
        """
        env = fx.setup_fuel_farm(permit_overrides={"max_daily_throughput_liters": 400000.0})
        tank = fx.register_tank(env["farm"]["id"], capacity_liters=5_000_000.0,
                                safe_fill_liters=4_000_000.0, density_kg_per_m3=800.0,
                                opening_volume_liters=0.0)
        receipt = fx.record_receipt(
            tank["id"], delivery_mode="PIPELINE", supplier_name="Refinery Two",
            meter_ticket_gross_liters=30500.0, tank_opening_gauge_liters=0.0,
            tank_closing_gauge_liters=30000.0, temperature_c=35.0,
            certificate_density_kg_per_m3=799.0, measured_water_liters=500.0)

        assert receipt["net_volume_liters"] == pytest.approx(29310.00, abs=0.005), \
            "799.0 falls in the 0.000900 band, giving a factor of 0.98200"


class TestUpliftLineRounding:
    def test_each_money_component_is_rounded_before_the_line_is_summed(self, api):
        """PRD §3.6: "Five components are then computed, each rounded half up to a whole number of
        cents **before** anything is summed: `fuel_component_cents` is the ticket's net liters
        multiplied by the sum of the account's `base_price_cents_per_liter` and the selected
        differential; the into-plane fee is the larger of 2,500 cents and net liters multiplied by
        0.45 cents per liter; the flowage fee is net liters multiplied by 0.12 cents per liter; the
        federal excise is net liters multiplied by 1.14 cents per liter; and the state sales tax is
        7.25 percent of the sum of the fuel component and the into-plane fee."
        PRD §3.6: "The `billed_line_cents` is the sum of those five already-rounded components.
        Summing the components unrounded and rounding once at the end is explicitly not the rule
        and gives a different answer."

        Design: Difficulty/combinatorial_formula/uplift_line_per_component_rounding_beats_sum_then_round
        """
        env = fx.setup_truck_order(
            target_state="FUELING", requested_uplift_liters=20_000.0,
            max_authorized_liters=20_000.0,
            account_overrides={"base_price_cents_per_liter": 62.00,
                               "credit_limit_cents": 100_000_000, "tax_exempt": False})
        uplift = fx.post_uplift(env["order"]["id"], env["order"]["version"],
                                ticket_number="TK-0007", meter_start_liters=1000.0,
                                meter_end_liters=20002.55, temperature_c=15.0)

        assert uplift["gross_liters"] == pytest.approx(19002.55, abs=0.005)
        assert uplift["net_liters"] == pytest.approx(19002.55, abs=0.005)
        assert uplift["volume_tier_diff_cents_per_liter"] == pytest.approx(3.20, abs=0.005)
        assert uplift["fuel_component_cents"] == 1238966
        assert uplift["billed_line_cents"] == 1361905, \
            "summing unrounded components and rounding once would give 1361906"
        assert uplift["status"] == "POSTED"

    def test_tax_exempt_account_zeroes_excise_and_sales_tax_components(self, api):
        """PRD §3.6: "When the account's `tax_exempt` flag is true both the excise and the sales tax
        are zero."
        PRD §3.6: "The `billed_line_cents` is the sum of those five already-rounded components.
        Summing the components unrounded and rounding once at the end is explicitly not the rule
        and gives a different answer."

        Design: Difficulty/combinatorial_formula/uplift_line_per_component_rounding_beats_sum_then_round
        """
        env = fx.setup_truck_order(
            target_state="FUELING", requested_uplift_liters=20_000.0,
            max_authorized_liters=20_000.0,
            account_overrides={"base_price_cents_per_liter": 62.00,
                               "credit_limit_cents": 100_000_000, "tax_exempt": True})
        uplift = fx.post_uplift(env["order"]["id"], env["order"]["version"],
                                ticket_number="TK-0008", meter_start_liters=1000.0,
                                meter_end_liters=20002.55, temperature_c=15.0)

        assert uplift["fuel_component_cents"] == 1238966
        assert uplift["billed_line_cents"] == 1238966 + 8551 + 2280, \
            "a tax-exempt line is fuel plus into-plane fee plus flowage fee only"


class TestInvoiceRebateThenAdminFee:
    def test_rebate_is_applied_before_the_admin_fee_is_assessed(self, api):
        """PRD §3.9: "**Step two** computes the volume rebate, which is keyed on liters and applied
        to the fuel component only: the rate is 1.5 percent once the swept volume reaches 250,000
        liters, otherwise 0.75 percent once it reaches 100,000 liters, otherwise nothing at all,
        and `volume_rebate_cents` is the fuel component multiplied by that rate, rounded half up to
        whole cents."
        PRD §3.9: "**Step three** computes the consortium administration fee on the post-rebate
        subtotal: `admin_fee_cents` is the smaller of 50,000 cents and four tenths of one percent
        of the subtotal less the rebate, rounded half up to whole cents."
        PRD §3.9: "**Step four** sets `total_cents` to the subtotal, less the rebate, plus the
        admin fee."

        Design: Difficulty/combinatorial_formula/invoice_volume_rebate_before_admin_fee_evaluation_order
        """
        env = fx.setup_sequential_uplifts_for_account(
            uplift_liters=(30_000.0, 30_000.0, 40_000.0),
            permit_overrides={"max_daily_throughput_liters": 400000.0})
        fx.set_clock("2026-08-11T01:00:00Z")
        invoice = fx.create_draft_invoice(env["account"]["id"], "2026-08-10T00:00:00Z",
                                         "2026-08-11T00:00:00Z")

        assert invoice["swept_net_liters"] == pytest.approx(100000.00, abs=0.005)
        assert invoice["fuel_component_cents"] == 6488000
        assert invoice["subtotal_cents"] == 7132643
        assert invoice["volume_rebate_cents"] == 48660
        assert invoice["admin_fee_cents"] == 28336, \
            "the admin fee is four tenths of one percent of the post-rebate subtotal"
        assert invoice["total_cents"] == 7112319, \
            "assessing the admin fee before the rebate would have produced 7112514"
        assert invoice["status"] == "DRAFT"

    def test_cumulative_volume_tier_crossing_feeds_the_swept_subtotal(self, api):
        """PRD §3.6: "From that cumulative a whole-line differential rate
        `volume_tier_diff_cents_per_liter` is selected — 1.60 cents per liter once the cumulative
        reaches 500,000 liters, otherwise 2.40 cents per liter once it reaches 100,000 liters,
        otherwise 3.20 cents per liter — and the rate applies to the entire line, not marginally."
        PRD §3.9: "**Step one** sums the swept figures: `swept_net_liters` is the sum of the
        tickets' `net_liters` rounded half up to two decimals, `fuel_component_cents` is the sum of
        the tickets' own `fuel_component_cents`, and `subtotal_cents` is the sum of the tickets'
        `billed_line_cents`, each of which was already rounded to whole cents when the ticket was
        posted."

        Design: Difficulty/combinatorial_formula/invoice_volume_rebate_before_admin_fee_evaluation_order
        """
        env = fx.setup_sequential_uplifts_for_account(
            uplift_liters=(30_000.0, 30_000.0, 40_000.0),
            permit_overrides={"max_daily_throughput_liters": 400000.0})

        first = validate_success(api.get_uplift_record(env["uplifts"][0]["id"], fx.AGENT))
        second = validate_success(api.get_uplift_record(env["uplifts"][1]["id"], fx.AGENT))
        third = validate_success(api.get_uplift_record(env["uplifts"][2]["id"], fx.AGENT))

        assert first["volume_tier_diff_cents_per_liter"] == pytest.approx(3.20, abs=0.005)
        assert first["billed_line_cents"] == 2150089
        assert second["volume_tier_diff_cents_per_liter"] == pytest.approx(3.20, abs=0.005)
        assert second["billed_line_cents"] == 2150089
        assert third["volume_tier_diff_cents_per_liter"] == pytest.approx(2.40, abs=0.005), \
            "the third ticket's cumulative month-to-date volume reaches 100,000 liters"
        assert third["billed_line_cents"] == 2832465
