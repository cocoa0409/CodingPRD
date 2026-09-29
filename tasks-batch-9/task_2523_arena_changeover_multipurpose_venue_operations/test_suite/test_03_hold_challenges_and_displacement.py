"""Contested holds: challenge credits, the held-challenged-held cycle, upheld
rulings, the displacement settlement waterfall and the cascade it fires."""
from test_helpers import (
    create_equipment_pool,
    create_labor_call,
    draft_booking,
    issue_equipment,
    open_challenge,
    open_changeover_order,
    place_hold,
    read_booking,
    read_challenge,
    read_issue,
    read_labor_call,
    read_order,
    read_reservation,
    read_tenant,
    read_venue,
    register_tenant,
    reserve_dock,
    rule_challenge,
    setup_arena,
    setup_open_challenge,
    withdraw_challenge,
    read_asset,
)

CHALLENGER_EVENT = ("2026-09-20T00:00:00Z", "2026-09-20T03:00:00Z")


def _thirty_days_notice_challenge():
    """A TIER_1 tenant challenging a TIER_2 hold with the clock exactly thirty
    days ahead of the incumbent show."""
    return setup_open_challenge(
        incumbent_tier="TIER_2",
        challenger_tier="TIER_1",
        clock="2026-08-11T00:00:00Z",
        challenger_event=CHALLENGER_EVENT,
    )


def _cascade_arena():
    """An incumbent ice hold carrying a dock window, a turnaround into a
    promoter concert, issued floor panels and an open rigger call, all sitting
    under one open challenge from a stronger tenant."""
    arena = setup_arena(profiles=("ICE", "CONCERT"), clock="2026-08-11T00:00:00Z")
    venue_id = arena["venue_id"]
    arena["floor_pool"] = create_equipment_pool(venue_id, "FLOOR_PANEL_SET", 10, 12)
    arena["incumbent_tenant"] = register_tenant(
        venue_id, "Lakeside Hockey Club", "TIER_2", 5
    )
    arena["challenger_tenant"] = register_tenant(
        venue_id, "Riverton Athletics", "TIER_1", 5
    )
    incumbent = draft_booking(
        venue_id, arena["profiles"]["ICE"]["id"], "Hockey Sep 10",
        "2026-09-10T00:00:00Z", "2026-09-10T03:00:00Z",
        expected_attendance=15_000, rigging_load_kg=3_000,
        tenant_id=arena["incumbent_tenant"]["id"],
    )
    arena["incumbent_booking"] = place_hold(incumbent["id"])
    concert = draft_booking(
        venue_id, arena["profiles"]["CONCERT"]["id"], "Concert Sep 10",
        "2026-09-10T16:00:00Z", "2026-09-10T19:00:00Z",
        expected_attendance=8_000, rigging_load_kg=5_000,
        promoter_name="Northline Live",
    )
    arena["incoming_booking"] = place_hold(concert["id"])
    arena["challenger_booking"] = draft_booking(
        venue_id, arena["profiles"]["ICE"]["id"], "Riverton Sep 20",
        CHALLENGER_EVENT[0], CHALLENGER_EVENT[1],
        expected_attendance=14_000, rigging_load_kg=2_000,
        tenant_id=arena["challenger_tenant"]["id"],
    )
    arena["reservation"] = reserve_dock(
        arena["incumbent_booking"]["id"], 1, "LOAD_IN",
        "2026-09-09T18:00:00Z", "2026-09-09T22:00:00Z", truck_count=8,
    )
    arena["order"] = open_changeover_order(
        venue_id,
        arena["incumbent_booking"]["id"],
        arena["incoming_booking"]["id"],
        crew_headcount=40,
    )
    arena["issue"] = issue_equipment(
        arena["floor_pool"]["id"], arena["order"]["id"], 3
    )
    arena["labor_call"] = create_labor_call(
        "RIGGER", 6, "2026-08-11T06:00:00Z", "2026-08-11T14:00:00Z",
        guaranteed_hours=4, changeover_order_id=arena["order"]["id"],
    )
    arena["challenge"] = open_challenge(
        arena["incumbent_booking"]["id"],
        arena["challenger_tenant"]["id"],
        arena["challenger_booking"]["id"],
    )
    return arena


