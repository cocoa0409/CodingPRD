"""No-show scoring windows and compensating-invariant conservation of run capacity
and penalty points.

Queue A (Difficulty): dual_variant_calc (rolling vs lifetime), compensating_invariant
(seat capacity conserved, penalty points conserved).
"""
from test_helpers import validate_success, TEST_USERS
import test_helpers as th

DISPATCHER = TEST_USERS["dispatcher_headers"]
DRIVER = TEST_USERS["driver_headers"]
SPECIALIST = TEST_USERS["specialist_headers"]


# ==========================================================================
# Difficulty A — rolling vs lifetime divergence after window aging
# ==========================================================================
def _no_show_then_age_past_window(api):
    base = th.no_showed_trip(api, clock="2026-06-01T00:00:00Z")
    # Advance the logical clock 34 days: the single penalty (occurred 2026-06-01) ages
    # out of the trailing 30-day rolling window but remains in the lifetime total.
    th.set_clock(api, "2026-07-05T00:00:00Z")
    return validate_success(api.get_rider(base["rider"]["id"], SPECIALIST))


def test_rolling_total_drops_aged_penalty_to_zero(api):
    """PRD §2.10: "The rolling total, `no_show_points_rolling`, is the sum of `points` over
    the rider's `ACTIVE` penalty events whose `occurred_at` falls on or after the logical
    clock minus 30 days (the lower bound is inclusive)."

    Design: Difficulty/dual_variant_calc/no_show_rolling_vs_lifetime_diverge_after_window_aging
    """
    rider = _no_show_then_age_past_window(api)
    assert rider["no_show_points_rolling"] == 0


def test_lifetime_total_retains_aged_penalty(api):
    """PRD §2.10: "The lifetime total, `no_show_points_lifetime`, is the sum of `points`
    over all of the rider's `ACTIVE` penalty events regardless of age; once events age past
    30 days the lifetime total exceeds the rolling total."

    Design: Difficulty/dual_variant_calc/no_show_rolling_vs_lifetime_diverge_after_window_aging
    """
    rider = _no_show_then_age_past_window(api)
    assert rider["no_show_points_lifetime"] > 0
    assert rider["no_show_points_lifetime"] != rider["no_show_points_rolling"]


# ==========================================================================
# Difficulty A — run seat capacity conserved across accept + early cancel
# ==========================================================================
def _accept_then_early_cancel(api):
    base = th.scenario_scheduled_trip(api, requested_pickup_at="2026-06-05T09:00:00Z")
    trip_id = base["trip"]["id"]
    validate_success(api.cancel_trip(trip_id, th.make_rider_headers(base["rider"]["id"])))
    base["trip"] = validate_success(api.get_trip(trip_id, DISPATCHER))
    base["run"] = validate_success(api.get_run(base["run"]["id"], DISPATCHER))
    return base


def test_early_cancel_restores_run_capacity(api):
    """PRD §3.9: "A cancellation of a `SCHEDULED` trip depends on lead time: if the
    interval from the logical clock to `scheduled_pickup_at` is at least the late-cancel
    lead time (`LATE_CANCEL_LEAD_HOURS`), the trip moves to `CANCELLED`, its held positions
    and seats are released back to the run, and the run's `version` is incremented by one."

    Design: Difficulty/compensating_invariant/run_seat_capacity_conserved_accept_then_cancel
    """
    base = _accept_then_early_cancel(api)
    assert base["trip"]["status"] == "CANCELLED"
    assert base["run"]["available_ambulatory_seats"] == 4
    assert base["run"]["available_wheelchair_positions"] == 2


def test_accept_then_cancel_bumps_run_version_twice(api):
    """PRD §2.9: "Every capacity-mutating event on a run — an accept, a release on cancel
    or dropoff, and the dispatch cascade — increments the run's `version` by one and
    refreshes its `updated_at`."

    Design: Difficulty/compensating_invariant/run_seat_capacity_conserved_accept_then_cancel
    """
    base = th.scenario_scheduled_trip(api, requested_pickup_at="2026-06-05T09:00:00Z")
    baseline = base["run_version_at_create"]
    validate_success(api.cancel_trip(base["trip"]["id"], th.make_rider_headers(base["rider"]["id"])))
    run = validate_success(api.get_run(base["run"]["id"], DISPATCHER))
    # accept (+1) then early cancel release (+1) from the at-creation version.
    assert run["version"] == baseline + 2


# ==========================================================================
# Difficulty A — penalty points conserved across no-show + waive
# ==========================================================================
def _no_show_then_waive(api):
    base = th.no_showed_trip(api, clock="2026-06-01T00:00:00Z")
    penalty_id = base["penalty"]["id"]
    validate_success(api.waive_penalty(penalty_id, SPECIALIST))
    base["penalty"] = validate_success(api.get_penalty(penalty_id, SPECIALIST))
    base["rider"] = validate_success(api.get_rider(base["rider"]["id"], SPECIALIST))
    return base


def test_waive_voids_penalty_event(api):
    """PRD §3.10: "A specialist may waive a penalty event, moving its `status` from
    `ACTIVE` to `VOIDED`."

    Design: Difficulty/compensating_invariant/penalty_points_conserved_no_show_then_waive
    """
    base = _no_show_then_waive(api)
    assert base["penalty"]["status"] == "VOIDED"


def test_waive_returns_rider_points_to_zero(api):
    """PRD §3.10: "Because both running totals count only `ACTIVE` events, a waiver
    recomputes the affected rider's `no_show_points_rolling`, `no_show_points_lifetime`,
    and `penalty_tier`."

    Design: Difficulty/compensating_invariant/penalty_points_conserved_no_show_then_waive
    """
    base = _no_show_then_waive(api)
    assert base["rider"]["no_show_points_rolling"] == 0
    assert base["rider"]["no_show_points_lifetime"] == 0
