"""Validation precedence: when one request trips several checks at once, the
arena reports the earliest failure in its ladder and never a later one."""
from test_helpers import (
    ApiErrorId,
    draft_booking,
    make_anchor_tenant_rep_headers,
    place_hold,
    read_booking,
    read_tenant,
    read_venue,
    register_tenant,
    set_clock,
    setup_arena,
    validate_error,
    validate_paginated,
    venue_version,
    TEST_USERS,
)

MANAGER = TEST_USERS["booking_manager_headers"]
SUPERVISOR = TEST_USERS["changeover_supervisor_headers"]


def _two_curling_holds():
    """Two TIER_3 holds placed at the clock's startup instant, so both expire
    three days later at 2026-08-04T00:00:00Z."""
    arena = setup_arena(profiles=("ICE",))
    arena["tenant"] = register_tenant(
        arena["venue_id"], "Harbor Curling", "TIER_3", 5
    )
    first = draft_booking(
        arena["venue_id"], arena["profiles"]["ICE"]["id"], "Curling draw 1",
        "2026-09-12T00:00:00Z", "2026-09-12T03:00:00Z",
        expected_attendance=9_000, rigging_load_kg=1_500,
        tenant_id=arena["tenant"]["id"],
    )
    arena["first"] = place_hold(first["id"])
    arena["version_after_first_hold"] = venue_version(arena["venue_id"])
    second = draft_booking(
        arena["venue_id"], arena["profiles"]["ICE"]["id"], "Curling draw 2",
        "2026-09-13T00:00:00Z", "2026-09-13T03:00:00Z",
        expected_attendance=9_000, rigging_load_kg=1_500,
        tenant_id=arena["tenant"]["id"],
    )
    arena["second"] = place_hold(second["id"])
    return arena


def _three_bookings_for_two_windows():
    """One outgoing ice show plus two candidate incoming concerts: an early one
    whose turnaround window is far too short, and a late one that is roomy."""
    arena = setup_arena(profiles=("ICE", "CONCERT"), crew_headcount_cap=60)
    venue_id = arena["venue_id"]
    outgoing = draft_booking(
        venue_id, arena["profiles"]["ICE"]["id"], "Hockey Sep 10",
        "2026-09-10T00:00:00Z", "2026-09-10T03:00:00Z",
        expected_attendance=15_000, rigging_load_kg=3_000,
        promoter_name="Lakeside Hockey Club",
    )
    arena["outgoing"] = place_hold(outgoing["id"])
    early = draft_booking(
        venue_id, arena["profiles"]["CONCERT"]["id"], "Early concert Sep 10",
        "2026-09-10T08:00:00Z", "2026-09-10T11:00:00Z",
        expected_attendance=8_000, rigging_load_kg=5_000,
        promoter_name="Northline Live",
    )
    arena["early"] = place_hold(early["id"])
    late = draft_booking(
        venue_id, arena["profiles"]["CONCERT"]["id"], "Late concert Sep 10",
        "2026-09-10T16:00:00Z", "2026-09-10T19:00:00Z",
        expected_attendance=8_000, rigging_load_kg=5_000,
        promoter_name="Northline Live",
    )
    arena["late"] = place_hold(late["id"])
    arena["observed_version"] = venue_version(venue_id)
    return arena


def _tenant_at_its_hold_ceiling():
    """An anchor tenant entitled to exactly one concurrent hold, which it has
    already spent, plus a second draft and a rival tenant's representative."""
    arena = setup_arena(profiles=("ICE",))
    venue_id = arena["venue_id"]
    arena["owner"] = register_tenant(venue_id, "Lakeside Hockey Club", "TIER_2", 1)
    arena["rival"] = register_tenant(venue_id, "Riverton Athletics", "TIER_1", 5)
    spent = draft_booking(
        venue_id, arena["profiles"]["ICE"]["id"], "Home game Sep 10",
        "2026-09-10T00:00:00Z", "2026-09-10T03:00:00Z",
        expected_attendance=15_000, rigging_load_kg=3_000,
        tenant_id=arena["owner"]["id"],
    )
    arena["spent"] = place_hold(spent["id"])
    arena["pending"] = draft_booking(
        venue_id, arena["profiles"]["ICE"]["id"], "Home game Sep 11",
        "2026-09-11T00:00:00Z", "2026-09-11T03:00:00Z",
        expected_attendance=15_000, rigging_load_kg=3_000,
        tenant_id=arena["owner"]["id"],
    )
    return arena


