"""Event booking lifecycle: drafts, contractual holds, confirmation and the
two hold ledgers the arena and its anchor tenants maintain."""
import pytest

from test_helpers import (
    ApiErrorId,
    confirm_booking,
    draft_booking,
    place_hold,
    read_tenant,
    read_venue,
    register_tenant,
    release_booking,
    set_clock,
    setup_arena,
    validate_error,
    validate_success,
    venue_version,
    TEST_USERS,
)

MANAGER = TEST_USERS["booking_manager_headers"]


def _arena_with_tier3_tenant():
    arena = setup_arena(profiles=("ICE",))
    arena["tenant"] = register_tenant(
        arena["venue_id"], "Harbor Curling", "TIER_3", 5
    )
    return arena


def _two_held_curling_bookings(arena):
    first = draft_booking(
        arena["venue_id"],
        arena["profiles"]["ICE"]["id"],
        "Harbor Curling draw 1",
        "2026-09-12T00:00:00Z",
        "2026-09-12T03:00:00Z",
        expected_attendance=9_000,
        rigging_load_kg=1_500,
        tenant_id=arena["tenant"]["id"],
    )
    first = place_hold(first["id"])
    second = draft_booking(
        arena["venue_id"],
        arena["profiles"]["ICE"]["id"],
        "Harbor Curling draw 2",
        "2026-09-13T00:00:00Z",
        "2026-09-13T03:00:00Z",
        expected_attendance=9_000,
        rigging_load_kg=1_500,
        tenant_id=arena["tenant"]["id"],
    )
    second = place_hold(second["id"])
    return first, second


class TestHoldExpiryBoundaryOnConfirm:
    def test_confirm_at_exactly_the_hold_expiry_instant_is_accepted(self, api):
        """PRD §3.3: "Second, the logical clock must be at or before `hold_expires_at`;
        confirming at exactly the expiry instant still succeeds, and confirming strictly
        after it is `ERR_HOLD_EXPIRED`."
        PRD §3.3: "`hold_expires_at` is then computed as `hold_placed_at` advanced by the
        pinned tier's hold window from §3.2 — fourteen days for `TIER_1`, seven days for
        `TIER_2`, three days for `TIER_3`, twenty-four hours for `OPEN` — using whole-hour
        arithmetic and rendered as an ISO 8601 UTC instant with three fractional digits."

        Design: Difficulty/boundary_precision_check/hold_expiry_admits_the_confirm_at_the_exact_expiry_instant_and_refuses_it_one_second_later
        """
        arena = _arena_with_tier3_tenant()
        first, second = _two_held_curling_bookings(arena)

        assert first["hold_expires_at"] == "2026-08-04T00:00:00.000Z"
        assert second["hold_expires_at"] == "2026-08-04T00:00:00.000Z"

        set_clock("2026-08-04T00:00:00Z")
        payload = {"expected_venue_version": venue_version(arena["venue_id"])}
        response = api.confirm_event_booking(first["id"], payload, MANAGER)
        data = validate_success(response, 200)
        assert data["status"] == "CONFIRMED", (
            "A confirm at exactly hold_expires_at must be accepted, got "
            f"{data['status']}"
        )

    def test_confirm_one_second_after_hold_expiry_is_rejected_and_leaves_the_arena_untouched(
        self, api
    ):
        """PRD §3.3: "Second, the logical clock must be at or before `hold_expires_at`;
        confirming at exactly the expiry instant still succeeds, and confirming strictly
        after it is `ERR_HOLD_EXPIRED`."
        PRD §2.11: "`open_hold_count` is the number of bookings on the arena whose
        `status` is either `HELD` or `CHALLENGED`."
        PRD §3.3: "The stored arena field `rigging_committed_load_kg` uses exactly the same
        closed-interval arithmetic with the logical clock instant standing in as a
        zero-length candidate window: it is the sum of `rigging_load_kg` over confirmed
        bookings whose closed event interval contains the current instant."

        Design: Difficulty/boundary_precision_check/hold_expiry_admits_the_confirm_at_the_exact_expiry_instant_and_refuses_it_one_second_later
        """
        arena = _arena_with_tier3_tenant()
        first, second = _two_held_curling_bookings(arena)

        set_clock("2026-08-04T00:00:00Z")
        confirm_booking(first["id"], arena["venue_id"])

        set_clock("2026-08-04T00:00:01Z")
        version_before = venue_version(arena["venue_id"])
        response = api.confirm_event_booking(
            second["id"], {"expected_venue_version": version_before}, MANAGER
        )
        validate_error(response, ApiErrorId.ERR_HOLD_EXPIRED.value, 409)

        still_held = validate_success(api.get_event_booking(second["id"], MANAGER))
        assert still_held["status"] == "HELD"
        assert still_held["hold_expires_at"] == "2026-08-04T00:00:00.000Z"

        venue = read_venue(arena["venue_id"])
        assert venue["open_hold_count"] == 1
        assert venue["rigging_committed_load_kg"] == pytest.approx(0, abs=0.01), (
            "The clock sits in August; the confirmed September event's closed interval "
            "does not contain it, so the committed figure is the empty sum"
        )
        assert venue["version"] == version_before, (
            "A rejected confirm must not advance the arena version"
        )


