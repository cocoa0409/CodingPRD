"""The arena row as a concurrency anchor, and the promise that a write's whole
blast radius is already settled by the time its own response comes back."""
from test_helpers import (
    ApiErrorId,
    CLOCK_STARTUP_UTC,
    draft_booking,
    make_anchor_tenant_rep_headers,
    place_hold,
    read_booking,
    read_tenant,
    read_venue,
    register_tenant,
    reserve_dock,
    setup_arena,
    setup_ice_to_concert_bookings,
    validate_error,
    validate_paginated,
    validate_success,
    venue_version,
    TEST_USERS,
)

MANAGER = TEST_USERS["booking_manager_headers"]
SUPERVISOR = TEST_USERS["changeover_supervisor_headers"]


class TestOptimisticConcurrencyOnOpeningATurnaround:
    def test_a_version_read_before_an_unrelated_hold_is_refused_and_the_re_read_succeeds(
        self, api
    ):
        """PRD §2.6: "In both cases the request body must carry `expected_venue_version` as a
        required, non-optional integer field holding the `version` the client last observed on the
        arena."
        PRD §2.6: "If that value does not equal the arena's current `version` at the moment the write
        is evaluated, the request is rejected with `ERR_STALE_VENUE_VERSION` and HTTP status 412."
        PRD §2.6: "`POST /changeover-orders` requires `expected_venue_version`. Opening a turnaround
        claims an exclusive window on the arena floor and a slice of `crew_headcount_cap`, and its
        frozen plan is derived from `ice_deck_status` and `changeover_debt_minutes`. A create
        carrying an `expected_venue_version` that no longer matches the arena's `version` derived its
        plan from a superseded arena snapshot and is refused."
        PRD §2.6: "Placing a hold, confirming a booking, releasing a booking, driving a booking into
        `DISPLACED`, opening a hold challenge, withdrawing one, ruling on one, installing an ice
        sheet, any accepted ice sheet transition driven through the transition capability, opening a
        changeover order and signing one off all increment the arena's `version` by exactly 1."
        PRD §3.7: "`planned_turnaround_minutes` is the forward-looking plan, frozen once at creation
        and never recomputed for the life of the order."

        Design: Corner/cross_cutting_complexity_layers/changeover_order_create_rejects_a_stale_expected_venue_version_and_accepts_the_fresh_one
        """
        arena = setup_ice_to_concert_bookings(
            setup_arena(profiles=("ICE", "CONCERT"), clock=CLOCK_STARTUP_UTC),
            confirm_incoming=True,
        )
        venue_id = arena["venue_id"]
        from_booking_id = arena["from_booking"]["id"]
        to_booking_id = arena["to_booking"]["id"]
        stale_version = venue_version(venue_id)

        unrelated = draft_booking(
            venue_id, arena["profiles"]["ICE"]["id"], "Hockey Sep 20",
            "2026-09-20T00:00:00Z", "2026-09-20T03:00:00Z",
            expected_attendance=15_000, rigging_load_kg=3_000,
            promoter_name="Lakeside Hockey Club",
        )
        place_hold(unrelated["id"])

        body = {
            "venue_id": venue_id,
            "from_booking_id": from_booking_id,
            "to_booking_id": to_booking_id,
            "crew_headcount": 40,
        }
        refused = api.create_changeover_order(
            dict(body, expected_venue_version=stale_version), SUPERVISOR
        )
        validate_error(refused, ApiErrorId.ERR_STALE_VENUE_VERSION.value, 412)

        fresh_version = venue_version(venue_id)
        assert fresh_version == stale_version + 1, (
            "the unrelated hold contributed the single bump"
        )
        _orders, meta = validate_paginated(
            api.list_changeover_orders(SUPERVISOR, {"venue_id": venue_id})
        )
        assert meta["total_count"] == 0, "a refused create writes no row"

        accepted = validate_success(
            api.create_changeover_order(
                dict(body, expected_venue_version=fresh_version), SUPERVISOR
            ),
            201,
        )
        assert accepted["status"] == "PLANNED"
        assert accepted["planned_turnaround_minutes"] == 708
        assert accepted["window_minutes"] == 735
        assert venue_version(venue_id) == fresh_version + 1
        assert venue_version(venue_id) == stale_version + 2, (
            "the stale value is now two behind and can never be accepted"
        )