class TestStaleVersionOutranksExpiredHoldOnConfirm:
    def test_a_superseded_arena_version_is_reported_ahead_of_the_expired_hold(
        self, api
    ):
        """PRD §2.10: "When a single request could fail several checks at once, the response
        must name the first failure in the ladder below, never a later one."
        PRD §2.10: "Confirming a booking evaluates, in order: the stale-version check, then
        the from-state check, then the event-interval conflict, then hold expiry, and only
        last the roof-grid capacity check — so a confirm that is both expired and over
        capacity reports `ERR_HOLD_EXPIRED`."
        PRD §2.6: "If that value does not equal the arena's current `version` at the moment
        the write is evaluated, the request is rejected with `ERR_STALE_VENUE_VERSION` and
        HTTP status 412."

        Design: Difficulty/priority_pair_validation_conflict/stale_venue_version_at_priority_45_outranks_expired_hold_at_priority_78_on_confirm
        """
        arena = _two_curling_holds()
        stale_version = arena["version_after_first_hold"]

        set_clock("2026-08-05T00:00:00Z")
        response = api.confirm_event_booking(
            arena["first"]["id"], {"expected_venue_version": stale_version}, MANAGER
        )
        validate_error(response, ApiErrorId.ERR_STALE_VENUE_VERSION.value, 412)

        booking = read_booking(arena["first"]["id"])
        assert booking["status"] == "HELD"
        assert booking["hold_expires_at"] == "2026-08-04T00:00:00.000Z", (
            "the hold was already expired, yet the stale version outranks that failure"
        )

    def test_the_fresh_arena_version_then_surfaces_the_expired_hold(self, api):
        """PRD §3.3: "Second, the logical clock must be at or before `hold_expires_at`;
        confirming at exactly the expiry instant still succeeds, and confirming strictly
        after it is `ERR_HOLD_EXPIRED`."
        PRD §2.11: "`open_hold_count` is the number of bookings on the arena whose `status`
        is either `HELD` or `CHALLENGED`."

        Design: Difficulty/priority_pair_validation_conflict/stale_venue_version_at_priority_45_outranks_expired_hold_at_priority_78_on_confirm
        """
        arena = _two_curling_holds()
        set_clock("2026-08-05T00:00:00Z")

        fresh_version = venue_version(arena["venue_id"])
        assert fresh_version != arena["version_after_first_hold"]

        response = api.confirm_event_booking(
            arena["first"]["id"], {"expected_venue_version": fresh_version}, MANAGER
        )
        validate_error(response, ApiErrorId.ERR_HOLD_EXPIRED.value, 409)

        assert read_booking(arena["first"]["id"])["status"] == "HELD"
        assert read_booking(arena["second"]["id"])["status"] == "HELD"

        venue = read_venue(arena["venue_id"])
        assert venue["version"] == fresh_version, (
            "neither rejected confirm may advance the arena version"
        )
        assert venue["open_hold_count"] == 2


class TestWindowSufficiencyOutranksTheCrewCap:
    def test_an_insufficient_window_is_reported_ahead_of_the_crew_cap_excess(self, api):
        """PRD §2.10: "Opening a turnaround evaluates, in order: the stale-version check,
        then the booking-sequence check, then the window conflict, then window sufficiency,
        then the crew cap, then the debt freeze, then venue scoping — so a create that both
        exceeds the crew cap and hits a frozen debt ledger reports `ERR_CREW_CAP_EXCEEDED`."
        PRD §3.7: "Sufficiency is then measured inclusively: the order is accepted when
        `window_minutes` is greater than or equal to `planned_turnaround_minutes`, so a
        window exactly as long as the plan is accepted, and only a strictly shorter window is
        refused."
        PRD §3.7: "`window_start_utc` is the outgoing event's `event_end_utc` advanced by the
        arena's `min_turnaround_buffer_minutes`, the mandatory idle period the building
        insists on before crews go onto the floor."

        Design: Difficulty/priority_pair_validation_conflict/insufficient_turnaround_window_at_priority_74_outranks_crew_cap_excess_at_priority_80
        """
        arena = _three_bookings_for_two_windows()
        response = api.create_changeover_order(
            {
                "from_booking_id": arena["outgoing"]["id"],
                "to_booking_id": arena["early"]["id"],
                "crew_headcount": 200,
                "expected_venue_version": arena["observed_version"],
            },
            SUPERVISOR,
        )
        validate_error(
            response, ApiErrorId.ERR_TURNAROUND_WINDOW_INSUFFICIENT.value, 422
        )

        rows, meta = validate_paginated(
            api.list_changeover_orders(SUPERVISOR, {"venue_id": arena["venue_id"]})
        )
        assert meta["total_count"] == 0
        assert rows == []

    def test_a_roomy_window_then_surfaces_the_crew_cap_excess(self, api):
        """PRD §3.7: "Then `crew_headcount` must not exceed the arena's
        `crew_headcount_cap`, otherwise `ERR_CREW_CAP_EXCEEDED`."
        PRD §2.10: "Opening a turnaround evaluates, in order: the stale-version check, then
        the booking-sequence check, then the window conflict, then window sufficiency, then
        the crew cap, then the debt freeze, then venue scoping — so a create that both
        exceeds the crew cap and hits a frozen debt ledger reports `ERR_CREW_CAP_EXCEEDED`."
        PRD §2.6: "Recording progress on a turnaround, reworking a dimension, reserving or
        cancelling a dock window, issuing or returning equipment, creating, closing or
        cancelling a labor call, and equipment maintenance actions do not increment the
        arena's `version`."

        Design: Difficulty/priority_pair_validation_conflict/insufficient_turnaround_window_at_priority_74_outranks_crew_cap_excess_at_priority_80
        """
        arena = _three_bookings_for_two_windows()
        response = api.create_changeover_order(
            {
                "from_booking_id": arena["outgoing"]["id"],
                "to_booking_id": arena["late"]["id"],
                "crew_headcount": 200,
                "expected_venue_version": arena["observed_version"],
            },
            SUPERVISOR,
        )
        validate_error(response, ApiErrorId.ERR_CREW_CAP_EXCEEDED.value, 422)

        _rows, meta = validate_paginated(
            api.list_changeover_orders(SUPERVISOR, {"venue_id": arena["venue_id"]})
        )
        assert meta["total_count"] == 0

        venue = read_venue(arena["venue_id"])
        assert venue["version"] == arena["observed_version"], (
            "a refused turnaround create leaves the arena version alone"
        )
        assert venue["changeover_debt_minutes"] == 0


