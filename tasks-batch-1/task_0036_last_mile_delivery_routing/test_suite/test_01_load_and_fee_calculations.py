"""Weight metrics, redelivery surcharge, and handling-fee manifest calculations.

Queue A (Difficulty): dual_variant_calc, combinatorial_formula.
"""
import pytest
from test_helpers import (
    validate_success,
    get_success_data,
    TEST_USERS,
    make_driver_headers,
)
from test_helpers import fixtures as fx

DM = TEST_USERS["dispatch_manager_headers"]
SA = TEST_USERS["sort_associate_headers"]


# ===========================================================================
# dual_variant_calc / planned_vs_committed_weight_diverge_after_one_delivery
# ===========================================================================

def test_planned_keeps_delivered_weight(api):
    """PRD §3.3: "The `planned_weight_kg` is the sum of `weight_kg` over all stops
    whose `status` is `PENDING`, `OUT_FOR_DELIVERY`, `ATTEMPTED`,
    `REDELIVERY_SCHEDULED`, or `DELIVERED` — the capacity-planning view of
    everything loaded for the run, including parcels already delivered."

    Design: Difficulty/dual_variant_calc/planned_vs_committed_weight_diverge_after_one_delivery
    """
    center = fx.create_center(name="Hub1", hazmat_certified=True, sort_capacity=10)
    driver = fx.create_driver(name="Dee", hazmat_certified=True, vehicle_capacity_kg=50)
    pa = fx.create_sorted_parcel(center["id"], weight_kg=3.0)
    pb = fx.create_sorted_parcel(center["id"], weight_kg=5.0)
    route = fx.create_route(driver["id"], center["id"], service_date="2026-06-10")
    s1 = fx.add_stop(route["id"], pa["id"], sequence=1, window_start_min=540, window_end_min=600)
    fx.add_stop(route["id"], pb["id"], sequence=2, window_start_min=660, window_end_min=720)
    fx.dispatch_route(route["id"])
    fx.log_attempt(s1["id"], driver["id"], "DELIVERED")

    data = validate_success(api.get_route(route["id"], DM))
    assert data["planned_weight_kg"] == 8.0, (
        f"planned_weight_kg must keep the DELIVERED stop weight, got {data['planned_weight_kg']}")


def test_committed_drops_delivered_weight(api):
    """PRD §3.3: "The `committed_weight_kg` is the sum of `weight_kg` over stops
    whose `status` is `PENDING`, `OUT_FOR_DELIVERY`, `ATTEMPTED`, or
    `REDELIVERY_SCHEDULED` — the live owing-load view, which excludes both
    `DELIVERED` and `FAILED` stops because those no longer owe carriage."

    Design: Difficulty/dual_variant_calc/planned_vs_committed_weight_diverge_after_one_delivery
    """
    center = fx.create_center(name="Hub1", hazmat_certified=True, sort_capacity=10)
    driver = fx.create_driver(name="Dee", hazmat_certified=True, vehicle_capacity_kg=50)
    pa = fx.create_sorted_parcel(center["id"], weight_kg=3.0)
    pb = fx.create_sorted_parcel(center["id"], weight_kg=5.0)
    route = fx.create_route(driver["id"], center["id"], service_date="2026-06-10")
    s1 = fx.add_stop(route["id"], pa["id"], sequence=1, window_start_min=540, window_end_min=600)
    fx.add_stop(route["id"], pb["id"], sequence=2, window_start_min=660, window_end_min=720)
    fx.dispatch_route(route["id"])
    fx.log_attempt(s1["id"], driver["id"], "DELIVERED")

    data = validate_success(api.get_route(route["id"], DM))
    assert data["committed_weight_kg"] == 5.0, (
        f"committed_weight_kg must exclude the DELIVERED stop, got {data['committed_weight_kg']}")


# ===========================================================================
# dual_variant_calc / redelivery_fee_cumulative_not_latest_only
# ===========================================================================

