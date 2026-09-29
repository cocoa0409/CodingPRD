"""The performance battery: the maturity variant, normative bands and composite scoring."""
import pytest

from test_helpers import (
    api_client,
    assert_one_decimal,
    battery_results_payload,
    create_test_session_payload,
    fetch_athlete,
    finalize_performance_battery,
    find_metric_percentile,
    setup_cleared_athlete,
    validate_error,
    validate_success,
)

# One battery, three metrics, reused across the two maturity variants.
BATTERY = {"CMJ_CM": 46.0, "SPRINT_10M_S": 1.70, "IMTP_N": 2000}


def test_01_a_battery_without_result_rows_cannot_be_finalized(api):
    """An empty session is refused by the general no-results rule, not a norm failure.

    "If it holds no rows at all, the earlier and more general `ERR_NO_TEST_RESULTS`
    applies."

    Design: Difficulty/boundary_precision_check/empty_result_set_and_empty_norm_band_set_are_distinguished_on_finalize
    """
    athlete, _staff, coach = setup_cleared_athlete(
        athlete_overrides={"full_name": "Pete Sandoval", "sport": "BASEBALL",
                           "position": "PITCHER"},
        coach_name="Ada Bright")

    empty = validate_success(api.create_test_session(
        create_test_session_payload(athlete["id"], "PERFORMANCE_BATTERY"), coach),
        expected_status=201)

    validate_error(api.finalize_test_session(empty["id"], coach),
                   "ERR_NO_TEST_RESULTS", expected_status=422)

    reread = validate_success(api.get_test_session(empty["id"], coach))
    assert reread["status"] == "DRAFT"
    assert reread["result_count"] == 0
    assert reread["composite_percentile"] is None

    reread_athlete = fetch_athlete(athlete["id"])
    assert reread_athlete["last_composite_percentile"] is None
    assert reread_athlete["next_test_due_on"] is None
    assert reread_athlete["readiness_index"] == pytest.approx(50.00, abs=0.01)


def test_02_a_populated_battery_with_no_matching_band_is_a_distinct_refusal(api):
    """Three measured metrics that match no band row fail on band availability.

    "If a battery holds result rows but not one of them resolves to a band for the
    athlete's sport, position and lookup age, no percentile can be computed and
    finalize fails with `ERR_NORM_BAND_UNAVAILABLE`."

    Design: Difficulty/boundary_precision_check/empty_result_set_and_empty_norm_band_set_are_distinguished_on_finalize
    """
    athlete, _staff, coach = setup_cleared_athlete(
        athlete_overrides={"full_name": "Pete Sandoval", "sport": "BASEBALL",
                           "position": "PITCHER"},
        coach_name="Ada Bright")

    populated = validate_success(api.create_test_session(
        create_test_session_payload(athlete["id"], "PERFORMANCE_BATTERY"), coach),
        expected_status=201)
    filled = validate_success(api.submit_test_results(
        populated["id"], battery_results_payload(BATTERY), coach))
    assert filled["result_count"] == 3

    validate_error(api.finalize_test_session(populated["id"], coach),
                   "ERR_NORM_BAND_UNAVAILABLE", expected_status=422)

    reread = validate_success(api.get_test_session(populated["id"], coach))
    assert reread["status"] == "DRAFT", "a refused finalize leaves the session DRAFT"
    assert reread["result_count"] == 3
    assert reread["composite_percentile"] is None

    reread_athlete = fetch_athlete(athlete["id"])
    assert reread_athlete["last_composite_percentile"] is None
    assert reread_athlete["next_test_due_on"] is None


def test_03_the_raw_norm_variant_scores_against_the_chronological_age_band(api):
    """With no meaningful maturity offset the lookup age is the age at test.

    "**Raw norm** (`RAW_NORM`), when the absolute value of `maturity_offset_months`
    is under 12 months: the lookup age is `age_years_at_test`, and
    `effective_age_years` equals `age_years_at_test`."

    Design: Difficulty/dual_variant_calc/performance_composite_raw_norm_variant_diverges_from_maturity_adjusted_variant
    """
    athlete, _staff, coach = setup_cleared_athlete(
        athlete_overrides={"full_name": "Rosa Lin", "date_of_birth": "2010-01-15",
                           "maturity_offset_months": 0},
        coach_name="Ivan Petrov")

    battery = finalize_performance_battery(athlete["id"], coach, BATTERY)

    assert battery["variant_applied"] == "RAW_NORM"
    assert battery["age_years_at_test"] == 16
    assert battery["effective_age_years"] == 16
    assert_one_decimal(battery["composite_percentile"], "composite_percentile")
    # 0.40 x 74.0 + 0.35 x 70.0 + 0.25 x 70.0 in the 15-16 band
    assert battery["composite_percentile"] == pytest.approx(71.6, abs=0.05)

    reread = fetch_athlete(athlete["id"])
    assert reread["last_composite_percentile"] == pytest.approx(71.6, abs=0.05)
    assert reread["next_test_due_on"] == "2026-09-26"


