"""The booking's own state machine — draft, hold, confirmation, terminal
release — together with the dock and challenge transitions that hang off it."""
from test_helpers import (
    ApiErrorId,
    CLOCK_STARTUP_UTC,
    draft_booking,
    make_anchor_tenant_rep_headers,
    place_hold,
    read_booking,
    read_challenge,
    read_reservation,
    read_tenant,
    read_venue,
    register_tenant,
    release_booking,
    reserve_dock,
    setup_arena,
    setup_open_challenge,
    validate_error,
    validate_success,
    venue_version,
    withdraw_challenge,
    TEST_USERS,
)

MANAGER = TEST_USERS["booking_manager_headers"]
SUPERVISOR = TEST_USERS["changeover_supervisor_headers"]

HOCKEY_EVENT = ("2026-09-10T00:00:00Z", "2026-09-10T03:00:00Z")


def _promoter_draft(arena):
    """One promoter show drafted against the arena's ice configuration."""
    return draft_booking(
        arena["venue_id"], arena["profiles"]["ICE"]["id"], "Hockey Sep 10",
        HOCKEY_EVENT[0], HOCKEY_EVENT[1],
        expected_attendance=15_000, rigging_load_kg=3_000,
        promoter_name="Lakeside Hockey Club",
    )


class TestTheDraftAndHoldTransitions:
    def test_a_freshly_drafted_show_holds_nothing_and_counts_for_nothing(self, api):
        """PRD §3.3: "It begins as `DRAFT`, becomes `HELD` when the contractual hold is placed,
        may be pushed into `CHALLENGED` while a rival tenant contests that hold, becomes
        `CONFIRMED` when the calendar commitment is made, and finishes either as `RELEASED` or as
        `DISPLACED`."
        PRD §3.3: "A fresh draft has `status` reading `DRAFT`; `hold_tier`, `hold_placed_at`,
        `hold_expires_at`, `release_reason` and `displaced_by_booking_id` all unset; and
        `displacement_penalty_cents` at 0."
        PRD §2.11: "`open_hold_count` is the number of bookings on the arena whose `status` is
        either `HELD` or `CHALLENGED`."

        Design: Corner/state_machines/new_event_booking_starts_in_draft_with_null_hold_fields
        """
        arena = setup_arena(profiles=("ICE",), clock=CLOCK_STARTUP_UTC)

        booking = validate_success(
            api.create_event_booking(
                {
                    "venue_id": arena["venue_id"],
                    "config_profile_id": arena["profiles"]["ICE"]["id"],
                    "title": "Hockey Sep 10",
                    "promoter_name": "Lakeside Hockey Club",
                    "event_start_utc": HOCKEY_EVENT[0],
                    "event_end_utc": HOCKEY_EVENT[1],
                    "expected_attendance": 15_000,
                    "rigging_load_kg": 3_000,
                },
                MANAGER,
            ),
            201,
        )

        assert booking["status"] == "DRAFT"
        assert booking["hold_tier"] is None
        assert booking["hold_placed_at"] is None
        assert booking["hold_expires_at"] is None
        assert booking["displaced_by_booking_id"] is None
        assert booking["release_reason"] is None

        assert read_venue(arena["venue_id"])["open_hold_count"] == 0, (
            "a draft booking is not a hold"
        )

    def test_the_hold_snapshots_the_tier_stamps_the_window_and_moves_both_counters(
        self, api
    ):
        """PRD §3.3: "On acceptance the booking moves `DRAFT → HELD`, `hold_placed_at` is stamped
        with the logical clock instant, and `hold_tier` is **snapshotted** — taken from the
        tenant's `hold_priority_tier` for an anchor booking, or set to `OPEN` for a promoter
        booking."
        PRD §3.3: "`hold_expires_at` is then computed as `hold_placed_at` advanced by the pinned
        tier's hold window from §3.2 — fourteen days for `TIER_1`, seven days for `TIER_2`, three
        days for `TIER_3`, twenty-four hours for `OPEN` — using whole-hour arithmetic and rendered
        as an ISO 8601 UTC instant with three fractional digits."
        PRD §3.3: "The tenant's `holds_consumed` and the arena's `open_hold_count` are recomputed,
        each rising by one, and the arena's `version` advances by one."
        PRD §3.2: "`holds_consumed` counts the tenant's bookings that are currently `HELD`,
        `CHALLENGED` or `CONFIRMED`, and is the figure measured against
        `guaranteed_holds_per_season` when a new hold is placed."

        Design: Corner/state_machines/hold_moves_draft_to_held_and_applies_every_declared_side_effect
        """
        arena = setup_arena(profiles=("ICE",), clock=CLOCK_STARTUP_UTC)
        tenant = register_tenant(
            arena["venue_id"], "Lakeside Hockey Club", "TIER_2", 3
        )
        booking = draft_booking(
            arena["venue_id"], arena["profiles"]["ICE"]["id"], "Hockey Sep 10",
            HOCKEY_EVENT[0], HOCKEY_EVENT[1],
            expected_attendance=15_000, rigging_load_kg=3_000,
            tenant_id=tenant["id"],
        )
        version_before = venue_version(arena["venue_id"])

        held = validate_success(
            api.hold_event_booking(
                booking["id"], make_anchor_tenant_rep_headers(tenant["id"])
            ),
            200,
        )

        assert held["status"] == "HELD"
        assert held["hold_tier"] == "TIER_2"
        assert held["hold_placed_at"] == "2026-08-01T00:00:00.000Z"
        assert held["hold_expires_at"] == "2026-08-08T00:00:00.000Z", (
            "seven days of whole-hour arithmetic from the placement instant"
        )

        assert read_tenant(arena["venue_id"], tenant["id"])["holds_consumed"] == 1
        venue = read_venue(arena["venue_id"])
        assert venue["open_hold_count"] == 1
        assert venue["version"] == version_before + 1

    def test_a_second_hold_on_the_same_booking_is_refused_and_never_restamps_the_window(
        self, api
    ):
        """PRD §3.3: "It requires the booking to be `DRAFT` — any other state is
        `ERR_INVALID_BOOKING_STATE` — and, for an anchor booking, that the tenant's
        `holds_consumed` is strictly below its `guaranteed_holds_per_season`, otherwise
        `ERR_TENANT_HOLD_QUOTA_EXCEEDED`."
        PRD §2.11: "`open_hold_count` is the number of bookings on the arena whose `status` is
        either `HELD` or `CHALLENGED`."
        PRD §2.4: "`version` is an integer that starts at 1 when the row is created and increases
        by exactly 1 on every accepted mutation of that row."

        Design: Corner/state_machines/holding_an_already_held_booking_is_rejected
        """
        arena = setup_arena(profiles=("ICE",), clock=CLOCK_STARTUP_UTC)
        booking = place_hold(_promoter_draft(arena)["id"])
        assert booking["hold_expires_at"] == "2026-08-02T00:00:00.000Z"
        version_after_hold = venue_version(arena["venue_id"])

        response = api.hold_event_booking(booking["id"], MANAGER)
        validate_error(response, ApiErrorId.ERR_INVALID_BOOKING_STATE.value, 409)

        stored = read_booking(booking["id"])
        assert stored["status"] == "HELD"
        assert stored["hold_expires_at"] == "2026-08-02T00:00:00.000Z", (
            "the refused call does not re-stamp the expiry"
        )
        venue = read_venue(arena["venue_id"])
        assert venue["open_hold_count"] == 1, "the hold is not double counted"
        assert venue["version"] == version_after_hold

    def test_a_released_draft_can_never_be_held_again(self, api):
        """PRD §3.3: "`RELEASED` and `DISPLACED` are terminal; nothing leaves them."
        PRD §3.5: "Releasing a `DRAFT` booking is the trivial case: the booking moves
        `DRAFT → RELEASED`, `release_reason` is written, and the arena's `version` advances by
        one."
        PRD §3.3: "It requires the booking to be `DRAFT` — any other state is
        `ERR_INVALID_BOOKING_STATE` — and, for an anchor booking, that the tenant's
        `holds_consumed` is strictly below its `guaranteed_holds_per_season`, otherwise
        `ERR_TENANT_HOLD_QUOTA_EXCEEDED`."

        Design: Corner/state_machines/released_booking_cannot_be_held_again_from_its_terminal_state
        """
        arena = setup_arena(profiles=("ICE",), clock=CLOCK_STARTUP_UTC)
        released = release_booking(
            _promoter_draft(arena)["id"], "PROMOTER_WITHDREW"
        )
        assert released["status"] == "RELEASED"

        response = api.hold_event_booking(released["id"], MANAGER)
        validate_error(response, ApiErrorId.ERR_INVALID_BOOKING_STATE.value, 409)

        stored = read_booking(released["id"])
        assert stored["status"] == "RELEASED"
        assert stored["release_reason"] == "PROMOTER_WITHDREW"
        assert stored["hold_tier"] is None, "the booking never held"