def test_redelivery_fee_accrues_cumulatively_across_two_reschedules(api):
    """PRD §3.5: "the `redelivery_surcharge` calculation governs
    `redelivery_fee_cents`, which is a cumulative running total: each reschedule
    that schedules a redelivery adds its own surcharge to the field rather than
    overwriting it, so the value grows across successive reschedules of the same stop."

    Design: Difficulty/dual_variant_calc/redelivery_fee_cumulative_not_latest_only
    """
    center = fx.create_center(name="Hub2", hazmat_certified=True, sort_capacity=10)
    driver = fx.create_driver(name="Haz", hazmat_certified=True, vehicle_capacity_kg=50)
    parcel = fx.create_sorted_parcel(
        center["id"], weight_kg=2.0,
        service_level="GROUND", signature_required=True, hazmat_class="CLASS_8",
    )
    route = fx.create_route(driver["id"], center["id"], service_date="2026-06-11")
    stop = fx.add_stop(route["id"], parcel["id"])
    fx.dispatch_route(route["id"])
    fx.log_attempt(stop["id"], driver["id"], "NO_ONE_HOME")
    fx.reschedule(stop["id"])
    fx.log_attempt(stop["id"], driver["id"], "NO_ONE_HOME")
    data = validate_success(api.reschedule_stop(stop["id"], DM))

    assert data["redelivery_fee_cents"] == 1485, (
        f"cumulative fee 630 + 855 = 1485, got {data['redelivery_fee_cents']}")
    assert data["status"] == "REDELIVERY_SCHEDULED"


def test_redelivery_fee_equals_first_surcharge_after_one_reschedule(api):
    """PRD §3.5: "the `redelivery_surcharge` calculation governs
    `redelivery_fee_cents`, which is a cumulative running total: each reschedule
    that schedules a redelivery adds its own surcharge to the field rather than
    overwriting it, so the value grows across successive reschedules of the same stop."

    Design: Difficulty/dual_variant_calc/redelivery_fee_cumulative_not_latest_only
    """
    center = fx.create_center(name="Hub2b", hazmat_certified=True, sort_capacity=10)
    driver = fx.create_driver(name="Haz2", hazmat_certified=True, vehicle_capacity_kg=50)
    parcel = fx.create_sorted_parcel(
        center["id"], weight_kg=2.0,
        service_level="GROUND", signature_required=True, hazmat_class="CLASS_8",
    )
    route = fx.create_route(driver["id"], center["id"], service_date="2026-06-11")
    stop = fx.add_stop(route["id"], parcel["id"])
    fx.dispatch_route(route["id"])
    fx.log_attempt(stop["id"], driver["id"], "NO_ONE_HOME")
    data = validate_success(api.reschedule_stop(stop["id"], DM))
    # first reschedule index 0: (300 + 120) * 1.5 = 630
    assert data["redelivery_fee_cents"] == 630, (
        f"first surcharge (300 + 120) * 1.5 = 630, got {data['redelivery_fee_cents']}")


# ===========================================================================
# combinatorial_formula / redelivery_surcharge_multiinput_nonlinear_mode_a
# ===========================================================================

def test_redelivery_surcharge_combines_base_signature_and_hazmat_multiplier(api):
    """PRD §3.5: "Start from a service-level base: 300 cents for a `GROUND`
    parcel, 500 cents for `EXPRESS`, and 800 cents for `PRIORITY`. Add an
    attempt-escalation increment of 150 cents multiplied by the reschedule index"
    PRD §3.5: "add a flat 120-cent signature surcharge if the parcel's
    `signature_required` is true, and nothing otherwise. Then multiply the
    resulting sum by a hazmat multiplier of 1.5 if the parcel's `hazmat_class`
    is anything other than `NONE`, or by 1 otherwise."

    Design: Difficulty/combinatorial_formula/redelivery_surcharge_multiinput_nonlinear_mode_a
    """
    center = fx.create_center(name="Hub3", hazmat_certified=True, sort_capacity=10)
    driver = fx.create_driver(name="Hx", hazmat_certified=True, vehicle_capacity_kg=50)
    parcel = fx.create_sorted_parcel(
        center["id"], weight_kg=1.0,
        service_level="EXPRESS", signature_required=True, hazmat_class="CLASS_3",
    )
    route = fx.create_route(driver["id"], center["id"], service_date="2026-06-12")
    stop = fx.add_stop(route["id"], parcel["id"])
    fx.dispatch_route(route["id"])
    fx.log_attempt(stop["id"], driver["id"], "REFUSED")
    data = validate_success(api.reschedule_stop(stop["id"], DM))

    # (500 + 120) * 1.5 = 930
    assert data["redelivery_fee_cents"] == 930, (
        f"(EXPRESS 500 + sig 120) * hazmat 1.5 = 930, got {data['redelivery_fee_cents']}")


