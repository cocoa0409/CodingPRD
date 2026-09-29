"""Provisional versus final statements, and assessed versus realized fleet savings.

Both suites drive the same read data down two different pricing paths and prove
the two answers legitimately disagree.
"""

from test_helpers import (
    assert_fields,
    assert_lines_sum_to_usage_subtotal,
    assert_statement_total_is_consistent,
    close_period,
    create_quarterly_review,
    fetch_billing_period,
    fetch_contract,
    fetch_device,
    fetch_quarterly_review,
    fetch_statement_lines,
    generate_provisional_statement,
    run_sweep,
    set_clock,
    setup_print_environment,
    submit_automated_read,
)

# Rate card used by both suites: a three-band MONO ladder and a three-band
# COLOR ladder, so that an inflated volume can select a different band.
MONO_TIERS = ((1, 1, 20_000, 9_375), (2, 20_001, 60_000, 7_333), (3, 60_001, None, 6_250))
COLOR_TIERS = ((1, 1, 5_000, 61_875), (2, 5_001, 20_000, 55_000), (3, 20_001, None, 48_000))
FLAT_MONO_TIERS = ((1, 1, None, 9_375),)
FLAT_COLOR_TIERS = ((1, 1, None, 61_875),)

CONTRACT = {
    "customer_name": "Northwind Print",
    "minimum_mono_pages_per_period": 20_000,
    "minimum_color_pages_per_period": 2_000,
    "monthly_service_fee_cents": 250_000,
    "early_termination_fee_cents": 480_000,
}
COLOUR_DEVICE = {
    "model_code": "XR-C8100",
    "color_capable": True,
    "assessed_monthly_mono_pages": 9_000,
    "assessed_monthly_color_pages": 1_200,
    "rated_monthly_duty_cycle": 20_000,
    "baseline_cost_micro_dollars_per_page": 21_000,
    "baseline_overhead_cents_per_month": 4_500,
}

PERIOD_START = "2026-08-01T00:00:00Z"
PERIOD_END = "2026-09-01T00:00:00Z"
MID_PERIOD_CLOCK = "2026-08-16T00:00:00Z"
COVERAGE_END = "2026-08-15T00:00:00Z"


def _two_device_fleet_with_half_month_of_reads(mono_tiers, color_tiers):
    """Two colour devices, one accepted reading each covering the first half of August."""
    env = setup_print_environment(
        contract=CONTRACT,
        mono_tiers=mono_tiers,
        color_tiers=color_tiers,
        site={"name": "HQ Floor 3"},
        devices=[dict(COLOUR_DEVICE), dict(COLOUR_DEVICE)],
        release_method="BADGE",
        period=(PERIOD_START, PERIOD_END),
        clock=MID_PERIOD_CLOCK,
    )
    d1, d2 = env["device_ids"]
    env["reads"] = [
        submit_automated_read(
            d1,
            env["period_id"],
            mono_meter=12_000,
            color_meter=900,
            toner_level_pct=60,
            coverage_start=PERIOD_START,
            coverage_end=COVERAGE_END,
        ),
        submit_automated_read(
            d2,
            env["period_id"],
            mono_meter=6_000,
            color_meter=300,
            toner_level_pct=60,
            coverage_start=PERIOD_START,
            coverage_end=COVERAGE_END,
        ),
    ]
    return env