class TestRiggingGridClosedIntervalAggregation:
    @staticmethod
    def _grid_arena():
        arena = setup_arena(profiles=("ICE",))
        venue_id = arena["venue_id"]
        profile_id = arena["profiles"]["ICE"]["id"]
        first = draft_booking(
            venue_id, profile_id, "Grid load A",
            "2026-09-09T10:00:00Z", "2026-09-09T13:00:00Z",
            expected_attendance=15_000, rigging_load_kg=12_000,
            promoter_name="Lakeside Hockey Club",
        )
        place_hold(first["id"])
        arena["booking_a"] = confirm_booking(first["id"], venue_id)
        second = draft_booking(
            venue_id, profile_id, "Grid load B",
            "2026-09-09T13:00:00Z", "2026-09-09T16:00:00Z",
            expected_attendance=14_000, rigging_load_kg=8_000,
            promoter_name="Riverton Athletics",
        )
        arena["booking_b"] = place_hold(second["id"])
        third = draft_booking(
            venue_id, profile_id, "Grid load D",
            "2026-09-09T16:00:00Z", "2026-09-09T19:00:00Z",
            expected_attendance=9_000, rigging_load_kg=12_001,
            promoter_name="Harbor Curling",
        )
        arena["booking_d"] = place_hold(third["id"])
        return arena

    def test_touching_events_do_not_conflict_yet_both_load_the_grid_to_exactly_capacity(
        self, api
    ):
        """PRD §2.7: "Intervals that merely touch at an endpoint — one ending at exactly
        the instant the next begins — do not collide."
        PRD §3.3: "The confirm is accepted when the result is less than or equal to the
        arena's `rigging_capacity_kg`; a load landing exactly on capacity is accepted, and
        anything above it is `ERR_RIGGING_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/rigging_grid_counts_closed_interval_neighbours_that_the_half_open_booking_conflict_ignores
        """
        arena = self._grid_arena()
        payload = {"expected_venue_version": venue_version(arena["venue_id"])}
        response = api.confirm_event_booking(
            arena["booking_b"]["id"], payload, MANAGER
        )
        data = validate_success(response, 200)
        assert data["status"] == "CONFIRMED", (
            "[10:00,13:00) and [13:00,16:00) do not intersect under half-open "
            "arithmetic, and 12000 + 8000 == 20000 sits exactly on capacity"
        )

    def test_closed_interval_peer_set_refuses_the_load_one_kilogram_above_capacity(
        self, api
    ):
        """PRD §2.7: "Two bookings overlap for rigging purposes when the first starts at or
        before the second ends and the second starts at or before the first ends — closed
        on both sides."
        PRD §3.3: "The confirm is accepted when the result is less than or equal to the
        arena's `rigging_capacity_kg`; a load landing exactly on capacity is accepted, and
        anything above it is `ERR_RIGGING_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/rigging_grid_counts_closed_interval_neighbours_that_the_half_open_booking_conflict_ignores
        """
        arena = self._grid_arena()
        confirm_booking(arena["booking_b"]["id"], arena["venue_id"])

        version_before = venue_version(arena["venue_id"])
        response = api.confirm_event_booking(
            arena["booking_d"]["id"],
            {"expected_venue_version": version_before},
            MANAGER,
        )
        validate_error(response, ApiErrorId.ERR_RIGGING_CAPACITY_EXCEEDED.value, 422)

        still_held = validate_success(
            api.get_event_booking(arena["booking_d"]["id"], MANAGER)
        )
        assert still_held["status"] == "HELD"

        venue = read_venue(arena["venue_id"])
        assert venue["version"] == version_before
        assert venue["open_hold_count"] == 1
        assert venue["rigging_committed_load_kg"] == pytest.approx(0, abs=0.01), (
            "The logical clock instant lies inside no confirmed event's closed interval"
        )


