"""Giving dates back: the bulk hold-expiry sweep, its pinned processing order
and the dependent cascade each swept release fires."""
from test_helpers import (
    create_equipment_pool,
    create_labor_call,
    draft_booking,
    issue_equipment,
    open_changeover_order,
    place_hold,
    read_asset,
    read_booking,
    read_issue,
    read_labor_call,
    read_order,
    read_tenant,
    read_venue,
    register_tenant,
    set_clock,
    setup_arena,
    sweep_holds,
)


def _two_expiring_holds_over_one_turnaround():
    """A TIER_3 anchor hold expiring on 2026-08-04 and a promoter hold expiring
    on 2026-08-02, joined by a single turnaround with panels and crew on it."""
    arena = setup_arena(profiles=("ICE", "CONCERT"))
    venue_id = arena["venue_id"]
    arena["tenant"] = register_tenant(venue_id, "Harbor Curling", "TIER_3", 5)
    arena["floor_pool"] = create_equipment_pool(venue_id, "FLOOR_PANEL_SET", 10, 12)
    anchor = draft_booking(
        venue_id, arena["profiles"]["ICE"]["id"], "Curling Sep 9",
        "2026-09-09T00:00:00Z", "2026-09-09T03:00:00Z",
        expected_attendance=9_000, rigging_load_kg=1_500,
        tenant_id=arena["tenant"]["id"],
    )
    arena["anchor_booking"] = place_hold(anchor["id"])
    promoter = draft_booking(
        venue_id, arena["profiles"]["CONCERT"]["id"], "Concert Sep 9",
        "2026-09-09T16:00:00Z", "2026-09-09T19:00:00Z",
        expected_attendance=8_000, rigging_load_kg=5_000,
        promoter_name="Northline Live",
    )
    arena["promoter_booking"] = place_hold(promoter["id"])
    arena["order"] = open_changeover_order(
        venue_id,
        arena["anchor_booking"]["id"],
        arena["promoter_booking"]["id"],
        crew_headcount=40,
    )
    arena["issue"] = issue_equipment(
        arena["floor_pool"]["id"], arena["order"]["id"], 3
    )
    arena["labor_call"] = create_labor_call(
        "CONVERSION_CREW", 12, "2026-08-04T06:00:00Z", "2026-08-04T14:00:00Z",
        guaranteed_hours=4, changeover_order_id=arena["order"]["id"],
    )
    return arena


class TestHoldExpirySweep:
    def test_both_expired_holds_are_released_in_ascending_expiry_order(self, api):
        """PRD §3.5: "The sweep gathers every booking on that arena whose `status` is `HELD`
        or `CHALLENGED` and whose `hold_expires_at` is at or before the logical clock instant
        — a booking whose expiry equals the clock instant exactly *is* swept."
        PRD §3.5: "The gathered set is then processed in a pinned order: ascending
        `hold_expires_at` first, and ascending `created_at` as the tie-break."
        PRD §3.5: "The response reports `swept_count`, the number of bookings released;
        `released_booking_ids`, their identifiers listed in the same pinned processing order;
        and `venue_version`, the arena's `version` after the sweep."
        PRD §3.5: "Each swept booking takes the same release transition it would take
        individually — `HELD → RELEASED` or `CHALLENGED → RELEASED`, including the
        challenge-denial step for a contested booking — except that its `release_reason` is
        written as the literal string `HOLD_EXPIRY_SWEEP` rather than a caller-supplied
        reason."

        Design: Difficulty/transitive_cascade/hold_expiry_sweep_releases_two_bookings_in_expiry_order_and_cascades_into_one_shared_order
        """
        arena = _two_expiring_holds_over_one_turnaround()
        assert arena["anchor_booking"]["hold_expires_at"] == "2026-08-04T00:00:00.000Z"
        assert arena["promoter_booking"]["hold_expires_at"] == "2026-08-02T00:00:00.000Z"
        assert arena["promoter_booking"]["hold_tier"] == "OPEN"

        set_clock("2026-08-04T00:00:00Z")
        result = sweep_holds(arena["venue_id"])

        assert result["swept_count"] == 2
        assert result["released_booking_ids"] == [
            arena["promoter_booking"]["id"],
            arena["anchor_booking"]["id"],
        ], "the twenty-four hour promoter hold expired first and is processed first"

        for booking_id in result["released_booking_ids"]:
            released = read_booking(booking_id)
            assert released["status"] == "RELEASED"
            assert released["release_reason"] == "HOLD_EXPIRY_SWEEP"

        venue = read_venue(arena["venue_id"])
        assert venue["open_hold_count"] == 0
        assert venue["version"] == result["venue_version"]
        assert read_tenant(
            arena["venue_id"], arena["tenant"]["id"]
        )["holds_consumed"] == 0

    def test_the_sweep_cascade_abandons_the_shared_turnaround_and_its_children(
        self, api
    ):
        """PRD §2.11: "Every changeover order that names the booking as either its outgoing or
        its incoming event, and whose `status` is neither `SIGNED_OFF` nor `ABANDONED`, moves
        to `ABANDONED`."
        PRD §3.8: "The order records `abandon_reason` as `FROM_BOOKING_GONE` when the outgoing
        event went away and as `TO_BOOKING_GONE` when the incoming event did."
        PRD §2.11: "Every equipment issue on that order whose `status` is `ISSUED` moves to
        `RETURNED` with `damaged_units` forced to 0 and `return_reason` set to
        `ORDER_ABANDONED`, returning its full unit count to the pool."
        PRD §2.11: "Every labor call on that order whose `status` is `CALLED` moves to
        `CANCELLED` with `cancellation_fee_cents` computed from the notice bands of §3.9."
        PRD §3.9: "Notice of at least 48 hours attracts no fee at all; otherwise notice of at
        least 12 hours attracts a quarter of the estimate; otherwise half the estimate is
        charged."

        Design: Difficulty/transitive_cascade/hold_expiry_sweep_releases_two_bookings_in_expiry_order_and_cascades_into_one_shared_order
        """
        arena = _two_expiring_holds_over_one_turnaround()
        assert arena["order"]["planned_turnaround_minutes"] == 708
        assert arena["labor_call"]["estimated_cost_cents"] == 544_320

        set_clock("2026-08-04T00:00:00Z")
        sweep_holds(arena["venue_id"])

        order = read_order(arena["order"]["id"])
        assert order["status"] == "ABANDONED"
        assert order["abandon_reason"] == "TO_BOOKING_GONE", (
            "the promoter concert expired first, so the incoming event went away first"
        )
        assert order["planned_turnaround_minutes"] == 708

        issue = read_issue(arena["issue"]["id"])
        assert issue["status"] == "RETURNED"
        assert issue["return_reason"] == "ORDER_ABANDONED"
        assert issue["damaged_units"] == 0

        asset = read_asset(arena["floor_pool"]["id"])
        assert asset["units_available"] == 10
        assert asset["cycles_since_service"] == 1

        call = read_labor_call(arena["labor_call"]["id"])
        assert call["status"] == "CANCELLED"
        assert call["cancellation_fee_cents"] == 272_160
        assert call["settled_cost_cents"] is None
