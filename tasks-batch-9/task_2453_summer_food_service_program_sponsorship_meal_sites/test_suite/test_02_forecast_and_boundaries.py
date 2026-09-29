"""Attendance-forecast variants and the exact-threshold boundaries of the compliance metrics.

Three metrics are exercised here: the two forecasting philosophies offered by the attendance
forecast read, the area-income percentage compared against its per-data-source threshold, and the
truncated whole minutes of holding time compared against the four-hour limit.
"""

from typing import Any, Dict, List

import pytest

from test_helpers import (
    assert_holding_log_entry,
    assert_site,
    create_area_record,
    create_open_day,
    create_site,
    determine_eligibility,
    record_holding_log,
    set_clock,
    setup_finalized_history,
    setup_program_baseline,
    validate_success,
)

# --- Forecast history -------------------------------------------------------------------------

FORECAST_DATE = "2026-06-11"
FORECAST_CLOCK = "2026-06-10T18:00:00Z"

# A declining LUNCH attendance series, each day producing 150 meals.
FORECAST_WINDOW: List[Dict[str, Any]] = [
    {"service_date": "2026-06-08", "first_meals": 80, "planned_meals": 150},
    {"service_date": "2026-06-09", "first_meals": 100, "planned_meals": 150},
    {"service_date": "2026-06-10", "first_meals": 60, "planned_meals": 150},
]


def _forecast_scenario() -> dict:
    """Approved sponsor and one operating site with three FINALIZED days before the target date."""
    scenario = setup_program_baseline()
    scenario["days"] = setup_finalized_history(
        scenario["site"]["id"], scenario["sponsor"]["id"], FORECAST_WINDOW
    )
    set_clock(FORECAST_CLOCK)
    return scenario


def _read_forecast(api, scenario: dict, method: str) -> dict:
    return validate_success(
        api.get_attendance_forecast(
            scenario["site"]["id"],
            scenario["sponsor_headers"],
            params={"service_date": FORECAST_DATE, "method": method},
        )
    )


class TestAttendanceForecastVariants:
    """The same three-day window answered by both forecasting methods."""

    def test_peak_projection_uplifts_the_window_maximum_by_ten_percent(self, api):
        """PRD §3.9: "It takes the single highest attendance in the window, inflates it by 10 percent, rounds that product up to the next whole meal, and then caps the result at `approved_max_attendance`."

        Design: Difficulty/dual_variant_calc/attendance_forecast_peak_projection_versus_decay_weighted
        """
        scenario = _forecast_scenario()

        forecast = _read_forecast(api, scenario, "PEAK_PROJECTION")

        assert forecast["site_id"] == scenario["site"]["id"], (
            "the forecast must echo the site it was read for"
        )
        assert forecast["service_date"] == FORECAST_DATE, (
            f"expected the requested service_date {FORECAST_DATE}, got {forecast['service_date']}"
        )
        assert forecast["method"] == "PEAK_PROJECTION", (
            f"expected method PEAK_PROJECTION, got {forecast['method']}"
        )
        assert forecast["prior_days_used"] == 3, (
            "the three finalized days before 2026-06-11 all enter the window, so prior_days_used "
            f"must be 3, got {forecast['prior_days_used']}"
        )
        assert forecast["forecast_meals"] == 110, (
            "the window maximum of 100 first meals uplifted 10 percent and rounded up is 110, got "
            f"{forecast['forecast_meals']}"
        )

    def test_decay_weighted_recency_weights_shrink_the_declining_series(self, api):
        """PRD §3.9: "It takes a recency-weighted mean of the window: the most recent day carries a weight of 1, the day before it a weight of 0.6, the one before that 0.36, and so on, each step multiplying the weight by 0.6."

        Design: Difficulty/dual_variant_calc/attendance_forecast_peak_projection_versus_decay_weighted
        """
        scenario = _forecast_scenario()

        forecast = _read_forecast(api, scenario, "DECAY_WEIGHTED")

        assert forecast["method"] == "DECAY_WEIGHTED", (
            f"expected method DECAY_WEIGHTED, got {forecast['method']}"
        )
        assert forecast["prior_days_used"] == 3, (
            f"expected prior_days_used 3 for the three finalized days, got {forecast['prior_days_used']}"
        )
        assert forecast["forecast_meals"] == 76, (
            "60 at weight 1, 100 at weight 0.6 and 80 at weight 0.36 give a weighted mean of "
            f"148.80 / 1.96, which rounds half-up to 76, got {forecast['forecast_meals']}"
        )

    def test_both_methods_report_the_same_production_and_waste_risk_signal(self, api):
        """PRD §3.9: "`most_recent_production_meals` is the total of all values in the `production_counts` of the most recent day in the window, and `waste_risk_flag` is true when that production figure exceeds `forecast_meals` by strictly more than 10 percent of `forecast_meals`, with that tolerance floored to a whole meal."

        Design: Difficulty/dual_variant_calc/attendance_forecast_peak_projection_versus_decay_weighted
        """
        scenario = _forecast_scenario()

        peak = _read_forecast(api, scenario, "PEAK_PROJECTION")
        decay = _read_forecast(api, scenario, "DECAY_WEIGHTED")

        for method, forecast in (("PEAK_PROJECTION", peak), ("DECAY_WEIGHTED", decay)):
            assert forecast["most_recent_production_meals"] == 150, (
                f"{method}: the most recent window day produced 150 LUNCH meals, got "
                f"{forecast['most_recent_production_meals']}"
            )
            assert forecast["waste_risk_flag"] is True, (
                f"{method}: production 150 exceeds the forecast by more than the floored 10 percent "
                "tolerance, so waste_risk_flag must be true"
            )

        assert peak["forecast_meals"] - decay["forecast_meals"] == 34, (
            "the two philosophies must disagree on this declining series: 110 under peak "
            f"projection against 76 under decay weighting, got {peak['forecast_meals']} and "
            f"{decay['forecast_meals']}"
        )