class TestDisplacementSettlementWaterfall:
    def test_the_administrative_band_is_read_off_the_subtotal_and_not_the_running_total(
        self, api
    ):
        """PRD §3.4: "**Step one** reads a base amount from the displaced booking's pinned
        `hold_tier`: 650,000 cents for `TIER_2`, 250,000 cents for `TIER_3`, and 120,000
        cents for `OPEN`."
        PRD §3.4: "A notice of at least 90 days multiplies the base by 0.25; otherwise a
        notice of at least 30 days multiplies it by 0.60; otherwise the base is taken in
        full."
        PRD §3.4: "**Step two** reads an administrative rate off the subtotal alone: 8
        percent when the subtotal is at least 400,000 cents, otherwise 5 percent when the
        subtotal is at least 150,000 cents, otherwise 3 percent."
        PRD §3.4: "The band in step two must be read from the subtotal and never from the sum
        produced in step four; reading it off the total yields a different figure whenever
        the subtotal sits just below a band edge."

        Design: Difficulty/combinatorial_formula/displacement_settlement_admin_band_reads_subtotal_not_the_running_total
        """
        arena = _thirty_days_notice_challenge()
        ruled = rule_challenge(
            arena["challenge"]["id"],
            "UPHELD",
            "Tier-1 anchor claim prevails over the Tier-2 hold",
        )
        assert ruled["status"] == "UPHELD"
        assert ruled["priority_delta"] == 1
        assert ruled["ruled_at"] == "2026-08-11T00:00:00.000Z"

        displaced = read_booking(arena["incumbent_booking"]["id"])
        assert displaced["hold_tier"] == "TIER_2"
        assert displaced["status"] == "DISPLACED"
        assert displaced["displacement_penalty_cents"] == 409_500, (
            "650000 x 0.60 gives a 390000 subtotal, whose band is 5 percent"
        )
        assert displaced["displacement_penalty_cents"] != 421_200, (
            "421200 would read the 8 percent band off the 409500 running total"
        )
        assert displaced["displacement_penalty_cents"] != 390_000, (
            "the administrative fee is added on top of the subtotal"
        )

    def test_a_displacement_is_not_a_release_and_moves_both_tenant_ledgers(self, api):
        """PRD §3.4: "The displaced booking records `displaced_by_booking_id` pointing at the
        challenge's `challenger_booking_id`, and its `displacement_penalty_cents` is computed
        by the settlement waterfall below."
        PRD §3.4: "Its `release_reason` stays unset, because a displacement is not a release."
        PRD §3.4: "A credit is spent when the tenant opens a challenge and is restored only
        when the tenant itself withdraws that challenge — a challenge that is ruled on, in
        either direction, consumes the credit permanently."
        PRD §2.11: "Anchor tenants carry two derived counters in the same spirit:
        `holds_consumed` is the number of bookings naming that tenant whose `status` is
        `HELD`, `CHALLENGED` or `CONFIRMED`, and `challenge_credits` is the tenant's
        remaining challenge budget."

        Design: Difficulty/combinatorial_formula/displacement_settlement_admin_band_reads_subtotal_not_the_running_total
        """
        arena = _thirty_days_notice_challenge()
        rule_challenge(
            arena["challenge"]["id"],
            "UPHELD",
            "Tier-1 anchor claim prevails over the Tier-2 hold",
        )

        displaced = read_booking(arena["incumbent_booking"]["id"])
        assert displaced["displaced_by_booking_id"] == arena["challenger_booking"]["id"]
        assert displaced["release_reason"] is None

        challenger = read_tenant(
            arena["venue_id"], arena["challenger_tenant"]["id"]
        )
        assert challenger["challenge_credits"] == 1, (
            "an adjudicated challenge keeps the credit spent"
        )
        incumbent_tenant = read_tenant(
            arena["venue_id"], arena["incumbent_tenant"]["id"]
        )
        assert incumbent_tenant["holds_consumed"] == 0