class TestHoldLedgerReconciliation:
    @staticmethod
    def _three_tenant_drafts():
        arena = setup_arena(profiles=("ICE",))
        arena["tenant"] = register_tenant(
            arena["venue_id"], "Lakeside Hockey Club", "TIER_2", 5
        )
        drafts = []
        for day in (10, 11, 12):
            drafts.append(
                draft_booking(
                    arena["venue_id"],
                    arena["profiles"]["ICE"]["id"],
                    f"Home game Sep {day}",
                    f"2026-09-{day}T00:00:00Z",
                    f"2026-09-{day}T03:00:00Z",
                    expected_attendance=15_000,
                    rigging_load_kg=3_000,
                    tenant_id=arena["tenant"]["id"],
                )
            )
        arena["drafts"] = drafts
        return arena

    @staticmethod
    def _tenant_row(api, arena):
        return read_tenant(arena["venue_id"], arena["tenant"]["id"])

    def test_confirm_decrements_the_open_hold_count_but_not_the_tenant_hold_consumption(
        self, api
    ):
        """PRD §2.11: "`open_hold_count` is the number of bookings on the arena whose
        `status` is either `HELD` or `CHALLENGED`."
        PRD §2.11: "Anchor tenants carry two derived counters in the same spirit:
        `holds_consumed` is the number of bookings naming that tenant whose `status` is
        `HELD`, `CHALLENGED` or `CONFIRMED`, and `challenge_credits` is the tenant's
        remaining challenge budget."

        Design: Difficulty/compensating_invariant/hold_ledgers_reconcile_to_zero_after_confirm_and_release_although_the_two_counters_move_on_different_events
        """
        arena = self._three_tenant_drafts()
        for draft in arena["drafts"]:
            place_hold(draft["id"])

        venue = read_venue(arena["venue_id"])
        assert venue["open_hold_count"] == 3
        assert self._tenant_row(api, arena)["holds_consumed"] == 3

        confirm_booking(arena["drafts"][1]["id"], arena["venue_id"])

        venue = read_venue(arena["venue_id"])
        assert venue["open_hold_count"] == 2, (
            "Confirming a booking removes it from the HELD/CHALLENGED population"
        )
        assert venue["rigging_committed_load_kg"] == pytest.approx(0, abs=0.01)
        assert self._tenant_row(api, arena)["holds_consumed"] == 3, (
            "A CONFIRMED booking still counts against the tenant's seasonal guarantee"
        )

    def test_releasing_the_confirmed_and_held_bookings_returns_both_ledgers_to_zero(
        self, api
    ):
        """PRD §3.5: "Releasing a `HELD` booking moves it `HELD → RELEASED` and runs the
        dependent cascade in full — reserved dock windows to `RELEASED` with
        `release_reason` of `BOOKING_GONE`, non-terminal changeover orders on either side
        to `ABANDONED`, and from there the equipment returns and labor cancellations of
        §2.11."
        PRD §2.11: "Anchor tenants carry two derived counters in the same spirit:
        `holds_consumed` is the number of bookings naming that tenant whose `status` is
        `HELD`, `CHALLENGED` or `CONFIRMED`, and `challenge_credits` is the tenant's
        remaining challenge budget."

        Design: Difficulty/compensating_invariant/hold_ledgers_reconcile_to_zero_after_confirm_and_release_although_the_two_counters_move_on_different_events
        """
        arena = self._three_tenant_drafts()
        for draft in arena["drafts"]:
            place_hold(draft["id"])
        confirm_booking(arena["drafts"][1]["id"], arena["venue_id"])

        released_first = release_booking(
            arena["drafts"][0]["id"], "Tenant returned the date"
        )
        released_confirmed = release_booking(
            arena["drafts"][1]["id"], "Tenant returned the confirmed date"
        )
        released_last = release_booking(
            arena["drafts"][2]["id"], "Tenant returned the date"
        )

        assert released_first["status"] == "RELEASED"
        assert released_first["release_reason"] == "Tenant returned the date"
        assert released_confirmed["status"] == "RELEASED"
        assert released_confirmed["release_reason"] == "Tenant returned the confirmed date"
        assert released_last["status"] == "RELEASED"

        venue = read_venue(arena["venue_id"])
        assert venue["open_hold_count"] == 0, (
            "Releasing the CONFIRMED booking must not decrement open_hold_count twice"
        )
        assert venue["rigging_committed_load_kg"] == pytest.approx(0, abs=0.01)
        assert self._tenant_row(api, arena)["holds_consumed"] == 0
