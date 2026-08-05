"""Capacity and concurrency: the day-capacity boundary, half-open interval overlap,
the host concurrency ceiling, and the cancel/reserve conservation invariant.
"""
from test_helpers import (
    validate_error, get_success_data,
    ApiErrorId,
    setup_open_location, create_booking, create_additional_open_location, location_version,
)


def _bags(n, dim=100):
    return [{"declared_value_cents": 1000, "dimension_sum_cm": dim} for _ in range(n)]


def _create_expecting_error(api, ctx, *, check_in_date, check_out_date, bags, location=None):
    loc = location or ctx["location"]
    version = location_version(api, loc["id"], ctx["traveler_headers"])
    return api.create_booking(
        {"location_id": loc["id"], "traveler_id": ctx["traveler"]["id"],
         "insurance_plan_id": ctx["plan"]["id"], "check_in_date": check_in_date,
         "check_out_date": check_out_date, "bags": bags,
         "expected_location_version": version},
        ctx["traveler_headers"])


# --- Boundary: reserved+requested == capacity allowed, one over rejected -----

def test_capacity_exact_equal_allowed(api):
    """PRD §3.3: "For every day in the half-open interval from `check_in_date` up to
    `check_out_date`, adding this booking's bags must keep the day's total reserved bags
    within `daily_bag_capacity` and its reserved oversize bags within `oversize_capacity`;
    a violation of the former is `ERR_CAPACITY_EXCEEDED` and of the latter
    `ERR_OVERSIZE_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/capacity_exact_equal_allowed_one_over_rejected
    """
    ctx = setup_open_location(api, tier="NONE", per_bag_coverage_cents=0,
                              premium_cents_per_bag_day=0, daily_bag_capacity=10, oversize_capacity=10)
    create_booking(api, ctx, check_in_date="2026-06-10", check_out_date="2026-06-13", bags=_bags(8))
    second = create_booking(api, ctx, check_in_date="2026-06-10", check_out_date="2026-06-13", bags=_bags(2))
    assert second["bag_count"] == 2
    assert second["status"] == "RESERVED"


def test_capacity_one_over_rejected(api):
    """PRD §3.3: "For every day in the half-open interval from `check_in_date` up to
    `check_out_date`, adding this booking's bags must keep the day's total reserved bags
    within `daily_bag_capacity` and its reserved oversize bags within `oversize_capacity`;
    a violation of the former is `ERR_CAPACITY_EXCEEDED` and of the latter
    `ERR_OVERSIZE_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/capacity_exact_equal_allowed_one_over_rejected
    """
    ctx = setup_open_location(api, tier="NONE", per_bag_coverage_cents=0,
                              premium_cents_per_bag_day=0, daily_bag_capacity=10, oversize_capacity=10)
    create_booking(api, ctx, check_in_date="2026-06-10", check_out_date="2026-06-13", bags=_bags(8))
    create_booking(api, ctx, check_in_date="2026-06-10", check_out_date="2026-06-13", bags=_bags(2))
    resp = _create_expecting_error(api, ctx, check_in_date="2026-06-10",
                                   check_out_date="2026-06-13", bags=_bags(1))
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED.value)


# --- Half-open interval: overlap rejected, adjacent allowed --------------------

def test_capacity_overlapping_interval_rejected(api):
    """PRD §3.3: "For every day in the half-open interval from `check_in_date` up to
    `check_out_date`, adding this booking's bags must keep the day's total reserved bags
    within `daily_bag_capacity` and its reserved oversize bags within `oversize_capacity`;
    a violation of the former is `ERR_CAPACITY_EXCEEDED` and of the latter
    `ERR_OVERSIZE_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/location_daily_capacity_halfopen_adjacent_ok
    """
    ctx = setup_open_location(api, tier="NONE", per_bag_coverage_cents=0,
                              premium_cents_per_bag_day=0, daily_bag_capacity=3, oversize_capacity=3)
    create_booking(api, ctx, check_in_date="2026-06-10", check_out_date="2026-06-13", bags=_bags(3))
    resp = _create_expecting_error(api, ctx, check_in_date="2026-06-12",
                                   check_out_date="2026-06-15", bags=_bags(1))
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED.value)


