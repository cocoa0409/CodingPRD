"""RENTAL linen charges and the tiered utility surcharge in both its
estimated (trailing-window) and actual (posted-reading) variants."""
from test_helpers import (
    TEST_USERS,
    assert_invoice_total_invariants,
    create_plant, create_linen_category, create_customer, set_par_level,
    post_utility_reading, generate_invoice, billing_preview,
    setup_finished_load,
)

MAY = {"billing_period_start": "2026-05-01", "billing_period_end": "2026-06-01"}
JUNE = {"billing_period_start": "2026-06-01", "billing_period_end": "2026-07-01"}


class TestRentalCharge:
    def test_rental_charge_uses_par_pieces_per_day(self, api):
        """PRD §3.8: "For a `RENTAL` customer, the charge is forward-looking against the par snapshot at generation time. The period length is the whole number of days from `billing_period_start` to `billing_period_end`. Each par row of the customer contributes its `par_pieces` multiplied by a daily rate and by the day count: the daily rate per piece is the category's `replacement_cost_cents` multiplied by 2 percent — two percent of replacement cost per piece-day — and each category line is rounded half-up to whole cents before the lines are summed into `linen_charges_cents`."

        Design: Corner/calculations/rental_linen_charge_uses_par_pieces_per_day
        """
        plant = create_plant()
        category = create_linen_category(plant["id"], replacement_cost_cents=500)
        customer = create_customer(plant["id"], billing_mode="RENTAL")
        set_par_level(customer["id"], category["id"], 10)
        invoice = generate_invoice(
            customer["id"],
            billing_period_start="2026-05-01", billing_period_end="2026-05-31",
        )
        # daily rate = 500 * 2% = 10 cents/piece-day; 10 pieces * 30 days.
        assert invoice["linen_charges_cents"] == 3000, (
            f"10 * 10 * 30 must charge 3000, got {invoice['linen_charges_cents']}"
        )
        assert_invoice_total_invariants(invoice)


class TestSurchargeEstimatedVsActual:
    def _setup_may(self, api):
        """COG customer with 4000 clean lb unloaded in May (the default
        logical clock 2026-05-01T00:00:00Z, PRD §2.5), plus Feb/Mar/Apr
        readings on the same plant with tiered excesses 6000/9000/15000."""
        ctx = setup_finished_load(
            pieces=1000,
            category_overrides={
                "code": "SHEET", "piece_weight_lb": 4.0,
                "replacement_cost_cents": 4000, "cog_wash_rate_cents_per_lb": 100,
            },
            route_overrides={"service_date": "2026-05-10"},
            stop_overrides={"declared_soiled_weight_lb": 4000.0},
            carts=[{"cart_tag": "CART-1", "scale_weight_lb": 4000.0}],
            load_overrides={
                "machine_id": "M1",
                "scheduled_start": "2026-05-10T08:00:00Z",
                "scheduled_end": "2026-05-10T09:00:00Z",
            },
        )
        for month, kwh in (("2026-02", 5200), ("2026-03", 5800), ("2026-04", 7000)):
            post_utility_reading(
                ctx["plant"]["id"], period_month=month, kwh_used=kwh,
                gallons_used=8000, clean_lbs_processed=4000,
                kwh_rate_cents=10, gallon_rate_cents=2,
            )
        return ctx

    def test_estimated_surcharge_uses_trailing_window(self, api):
        """PRD §3.8: "The trailing window is the three calendar months immediately preceding the invoice month that have utility readings; the average of those months' tiered excess values, rounded half-up to whole cents, stands in for the current month's excess. The share percentage uses the same customer clean pounds for the invoice month, but divides by the `clean_lbs_processed` of the most recent reading in the trailing window. With fewer than three trailing readings the average runs over what is available; with no readings at all the estimated surcharge is zero."
        PRD §3.8: "The excess passes through on a tiered schedule: the first 100000 cents of excess pass at 50 percent, the portion of the excess above 100000 and up to 500000 cents passes at 75 percent, and any portion above 500000 cents passes at 100 percent."

        Design: Difficulty/dual_variant_calc/utility_surcharge_estimated_vs_actual_diverge
        """
        ctx = self._setup_may(api)
        invoice = generate_invoice(ctx["customer"]["id"], **MAY)
        # Trailing tiered excesses 6000/9000/15000 -> average 10000; customer
        # May lbs 4000 / latest trailing (April) 4000 -> share 100%.
        assert invoice["utility_surcharge_cents"] == 10000, (
            f"estimated surcharge must average the trailing window, "
            f"got {invoice['utility_surcharge_cents']}"
        )
        assert_invoice_total_invariants(invoice)

    def test_actual_surcharge_after_reading_posts(self, api):
        """PRD §3.8: "When a `UtilityReading` exists for the invoice's month, the actual variant computes the month's true utility cost as `kwh_used` times `kwh_rate_cents` plus `gallons_used` times `gallon_rate_cents`; computes the baseline cost as the month's `clean_lbs_processed` multiplied by the plant's `utility_baseline_kwh_per_lb` times `kwh_rate_cents`, plus `clean_lbs_processed` multiplied by `utility_baseline_gal_per_lb` times `gallon_rate_cents`, the sum rounded half-up to whole cents; and takes the excess as the actual minus the baseline, floored at zero."
        PRD §3.8: "The customer's share of that tiered excess is the customer's clean pounds for the month — the sum of `clean_weight_lb` over the customer's `FINISHED` loads unloaded within the invoice month — divided by the reading's `clean_lbs_processed`, multiplied by 100, and rounded half-up to 4 decimal places; the surcharge is the tiered excess multiplied by that share percentage, divided by 100, and rounded half-up to whole cents."

        Design: Difficulty/dual_variant_calc/utility_surcharge_estimated_vs_actual_diverge
        """
        ctx = self._setup_may(api)
        invoice = generate_invoice(ctx["customer"]["id"], **MAY)
        estimated = invoice["utility_surcharge_cents"]

        post_utility_reading(
            ctx["plant"]["id"], period_month="2026-05", kwh_used=10000,
            gallons_used=30000, clean_lbs_processed=8000,
            kwh_rate_cents=10, gallon_rate_cents=2,
        )
        preview = billing_preview(ctx["customer"]["id"], "2026-05-01", "2026-06-01")
        # May: actual 160000, baseline 112000, excess 48000 (all tier A at
        # 50% -> 24000); share 4000/8000 = 50% -> 12000.
        assert preview["utility_surcharge_cents"] == 12000, (
            f"actual variant must compute from the posted May reading, "
            f"got {preview['utility_surcharge_cents']}"
        )
        assert estimated != preview["utility_surcharge_cents"], (
            "estimated and actual variants must diverge on this setup"
        )


