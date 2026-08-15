"""Post-season markdown: tier selection by days after season end, half-up
rounding, the fifty-cent floor, and overwrite (not compounding) semantics."""
import pytest

from test_helpers import (
    MANAGER,
    get_lot,
    set_clock,
    setup_closed_window_with_seasonal_lots,
    validate_success,
)

HOLIDAY_TIERS = [
    {"day_offset_min": 0, "discount_pct": 0.30},
    {"day_offset_min": 7, "discount_pct": 0.50},
    {"day_offset_min": 14, "discount_pct": 0.70},
]


class TestTieredPriceWithFloor:
    def _setup(self, api):
        """Lots A (base 1000, 200 units) and B (base 90, 100 units); window
        closed at 2027-01-03, eight days after the 2026-12-26 ship end."""
        return setup_closed_window_with_seasonal_lots(
            [{"sku": "MD-A", "base_price_cents": 1000, "units": 200,
              "day": "2026-09-05"},
             {"sku": "MD-B", "base_price_cents": 90, "units": 100,
              "day": "2026-09-06"}],
            markdown_tiers=HOLIDAY_TIERS, close_clock="2027-01-03T00:00:00Z")

    def test_tier_selection_and_response_fields(self, api):
        """PRD §3.8: "The response's `days_after_season_end` is the whole-day
        difference between the logical clock's current UTC date and the window's
        `ship_end` date" and "Each markdown tier applies once the day count
        reaches its `day_offset_min`, and the applicable `discount_pct` is the
        largest among the tiers whose `day_offset_min` has been reached"
        PRD §3.8: "The operation reports back the `updated_lot_count`, the
        `discount_pct` that was applied, and the `days_after_season_end` the
        discount was measured from"

        Design: Difficulty/combinatorial_formula/markdown_tiered_price_with_floor
        """
        ctx = self._setup(api)
        result = validate_success(api.apply_markdown(ctx["window"]["id"], MANAGER))
        assert result["updated_lot_count"] == 2
        assert result["discount_pct"] == pytest.approx(0.5), "day 8 reaches the day-7 tier"
        assert result["days_after_season_end"] == 8

        lot_a = get_lot(ctx["lots"][0]["id"])
        assert lot_a["unit_price_cents"] == 500, "round_half_up(1000 * 0.5)"

    def test_price_floor_lifts_sub_floor_result(self, api):
        """PRD §3.8: "the lot's new `unit_price_cents` is the greater of that
        rounded figure and the price floor of fifty cents — seasonal stock is
        never priced below the floor, whatever the tier says."

        Design: Difficulty/combinatorial_formula/markdown_tiered_price_with_floor
        """
        ctx = self._setup(api)
        validate_success(api.apply_markdown(ctx["window"]["id"], MANAGER))
        lot_b = get_lot(ctx["lots"][1]["id"])
        assert lot_b["unit_price_cents"] == 50, (
            "round_half_up(90 * 0.5) = 45 is lifted to the fifty-cent floor")


class TestTierBoundary:
    def test_day_six_stays_in_first_tier(self, api):
        """PRD §3.8: "Each markdown tier applies once the day count reaches its
        `day_offset_min`, and the applicable `discount_pct` is the largest among
        the tiers whose `day_offset_min` has been reached; when no tier
        qualifies, the discount is zero."
        PRD §3.8: "the raw price is rounded half-up to a whole cent"

        Design: Difficulty/boundary_precision_check/markdown_tier_day_seven_boundary
        """
        ctx = setup_closed_window_with_seasonal_lots(
            [{"sku": "MD-C", "base_price_cents": 1000, "units": 100,
              "day": "2026-09-05"}],
            markdown_tiers=HOLIDAY_TIERS, close_clock="2027-01-01T00:00:00Z")
        result = validate_success(api.apply_markdown(ctx["window"]["id"], MANAGER))
        assert result["days_after_season_end"] == 6
        assert result["discount_pct"] == pytest.approx(0.3), (
            "day 6 has not reached the day-7 tier")
        assert get_lot(ctx["lots"][0]["id"])["unit_price_cents"] == 700

    def test_day_seven_crosses_into_second_tier_and_overwrites(self, api):
        """PRD §3.8: "For every lot in scope, the raw price is the product's
        `base_price_cents` reduced by that discount percentage"
        PRD §3.8: "it overwrites whatever `unit_price_cents` the lots carried,
        including any earlier markdown."

        Design: Difficulty/boundary_precision_check/markdown_tier_day_seven_boundary
        """
        ctx = setup_closed_window_with_seasonal_lots(
            [{"sku": "MD-C", "base_price_cents": 1000, "units": 100,
              "day": "2026-09-05"}],
            markdown_tiers=HOLIDAY_TIERS, close_clock="2027-01-01T00:00:00Z")
        # First markdown at day 6 (30%), then re-apply at day 7.
        validate_success(api.apply_markdown(ctx["window"]["id"], MANAGER))
        assert get_lot(ctx["lots"][0]["id"])["unit_price_cents"] == 700

        set_clock("2027-01-02T00:00:00Z")
        result = validate_success(api.apply_markdown(ctx["window"]["id"], MANAGER))
        assert result["days_after_season_end"] == 7
        assert result["discount_pct"] == pytest.approx(0.5), (
            "day 7 reaches the day-7 tier")
        lot = get_lot(ctx["lots"][0]["id"])
        assert lot["unit_price_cents"] == 500, (
            "recomputed from the 1000-cent base, not compounded from 700")


class TestMarkdownRounding:
    def test_half_cent_rounds_half_up(self, api):
        """PRD §3.8: "the raw price is rounded half-up to a whole cent"
        PRD §2.9: "Where a price calculation produces a fractional cent, the
        value is rounded half-up to a whole cent."

        Design: Corner/calculations/markdown_rounding_half_up
        """
        ctx = setup_closed_window_with_seasonal_lots(
            [{"sku": "MD-R", "base_price_cents": 995, "units": 100,
              "day": "2026-09-05"}],
            markdown_tiers=[{"day_offset_min": 7, "discount_pct": 0.50}],
            close_clock="2027-01-02T00:00:00Z")
        result = validate_success(api.apply_markdown(ctx["window"]["id"], MANAGER))
        assert result["discount_pct"] == pytest.approx(0.5)
        lot = get_lot(ctx["lots"][0]["id"])
        assert lot["unit_price_cents"] == 498, (
            "round_half_up(497.5) rounds up to 498, not truncated to 497")
