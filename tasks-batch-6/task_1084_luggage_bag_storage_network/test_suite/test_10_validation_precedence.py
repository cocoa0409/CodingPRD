"""Validation precedence: when two checks could both reject a request, the lower-numbered
check in the §2.8 order wins. Each pair is verified two ways — the conflict resolves to
the higher-priority error, and the lower-priority error still fires in isolation.
"""
from test_helpers import (
    validate_error, get_success_data,
    ApiErrorId,
    setup_open_location, create_booking, location_version,
    setup_completed_booking, set_clock,
)


# --- State (priority 6) beats Capacity (priority 9) on booking create ---------

def test_booking_create_location_state_beats_capacity(api):
    """PRD §3.3: "The referenced location must be `OPEN` at creation time, or the request is
    rejected with `ERR_LOCATION_NOT_OPEN`."
    PRD §2.8: "The higher-priority (lower-numbered) check always wins."

    Design: Difficulty/priority_pair_validation_conflict/booking_create_location_state_beats_capacity
    """
    ctx = setup_open_location(api, tier="BASIC", per_bag_coverage_cents=10000,
                              premium_cents_per_bag_day=100, daily_bag_capacity=2, oversize_capacity=2)
    create_booking(api, ctx, check_in_date="2026-06-10", check_out_date="2026-06-13",
                   bags=[{"declared_value_cents": 5000, "dimension_sum_cm": 100},
                         {"declared_value_cents": 5000, "dimension_sum_cm": 100}])
    get_success_data(api.set_location_status(
        ctx["location"]["id"], {"to_status": "SUSPENDED"}, ctx["host_headers"]))
    version = location_version(api, ctx["location"]["id"], ctx["traveler_headers"])
    # Both a state violation (SUSPENDED) and a capacity violation (2+2 > 2) are present.
    resp = api.create_booking(
        {"location_id": ctx["location"]["id"], "traveler_id": ctx["traveler"]["id"],
         "insurance_plan_id": ctx["plan"]["id"], "check_in_date": "2026-06-10",
         "check_out_date": "2026-06-13",
         "bags": [{"declared_value_cents": 5000, "dimension_sum_cm": 100},
                  {"declared_value_cents": 5000, "dimension_sum_cm": 100}],
         "expected_location_version": version},
        ctx["traveler_headers"])
    validate_error(resp, ApiErrorId.ERR_LOCATION_NOT_OPEN.value)


def test_booking_capacity_fires_when_location_open(api):
    """PRD §3.3: "For every day in the half-open interval from `check_in_date` up to
    `check_out_date`, adding this booking's bags must keep the day's total reserved bags
    within `daily_bag_capacity` and its reserved oversize bags within `oversize_capacity`;
    a violation of the former is `ERR_CAPACITY_EXCEEDED` and of the latter
    `ERR_OVERSIZE_CAPACITY_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/booking_create_location_state_beats_capacity
    """
    ctx = setup_open_location(api, tier="BASIC", per_bag_coverage_cents=10000,
                              premium_cents_per_bag_day=100, daily_bag_capacity=2, oversize_capacity=2)
    create_booking(api, ctx, check_in_date="2026-06-10", check_out_date="2026-06-13",
                   bags=[{"declared_value_cents": 5000, "dimension_sum_cm": 100},
                         {"declared_value_cents": 5000, "dimension_sum_cm": 100}])
    version = location_version(api, ctx["location"]["id"], ctx["traveler_headers"])
    # Location still OPEN, so with no state violation the capacity check surfaces.
    resp = api.create_booking(
        {"location_id": ctx["location"]["id"], "traveler_id": ctx["traveler"]["id"],
         "insurance_plan_id": ctx["plan"]["id"], "check_in_date": "2026-06-10",
         "check_out_date": "2026-06-13",
         "bags": [{"declared_value_cents": 5000, "dimension_sum_cm": 100},
                  {"declared_value_cents": 5000, "dimension_sum_cm": 100}],
         "expected_location_version": version},
        ctx["traveler_headers"])
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED.value)


# --- Temporal (priority 7) beats Monetary (priority 11) on claim create -------

def test_claim_create_window_beats_amount(api):
    """PRD §3.8: "The claim must be filed within a window of 3 days after the booking's
    `pickup_at`; a later filing is rejected with `ERR_CLAIM_WINDOW_CLOSED`."
    PRD §2.8: "The higher-priority (lower-numbered) check always wins."

    Design: Difficulty/priority_pair_validation_conflict/claim_create_window_beats_amount
    """
    ctx, booking, bags = setup_completed_booking(
        api, tier="PREMIUM", per_bag_coverage_cents=50000, premium_cents_per_bag_day=200,
        bags=[{"declared_value_cents": 20000, "dimension_sum_cm": 100}], seal_codes=["K0"],
        check_in_date="2026-06-10", check_out_date="2026-06-11", pickup_clock="2026-06-11")
    set_clock(api, "2026-06-20T00:00:00Z")   # past the 3-day claim window
    # claimed_amount 999999 also exceeds declared 20000; the window error must win.
    resp = api.create_claim(
        booking["id"],
        {"bag_id": bags[0]["id"], "reason": "DAMAGE", "description": "late+overclaim",
         "claimed_amount_cents": 999999},
        ctx["traveler_headers"])
    validate_error(resp, ApiErrorId.ERR_CLAIM_WINDOW_CLOSED.value)


def test_claim_amount_fires_within_window(api):
    """PRD §3.8: "The `claimed_amount_cents` must be greater than zero and no more than the
    bag's `declared_value_cents`, else `ERR_CLAIM_AMOUNT_INVALID`."

    Design: Difficulty/priority_pair_validation_conflict/claim_create_window_beats_amount
    """
    ctx, booking, bags = setup_completed_booking(
        api, tier="PREMIUM", per_bag_coverage_cents=50000, premium_cents_per_bag_day=200,
        bags=[{"declared_value_cents": 20000, "dimension_sum_cm": 100}], seal_codes=["K0"],
        check_in_date="2026-06-10", check_out_date="2026-06-11", pickup_clock="2026-06-11")
    # Still within the window; only the over-declared amount is wrong.
    resp = api.create_claim(
        booking["id"],
        {"bag_id": bags[0]["id"], "reason": "DAMAGE", "description": "overclaim",
         "claimed_amount_cents": 999999},
        ctx["traveler_headers"])
    validate_error(resp, ApiErrorId.ERR_CLAIM_AMOUNT_INVALID.value)
