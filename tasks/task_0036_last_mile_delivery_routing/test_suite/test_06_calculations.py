"""Failure-score accrual/recovery, redelivery surcharge, sorted-count recompute.

Queue B (Corner): section calculations.
"""
import pytest
from test_helpers import validate_success, get_success_data, TEST_USERS
from test_helpers import fixtures as fx

DM = TEST_USERS["dispatch_manager_headers"]


def test_service_failure_score_accrues_and_recovers(api):
    """PRD §3.6: "The base penalty is 10 points. On top of that, an escalation
    of 5 points is multiplied by the attempt's `attempt_index` minus 1 ... if the
    parcel's `hazmat_class` is anything other than `NONE`, an extra 8 points is
    added".
    PRD §3.6: "When a stop is successfully redelivered out of
    `REDELIVERY_SCHEDULED` into `DELIVERED`, 6 points are subtracted from
    `failure_points` as a recovery credit (with the floor at zero applied so the
    score never drops below zero)."

    Design: Corner/calculations/service_failure_score_accrues_and_recovers
    """
    center = fx.create_center(name="HubC14", hazmat_certified=True, sort_capacity=10)
    driver = fx.create_driver(name="Dsf", hazmat_certified=True, vehicle_capacity_kg=50)
    parcel = fx.create_sorted_parcel(center["id"], weight_kg=1.0, hazmat_class="CLASS_3")
    route = fx.create_route(driver["id"], center["id"], service_date="2026-07-13")
    stop = fx.add_stop(route["id"], parcel["id"])
    fx.dispatch_route(route["id"])
    fx.log_attempt(stop["id"], driver["id"], "NO_ONE_HOME")  # +18 -> 18
    fx.reschedule(stop["id"])
    fx.log_attempt(stop["id"], driver["id"], "NO_ONE_HOME")  # +23 -> 41
    fx.reschedule(stop["id"])
    fx.log_attempt(stop["id"], driver["id"], "DELIVERED")    # -6 -> 35

    data = validate_success(api.get_driver(driver["id"], DM))
    assert data["failure_points"] == 35, f"expected 35, got {data['failure_points']}"
    stop_d = validate_success(api.get_stop(stop["id"], DM))
    assert stop_d["status"] == "DELIVERED"


def test_failure_points_never_negative(api):
    """PRD §3.6: "A driver's `failure_points` is a running accumulator that
    begins at zero, is floored at zero so it is never negative, and has no upper
    cap."

    Design: Corner/calculations/failure_points_floored_at_zero
    """
    s = fx.setup_redelivery_scheduled_stop(name_suffix="fl", service_date="2026-07-14")
    # one non-hazmat failed attempt (+10), then successful redelivery (-6) -> 4
    fx.log_attempt(s["stop"]["id"], s["driver"]["id"], "DELIVERED")
    data = validate_success(api.get_driver(s["driver"]["id"], DM))
    assert data["failure_points"] == 4, f"expected 4 (10 - 6), got {data['failure_points']}"


def test_redelivery_surcharge_priority_no_extras(api):
    """PRD §3.5: "Start from a service-level base: 300 cents for a `GROUND`
    parcel, 500 cents for `EXPRESS`, and 800 cents for `PRIORITY`. Add an
    attempt-escalation increment of 150 cents multiplied by the reschedule
    index, where the reschedule index is the stop's `attempt_count` minus 1
    taken at the moment of reschedule (so the first reschedule, which follows the
    first attempt, uses index 0".

    Design: Corner/calculations/redelivery_surcharge_priority_no_extras
    """
    center = fx.create_center(name="HubC16", sort_capacity=10)
    driver = fx.create_driver(name="Dpr", vehicle_capacity_kg=50)
    parcel = fx.create_sorted_parcel(center["id"], weight_kg=1.0, service_level="PRIORITY")
    route = fx.create_route(driver["id"], center["id"], service_date="2026-07-15")
    stop = fx.add_stop(route["id"], parcel["id"])
    fx.dispatch_route(route["id"])
    fx.log_attempt(stop["id"], driver["id"], "NO_ONE_HOME")
    data = validate_success(api.reschedule_stop(stop["id"], DM))
    assert data["redelivery_fee_cents"] == 800, (
        f"PRIORITY base 800, no extras, got {data['redelivery_fee_cents']}")


def test_center_sorted_count_decrements_on_route(api):
    """PRD §3.3: "On success, the new stop starts in `PENDING`, the parcel moves
    from `SORTED` to `ROUTED`, the origin center's `sorted_count` is recomputed
    downward".

    Design: Corner/calculations/center_sorted_count_decrements_on_route
    """
    center = fx.create_center(name="HubC17", sort_capacity=10)
    driver = fx.create_driver(name="Dsc", vehicle_capacity_kg=50)
    pa = fx.create_sorted_parcel(center["id"], weight_kg=1.0)
    fx.create_sorted_parcel(center["id"], weight_kg=1.0)  # sorted_count == 2
    route = fx.create_route(driver["id"], center["id"], service_date="2026-07-16")
    fx.add_stop(route["id"], pa["id"])  # routes one -> sorted_count 1
    data = validate_success(api.get_transit_center(center["id"], DM))
    assert data["sorted_count"] == 1, f"expected 1, got {data['sorted_count']}"