def test_redelivery_surcharge_escalation_index_on_second_reschedule(api):
    """PRD §3.5: "Add an attempt-escalation increment of 150 cents multiplied by
    the reschedule index, where the reschedule index is the stop's
    `attempt_count` minus 1 taken at the moment of reschedule (so the first
    reschedule, which follows the first attempt, uses index 0; the second uses
    index 1; and so on)."

    Design: Difficulty/combinatorial_formula/redelivery_surcharge_multiinput_nonlinear_mode_a
    """
    center = fx.create_center(name="Hub3b", hazmat_certified=True, sort_capacity=10)
    driver = fx.create_driver(name="Hx2", hazmat_certified=True, vehicle_capacity_kg=50)
    parcel = fx.create_sorted_parcel(
        center["id"], weight_kg=1.0,
        service_level="EXPRESS", signature_required=True, hazmat_class="CLASS_3",
    )
    route = fx.create_route(driver["id"], center["id"], service_date="2026-06-12")
    stop = fx.add_stop(route["id"], parcel["id"])
    fx.dispatch_route(route["id"])
    fx.log_attempt(stop["id"], driver["id"], "REFUSED")
    fx.reschedule(stop["id"])  # index 0: 930
    fx.log_attempt(stop["id"], driver["id"], "REFUSED")
    data = validate_success(api.reschedule_stop(stop["id"], DM))  # index 1
    # second surcharge: (500 + 150*1 + 120) * 1.5 = 1155; cumulative 930 + 1155 = 2085
    assert data["redelivery_fee_cents"] == 2085, (
        f"cumulative 930 + 1155 = 2085, got {data['redelivery_fee_cents']}")


# ===========================================================================
# combinatorial_formula / sort_handling_fee_round_per_line_then_sum_mode_b
# ===========================================================================

def test_manifest_rounds_per_line_then_sums(api):
    """PRD §3.8: "For each non-`CANCELLED` stop on the route, taken in ascending
    `sequence` (ties broken by `created_at` ascending), compute that line's raw
    fee as a base of 50 cents plus the parcel's `weight_kg` multiplied by 12.5
    cents per kilogram, then round that raw fee half up to a whole number of
    cents to obtain the line fee. The `total_handling_fee_cents` is the sum of
    those already-rounded per-line fees."

    Design: Difficulty/combinatorial_formula/sort_handling_fee_round_per_line_then_sum_mode_b
    """
    center = fx.create_center(name="Hub4", sort_capacity=10)
    driver = fx.create_driver(name="Dn", vehicle_capacity_kg=50)
    pa = fx.create_sorted_parcel(center["id"], weight_kg=0.02)
    pb = fx.create_sorted_parcel(center["id"], weight_kg=0.02)
    route = fx.create_route(driver["id"], center["id"], service_date="2026-06-13")
    fx.add_stop(route["id"], pa["id"], sequence=1, window_start_min=540, window_end_min=600)
    fx.add_stop(route["id"], pb["id"], sequence=2, window_start_min=660, window_end_min=720)

    data = validate_success(api.get_route_manifest(route["id"], DM))
    # each raw 50 + 0.02*12.5 = 50.25 -> round to 50; total 100 (sum-then-round would give 101)
    assert data["total_handling_fee_cents"] == 100, (
        f"round-per-line (50+50) = 100, got {data['total_handling_fee_cents']}")
    assert data["stop_count"] == 2


def test_manifest_single_line_fee_rounds_half_up(api):
    """PRD §3.8: "compute that line's raw fee as a base of 50 cents plus the
    parcel's `weight_kg` multiplied by 12.5 cents per kilogram, then round that
    raw fee half up to a whole number of cents to obtain the line fee."

    Design: Difficulty/combinatorial_formula/sort_handling_fee_round_per_line_then_sum_mode_b
    """
    center = fx.create_center(name="Hub4b", sort_capacity=10)
    driver = fx.create_driver(name="Dn2", vehicle_capacity_kg=50)
    # one 0.02kg parcel: raw 50.25 -> round half up -> 50
    parcel = fx.create_sorted_parcel(center["id"], weight_kg=0.02)
    route = fx.create_route(driver["id"], center["id"], service_date="2026-06-13")
    fx.add_stop(route["id"], parcel["id"])
    data = validate_success(api.get_route_manifest(route["id"], DM))
    assert data["total_handling_fee_cents"] == 50, (
        f"round_half_up(50.25) = 50, got {data['total_handling_fee_cents']}")
    assert data["stop_count"] == 1
