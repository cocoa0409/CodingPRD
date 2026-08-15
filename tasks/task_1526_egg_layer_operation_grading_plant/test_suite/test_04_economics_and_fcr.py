"""Flock economics: the two cost-per-dozen variants and the FCR weight switch."""
import pytest

from test_helpers import (
    confirm_grading_run,
    record_feed_delivery,
    record_production_days,
    setup_laying_flock,
    validate_success,
)
from test_helpers.fixtures import FARM_MANAGER

PERIOD = {"period_start": "2026-06-22", "period_end": "2026-06-28"}


def _econ_setup(api):
    """One flock with seven production days (2026-06-22..28) and two feed
    layers (50c/kg then 60c/kg); 3 hens of mortality -> 997 current hens."""
    ctx = setup_laying_flock(clock_iso="2026-06-28T00:00:00Z")
    farm_id = ctx["farm"]["id"]
    flock_id = ctx["flock"]["id"]
    record_feed_delivery(
        farm_id, delivered_at="2026-06-01", quantity_kg=5000, cost_per_kg_cents=50
    )
    record_feed_delivery(
        farm_id, delivered_at="2026-06-20", quantity_kg=4000, cost_per_kg_cents=60
    )
    days = [
        {"lay_date": "2026-06-22", "eggs_collected": 890, "rejected_eggs": 10, "feed_issued_kg": 118, "mortality_count": 1},
        {"lay_date": "2026-06-23", "eggs_collected": 895, "rejected_eggs": 8, "feed_issued_kg": 118, "mortality_count": 0},
        {"lay_date": "2026-06-24", "eggs_collected": 892, "rejected_eggs": 9, "feed_issued_kg": 118, "mortality_count": 1},
        {"lay_date": "2026-06-25", "eggs_collected": 900, "rejected_eggs": 10, "feed_issued_kg": 118, "mortality_count": 0},
        {"lay_date": "2026-06-26", "eggs_collected": 898, "rejected_eggs": 7, "feed_issued_kg": 118, "mortality_count": 0},
        {"lay_date": "2026-06-27", "eggs_collected": 901, "rejected_eggs": 8, "feed_issued_kg": 118, "mortality_count": 1},
        {"lay_date": "2026-06-28", "eggs_collected": 905, "rejected_eggs": 9, "feed_issued_kg": 118, "mortality_count": 0},
    ]
    ctx["production_days"] = record_production_days(flock_id, days)
    return ctx


