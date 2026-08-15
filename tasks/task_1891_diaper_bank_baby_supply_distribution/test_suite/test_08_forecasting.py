"""Size-mix forecasting: trailing-actual vs booked-pipeline variants and the mix gap."""
import pytest

from test_helpers import (
    TEST_USERS,
    find_forecast_size_entry,
    init_inventory,
    post_donation,
    setup_completed_event,
    supply_line,
    validate_success,
)

WAREHOUSE = TEST_USERS["warehouse_manager_headers"]


class TestForecastVariants:
    def test_trailing_actual_forecast_from_fulfilled_history(self, api):
        """PRD §3.8: "The default `TRAILING_ACTUAL` variant is backward-looking: over the trailing window from twenty-eight days before the logical clock through now, inclusive at both ends, each size's `weekly_rate` is the total fulfilled issuance quantity for that size in the window divided by four, and `forecast_4wk_units` is that weekly rate multiplied by four, rounded half up to a whole unit. Its `weeks_of_supply` is the size's `on_hand_units` divided by the weekly rate, rounded half up to two decimal places — or null when the trailing rate is zero."

        Design: Difficulty/dual_variant_calc/forecast_trailing_actual_vs_booked_pipeline
        """
        # 280 SIZE_2 fulfilled at the default clock (inside the trailing window);
        # on_hand is 420 after fulfillment (700 posted - 280 fulfilled).
        setup_completed_event(size_code="SIZE_2", stock_units=700,
                              issue_quantity=280)

        resp = api.get_inventory_forecast(WAREHOUSE,
                                          params={"variant": "TRAILING_ACTUAL"})
        forecast = validate_success(resp, 200)
        assert forecast["variant"] == "TRAILING_ACTUAL"

        entry = find_forecast_size_entry(forecast["sizes"], "SIZE_2")
        # weekly_rate = 280 / 4 = 70; forecast = round_half_up(70 * 4) = 280.
        assert entry["forecast_4wk_units"] == 280
        # weeks_of_supply = round_half_up(420 / 70, 2) = 6.0.
        assert entry["weeks_of_supply"] == pytest.approx(6.0)

    def test_booked_pipeline_forecast_from_published_remainder(self, api):
        """PRD §3.8: "The `BOOKED_PIPELINE` variant is forward-looking committed demand instead: `forecast_4wk_units` is the sum of `allocated_units` minus `fulfilled_units` over the size's lines belonging to `PUBLISHED` runs, plus the sum of quantities over `RECORDED` issuance lines for the size at events that are `OPEN` or `LOCKED`, and its `weeks_of_supply` is always null — identical inventory and history produce different numbers under the two variants."

        Design: Difficulty/dual_variant_calc/forecast_trailing_actual_vs_booked_pipeline
        """
        # PUBLISHED line of 700 with 280 fulfilled -> remainder 420; the only
        # issuance is FULFILLED at a COMPLETED event, so no RECORDED-at-OPEN/
        # LOCKED quantities contribute.
        setup_completed_event(size_code="SIZE_2", stock_units=700,
                              issue_quantity=280)

        booked = validate_success(
            api.get_inventory_forecast(WAREHOUSE,
                                       params={"variant": "BOOKED_PIPELINE"}),
            200,
        )
        assert booked["variant"] == "BOOKED_PIPELINE"
        entry = find_forecast_size_entry(booked["sizes"], "SIZE_2")
        assert entry["forecast_4wk_units"] == 420, "700 allocated - 280 fulfilled"
        assert entry["weeks_of_supply"] is None, (
            "BOOKED_PIPELINE never reports weeks of supply"
        )

        trailing = validate_success(
            api.get_inventory_forecast(WAREHOUSE,
                                       params={"variant": "TRAILING_ACTUAL"}),
            200,
        )
        trailing_entry = find_forecast_size_entry(trailing["sizes"], "SIZE_2")
        assert trailing_entry["forecast_4wk_units"] == 280
        assert entry["forecast_4wk_units"] != trailing_entry["forecast_4wk_units"], (
            "Identical inventory and history produce different numbers per variant"
        )


class TestForecastEdgeInputs:
    def test_forecast_zero_history_null_weeks(self, api):
        """PRD §3.8: "Its `weeks_of_supply` is the size's `on_hand_units` divided by the weekly rate, rounded half up to two decimal places — or null when the trailing rate is zero."
        PRD §3.8: "A size's `need_share` is its `forecast_4wk_units` divided by the sum of `forecast_4wk_units` across all sizes; when that denominator is zero, every size's `need_share` is zero."
        PRD §3.8: "a size's `donation_share` is its posted donation units in the window divided by the total posted donation units in the window, or zero when the window contains no posted donations."

        Design: Corner/calculations/forecast_zero_history_null_weeks
        """
        init_inventory()

        forecast = validate_success(api.get_inventory_forecast(WAREHOUSE), 200)
        assert forecast["variant"] == "TRAILING_ACTUAL", (
            "The variant defaults to TRAILING_ACTUAL"
        )
        sizes = forecast["sizes"]
        assert len(sizes) == 8, "One forecast entry per size code"
        for entry in sizes:
            assert entry["forecast_4wk_units"] == 0
            assert entry["weeks_of_supply"] is None, (
                "A zero trailing rate reports null, not infinity or an error"
            )
            assert entry["need_share"] == 0
            assert entry["donation_share"] == 0
            assert entry["mix_gap"] == 0

    def test_donation_mix_gap_share_precision(self, api):
        """PRD §3.8: "The donation window runs from ninety days before the logical clock through now, inclusive, over `posted_at` of `POSTED` batches with `source_type` `DONATION`: a size's `donation_share` is its posted donation units in the window divided by the total posted donation units in the window, or zero when the window contains no posted donations. A size's `mix_gap` is its `need_share` minus its `donation_share`, rounded half up to four decimal places — the single number that tells the bank which sizes the community donates too much of and which it must buy."

        Design: Corner/calculations/donation_mix_gap_share_precision
        """
        init_inventory()
        # Both batches post at the default clock, inside the 90-day window.
        post_donation([supply_line("SIZE_1", 700)], donor_name="Donor M1")
        post_donation([supply_line("SIZE_2", 300)], donor_name="Donor M2")

        forecast = validate_success(api.get_inventory_forecast(WAREHOUSE), 200)
        size_1 = find_forecast_size_entry(forecast["sizes"], "SIZE_1")
        size_2 = find_forecast_size_entry(forecast["sizes"], "SIZE_2")
        size_3 = find_forecast_size_entry(forecast["sizes"], "SIZE_3")

        # donation shares: 700 / 1000 and 300 / 1000, four-decimal rounded.
        assert size_1["donation_share"] == pytest.approx(0.7, abs=1e-9)
        assert size_2["donation_share"] == pytest.approx(0.3, abs=1e-9)
        # No fulfilled history -> need_share is 0 everywhere, so the mix gap is
        # the negated donation share.
        assert size_1["need_share"] == 0
        assert size_1["mix_gap"] == pytest.approx(-0.7, abs=1e-9)
        assert size_2["mix_gap"] == pytest.approx(-0.3, abs=1e-9)
        # Sizes with no posted donations report a zero share and zero gap.
        assert size_3["donation_share"] == 0
        assert size_3["mix_gap"] == 0