def test_capacity_adjacent_interval_allowed(api):
    """PRD §3.3: "For every day in the half-open interval from `check_in_date` up to
    `check_out_date`, adding this booking's bags must keep the day's total reserved bags
    within `daily_bag_capacity`."

    Design: Difficulty/resource_temporal_overlap/location_daily_capacity_halfopen_adjacent_ok
    """
    ctx = setup_open_location(api, tier="NONE", per_bag_coverage_cents=0,
                              premium_cents_per_bag_day=0, daily_bag_capacity=3, oversize_capacity=3)
    create_booking(api, ctx, check_in_date="2026-06-10", check_out_date="2026-06-13", bags=_bags(3))
    # [06-13, 06-15) shares no day with [06-10, 06-13): the earlier booking releases 06-13.
    adjacent = create_booking(api, ctx, check_in_date="2026-06-13", check_out_date="2026-06-15", bags=_bags(1))
    assert adjacent["status"] == "RESERVED"


# --- Host concurrency ceiling -------------------------------------------------

def test_host_concurrency_ceiling_exceeded(api):
    """PRD §3.3: "The host's network-wide `max_concurrent_bookings` must also not be
    exceeded by the count of simultaneously-active (reserved or stored) bookings across all
    of that host's locations, else `ERR_HOST_CONCURRENCY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/host_concurrency_closed_interval_count
    """
    ctx = setup_open_location(api, tier="NONE", per_bag_coverage_cents=0,
                              premium_cents_per_bag_day=0, max_concurrent_bookings=1)
    loc_b = create_additional_open_location(api, ctx, name="B", address="2 Main")
    create_booking(api, ctx, check_in_date="2026-06-10", check_out_date="2026-06-13", bags=_bags(1))
    resp = _create_expecting_error(api, ctx, check_in_date="2026-06-12",
                                   check_out_date="2026-06-16", bags=_bags(1), location=loc_b)
    validate_error(resp, ApiErrorId.ERR_HOST_CONCURRENCY_EXCEEDED.value)


def test_host_concurrency_at_ceiling_allowed(api):
    """PRD §3.3: "The host's network-wide `max_concurrent_bookings` must also not be
    exceeded by the count of simultaneously-active (reserved or stored) bookings across all
    of that host's locations, else `ERR_HOST_CONCURRENCY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/host_concurrency_closed_interval_count
    """
    ctx = setup_open_location(api, tier="NONE", per_bag_coverage_cents=0,
                              premium_cents_per_bag_day=0, max_concurrent_bookings=2)
    loc_b = create_additional_open_location(api, ctx, name="B", address="2 Main")
    b1 = create_booking(api, ctx, check_in_date="2026-06-10", check_out_date="2026-06-13", bags=_bags(1))
    b2 = create_booking(api, ctx, check_in_date="2026-06-12", check_out_date="2026-06-16",
                        bags=_bags(1), location=loc_b)
    # Two simultaneously-active bookings under a ceiling of 2 is allowed (count not exceeded).
    assert b1["status"] == "RESERVED"
    assert b2["status"] == "RESERVED"


# --- Capacity conservation on cancel ------------------------------------------

def test_capacity_restored_after_cancel(api):
    """PRD §3.3: "Cancellation cascades every bag of the booking to `VOIDED` and releases
    the booking's reserved day-capacity back to the location, restoring the conservation
    invariant of §2.7."

    Design: Difficulty/compensating_invariant/capacity_conservation_on_cancel
    """
    ctx = setup_open_location(api, tier="NONE", per_bag_coverage_cents=0,
                              premium_cents_per_bag_day=0, daily_bag_capacity=3, oversize_capacity=3)
    first = create_booking(api, ctx, check_in_date="2026-06-10", check_out_date="2026-06-13", bags=_bags(3))
    get_success_data(api.cancel_booking(first["id"], ctx["traveler_headers"]))
    fresh = create_booking(api, ctx, check_in_date="2026-06-10", check_out_date="2026-06-13", bags=_bags(3))
    assert fresh["bag_count"] == 3
    assert fresh["status"] == "RESERVED"


def test_capacity_consumed_while_active(api):
    """PRD §2.7: "A booking reserves capacity for every day in its stay, and the platform
    must guarantee that on no day does the sum of reserved bags exceed `daily_bag_capacity`."

    Design: Difficulty/compensating_invariant/capacity_conservation_on_cancel
    """
    ctx = setup_open_location(api, tier="NONE", per_bag_coverage_cents=0,
                              premium_cents_per_bag_day=0, daily_bag_capacity=3, oversize_capacity=3)
    create_booking(api, ctx, check_in_date="2026-06-10", check_out_date="2026-06-13", bags=_bags(3))
    # Without a cancel, the reservation stands and a second full booking is refused.
    resp = _create_expecting_error(api, ctx, check_in_date="2026-06-10",
                                   check_out_date="2026-06-13", bags=_bags(3))
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED.value)