class TestCostPerDozenVariants:
    def test_cost_per_dozen_actual_fifo_variant(self, api):
        """PRD §3.3: "The `ACTUAL_FIFO` variant works from trailing actuals
        and is the variant a `COST_PLUS` settlement uses at finalize time.
        `feed_cost_cents` is the sum of the window's recorded `feed_cost_cents`
        values (the FIFO layer costs), and `total_eggs` is the sum of
        `eggs_collected` over the window. The cost per dozen is then the sum
        of feed cents, overhead cents, and amortization cents, minus the
        spent-hen credit, the difference multiplied by 12 and divided by
        `total_eggs`, rounded half-up to two decimal places."
        PRD §3.3: "`overhead_cents` is then the farm's `daily_overhead_cents`
        multiplied by the number of days in the period and by the flock's
        share, rounded half-up."
        PRD §3.3: "`amortization_cents` is the flock's `pullet_cost_cents`
        multiplied by the number of days in the period and divided by 420 —
        the fixed amortization horizon — rounded half-up."

        Design: Difficulty/dual_variant_calc/cost_per_dozen_actual_fifo_vs_projected_standard
        """
        ctx = _econ_setup(api)
        data = validate_success(
            api.get_flock_economics(
                ctx["flock"]["id"],
                FARM_MANAGER,
                params={**PERIOD, "variant": "ACTUAL_FIFO"},
            )
        )
        assert data["feed_cost_cents"] == 41300, (
            f"7 x 118 kg all from the 50c/kg layer = 41300c, got "
            f"{data['feed_cost_cents']}"
        )
        assert data["overhead_cents"] == 84000  # 12000 x 7 days x share 1
        assert data["amortization_cents"] == 7000  # 420000 x 7 / 420
        assert data["spent_hen_credit_cents"] == 0
        assert data["total_eggs"] == 6281
        assert data["cost_per_dozen_cents"] == pytest.approx(252.76), (
            f"(41300 + 84000 + 7000) x 12 / 6281 = 252.76, got "
            f"{data['cost_per_dozen_cents']}"
        )
        assert data["feed_conversion_ratio"] == pytest.approx(2.192), (
            f"826 kg / (6281 x 60 g / 1000) = 2.192, got "
            f"{data['feed_conversion_ratio']}"
        )

    def test_cost_per_dozen_projected_standard_variant(self, api):
        """PRD §3.3: "Its egg projection applies the lay-curve projection
        evaluated at the flock's `age_weeks` as of `period_end`, using the
        current `lay_cycle`, `breed_peak_rate_pct`, and `status`: projected
        eggs equal `current_hen_count` multiplied by that projected rate
        divided by 100 and by the number of days in the period, rounded
        half-up to a whole number."
        PRD §3.3: "Its feed term prices a standard intake of 115 grams per hen
        per day: `current_hen_count` multiplied by 115 and by the number of
        days in the period, divided by 1000 to reach kilograms, then
        multiplied by the `cost_per_kg_cents` of the farm's most recent feed
        delivery — the one with the latest `delivered_at`, ties broken by
        earliest `created_at` — and rounded half-up to cents."

        Design: Difficulty/dual_variant_calc/cost_per_dozen_actual_fifo_vs_projected_standard
        """
        ctx = _econ_setup(api)
        data = validate_success(
            api.get_flock_economics(
                ctx["flock"]["id"],
                FARM_MANAGER,
                params={**PERIOD, "variant": "PROJECTED_STANDARD"},
            )
        )
        # 997 hens x 95.00% x 7 days = 6630 projected eggs (age 24 -> plateau).
        assert data["total_eggs"] == 6630, (
            f"projected eggs must be 6630, got {data['total_eggs']}"
        )
        # 997 x 115 g x 7 / 1000 = 802.585 kg x 60c (latest delivery) = 48155c.
        assert data["feed_cost_cents"] == 48155, (
            f"projected feed term must price the latest 60c/kg layer, got "
            f"{data['feed_cost_cents']}"
        )
        assert data["cost_per_dozen_cents"] == pytest.approx(251.86), (
            f"(48155 + 84000 + 7000) x 12 / 6630 = 251.86, got "
            f"{data['cost_per_dozen_cents']}"
        )

    def test_cost_per_dozen_variants_diverge_on_same_window(self, api):
        """PRD §3.3: "The `ACTUAL_FIFO` variant works from trailing actuals
        and is the variant a `COST_PLUS` settlement uses at finalize time."
        PRD §3.3: "The `PROJECTED_STANDARD` variant supports forward-looking
        quotes."
        (Same flock, same window: the two variants price from different inputs
        and therefore answer differently — 252.76 vs 251.86 here.)

        Design: Difficulty/dual_variant_calc/cost_per_dozen_actual_fifo_vs_projected_standard
        """
        ctx = _econ_setup(api)
        actual = validate_success(
            api.get_flock_economics(
                ctx["flock"]["id"],
                FARM_MANAGER,
                params={**PERIOD, "variant": "ACTUAL_FIFO"},
            )
        )
        projected = validate_success(
            api.get_flock_economics(
                ctx["flock"]["id"],
                FARM_MANAGER,
                params={**PERIOD, "variant": "PROJECTED_STANDARD"},
            )
        )
        assert actual["cost_per_dozen_cents"] == pytest.approx(252.76)
        assert projected["cost_per_dozen_cents"] == pytest.approx(251.86)
        assert actual["cost_per_dozen_cents"] != projected["cost_per_dozen_cents"]


class TestFeedConversionRatio:
    def test_fcr_switches_to_size_weighted_mass_after_confirm(self, api):
        """PRD §3.3: "The average egg weight defaults to 60 grams until the
        flock has a confirmed, non-voided grading run; once one exists, it
        becomes the size-weighted average over the most recently confirmed
        run's six size-class counts, using reference weights of 42 grams for
        `PEEWEE`, 49 for `SMALL`, 56 for `MEDIUM`, 63 for `LARGE`, 70 for
        `XLARGE`, and 77 for `JUMBO` — each class count multiplied by its
        reference weight, the products summed, and the sum divided by the
        total count of eggs in the six size classes."
        PRD §3.3: "The ratio itself is rounded half-up to three decimal
        places, and it is reported as null when the egg mass over the window
        is zero."

        Design: Corner/calculations/fcr_switches_to_size_weighted_mass_after_confirm
        """
        ctx = setup_laying_flock()
        # Stock the FIFO queue so the 120 kg issuance can be costed.
        record_feed_delivery(
            ctx["farm"]["id"],
            delivered_at="2026-07-01",
            quantity_kg=5000,
            cost_per_kg_cents=50,
        )
        record_production_days(
            ctx["flock"]["id"],
            [
                {
                    "lay_date": "2026-07-31",
                    "eggs_collected": 240,
                    "rejected_eggs": 0,
                    "feed_issued_kg": 120,
                    "mortality_count": 0,
                }
            ],
        )
        _run, lots = confirm_grading_run(ctx["flock"]["id"], grade="A", eggs_to_grade=240)
        assert len(lots) == 1 and lots[0]["size_class"] == "LARGE"

        data = validate_success(
            api.get_flock_economics(
                ctx["flock"]["id"],
                FARM_MANAGER,
                params={
                    "period_start": "2026-07-27",
                    "period_end": "2026-08-02",
                    "variant": "ACTUAL_FIFO",
                },
            )
        )
        assert data["feed_conversion_ratio"] == pytest.approx(7.937), (
            f"120 kg / (240 eggs x 63 g / 1000) = 7.937 with the size-weighted "
            f"LARGE weight, got {data['feed_conversion_ratio']}"
        )
        assert data["feed_conversion_ratio"] != pytest.approx(8.333), (
            "the 60 g default (8.333) must not apply once a confirmed run exists"
        )