def test_04_the_maturity_adjusted_variant_shifts_the_band_and_the_composite(api):
    """A two-year maturity offset scores identical measurements against an older band.

    "**Maturity adjusted** (`MATURITY_ADJUSTED`), when the absolute value of
    `maturity_offset_months` is 12 months or more — a full year or beyond of early
    or late maturation: the lookup age is `age_years_at_test` plus the maturity
    offset converted from months to whole years by dividing by 12 and rounding half
    up to a whole number, and `effective_age_years` records that adjusted age."

    Design: Difficulty/dual_variant_calc/performance_composite_raw_norm_variant_diverges_from_maturity_adjusted_variant
    """
    raw_athlete, _staff, raw_coach = setup_cleared_athlete(
        athlete_overrides={"full_name": "Rosa Lin", "date_of_birth": "2010-01-15",
                           "maturity_offset_months": 0},
        coach_name="Ivan Petrov")
    adjusted_athlete, _staff_b, adjusted_coach = setup_cleared_athlete(
        athlete_overrides={"full_name": "Mateo Diaz", "date_of_birth": "2010-01-15",
                           "maturity_offset_months": 24},
        coach_name="Ivan Petrov Two")

    raw_battery = finalize_performance_battery(raw_athlete["id"], raw_coach, BATTERY)
    adjusted_battery = finalize_performance_battery(
        adjusted_athlete["id"], adjusted_coach, BATTERY)

    assert adjusted_battery["variant_applied"] == "MATURITY_ADJUSTED"
    assert adjusted_battery["age_years_at_test"] == 16
    assert adjusted_battery["effective_age_years"] == 18, \
        "24 months divided by 12 adds two whole years to the lookup age"
    # 0.40 x 53.6 + 0.35 x 55.0 + 0.25 x 50.0 in the 17-18 band
    assert adjusted_battery["composite_percentile"] == pytest.approx(53.2, abs=0.05)
    assert adjusted_battery["composite_percentile"] != raw_battery["composite_percentile"]
    assert raw_battery["composite_percentile"] == pytest.approx(71.6, abs=0.05)

    assert fetch_athlete(adjusted_athlete["id"])["next_test_due_on"] == "2026-09-26"
    assert fetch_athlete(raw_athlete["id"])["next_test_due_on"] == "2026-09-26"


def test_05_the_composite_renormalises_its_weights_over_the_matched_metrics_only(api):
    """A two-metric battery divides by the matched weights, not by the full 1.00.

    "Metrics with no matching band are excluded entirely rather than scored as
    zero, so the divisor is the sum of the weights of the matched metrics only."

    Design: Corner/calculations/composite_renormalises_weights_over_matched_metrics_only
    """
    athlete, _staff, coach = setup_cleared_athlete(
        athlete_overrides={"full_name": "Partial Battery Athlete",
                           "date_of_birth": "2010-01-15"},
        coach_name="Coach Partial")

    battery = finalize_performance_battery(
        athlete["id"], coach, {"CMJ_CM": 45.0, "IMTP_N": 1850})

    assert battery["result_count"] == 2
    # (0.40 x 70.0 + 0.25 x 60.0) / 0.65 = 66.153... -> 66.2
    assert battery["composite_percentile"] == pytest.approx(66.2, abs=0.05)
    assert battery["composite_percentile"] != pytest.approx(43.0, abs=0.05), \
        "dividing by the full weight set instead of the matched weights is not the contract"
    assert len(battery["metric_percentiles"]) == 2
    assert find_metric_percentile(battery, "SPRINT_10M_S") is None
    assert find_metric_percentile(battery, "CMJ_CM")["percentile"] == pytest.approx(
        70.0, abs=0.05)
    assert find_metric_percentile(battery, "IMTP_N")["percentile"] == pytest.approx(
        60.0, abs=0.05)

    reread = fetch_athlete(athlete["id"])
    assert reread["last_composite_percentile"] == pytest.approx(66.2, abs=0.05)
    assert reread["readiness_index"] == pytest.approx(66.20, abs=0.01)