class TestReleaseEffectsAreSettledInTheSameResponse:
    def test_the_release_response_and_the_next_reads_already_carry_the_whole_cascade(
        self, api
    ):
        """PRD §3.5: "A `BookingManager` may hand a date back from any of the four live states,
        supplying a `reason` that is recorded verbatim as the booking's `release_reason`."
        PRD §3.5: "Releasing a `HELD` booking moves it `HELD → RELEASED` and runs the dependent
        cascade in full — reserved dock windows to `RELEASED` with `release_reason` of
        `BOOKING_GONE`, non-terminal changeover orders on either side to `ABANDONED`, and from there
        the equipment returns and labor cancellations of §2.11."
        PRD §2.11: "Every entity a cascade touches has its `updated_at` refreshed and its own
        `version` incremented by 1, exactly as if it had been mutated directly."
        PRD §2.11: "Derived counters on the arena and on affected anchor tenants are recomputed as
        part of the same atomic operation, so a client reading any of them immediately after a
        cascading write observes the settled values rather than an intermediate state."
        PRD §2.11: "`open_hold_count` is the number of bookings on the arena whose `status` is either
        `HELD` or `CHALLENGED`."
        PRD §2.11: "Anchor tenants carry two derived counters in the same spirit: `holds_consumed` is
        the number of bookings naming that tenant whose `status` is `HELD`, `CHALLENGED` or
        `CONFIRMED`, and `challenge_credits` is the tenant's remaining challenge budget."

        Design: Corner/consistency_model/hold_and_release_effects_are_visible_in_the_same_response_and_in_the_next_read
        """
        arena = setup_arena(profiles=("ICE",), clock=CLOCK_STARTUP_UTC)
        venue_id = arena["venue_id"]
        tenant = register_tenant(venue_id, "Lakeside Hockey Club", "TIER_2", 5)
        rep = make_anchor_tenant_rep_headers(tenant["id"])

        draft = draft_booking(
            venue_id, arena["profiles"]["ICE"]["id"], "Anchor game Sep 10",
            "2026-09-10T00:00:00Z", "2026-09-10T03:00:00Z",
            expected_attendance=15_000, rigging_load_kg=3_000,
            tenant_id=tenant["id"], headers=rep,
        )
        held = validate_success(api.hold_event_booking(draft["id"], rep), 200)
        assert held["status"] == "HELD"
        assert held["hold_expires_at"] == "2026-08-08T00:00:00.000Z", (
            "the TIER_2 window runs a hundred and sixty-eight hours"
        )
        reservation = reserve_dock(
            held["id"], 1, "LOAD_IN",
            "2026-09-09T12:00:00Z", "2026-09-09T18:00:00Z",
            truck_count=6, headers=SUPERVISOR,
        )
        assert reservation["status"] == "RESERVED"
        assert read_tenant(venue_id, tenant["id"])["holds_consumed"] == 1
        version_before = venue_version(venue_id)

        released = validate_success(
            api.release_event_booking(
                held["id"], {"reason": "TENANT_WITHDREW"}, MANAGER
            ),
            200,
        )
        assert released["status"] == "RELEASED"
        assert released["release_reason"] == "TENANT_WITHDREW", (
            "the caller's reason is recorded verbatim in the response that performs it"
        )

        assert read_booking(held["id"])["status"] == "RELEASED"

        rows, meta = validate_paginated(
            api.list_dock_slot_reservations(held["id"], MANAGER)
        )
        assert meta["total_count"] == 1
        cascaded = rows[0]
        assert cascaded["id"] == reservation["id"]
        assert cascaded["status"] == "RELEASED"
        assert cascaded["release_reason"] == "BOOKING_GONE", (
            "the dock cascade is visible in the very next read"
        )

        venue = read_venue(venue_id)
        assert venue["open_hold_count"] == 0
        assert venue["version"] == version_before + 1

        assert read_tenant(venue_id, tenant["id"])["holds_consumed"] == 0
        assert read_tenant(venue_id, tenant["id"])["challenge_credits"] == 2, (
            "a voluntary release spends none of the two granted credits"
        )