class TestProvisionalVersusFinalStatement:
    """The same two readings, priced as a mid-period projection and as actuals."""

    def test_provisional_projection_scales_pages_and_selects_the_second_mono_band(self):
        """A mid-period projection annualises each meter before tier selection.

        PRD: "On the **PROVISIONAL** variant they are scaled up to the whole
        period: the period length in days is the number of seconds between
        `period_start` and `period_end` divided by 86,400 and rounded **up** to a
        whole day; the elapsed length in days is the number of seconds between
        `period_start` and the earlier of the current logical clock and
        `period_end`, divided by 86,400, rounded **down** to a whole day, and then
        floored at a minimum of 1 day so the scaling never divides by zero."
        PRD: "Each device's projected pages for a meter are its actual pages for
        that meter multiplied by the period length in days, divided by the elapsed
        length in days, and rounded half up to a whole page."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_statement_diverge_on_identical_reads
        """
        env = _two_device_fleet_with_half_month_of_reads(MONO_TIERS, COLOR_TIERS)

        statement = generate_provisional_statement(env["period_id"])

        assert_fields(
            statement,
            variant="PROVISIONAL",
            projection_basis="PROJECTED",
            mono_pages_billed=37_200,
            color_pages_billed=2_480,
            mono_tier_index=2,
            mono_rate_micro_dollars_per_page=7_333,
            color_tier_index=1,
            color_rate_micro_dollars_per_page=61_875,
            usage_subtotal_cents=42_624,
            shortfall_pages=0,
            shortfall_cents=0,
            waste_penalty_cents=0,
            total_cents=42_624,
        )
        assert_statement_total_is_consistent(statement)
        assert_fields(
            fetch_billing_period(env["period_id"]),
            status="PROVISIONAL",
            provisional_total_cents=42_624,
        )

    def test_final_statement_prices_the_actual_pages_and_charges_the_shortfall(self):
        """Closing the period prices the real pages at the band the real volume selects.

        PRD: "On the **FINAL** variant, the device's billable pages for each meter
        are exactly those actual sums."
        PRD: "The monochrome shortfall in pages is the contract's
        `minimum_mono_pages_per_period` less the contract-level monochrome volume,
        floored at zero; the colour shortfall is `minimum_color_pages_per_period`
        less the contract-level colour volume, likewise floored at zero."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_statement_diverge_on_identical_reads
        """
        env = _two_device_fleet_with_half_month_of_reads(MONO_TIERS, COLOR_TIERS)
        generate_provisional_statement(env["period_id"])

        set_clock(PERIOD_END)
        final_statement = close_period(env["period_id"])

        assert_fields(
            final_statement,
            variant="FINAL",
            projection_basis="ACTUAL",
            mono_pages_billed=18_000,
            color_pages_billed=1_200,
            mono_tier_index=1,
            mono_rate_micro_dollars_per_page=9_375,
            usage_subtotal_cents=24_300,
            shortfall_pages=2_800,
            shortfall_cents=6_825,
            total_cents=31_125,
        )
        assert_statement_total_is_consistent(final_statement)
        assert_fields(
            fetch_billing_period(env["period_id"]),
            status="CLOSED",
            provisional_total_cents=42_624,
            final_total_cents=31_125,
        )

    def test_close_accumulates_the_signed_variance_into_the_true_up_balance(self):
        """The projection was higher than the actuals, so the true-up runs negative.

        PRD: "`lifetime_billed_cents` grows by the statement's `total_cents`, and
        `true_up_balance_cents` grows by the period's `final_total_cents` less its
        `provisional_total_cents` — treating a null `provisional_total_cents` as
        equal to the final total, so that a period which never carried a projection
        contributes exactly zero to the true-up."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_statement_diverge_on_identical_reads
        """
        env = _two_device_fleet_with_half_month_of_reads(MONO_TIERS, COLOR_TIERS)
        generate_provisional_statement(env["period_id"])

        set_clock(PERIOD_END)
        close_period(env["period_id"])

        assert_fields(
            fetch_contract(env["contract_id"]),
            lifetime_billed_cents=31_125,
            true_up_balance_cents=-11_499,
        )

    def test_final_statement_lines_price_every_device_meter_in_created_at_order(self):
        """Four lines, monochrome before colour within each device.

        PRD: "Lines are emitted device by device in ascending order of the device's
        `created_at`, and within each device the monochrome line comes before the
        colour line."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_statement_diverge_on_identical_reads
        """
        env = _two_device_fleet_with_half_month_of_reads(MONO_TIERS, COLOR_TIERS)
        generate_provisional_statement(env["period_id"])
        set_clock(PERIOD_END)
        final_statement = close_period(env["period_id"])

        lines = fetch_statement_lines(final_statement["id"])
        d1, d2 = env["device_ids"]

        assert len(lines) == 4, f"expected 4 statement lines, got {len(lines)}: {lines}"
        expected = [
            (d1, "MONO", 12_000, 9_375, 11_250),
            (d1, "COLOR", 900, 61_875, 5_569),
            (d2, "MONO", 6_000, 9_375, 5_625),
            (d2, "COLOR", 300, 61_875, 1_856),
        ]
        for line, (device_id, page_class, pages, rate, amount_cents) in zip(lines, expected):
            assert_fields(
                line,
                statement_id=final_statement["id"],
                device_id=device_id,
                page_class=page_class,
                pages=pages,
                rate_micro_dollars_per_page=rate,
                amount_cents=amount_cents,
            )
        assert_lines_sum_to_usage_subtotal(lines, final_statement)