class TestHeldChallengedHeldCycleTraversedTwice:
    def test_withdrawal_refunds_the_credit_so_a_second_challenge_is_not_a_duplicate(
        self, api
    ):
        """PRD §3.4: "The challenge moves `OPEN → WITHDRAWN`, the challenging tenant's
        `challenge_credits` rises by one, and — provided the incumbent is still `CHALLENGED`
        and no other challenge against it remains `OPEN` — the incumbent returns
        `CHALLENGED → HELD` with its hold fields untouched."
        PRD §3.4: "And no challenge may already exist with the same `booking_id` and the same
        `challenger_tenant_id` in `OPEN` status, otherwise `ERR_DUPLICATE_CHALLENGE`."
        PRD §3.4: "Being challenged does **not** buy the incumbent any time:
        `hold_expires_at` is not extended, and the original expiry keeps running while the
        challenge is pending."

        Design: Difficulty/non_linear_state_machine/booking_traverses_held_challenged_held_cycle_twice_with_expiry_preserved_and_asymmetric_credit_ledger
        """
        arena = setup_open_challenge(
            incumbent_tier="TIER_2", challenger_tier="TIER_1"
        )
        first = withdraw_challenge(
            arena["challenge"]["id"], arena["challenger_tenant"]["id"]
        )
        assert first["status"] == "WITHDRAWN"
        assert first["ruled_at"] is None

        back_on_hold = read_booking(arena["incumbent_booking"]["id"])
        assert back_on_hold["status"] == "HELD"
        assert back_on_hold["hold_expires_at"] == "2026-08-08T00:00:00.000Z"

        second = open_challenge(
            arena["incumbent_booking"]["id"],
            arena["challenger_tenant"]["id"],
            arena["challenger_booking"]["id"],
        )
        assert second["status"] == "OPEN", (
            "the withdrawn challenge is terminal, so it cannot block a fresh one"
        )
        assert second["id"] != arena["challenge"]["id"]
        assert read_booking(arena["incumbent_booking"]["id"])["status"] == "CHALLENGED"

    def test_the_denied_ruling_closes_the_second_cycle_with_the_hold_fields_untouched(
        self, api
    ):
        """PRD §3.4: "A `DENIED` ruling has no further preconditions: `ruled_at` is stamped
        with the logical clock instant, the `ruling_note` is stored when supplied, and —
        provided the incumbent booking is still `CHALLENGED` and no other challenge against it
        remains `OPEN` — the incumbent moves `CHALLENGED → HELD` with `hold_tier`,
        `hold_placed_at` and `hold_expires_at` left exactly as they were before the contest."
        PRD §3.4: "A denial does not refund the credit; a spent challenge that was actually
        adjudicated stays spent."
        PRD §2.11: "`open_hold_count` is the number of bookings on the arena whose `status`
        is either `HELD` or `CHALLENGED`."

        Design: Difficulty/non_linear_state_machine/booking_traverses_held_challenged_held_cycle_twice_with_expiry_preserved_and_asymmetric_credit_ledger
        """
        arena = setup_open_challenge(
            incumbent_tier="TIER_2", challenger_tier="TIER_1"
        )
        withdraw_challenge(
            arena["challenge"]["id"], arena["challenger_tenant"]["id"]
        )
        second = open_challenge(
            arena["incumbent_booking"]["id"],
            arena["challenger_tenant"]["id"],
            arena["challenger_booking"]["id"],
        )
        ruled = rule_challenge(
            second["id"], "DENIED", "Incumbent tier retained on calendar grounds"
        )

        assert ruled["status"] == "DENIED"
        assert ruled["ruled_at"] == "2026-08-01T00:00:00.000Z"
        assert read_challenge(arena["challenge"]["id"])["ruled_at"] is None

        incumbent = read_booking(arena["incumbent_booking"]["id"])
        assert incumbent["status"] == "HELD"
        assert incumbent["hold_tier"] == "TIER_2"
        assert incumbent["hold_placed_at"] == "2026-08-01T00:00:00.000Z"
        assert incumbent["hold_expires_at"] == "2026-08-08T00:00:00.000Z"

        challenger = read_tenant(arena["venue_id"], arena["challenger_tenant"]["id"])
        assert challenger["challenge_credits"] == 1, (
            "one credit was refunded by the withdrawal and one stays spent on the denial"
        )
        incumbent_tenant = read_tenant(
            arena["venue_id"], arena["incumbent_tenant"]["id"]
        )
        assert incumbent_tenant["holds_consumed"] == 1
        assert read_venue(arena["venue_id"])["open_hold_count"] == 1