class TestTenantScopeOutranksTheHoldQuota:
    def test_a_rival_representative_is_refused_before_the_quota_is_consulted(self, api):
        """PRD §2.10: "**Anchor-tenant ownership scope.** `ERR_TENANT_SCOPE_VIOLATION`, on
        exactly four operations: creating a booking, placing a hold on a booking, opening a
        hold challenge, and withdrawing a hold challenge."
        PRD §2.10: "**Fiscal capacity, last.** `ERR_RIGGING_CAPACITY_EXCEEDED` on booking
        confirm; then `ERR_TENANT_HOLD_QUOTA_EXCEEDED` on placing a hold."
        PRD §3.3: "When the caller acts as an `AnchorTenantRep`, `X-User-ID` must equal the
        booking's `tenant_id` or the request is `ERR_TENANT_SCOPE_VIOLATION`."

        Design: Difficulty/priority_pair_validation_conflict/tenant_scope_violation_at_priority_22_outranks_hold_quota_exhaustion_at_priority_102
        """
        arena = _tenant_at_its_hold_ceiling()
        response = api.hold_event_booking(
            arena["pending"]["id"],
            make_anchor_tenant_rep_headers(arena["rival"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_TENANT_SCOPE_VIOLATION.value, 403)

        pending = read_booking(arena["pending"]["id"])
        assert pending["status"] == "DRAFT"
        assert pending["hold_placed_at"] is None
        assert pending["hold_tier"] is None

    def test_the_owning_representative_then_meets_the_exhausted_hold_quota(self, api):
        """PRD §3.3: "It requires the booking to be `DRAFT` — any other state is
        `ERR_INVALID_BOOKING_STATE` — and, for an anchor booking, that the tenant's
        `holds_consumed` is strictly below its `guaranteed_holds_per_season`, otherwise
        `ERR_TENANT_HOLD_QUOTA_EXCEEDED`."
        PRD §2.11: "Anchor tenants carry two derived counters in the same spirit:
        `holds_consumed` is the number of bookings naming that tenant whose `status` is
        `HELD`, `CHALLENGED` or `CONFIRMED`, and `challenge_credits` is the tenant's
        remaining challenge budget."
        PRD §2.11: "`open_hold_count` is the number of bookings on the arena whose `status`
        is either `HELD` or `CHALLENGED`."

        Design: Difficulty/priority_pair_validation_conflict/tenant_scope_violation_at_priority_22_outranks_hold_quota_exhaustion_at_priority_102
        """
        arena = _tenant_at_its_hold_ceiling()
        response = api.hold_event_booking(
            arena["pending"]["id"],
            make_anchor_tenant_rep_headers(arena["owner"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_TENANT_HOLD_QUOTA_EXCEEDED.value, 422)

        assert read_booking(arena["pending"]["id"])["status"] == "DRAFT"
        assert read_tenant(arena["venue_id"], arena["owner"]["id"])["holds_consumed"] == 1
        assert read_tenant(arena["venue_id"], arena["rival"]["id"])["holds_consumed"] == 0
        assert read_venue(arena["venue_id"])["open_hold_count"] == 1
