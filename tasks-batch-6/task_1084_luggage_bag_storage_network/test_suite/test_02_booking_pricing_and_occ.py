"""Booking creation: the multi-input estimate, the oversize threshold, date-range
validity, and the optimistic-concurrency guard on Location.version.
"""
from test_helpers import (
    validate_error, get_success_data,
    ApiErrorId,
    setup_open_location, create_booking, get_bags, location_version,
)


def test_booking_estimate_multiinput_value(api):
    """PRD §3.3: "The base storage component is the location's `per_bag_day_rate_cents`
    multiplied by `bag_count` and by `billable_days`. The oversize component is the
    location's `oversize_surcharge_cents_per_day` multiplied by `oversize_count` and by
    `billable_days`. The insurance component is the plan's `premium_cents_per_bag_day`
    multiplied by `bag_count` and by `billable_days`, and is zero whenever the plan tier is
    `NONE`. The estimate is the sum of these three components, in whole cents."

    Design: Difficulty/combinatorial_formula/booking_estimate_multiinput_nonlinear_mode_a
    """
    ctx = setup_open_location(api, tier="PREMIUM", per_bag_coverage_cents=50000,
                              premium_cents_per_bag_day=200)
    booking = create_booking(
        api, ctx, check_in_date="2026-06-10", check_out_date="2026-06-13",
        bags=[{"declared_value_cents": 20000, "dimension_sum_cm": 100},
              {"declared_value_cents": 20000, "dimension_sum_cm": 100},
              {"declared_value_cents": 20000, "dimension_sum_cm": 160}])
    # base 500*3*3=4500 + oversize 300*1*3=900 + insurance 200*3*3=1800 = 7200
    assert booking["estimated_total_cents"] == 7200


def test_booking_estimate_multiinput_component_counts(api):
    """PRD §3.3: "The booking's `bag_count` is the number of bags minted, and its
    `oversize_count` is how many of them are oversize."
    PRD §3.3: "The booking's `billable_days` is the number of days between check-in and
    check-out, floored at a minimum of 1 so that even a same-day stay bills one day."

    Design: Difficulty/combinatorial_formula/booking_estimate_multiinput_nonlinear_mode_a
    """
    ctx = setup_open_location(api, tier="PREMIUM", per_bag_coverage_cents=50000,
                              premium_cents_per_bag_day=200)
    booking = create_booking(
        api, ctx, check_in_date="2026-06-10", check_out_date="2026-06-13",
        bags=[{"declared_value_cents": 20000, "dimension_sum_cm": 100},
              {"declared_value_cents": 20000, "dimension_sum_cm": 100},
              {"declared_value_cents": 20000, "dimension_sum_cm": 160}])
    assert booking["bag_count"] == 3
    assert booking["oversize_count"] == 1
    assert booking["billable_days"] == 3


def test_oversize_threshold_150_boundary(api):
    """PRD §3.3: "a bag is oversize exactly when its `dimension_sum_cm` is at least 150
    centimeters."

    Design: Corner/calculations/oversize_threshold_150_boundary
    """
    ctx = setup_open_location(api, tier="NONE", per_bag_coverage_cents=0, premium_cents_per_bag_day=0)
    booking = create_booking(
        api, ctx, check_in_date="2026-06-10", check_out_date="2026-06-11",
        bags=[{"declared_value_cents": 1000, "dimension_sum_cm": 149},
              {"declared_value_cents": 1000, "dimension_sum_cm": 150}])
    assert booking["oversize_count"] == 1
    bags = get_bags(api, ctx, booking["id"])
    by_dim = {b["dimension_sum_cm"]: b["is_oversize"] for b in bags}
    assert by_dim[149] is False
    assert by_dim[150] is True


def test_booking_invalid_date_range_returns_error(api):
    """PRD §3.3: "the `check_out_date` must be strictly after the `check_in_date`, and the
    check-in must not lie in the past — otherwise `ERR_INVALID_DATE_RANGE`."

    Design: Corner/validations/booking_invalid_date_range_returns_error
    """
    ctx = setup_open_location(api, tier="NONE", per_bag_coverage_cents=0, premium_cents_per_bag_day=0)
    version = location_version(api, ctx["location"]["id"], ctx["traveler_headers"])
    resp = api.create_booking(
        {"location_id": ctx["location"]["id"], "traveler_id": ctx["traveler"]["id"],
         "insurance_plan_id": ctx["plan"]["id"], "check_in_date": "2026-06-13",
         "check_out_date": "2026-06-10",
         "bags": [{"declared_value_cents": 1000, "dimension_sum_cm": 100}],
         "expected_location_version": version},
        ctx["traveler_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE.value)


def test_booking_create_stale_location_version_returns_412(api):
    """PRD §2.5: "In that case the create is rejected with `ERR_STALE_LOCATION_VERSION`
    (HTTP 412) before capacity is ever evaluated, so the client cannot overwrite capacity
    decisions it has not observed."

    Design: Corner/cross_cutting_complexity_layers/booking_create_stale_location_version_returns_412
    """
    ctx = setup_open_location(api, tier="NONE", per_bag_coverage_cents=0, premium_cents_per_bag_day=0)
    stale_version = location_version(api, ctx["location"]["id"], ctx["traveler_headers"])
    # First booking consumes the version the client holds and advances Location.version.
    create_booking(api, ctx, check_in_date="2026-06-10", check_out_date="2026-06-11",
                   bags=[{"declared_value_cents": 1000, "dimension_sum_cm": 100}],
                   expected_location_version=stale_version)
    # Second booking replays the now-stale version.
    resp = api.create_booking(
        {"location_id": ctx["location"]["id"], "traveler_id": ctx["traveler"]["id"],
         "insurance_plan_id": ctx["plan"]["id"], "check_in_date": "2026-06-10",
         "check_out_date": "2026-06-11",
         "bags": [{"declared_value_cents": 1000, "dimension_sum_cm": 100}],
         "expected_location_version": stale_version},
        ctx["traveler_headers"])
    validate_error(resp, ApiErrorId.ERR_STALE_LOCATION_VERSION.value)