class TestUpheldDisplacementCascadesFourHops:
    def test_the_upheld_ruling_displaces_the_incumbent_and_settles_the_penalty(
        self, api
    ):
        """PRD §3.4: "When both pass, `ruled_at` and `ruling_note` are written, the credit
        stays spent, and the incumbent booking is driven `CHALLENGED → DISPLACED`."
        PRD §3.4: "The delta is the ordinal of the incumbent booking's **pinned** `hold_tier`
        minus the ordinal of the challenging tenant's current `hold_priority_tier`, so it
        lands somewhere between negative three and positive three."
        PRD §3.4: "Its `release_reason` stays unset, because a displacement is not a release."
        PRD §2.11: "`open_hold_count` is the number of bookings on the arena whose `status`
        is either `HELD` or `CHALLENGED`."

        Design: Difficulty/transitive_cascade/upheld_challenge_displacement_cascades_four_hops_from_ruling_to_equipment_and_labor_ledgers
        """
        arena = _cascade_arena()
        ruled = rule_challenge(
            arena["challenge"]["id"],
            "UPHELD",
            "Tier-1 anchor claim prevails over the Tier-2 hold",
        )
        assert ruled["status"] == "UPHELD"
        assert ruled["priority_delta"] == 1
        assert ruled["ruled_at"] == "2026-08-11T00:00:00.000Z"

        displaced = read_booking(arena["incumbent_booking"]["id"])
        assert displaced["status"] == "DISPLACED"
        assert displaced["displaced_by_booking_id"] == arena["challenger_booking"]["id"]
        assert displaced["displacement_penalty_cents"] == 409_500
        assert displaced["release_reason"] is None

        assert read_tenant(
            arena["venue_id"], arena["incumbent_tenant"]["id"]
        )["holds_consumed"] == 0
        assert read_tenant(
            arena["venue_id"], arena["challenger_tenant"]["id"]
        )["challenge_credits"] == 1
        assert read_venue(arena["venue_id"])["open_hold_count"] == 1, (
            "only the incoming promoter concert is still holding a date"
        )

    def test_the_dock_window_and_the_turnaround_go_with_the_displaced_show(self, api):
        """PRD §2.11: "Every dock slot reservation attached to that booking whose `status` is
        `RESERVED` moves to `RELEASED` with `release_reason` set to `BOOKING_GONE`."
        PRD §2.11: "Every changeover order that names the booking as either its outgoing or
        its incoming event, and whose `status` is neither `SIGNED_OFF` nor `ABANDONED`, moves
        to `ABANDONED`."
        PRD §3.8: "The order records `abandon_reason` as `FROM_BOOKING_GONE` when the outgoing
        event went away and as `TO_BOOKING_GONE` when the incoming event did."

        Design: Difficulty/transitive_cascade/upheld_challenge_displacement_cascades_four_hops_from_ruling_to_equipment_and_labor_ledgers
        """
        arena = _cascade_arena()
        rule_challenge(
            arena["challenge"]["id"],
            "UPHELD",
            "Tier-1 anchor claim prevails over the Tier-2 hold",
        )

        reservation = read_reservation(
            arena["incumbent_booking"]["id"], arena["reservation"]["id"]
        )
        assert reservation["status"] == "RELEASED"
        assert reservation["release_reason"] == "BOOKING_GONE"

        order = read_order(arena["order"]["id"])
        assert order["status"] == "ABANDONED"
        assert order["abandon_reason"] == "FROM_BOOKING_GONE", (
            "the displaced ice show was this turnaround's outgoing event"
        )

    def test_abandonment_returns_the_panels_whole_and_cancels_the_rigger_call(
        self, api
    ):
        """PRD §2.11: "Every equipment issue on that order whose `status` is `ISSUED` moves to
        `RETURNED` with `damaged_units` forced to 0 and `return_reason` set to
        `ORDER_ABANDONED`, returning its full unit count to the pool."
        PRD §2.11: "Every labor call on that order whose `status` is `CALLED` moves to
        `CANCELLED` with `cancellation_fee_cents` computed from the notice bands of §3.9."
        PRD §3.9: "Notice of at least 48 hours attracts no fee at all; otherwise notice of at
        least 12 hours attracts a quarter of the estimate; otherwise half the estimate is
        charged."
        PRD §3.9: "The call moves `CALLED → CANCELLED` and `settled_cost_cents` stays unset,
        because cancelled work is never settled."
        PRD §3.9: "The pool's `cycles_since_service` rises by one and `service_due` is
        re-evaluated against `service_interval_cycles`."

        Design: Difficulty/transitive_cascade/upheld_challenge_displacement_cascades_four_hops_from_ruling_to_equipment_and_labor_ledgers
        """
        arena = _cascade_arena()
        assert arena["labor_call"]["estimated_cost_cents"] == 466_560

        rule_challenge(
            arena["challenge"]["id"],
            "UPHELD",
            "Tier-1 anchor claim prevails over the Tier-2 hold",
        )

        issue = read_issue(arena["issue"]["id"])
        assert issue["status"] == "RETURNED"
        assert issue["return_reason"] == "ORDER_ABANDONED"
        assert issue["damaged_units"] == 0

        asset = read_asset(arena["floor_pool"]["id"])
        assert asset["units_available"] == 10
        assert asset["units_out_of_service"] == 0
        assert asset["cycles_since_service"] == 1

        call = read_labor_call(arena["labor_call"]["id"])
        assert call["status"] == "CANCELLED"
        assert call["cancellation_fee_cents"] == 233_280, (
            "six hours notice falls below the twelve-hour band, so half the estimate"
        )
        assert call["settled_cost_cents"] is None