# --- Area eligibility percentage boundaries ---------------------------------------------------


def _site_with_area_record(area_code: str, data_source: str, free_reduced_pct: float,
                           name: str) -> dict:
    """An approved sponsor's PENDING_REVIEW OPEN site citing one area income record."""
    scenario = setup_program_baseline(site_count=0, include_budget=False)
    record = create_area_record(
        area_code=area_code,
        data_source=data_source,
        free_reduced_pct=free_reduced_pct,
        determination_date="2026-03-15",
        valid_through_date="2031-06-30",
    )
    site = create_site(scenario["sponsor"]["id"], record["id"], name=name)
    return {"scenario": scenario, "record": record, "site": site}


class TestAreaEligibilityPercentageBoundary:
    """The inclusive percentage thresholds, one per data source, at two decimal places."""

    @pytest.mark.parametrize(
        "area_code,free_reduced_pct,expected_basis",
        [
            ("CT-0031", 50.00, "AREA_ELIGIBLE"),
            ("CT-0032", 49.99, "NOT_ELIGIBLE"),
        ],
    )
    def test_school_data_threshold_is_inclusive_at_fifty_percent(
        self, area_code, free_reduced_pct, expected_basis
    ):
        """PRD §3.4: "Otherwise, if the record's `data_source` is `SCHOOL_DATA`, the basis is `AREA_ELIGIBLE` when the percentage is at least 50.00 and `NOT_ELIGIBLE` otherwise."

        Design: Difficulty/boundary_precision_check/area_eligibility_percentage_at_exact_threshold_by_data_source
        """
        built = _site_with_area_record(
            area_code, "SCHOOL_DATA", free_reduced_pct, f"School Data Site {area_code}"
        )

        determined = determine_eligibility(built["site"]["id"])

        assert determined["eligibility_basis"] == expected_basis, (
            f"school data at {free_reduced_pct:.2f} percent must yield eligibility_basis "
            f"{expected_basis}, got {determined['eligibility_basis']}"
        )
        assert float(determined["eligibility_pct_used"]) == pytest.approx(
            free_reduced_pct, abs=0.005
        ), (
            "eligibility_pct_used must carry the cited record's free_reduced_pct "
            f"{free_reduced_pct:.2f}, got {determined['eligibility_pct_used']}"
        )

    @pytest.mark.parametrize(
        "area_code,free_reduced_pct,expected_basis",
        [
            ("CT-0033", 55.00, "AREA_ELIGIBLE"),
            ("CT-0034", 54.99, "NOT_ELIGIBLE"),
        ],
    )
    def test_census_acs_surcharge_moves_the_threshold_to_fifty_five_percent(
        self, area_code, free_reduced_pct, expected_basis
    ):
        """PRD §3.4: "Otherwise the record came from `CENSUS_ACS`, which carries a documentation surcharge, and the basis is `AREA_ELIGIBLE` only when the percentage is at least 55.00."

        Design: Difficulty/boundary_precision_check/area_eligibility_percentage_at_exact_threshold_by_data_source
        """
        built = _site_with_area_record(
            area_code, "CENSUS_ACS", free_reduced_pct, f"Census Site {area_code}"
        )

        determined = determine_eligibility(built["site"]["id"])

        assert determined["eligibility_basis"] == expected_basis, (
            f"census data at {free_reduced_pct:.2f} percent must yield eligibility_basis "
            f"{expected_basis}, got {determined['eligibility_basis']}"
        )
        assert float(determined["eligibility_pct_used"]) == pytest.approx(
            free_reduced_pct, abs=0.005
        ), (
            "eligibility_pct_used must carry the cited record's free_reduced_pct "
            f"{free_reduced_pct:.2f}, got {determined['eligibility_pct_used']}"
        )

    def test_determination_leaves_the_site_pending_review_and_may_be_rerun(self, api):
        """PRD §3.4: "Re-running the determination is permitted while the site remains in `PENDING_REVIEW`, and each run recomputes both fields from whatever the underlying data now says."

        Design: Difficulty/boundary_precision_check/area_eligibility_percentage_at_exact_threshold_by_data_source
        """
        built = _site_with_area_record("CT-0035", "SCHOOL_DATA", 50.00, "Boundary Site")

        first = determine_eligibility(built["site"]["id"])
        assert first["approval_status"] == "PENDING_REVIEW", (
            "determining eligibility writes eligibility_basis and eligibility_pct_used only, so "
            f"approval_status must stay PENDING_REVIEW, got {first['approval_status']}"
        )

        second = determine_eligibility(built["site"]["id"])
        assert second["eligibility_basis"] == "AREA_ELIGIBLE", (
            "a re-run over unchanged school data at exactly 50.00 percent must again read "
            f"AREA_ELIGIBLE, got {second['eligibility_basis']}"
        )
        assert float(second["eligibility_pct_used"]) == pytest.approx(50.00, abs=0.005), (
            f"the re-run must recompute eligibility_pct_used as 50.00, got "
            f"{second['eligibility_pct_used']}"
        )

        site = validate_success(
            api.get_site(built["site"]["id"], built["scenario"]["sponsor_headers"])
        )
        assert_site(site)
        assert site["approval_status"] == "PENDING_REVIEW", (
            f"the persisted site must still read PENDING_REVIEW, got {site['approval_status']}"
        )