class TestTheConfirmationTransition:
    def test_confirming_clears_the_hold_counter_and_leaves_the_stale_expiry_in_place(
        self, api
    ):
        """PRD §3.3: "On success the booking moves `HELD → CONFIRMED`, the arena's
        `open_hold_count` drops by one, `rigging_committed_load_kg` is recomputed, and the arena's
        `version` advances by one."
        PRD §3.3: "Second, the logical clock must be at or before `hold_expires_at`; confirming at
        exactly the expiry instant still succeeds, and confirming strictly after it is
        `ERR_HOLD_EXPIRED`."
        PRD §3.3: "The stored arena field `rigging_committed_load_kg` uses exactly the same
        closed-interval arithmetic with the logical clock instant standing in as a zero-length
        candidate window: it is the sum of `rigging_load_kg` over confirmed bookings whose closed
        event interval contains the current instant."

        Design: Corner/state_machines/confirm_moves_held_to_confirmed_and_clears_the_open_hold_counter
        """
        arena = setup_arena(profiles=("ICE",), clock=CLOCK_STARTUP_UTC)
        booking = place_hold(_promoter_draft(arena)["id"])
        version_after_hold = venue_version(arena["venue_id"])

        confirmed = validate_success(
            api.confirm_event_booking(
                booking["id"],
                {"expected_venue_version": version_after_hold},
                MANAGER,
            ),
            200,
        )

        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["hold_expires_at"] == "2026-08-02T00:00:00.000Z", (
            "the twenty-four hour promoter window is simply no longer consulted"
        )

        venue = read_venue(arena["venue_id"])
        assert venue["open_hold_count"] == 0
        assert float(venue["rigging_committed_load_kg"]) == 0.00, (
            "the August clock instant lies outside the September event interval"
        )
        assert venue["version"] == version_after_hold + 1


