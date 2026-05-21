"""Driver quests: SCHEDULED → ACTIVE → CLOSED lifecycle, deferred bonus
payout, closed-closed window-overlap semantics on enrollment."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    add_hours_iso,
    add_seconds_iso,
    advance_clock_to,
    assert_quest_bonus,
    create_and_online_driver,
    create_driver,
    create_grid,
    create_quest_bonus,
    create_quest_bonus_payload,
    create_requested_ride,
    create_rider,
    enroll_driver_in_quest,
    get_driver,
    get_quest_bonus,
    iso_now_utc,
    make_driver_headers,
    patch_driver_quest_payload,
    setup_grid_with_supply,
    setup_quest_payout_scenario,
    validate_error,
    validate_success,
)


# ===========================================================================
# Quest creation + lifecycle.
# ===========================================================================
class TestQuestCreation:

    def test_create_quest_starts_in_scheduled(self, api, admin_headers):
        """PRD §3.6: "The quest is created in SCHEDULED status, the
        initial state of its lifecycle."
        PRD §4: POST returns 201.
        """
        payload = create_quest_bonus_payload()
        resp = api.create_quest_bonus(payload, admin_headers)
        data = validate_success(resp, expected_status=201)
        assert_quest_bonus(data)
        assert data["status"] == "SCHEDULED"

    def test_create_quest_with_window_end_before_start_rejected(
            self, api, admin_headers):
        """PRD §3.6: "window_end must also be strictly after
        window_start." PRD §2.9 (twelfth): bundled under
        ERR_QUEST_WINDOW_OVERLAP.

        Either ERR_QUEST_WINDOW_OVERLAP or ERR_INVALID_INPUT is
        faithful — accept both.
        """
        from test_helpers import validate_error_is_one_of
        t0 = iso_now_utc()
        t_back = add_seconds_iso(t0, -100)
        resp = api.create_quest_bonus(
            {"name": "x", "target_ride_count": 2,
             "bonus_amount_cents": 100,
             "window_start": t0,
             "window_end": t_back},
            admin_headers,
        )
        validate_error_is_one_of(
            resp,
            [
                ApiErrorId.ERR_QUEST_WINDOW_OVERLAP.value,
                ApiErrorId.ERR_INVALID_INPUT.value,
            ],
        )

    def test_create_quest_with_zero_target_ride_count_rejected(
            self, api, admin_headers):
        """PRD §3.6: "a target_ride_count (at least 1)."
        PRD §2.9 (sixteenth): generic range validation yields
        ERR_INVALID_INPUT."""
        t0 = iso_now_utc()
        resp = api.create_quest_bonus(
            {"name": "x", "target_ride_count": 0,
             "bonus_amount_cents": 100,
             "window_start": t0,
             "window_end": add_hours_iso(t0, 1)},
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_INPUT.value)


# ===========================================================================
# Time-gated transitions.
# ===========================================================================
class TestQuestTimeGated:

    def test_clock_advance_to_window_start_transitions_to_active(self):
        """PRD §3.6: "A quest transitions from SCHEDULED to ACTIVE
        automatically when the server clock crosses (reaches or
        passes) the quest's window_start."
        """
        t0 = add_hours_iso(iso_now_utc(), 1)
        t_end = add_seconds_iso(t0, 3600)
        quest = create_quest_bonus(window_start=t0, window_end=t_end)
        assert quest["status"] == "SCHEDULED"
        advance_clock_to(t0)
        quest_after = get_quest_bonus(quest["id"])
        assert quest_after["status"] == "ACTIVE", (
            "PRD §3.6: clock crossing window_start transitions to ACTIVE."
        )


# ===========================================================================
# Driver enrollment.
# ===========================================================================
class TestDriverEnrollment:

    def test_enroll_driver_sets_quest_id(self):
        """PRD §3.6: "A driver enrolls (or unenrolls) in a quest via
        the patch-driver-quest capability. The body provides a
        quest_id, or null to unenroll."
        """
        driver = create_driver()
        t0 = add_hours_iso(iso_now_utc(), 1)
        t_end = add_seconds_iso(t0, 3600)
        quest = create_quest_bonus(window_start=t0, window_end=t_end)
        d_after = enroll_driver_in_quest(
            driver["id"], quest["id"],
            current_version=driver["version"],
        )
        assert d_after["quest_id"] == quest["id"]

    def test_enroll_overlapping_closed_closed_quest_rejected(self, api):
        """PRD §3.6: "Note that the overlap semantics for quest
        enrollment differ from rush-hour windows: rush-hour overlap is
        checked with half-open intervals (adjacency at the boundary
        minute is fine), but quest enrollment uses fully closed
        intervals — a quest that starts at exactly the moment another
        quest ends counts as overlapping. A violation yields
        ERR_QUEST_WINDOW_OVERLAP."
        # difficulty: resource_temporal_overlap/quest_bonus_closed_overlap_with_buffer
        """
        # Q1 ends at T0+3600s; Q2 starts at T0+3600s exactly →
        # closed-closed overlap at the boundary instant.
        t0 = add_hours_iso(iso_now_utc(), 1)
        t_mid = add_seconds_iso(t0, 3600)
        t_end = add_seconds_iso(t0, 7200)
        q1 = create_quest_bonus(window_start=t0, window_end=t_mid)
        q2 = create_quest_bonus(window_start=t_mid, window_end=t_end)
        driver = create_driver()
        # Enroll in Q1 first.
        d_after_q1 = enroll_driver_in_quest(
            driver["id"], q1["id"],
            current_version=driver["version"],
        )
        # Try to re-enroll in Q2 (touching at boundary) — must fail.
        resp = api.patch_driver_quest(
            driver["id"],
            patch_driver_quest_payload(
                q2["id"], version=d_after_q1["version"],
            ),
            make_driver_headers(driver["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_QUEST_WINDOW_OVERLAP.value)


# ===========================================================================
# Deferred payout — PRD §3.4 + §3.6.
# ===========================================================================
class TestDeferredPayout:

    def test_quest_progress_only_increments_during_active(self):
        """PRD §3.4: "If the driver was enrolled in a quest whose
        status was ACTIVE at the completion instant, the driver's
        quest_completed_rides is incremented by 1."
        """
        sc = setup_quest_payout_scenario(target_ride_count=2,
                                         bonus_amount_cents=5_000)
        driver = sc["driver"]
        # Two rides completed while ACTIVE.
        assert driver["quest_completed_rides"] == 2

    def test_quest_payout_settles_only_at_close(self):
        """PRD §3.6: "The bonus is paid out only on the next
        system-driven transition of the quest from ACTIVE to CLOSED."
        And PRD §3.4: "If that increment causes quest_completed_rides
        to reach the quest's target_ride_count, the quest's
        bonus_amount_cents is held for payout — but it is not credited
        yet."
        # difficulty: dual_variant_calc/driver_total_earnings_vs_quest_bonus_aggregation
        """
        sc = setup_quest_payout_scenario(target_ride_count=2,
                                         bonus_amount_cents=5_000)
        driver = sc["driver"]
        # PRE-close: total_earnings_cents covers only ride earnings,
        # NOT the bonus yet.
        per_ride_earnings = driver["total_earnings_cents"]
        # Advance to window_end → quest CLOSED → payout settles.
        advance_clock_to(sc["t_end"])
        d_after = get_driver(driver["id"])
        # Bonus credited.
        assert d_after["total_earnings_cents"] == per_ride_earnings + 5_000, (
            f"PRD §3.6: total_earnings_cents incremented by "
            f"bonus_amount_cents on CLOSED. Got "
            f"{d_after['total_earnings_cents']} (expected "
            f"{per_ride_earnings + 5_000})."
        )
        quest_after = get_quest_bonus(sc["quest"]["id"])
        assert quest_after["status"] == "CLOSED"

    def test_payout_idempotent_across_repeat_close_attempts(self):
        """PRD §3.6: "The payout is one-time and idempotent — if the
        close transition is somehow attempted twice, the payout flag
        prevents a second credit."
        # difficulty: dual_variant_calc/driver_total_earnings_vs_quest_bonus_aggregation
        """
        sc = setup_quest_payout_scenario(target_ride_count=2,
                                         bonus_amount_cents=5_000)
        advance_clock_to(sc["t_end"])
        d_first = get_driver(sc["driver"]["id"])
        first_total = d_first["total_earnings_cents"]
        # Advance further past window_end — close should not re-pay.
        advance_clock_to(add_seconds_iso(sc["t_end"], 60))
        d_second = get_driver(sc["driver"]["id"])
        assert d_second["total_earnings_cents"] == first_total, (
            f"PRD §3.6: payout is one-time and idempotent. Total moved "
            f"from {first_total} to {d_second['total_earnings_cents']}."
        )

    def test_payout_excludes_completed_at_equal_to_window_end(self):
        """PRD §3.6: "the aggregate that feeds quest_completed_rides
        counts only rides whose status is COMPLETED, whose driver_id
        equals the enrolled driver's id, and whose completed_at lies
        within the right-half-open interval bounded by window_start
        inclusive and window_end exclusive. A ride whose completed_at
        coincides exactly with window_end is excluded."

        We can't directly observe completed_at == window_end with
        deterministic clock control in this PRD; the property under
        test is the half-openness. Verify: rides COMPLETED before
        window_end are counted (already done in setup); a ride
        COMPLETED AFTER window_end (when quest is CLOSED) is NOT
        counted toward the (now-closed) quest.
        """
        sc = setup_quest_payout_scenario(target_ride_count=2,
                                         bonus_amount_cents=5_000)
        # Quest is currently ACTIVE. Close it explicitly.
        advance_clock_to(sc["t_end"])
        # Try to add another COMPLETED ride for the driver AFTER
        # close: it must NOT increment quest_completed_rides because
        # the quest is no longer ACTIVE.
        rider = sc["rider"]
        grid = sc["grid"]
        # Ensure driver is AVAILABLE in the grid (returned to grid
        # by completion).
        from test_helpers import assign_ride, start_ride, complete_ride
        # Note: driver was returned to AVAILABLE in dropoff (=pickup)
        # grid after each completion in setup. So another ride request
        # is dispatchable.
        ride = create_requested_ride(rider["id"], grid["code"],
                                     distance_km=2.0)
        assign_ride(ride["id"])
        start_ride(ride["id"], sc["driver"]["id"])
        complete_ride(ride["id"], sc["driver"]["id"])
        d_after = get_driver(sc["driver"]["id"])
        # Quest already closed; the prior completed_rides count
        # remains the same as before (the bonus is closed-out).
        assert d_after["quest_completed_rides"] == 2, (
            "PRD §3.6: a ride completed AFTER the quest closes is "
            "outside the right-half-open window and is not counted "
            "toward the quest aggregate."
        )