class TestAssessedVersusRealizedFleetSavings:
    """The quarterly review's two savings figures on one unchanged fleet."""

    @staticmethod
    def _closed_period_fleet():
        env = _two_device_fleet_with_half_month_of_reads(FLAT_MONO_TIERS, FLAT_COLOR_TIERS)
        set_clock(PERIOD_END)
        run_sweep(env["period_id"])
        env["statement"] = close_period(env["period_id"])
        return env

    def test_baseline_savings_price_the_assessment_promise(self):
        """Assessed volumes at entry rates, rounded per device before summation.

        PRD: "For each fleet device, its pre-contract monthly cost is the sum of
        `assessed_monthly_mono_pages` and `assessed_monthly_color_pages` multiplied
        by `baseline_cost_micro_dollars_per_page`, divided by 10,000 and rounded
        half up to a whole cent, plus its `baseline_overhead_cents_per_month`."
        PRD: "`baseline_savings_cents` is the sum, over the fleet, of each device's
        pre-contract cost less its managed-print cost. Each device's two costs are
        rounded before the fleet-wide summation — round per device, then sum."

        Design: Difficulty/dual_variant_calc/tco_savings_assessed_vs_realized_diverge_on_same_fleet
        """
        env = self._closed_period_fleet()

        review = create_quarterly_review(env["contract_id"], quarter_label="2026-Q3")

        assert_fields(
            review,
            baseline_savings_cents=20_114,
            status="DRAFT",
            authored_by_user_id="am-1",
        )

    def test_realized_savings_price_the_closed_period_actuals(self):
        """Realized savings read the final statement's lines, not the assessment.

        PRD: "Otherwise, from that period's `FINAL` statement, each fleet device's
        realized pages are the sum of `pages` across the statement lines naming
        that device, and its realized billed amount is the sum of `amount_cents`
        across those same lines."
        PRD: "`realized_savings_cents` is the sum, over the fleet, of each device's
        realized baseline less its realized billed amount — again rounded per device
        before summation."

        Design: Difficulty/dual_variant_calc/tco_savings_assessed_vs_realized_diverge_on_same_fleet
        """
        env = self._closed_period_fleet()
        assert env["statement"]["total_cents"] == 31_125

        review = create_quarterly_review(env["contract_id"], quarter_label="2026-Q3")

        assert_fields(review, realized_savings_cents=25_020, volume_trend_pct=0)
        assert review["realized_savings_cents"] != review["baseline_savings_cents"], (
            "the two savings figures must diverge on under-run actuals: "
            f"{review['realized_savings_cents']} vs {review['baseline_savings_cents']}"
        )

    def test_right_sizing_classifies_each_device_from_its_realized_utilization(self):
        """One device retains at 64.5 percent, the other downgrades at 31.5 percent.

        PRD: "Each fleet device's utilization is its realized pages from the most
        recently closed period's `FINAL` statement lines divided by its
        `rated_monthly_duty_cycle`, and the comparison is made as an **exact
        rational** — pages against duty cycle scaled by the threshold percentage —
        never as a rounded decimal, so that a device sitting exactly on a boundary
        lands on the inclusive side."
        PRD: "The classification writes `right_sizing_action` on the device and is
        evaluated in this order: utilization at or below 15 percent yields
        `CONSOLIDATE`; otherwise utilization at or below 40 percent yields
        `DOWNGRADE`; otherwise utilization at or above 90 percent yields `UPGRADE`;
        otherwise the device yields `RETAIN`."

        Design: Difficulty/dual_variant_calc/tco_savings_assessed_vs_realized_diverge_on_same_fleet
        """
        env = self._closed_period_fleet()
        d1, d2 = env["device_ids"]

        review = create_quarterly_review(env["contract_id"], quarter_label="2026-Q3")

        assert_fields(
            review,
            retain_count=1,
            downgrade_count=1,
            upgrade_count=0,
            consolidate_count=0,
            refresh_due_device_count=0,
        )
        assert_fields(fetch_device(d1), right_sizing_action="RETAIN", refresh_due=False)
        assert_fields(fetch_device(d2), right_sizing_action="DOWNGRADE", refresh_due=False)
        assert_fields(fetch_quarterly_review(review["id"]), retain_count=1, downgrade_count=1)