class TestTheDockReservationTerminalState:
    def test_a_second_cancellation_is_refused_and_the_first_reason_survives(self, api):
        """PRD §3.9: "A reservation is created `RESERVED`; the only other state is `RELEASED`,
        which is terminal."
        PRD §3.9: "The reservation must be `RESERVED`, otherwise
        `ERR_INVALID_DOCK_RESERVATION_STATE`, and on acceptance it moves `RESERVED → RELEASED`
        with `release_reason` set to `OPERATOR_CANCEL`."
        PRD §3.9: "The same transition also arrives as a cascade whenever the parent booking
        enters `RELEASED` or `DISPLACED`, in which case `release_reason` reads `BOOKING_GONE`
        instead."

        Design: Corner/state_machines/cancelling_a_dock_slot_reservation_twice_is_rejected
        """
        arena = setup_arena(profiles=("ICE",), clock=CLOCK_STARTUP_UTC)
        booking = place_hold(_promoter_draft(arena)["id"])
        reservation = reserve_dock(
            booking["id"], 1, "LOAD_IN",
            "2026-09-09T10:00:00Z", "2026-09-09T14:00:00Z", truck_count=6,
        )
        assert reservation["status"] == "RESERVED"

        cancelled = validate_success(
            api.cancel_dock_slot_reservation(reservation["id"], SUPERVISOR), 200
        )
        assert cancelled["status"] == "RELEASED"
        assert cancelled["release_reason"] == "OPERATOR_CANCEL"

        response = api.cancel_dock_slot_reservation(reservation["id"], SUPERVISOR)
        validate_error(
            response, ApiErrorId.ERR_INVALID_DOCK_RESERVATION_STATE.value, 409
        )

        stored = read_reservation(booking["id"], reservation["id"])
        assert stored["status"] == "RELEASED"
        assert stored["release_reason"] == "OPERATOR_CANCEL", (
            "the refused second cancel does not rewrite the reason"
        )


