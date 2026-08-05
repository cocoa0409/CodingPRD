"""Occupancy posture, effective/nominal capacity, pickup cascades, and occupancy conservation.

Queue A (Difficulty): locker_effective_vs_nominal_capacity, posture_restricted_at_exact_threshold,
pickup_release_recompute_posture_depth3, locker_occupancy_conserved.
Queue B (Corner): effective_capacity_excludes_out_of_service,
out_of_service_on_occupied_locker_returns_locker_unavailable.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    pickup_payload,
    TEST_USERS,
    setup_bank_with_lockers, setup_notified_locker_package,
    make_property, make_bank, make_locker, log_package, notify_into_locker,
    get_bank, get_property, get_locker,
)

PM = TEST_USERS["pm_headers"]
CONCIERGE = TEST_USERS["concierge_headers"]


# ─── locker_effective_vs_nominal_capacity ─────────────────────────────────────
def test_available_count_diverges_from_nominal_after_occupancy(api):
    """PRD §2.6: "At the bank level these roll up as `nominal_locker_count` (all lockers under
    the bank regardless of status) and `available_locker_count` (lockers under the bank whose
    `status` is `AVAILABLE`)."

    Design: Difficulty/dual_variant_calc/locker_effective_vs_nominal_capacity
    """
    ctx = setup_bank_with_lockers(bank_storage="AMBIENT",
                                  locker_specs=(("MEDIUM", None), ("MEDIUM", None)))
    pkg = log_package(ctx["property"]["id"], ctx["resident"]["id"], ctx["carrier"]["id"],
                      size_class="MEDIUM")
    notify_into_locker(pkg["id"], ctx["lockers"][0]["id"])
    bank = get_bank(ctx["bank"]["id"])
    assert bank["nominal_locker_count"] == 2
    assert bank["available_locker_count"] == 1


def test_available_equals_nominal_when_all_free(api):
    """PRD §2.6: "the **nominal** compartment count for a requested size and class counts every
    matching locker regardless of `status`, while the **effective** count includes only those
    matching lockers whose `status` is `AVAILABLE`."

    Design: Difficulty/dual_variant_calc/locker_effective_vs_nominal_capacity
    """
    ctx = setup_bank_with_lockers(bank_storage="AMBIENT",
                                  locker_specs=(("MEDIUM", None), ("MEDIUM", None)))
    bank = get_bank(ctx["bank"]["id"])
    assert bank["nominal_locker_count"] == 2
    assert bank["available_locker_count"] == 2


# ─── posture_restricted_at_exact_threshold ────────────────────────────────────
def test_posture_restricted_at_exact_threshold(api):
    """PRD §2.5: "The threshold comparison is inclusive at its boundary — a utilization exactly
    equal to the configured threshold (default 0.85, i.e. 85 percent) already yields
    `RESTRICTED`."

    Design: Difficulty/boundary_precision_check/posture_restricted_at_exact_threshold
    """
    ctx = setup_bank_with_lockers(prop_overrides={"overflow_threshold_pct": 0.5},
                                  locker_specs=(("LARGE", None), ("LARGE", None)))
    pkg = log_package(ctx["property"]["id"], ctx["resident"]["id"], ctx["carrier"]["id"])
    notify_into_locker(pkg["id"], ctx["lockers"][0]["id"])  # util = 1/2 = 0.5 == threshold
    prop = get_property(ctx["property"]["id"])
    assert prop["occupancy_posture"] == "RESTRICTED"
    assert prop["occupied_locker_count"] == 1
    assert prop["in_service_locker_count"] == 2


def test_posture_open_below_threshold(api):
    """PRD §2.5: "The posture is `FROZEN` when utilization is greater than or equal to 1.0; it
    is `RESTRICTED` when utilization is greater than or equal to the property's
    `overflow_threshold_pct` and strictly less than 1.0; otherwise it is `OPEN`."

    Design: Difficulty/boundary_precision_check/posture_restricted_at_exact_threshold
    """
    ctx = setup_bank_with_lockers(prop_overrides={"overflow_threshold_pct": 0.5},
                                  locker_specs=(("LARGE", None), ("LARGE", None), ("LARGE", None)))
    pkg = log_package(ctx["property"]["id"], ctx["resident"]["id"], ctx["carrier"]["id"])
    notify_into_locker(pkg["id"], ctx["lockers"][0]["id"])  # util = 1/3 = 0.333 < 0.5
    prop = get_property(ctx["property"]["id"])
    assert prop["occupancy_posture"] == "OPEN"
    assert prop["occupied_locker_count"] == 1


# ─── pickup_release_recompute_posture_depth3 ──────────────────────────────────
def test_pickup_release_flips_posture_restricted_to_open(api):
    """PRD §3.4: "The system then releases storage — an occupied locker transitions
    `OCCUPIED → AVAILABLE` with `current_package_id` cleared to null, or the assigned shelf's
    occupied count is decremented — sets `storage_mode` back to `NONE`, recomputes the bank and
    property locker counts, recomputes and persists `occupancy_posture`, and bumps the
    property's `version`."
    PRD §2.5: "`RESTRICTED → OPEN` when it drops below the threshold."

    Design: Difficulty/transitive_cascade/pickup_release_recompute_posture_depth3
    """
    ctx = setup_bank_with_lockers(prop_overrides={"overflow_threshold_pct": 0.5},
                                  locker_specs=(("LARGE", None), ("LARGE", None)))
    pkg = log_package(ctx["property"]["id"], ctx["resident"]["id"], ctx["carrier"]["id"])
    notified = notify_into_locker(pkg["id"], ctx["lockers"][0]["id"])
    assert get_property(ctx["property"]["id"])["occupancy_posture"] == "RESTRICTED"
    validate_success(
        api.pickup_package(pkg["id"], pickup_payload(notified["pickup_code"]), CONCIERGE), 200)
    prop = get_property(ctx["property"]["id"])
    assert prop["occupancy_posture"] == "OPEN"
    assert prop["occupied_locker_count"] == 0


def test_pickup_releases_locker_to_available(api):
    """PRD §3.4: "an occupied locker transitions `OCCUPIED → AVAILABLE` with `current_package_id`
    cleared to null, or the assigned shelf's occupied count is decremented".

    Design: Difficulty/transitive_cascade/pickup_release_recompute_posture_depth3
    """
    ctx = setup_bank_with_lockers(prop_overrides={"overflow_threshold_pct": 0.5},
                                  locker_specs=(("LARGE", None), ("LARGE", None)))
    pkg = log_package(ctx["property"]["id"], ctx["resident"]["id"], ctx["carrier"]["id"])
    notified = notify_into_locker(pkg["id"], ctx["lockers"][0]["id"])
    picked = validate_success(
        api.pickup_package(pkg["id"], pickup_payload(notified["pickup_code"]), CONCIERGE), 200)
    assert picked["status"] == "PICKED_UP"
    locker = get_locker(ctx["lockers"][0]["id"])
    assert locker["status"] == "AVAILABLE"
    assert locker["current_package_id"] in (None, "")


# ─── locker_occupancy_conserved ───────────────────────────────────────────────
def test_occupancy_count_conserved_after_partial_pickup(api):
    """PRD §2.5: "`occupied_locker_count` as the number whose `status` is `OCCUPIED`."
    PRD §3.4: "an occupied locker transitions `OCCUPIED → AVAILABLE` with `current_package_id`
    cleared to null".

    Design: Difficulty/compensating_invariant/locker_occupancy_conserved
    """
    ctx = setup_bank_with_lockers(locker_specs=(("LARGE", None), ("LARGE", None)))
    pkg1 = log_package(ctx["property"]["id"], ctx["resident"]["id"], ctx["carrier"]["id"])
    n1 = notify_into_locker(pkg1["id"], ctx["lockers"][0]["id"])
    pkg2 = log_package(ctx["property"]["id"], ctx["resident"]["id"], ctx["carrier"]["id"])
    notify_into_locker(pkg2["id"], ctx["lockers"][1]["id"])
    assert get_property(ctx["property"]["id"])["occupied_locker_count"] == 2
    validate_success(api.pickup_package(pkg1["id"], pickup_payload(n1["pickup_code"]), CONCIERGE), 200)
    assert get_property(ctx["property"]["id"])["occupied_locker_count"] == 1
    assert get_locker(ctx["lockers"][0]["id"])["status"] == "AVAILABLE"
    assert get_locker(ctx["lockers"][1]["id"])["status"] == "OCCUPIED"


def test_occupancy_count_equals_remaining_holding_packages(api):
    """PRD §2.5: "the system counts `in_service_locker_count` as the number of that property's
    lockers whose `status` is not `OUT_OF_SERVICE`, and `occupied_locker_count` as the number
    whose `status` is `OCCUPIED`."

    Design: Difficulty/compensating_invariant/locker_occupancy_conserved
    """
    ctx = setup_bank_with_lockers(locker_specs=(("LARGE", None), ("LARGE", None)))
    pkg1 = log_package(ctx["property"]["id"], ctx["resident"]["id"], ctx["carrier"]["id"])
    n1 = notify_into_locker(pkg1["id"], ctx["lockers"][0]["id"])
    pkg2 = log_package(ctx["property"]["id"], ctx["resident"]["id"], ctx["carrier"]["id"])
    notify_into_locker(pkg2["id"], ctx["lockers"][1]["id"])
    validate_success(api.pickup_package(pkg1["id"], pickup_payload(n1["pickup_code"]), CONCIERGE), 200)
    from test_helpers.fixtures import get_package as _get_package
    assert _get_package(pkg1["id"])["status"] == "PICKED_UP"
    assert _get_package(pkg2["id"])["status"] == "AWAITING_PICKUP"
    # one AWAITING package still holds a locker -> occupied count is exactly 1 (no drift)
    assert get_property(ctx["property"]["id"])["occupied_locker_count"] == 1


# ─── effective_capacity_excludes_out_of_service (Corner) ──────────────────────
def test_out_of_service_reduces_available_not_nominal(api):
    """PRD §2.6: "the two diverge whenever any matching compartment is `OCCUPIED` or
    `OUT_OF_SERVICE`. At the bank level these roll up as `nominal_locker_count` (all lockers
    under the bank regardless of status) and `available_locker_count` (lockers under the bank
    whose `status` is `AVAILABLE`)."

    Design: Corner/cross_cutting_complexity_layers/effective_capacity_excludes_out_of_service
    """
    prop = make_property(name="Eff Court")
    bank = make_bank(prop["id"], storage_class="AMBIENT")
    locker1 = make_locker(bank["id"], size_class="MEDIUM")
    make_locker(bank["id"], size_class="MEDIUM")
    validate_success(api.locker_out_of_service(locker1["id"], PM), 200)
    bank_after = get_bank(bank["id"])
    assert bank_after["nominal_locker_count"] == 2
    assert bank_after["available_locker_count"] == 1


# ─── out_of_service_on_occupied_locker_returns_locker_unavailable (Corner) ────
def test_out_of_service_on_occupied_locker_rejected(api):
    """PRD §3.1: "A manager may take an `AVAILABLE` locker `OUT_OF_SERVICE`; this is permitted
    only while the locker is `AVAILABLE` — attempting it on an `OCCUPIED` locker is rejected
    with `ERR_LOCKER_UNAVAILABLE`".

    Design: Corner/state_machines/out_of_service_on_occupied_locker_returns_locker_unavailable
    """
    ctx = setup_bank_with_lockers(prop_overrides={"overflow_threshold_pct": 0.85},
                                  locker_specs=(("LARGE", None), ("LARGE", None)))
    pkg = log_package(ctx["property"]["id"], ctx["resident"]["id"], ctx["carrier"]["id"])
    notify_into_locker(pkg["id"], ctx["lockers"][0]["id"])
    res = api.locker_out_of_service(ctx["lockers"][0]["id"], PM)
    validate_error(res, "ERR_LOCKER_UNAVAILABLE", expected_status=409)
    assert get_locker(ctx["lockers"][0]["id"])["status"] == "OCCUPIED"