class TestSurchargeTieredBrackets:
    def _setup_june(self, api):
        """COG customer with 8000 clean lb unloaded in June; June reading:
        actual 374000, baseline 224000, excess 150000. The logical clock is
        set into June before unload so the unload stamps a June timestamp."""
        ctx = setup_finished_load(
            pieces=2000,
            category_overrides={
                "code": "SHEET", "piece_weight_lb": 4.0,
                "replacement_cost_cents": 4000, "cog_wash_rate_cents_per_lb": 100,
            },
            route_overrides={"service_date": "2026-06-10"},
            stop_overrides={"declared_soiled_weight_lb": 8000.0},
            carts=[{"cart_tag": "CART-1", "scale_weight_lb": 8000.0}],
            load_overrides={
                "machine_id": "M1",
                "scheduled_start": "2026-06-10T08:00:00Z",
                "scheduled_end": "2026-06-10T09:00:00Z",
            },
            clock_iso="2026-06-10T09:00:00Z",
        )
        post_utility_reading(
            ctx["plant"]["id"], period_month="2026-06", kwh_used=26600,
            gallons_used=54000, clean_lbs_processed=16000,
            kwh_rate_cents=10, gallon_rate_cents=2,
        )
        return ctx

    def test_excess_straddling_tier_b_in_preview(self, api):
        """PRD §3.8: "The excess passes through on a tiered schedule: the first 100000 cents of excess pass at 50 percent, the portion of the excess above 100000 and up to 500000 cents passes at 75 percent, and any portion above 500000 cents passes at 100 percent."
        PRD §3.8: "the surcharge is the tiered excess multiplied by that share percentage, divided by 100, and rounded half-up to whole cents"

        Design: Difficulty/combinatorial_formula/utility_surcharge_tiered_min_max_mode_a
        """
        ctx = self._setup_june(api)
        preview = billing_preview(ctx["customer"]["id"], "2026-06-01", "2026-07-01")
        # tiered excess = 100000*0.50 + 50000*0.75 = 87500; share 8000/16000
        # = 50% -> 43750.
        assert preview["utility_surcharge_cents"] == 43750, (
            f"excess 150000 must split across tiers A and B, "
            f"got {preview['utility_surcharge_cents']}"
        )

    def test_excess_straddling_tier_b_on_generated_invoice(self, api):
        """PRD §3.8: "When a `UtilityReading` exists for the invoice's month, the actual variant computes the month's true utility cost as `kwh_used` times `kwh_rate_cents` plus `gallons_used` times `gallon_rate_cents`; computes the baseline cost as the month's `clean_lbs_processed` multiplied by the plant's `utility_baseline_kwh_per_lb` times `kwh_rate_cents`, plus `clean_lbs_processed` multiplied by `utility_baseline_gal_per_lb` times `gallon_rate_cents`, the sum rounded half-up to whole cents; and takes the excess as the actual minus the baseline, floored at zero. The excess passes through on a tiered schedule: the first 100000 cents of excess pass at 50 percent, the portion of the excess above 100000 and up to 500000 cents passes at 75 percent, and any portion above 500000 cents passes at 100 percent."

        Design: Difficulty/combinatorial_formula/utility_surcharge_tiered_min_max_mode_a
        """
        ctx = self._setup_june(api)
        invoice = generate_invoice(ctx["customer"]["id"], **JUNE)
        assert invoice["utility_surcharge_cents"] == 43750, (
            f"invoice generation must use the actual variant once the June "
            f"reading exists, got {invoice['utility_surcharge_cents']}"
        )
        assert_invoice_total_invariants(invoice)