class TestTheChallengeWithdrawalCycle:
    def test_withdrawal_refunds_the_credit_and_hands_the_date_back_unchanged(self, api):
        """PRD §3.4: "The challenge moves `OPEN → WITHDRAWN`, the challenging tenant's
        `challenge_credits` rises by one, and — provided the incumbent is still `CHALLENGED` and
        no other challenge against it remains `OPEN` — the incumbent returns
        `CHALLENGED → HELD` with its hold fields untouched."
        PRD §3.4: "Being challenged does **not** buy the incumbent any time: `hold_expires_at` is
        not extended, and the original expiry keeps running while the challenge is pending."
        PRD §3.4: "The delta is the ordinal of the incumbent booking's **pinned** `hold_tier`
        minus the ordinal of the challenging tenant's current `hold_priority_tier`, so it lands
        somewhere between negative three and positive three."
        PRD §3.4: "The arena's `version` advances by one."

        Design: Corner/state_machines/challenge_withdrawal_refunds_the_credit_and_returns_the_incumbent_booking_to_held
        """
        arena = setup_open_challenge(
            incumbent_tier="TIER_2", challenger_tier="TIER_1"
        )
        assert arena["challenge"]["priority_delta"] == 1, (
            "tier two at ordinal two less tier one at ordinal one"
        )
        assert arena["challenge"]["status"] == "OPEN"
        assert read_booking(arena["incumbent_booking"]["id"])["status"] == "CHALLENGED"
        assert read_tenant(
            arena["venue_id"], arena["challenger_tenant"]["id"]
        )["challenge_credits"] == 1
        version_before = venue_version(arena["venue_id"])

        withdrawn = withdraw_challenge(
            arena["challenge"]["id"], arena["challenger_tenant"]["id"]
        )

        assert withdrawn["status"] == "WITHDRAWN"

        incumbent = read_booking(arena["incumbent_booking"]["id"])
        assert incumbent["status"] == "HELD"
        assert incumbent["hold_tier"] == "TIER_2"
        assert incumbent["hold_expires_at"] == "2026-08-08T00:00:00.000Z", (
            "the contest never extended the original seven-day window"
        )

        assert read_tenant(
            arena["venue_id"], arena["challenger_tenant"]["id"]
        )["challenge_credits"] == 2, "the credit comes back on withdrawal"
        assert read_tenant(
            arena["venue_id"], arena["incumbent_tenant"]["id"]
        )["holds_consumed"] == 1, "the incumbent's own tally is untouched"
        assert venue_version(arena["venue_id"]) == version_before + 1

    def test_a_withdrawn_challenge_can_no_longer_be_ruled_on(self, api):
        """PRD §3.4: "A **hold challenge** is opened by an `AnchorTenantRep` and moves through
        four states: it is created `OPEN` and finishes as `UPHELD`, `DENIED` or `WITHDRAWN`, all
        three of which are terminal."
        PRD §3.4: "The challenge must be `OPEN`, otherwise `ERR_INVALID_CHALLENGE_STATE`."
        PRD §3.4: "A `DENIED` ruling has no further preconditions: `ruled_at` is stamped with the
        logical clock instant, the `ruling_note` is stored when supplied, and — provided the
        incumbent booking is still `CHALLENGED` and no other challenge against it remains `OPEN`
        — the incumbent moves `CHALLENGED → HELD` with `hold_tier`, `hold_placed_at` and
        `hold_expires_at` left exactly as they were before the contest."

        Design: Corner/state_machines/ruling_on_an_already_withdrawn_challenge_is_rejected
        """
        arena = setup_open_challenge(
            incumbent_tier="TIER_2", challenger_tier="TIER_1"
        )
        withdraw_challenge(
            arena["challenge"]["id"], arena["challenger_tenant"]["id"]
        )

        response = api.rule_hold_challenge(
            arena["challenge"]["id"],
            {"decision": "DENIED", "ruling_note": "late ruling attempt"},
            MANAGER,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_CHALLENGE_STATE.value, 409)

        stored = read_challenge(arena["challenge"]["id"])
        assert stored["status"] == "WITHDRAWN"
        assert stored["ruled_at"] is None
        assert stored["ruling_note"] is None
        assert read_tenant(
            arena["venue_id"], arena["challenger_tenant"]["id"]
        )["challenge_credits"] == 2, "the refunded credit is not spent again"
        assert read_booking(arena["incumbent_booking"]["id"])["status"] == "HELD"
