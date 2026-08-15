"""Attendance-forecast calculation: dual variants, multi-factor branching, and
the opening-week inclusive boundary."""
from test_helpers import (
    constants, setup_theater_screen_feature, validate_success,
    make_network_ops_headers,
)
from test_helpers import api_client
from test_helpers.factories import create_showtime_payload


def _create_showtime(screen_id, feature_id, starts_at):
    resp = api_client.create_showtime(screen_id, create_showtime_payload(feature_id, starts_at=starts_at),
                                      make_network_ops_headers())
    return validate_success(resp, expected_status=201)


class TestForecastDualVariant:
    def test_forecast_opening_week_vs_standard_opening(self, api):
        """PRD §3.1: "the opening-week multiplier, which is 1.25 when the
        showtime's calendar date falls within the opening-week window described
        above and 1.0 outside it."

        Design: Difficulty/dual_variant_calc/forecast_opening_week_vs_standard
        """
        _, screen, feature = setup_theater_screen_feature()
        showtime = _create_showtime(screen["id"], feature["id"], constants.OPENING_EVENING_START)
        assert showtime["forecast_attendance"] == 132

    def test_forecast_opening_week_vs_standard_standard(self, api):
        """PRD §3.1: "the opening-week multiplier, which is 1.25 when the
        showtime's calendar date falls within the opening-week window described
        above and 1.0 outside it."

        Design: Difficulty/dual_variant_calc/forecast_opening_week_vs_standard
        """
        _, screen, feature = setup_theater_screen_feature()
        opening = _create_showtime(screen["id"], feature["id"], constants.OPENING_EVENING_START)
        standard = _create_showtime(screen["id"], feature["id"], constants.STANDARD_EVENING_START)
        assert standard["forecast_attendance"] == 105
        # Identical seat_count, market_tier, daypart, and content_rating — only
        # the opening-week branch differs.
        assert opening["forecast_attendance"] != standard["forecast_attendance"]


class TestForecastMultiFactorConditionalBranch:
    def test_forecast_opening_matinee_branch(self, api):
        """PRD §3.1: "the resulting base is multiplied by the daypart factor
        (0.80 for `MATINEE`, 1.20 for `EVENING`), by the rating-demand factor for
        the feature's `content_rating` (0.90 for `G`, 1.00 for `PG`, 1.10 for
        `PG13`, 1.05 for `R`, and 0.70 for `NC17`), and finally by the
        opening-week multiplier"
        PRD §3.1: "The forecast is the floor of that full product, taken only
        after every multiplication has been applied."

        Design: Difficulty/combinatorial_formula/forecast_multi_factor_conditional_branch
        """
        _, screen, feature = setup_theater_screen_feature()
        matinee = _create_showtime(screen["id"], feature["id"], constants.OPENING_MATINEE_START)
        # floor(200 x 0.40 x 0.80 x 1.10 x 1.25) == 88
        assert matinee["daypart"] == "MATINEE"
        assert matinee["forecast_attendance"] == 88

    def test_forecast_opening_evening_branch(self, api):
        """PRD §3.1: "the resulting base is multiplied by the daypart factor
        (0.80 for `MATINEE`, 1.20 for `EVENING`), by the rating-demand factor for
        the feature's `content_rating` (0.90 for `G`, 1.00 for `PG`, 1.10 for
        `PG13`, 1.05 for `R`, and 0.70 for `NC17`), and finally by the
        opening-week multiplier"

        Design: Difficulty/combinatorial_formula/forecast_multi_factor_conditional_branch
        """
        _, screen, feature = setup_theater_screen_feature()
        evening = _create_showtime(screen["id"], feature["id"], constants.OPENING_EVENING_START)
        # floor(200 x 0.40 x 1.20 x 1.10 x 1.25) == 132
        assert evening["daypart"] == "EVENING"
        assert evening["forecast_attendance"] == 132


class TestForecastOpeningBoundary:
    def test_forecast_day7_inside_window(self, api):
        """PRD §3.1: "the release date opens the feature's opening-week window,
        the span from `release_date` through the date seven days after it, both
        endpoints inclusive."

        Design: Corner/calculations/forecast_opening_boundary_day7_vs_day8
        """
        _, screen, feature = setup_theater_screen_feature()
        day7 = _create_showtime(screen["id"], feature["id"], constants.DAY7_EVENING_START)
        assert day7["forecast_attendance"] == 132

    def test_forecast_day8_outside_window(self, api):
        """PRD §3.1: "the release date opens the feature's opening-week window,
        the span from `release_date` through the date seven days after it, both
        endpoints inclusive."

        Design: Corner/calculations/forecast_opening_boundary_day7_vs_day8
        """
        _, screen, feature = setup_theater_screen_feature()
        day8 = _create_showtime(screen["id"], feature["id"], constants.DAY8_EVENING_START)
        assert day8["forecast_attendance"] == 105