# --- Holding-time boundary --------------------------------------------------------------------

HOLDING_SERVICE_DATE = "2026-06-08"
FOOD_RECEIVED_AT = "2026-06-08T10:30:00Z"
AT_LIMIT_MEASURED_AT = "2026-06-08T14:30:00Z"
OVER_LIMIT_MEASURED_AT = "2026-06-08T14:31:00Z"


def _open_air_day_scenario() -> dict:
    """An open-air site with an OPEN day whose food was received at 10:30 and 150 LUNCH produced."""
    scenario = setup_program_baseline(site_overrides={"is_open_air": True})
    scenario["day"] = create_open_day(
        scenario["site"]["id"],
        HOLDING_SERVICE_DATE,
        production_counts={"LUNCH": 150},
        food_received_at=FOOD_RECEIVED_AT,
    )
    return scenario


def _instant(value) -> str:
    """The seconds-precision instant of an ISO 8601 timestamp, ignoring fractional digits."""
    return "" if value is None else str(value)[:19]


class TestHoldingTimeBoundary:
    """Truncated whole minutes of holding time against the four-hour limit."""

    def test_reading_at_exactly_240_holding_minutes_is_compliant(self, api):
        """PRD §3.6: "All three comparisons are strict, so a cold reading of exactly 41.0 is compliant and 41.1 breaches, a hot reading of exactly 135.0 is compliant and 134.9 breaches, and exactly 240 holding minutes is compliant while 241 breaches."

        Design: Difficulty/boundary_precision_check/holding_time_240_minutes_compliant_241_breaches
        """
        scenario = _open_air_day_scenario()

        entry = record_holding_log(
            scenario["day"],
            meal_type="LUNCH",
            temperature_class="HOT",
            temperature_f=140.0,
            measured_at=AT_LIMIT_MEASURED_AT,
        )

        assert_holding_log_entry(entry)
        assert entry["holding_minutes"] == 240, (
            "10:30 to 14:30 is exactly 240 whole minutes of holding time, got "
            f"{entry['holding_minutes']}"
        )
        assert entry["breach_flag"] is False, (
            "exactly 240 holding minutes at a compliant 140.0 F is not a breach"
        )
        assert entry["breach_reason"] is None, (
            f"a compliant reading carries no breach_reason, got {entry['breach_reason']}"
        )

        day = validate_success(
            api.get_meal_service_day(scenario["day"]["id"], scenario["sponsor_headers"])
        )
        assert day["food_safety_status"] == "OK", (
            "a compliant reading must leave the day's food_safety_status at OK, got "
            f"{day['food_safety_status']}"
        )

    def test_reading_at_241_holding_minutes_breaches_and_discards_the_day(self, api):
        """PRD §3.6: "When a breaching reading arrives while the day's `food_safety_status` is still `OK`, that status flips to `BREACH`, the day's `breach_at` is set to the reading's `measured_at`, the day's `discarded_meals` becomes the unserved production at that moment — the total of all values in `production_counts`, less `counted_first_meals`, less `counted_second_meals`, less `counted_adult_meals`, floored at 0 — and the day's `leftover_meals` is forced to 0, since food removed from service is discarded rather than left over."

        Design: Difficulty/boundary_precision_check/holding_time_240_minutes_compliant_241_breaches
        """
        scenario = _open_air_day_scenario()
        record_holding_log(
            scenario["day"],
            meal_type="LUNCH",
            temperature_class="HOT",
            temperature_f=140.0,
            measured_at=AT_LIMIT_MEASURED_AT,
        )

        entry = record_holding_log(
            scenario["day"],
            meal_type="LUNCH",
            temperature_class="HOT",
            temperature_f=140.0,
            measured_at=OVER_LIMIT_MEASURED_AT,
        )

        assert entry["holding_minutes"] == 241, (
            "10:30 to 14:31 truncates to 241 whole minutes, got "
            f"{entry['holding_minutes']}"
        )
        assert entry["breach_flag"] is True, (
            "241 holding minutes is above the 240-minute limit, so breach_flag must be true"
        )
        assert entry["breach_reason"] == "HOLDING_TIME_EXCEEDED", (
            "a compliant 140.0 F reading past four hours breaches on the holding clock, so "
            f"breach_reason must be HOLDING_TIME_EXCEEDED, got {entry['breach_reason']}"
        )

        day = validate_success(
            api.get_meal_service_day(scenario["day"]["id"], scenario["sponsor_headers"])
        )
        assert day["food_safety_status"] == "BREACH", (
            "the first breaching reading of the day flips food_safety_status to BREACH, got "
            f"{day['food_safety_status']}"
        )
        assert _instant(day["breach_at"]) == _instant(OVER_LIMIT_MEASURED_AT), (
            "breach_at must be the breaching reading's measured_at "
            f"{OVER_LIMIT_MEASURED_AT}, got {day['breach_at']}"
        )
        assert day["discarded_meals"] == 150, (
            "no meals had been counted, so the whole 150-meal production is discarded, got "
            f"{day['discarded_meals']}"
        )
        assert day["leftover_meals"] == 0, (
            f"leftover_meals is forced to 0 once food is discarded, got {day['leftover_meals']}"
        )
