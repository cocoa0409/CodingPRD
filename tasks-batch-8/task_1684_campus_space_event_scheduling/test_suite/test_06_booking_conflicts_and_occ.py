"""Room occupancy conflicts (buffered half-open semantics), optimistic
concurrency on creation endpoints, and rate pinning at approval."""

from test_helpers import (
    FACILITIES_MANAGER,
    SCHEDULER,
    ApiErrorId,
    approve_event,
    create_event,
    create_run,
    create_term,
    find_invoice_for_event,
    get_event,
    get_room,
    get_run,
    get_term,
    make_org_requester_headers,
    setup_org_room,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestBufferedHalfOpenAdjacency:
    def test_event_starting_exactly_at_buffered_occupancy_end_is_allowed(self, api):
        """PRD §2.6: "Occupancy intervals are half-open — the start instant is
        included and the end instant is excluded — so two intervals conflict
        only when each begins strictly before the other ends."
        PRD §2.6: "An occupancy that ends at exactly the instant another begins
        does not conflict with it."
        PRD §2.6: "The buffer is asymmetric: it is appended after teardown only,
        never before setup."

        Design: Difficulty/resource_temporal_overlap/room_conflict_buffered_halfopen_adjacency
        """
        scn = setup_org_room(room_overrides={"capacity": 40})
        e1 = create_event(
            scn.org, scn.room["id"], title="E1", expected_attendance=10,
            start_at="2026-09-16T10:00:00Z", end_at="2026-09-16T11:00:00Z",
        )
        approve_event(e1["id"])

        # E1 occupies [10:00, 11:30) once the 30-minute turnaround buffer is
        # appended; a start at exactly 11:30 is adjacency, not overlap.
        e2 = create_event(
            scn.org, scn.room["id"], title="E2", expected_attendance=10,
            start_at="2026-09-16T11:30:00Z", end_at="2026-09-16T12:30:00Z",
        )
        approved = validate_success(api.approve_event(e2["id"], SCHEDULER), 200)
        assert approved["status"] == "APPROVED"

        # One minute earlier collides with the post-event buffer.
        response = api.create_event_reservation(
            {
                "room_id": scn.room["id"],
                "title": "E3",
                "expected_attendance": 10,
                "start_at": "2026-09-16T11:29:00Z",
                "end_at": "2026-09-16T12:00:00Z",
                "expected_room_version": get_room(scn.room["id"])["version"],
            },
            make_org_requester_headers(scn.org["id"]),
        )
        validate_error(response, ApiErrorId.ERR_ROOM_NOT_AVAILABLE)

        _, meta = validate_paginated(api.list_event_reservations(SCHEDULER))
        assert meta["total_count"] == 2, "the colliding request was not persisted"

    def test_buffered_edge_moves_with_the_rooms_buffer(self, api):
        """PRD §2.6: "An event occupies its room from `setup_minutes` before its
        `start_at` until `teardown_minutes` after its `end_at`, further extended
        by the room's `turnaround_buffer_minutes`."
        PRD §2.6: "A conflict surfaced at event creation, approval, or rebooking
        is rejected with `ERR_ROOM_NOT_AVAILABLE`."

        Design: Difficulty/resource_temporal_overlap/room_conflict_buffered_halfopen_adjacency
        """
        scn = setup_org_room(
            room_overrides={"capacity": 40, "turnaround_buffer_minutes": 45}
        )
        e1 = create_event(
            scn.org, scn.room["id"], title="E1", expected_attendance=10,
            start_at="2026-09-16T10:00:00Z", end_at="2026-09-16T11:00:00Z",
        )
        approve_event(e1["id"])

        # Occupancy is now [10:00, 11:45): adjacency sits at 11:45 exactly.
        e2 = create_event(
            scn.org, scn.room["id"], title="E2", expected_attendance=10,
            start_at="2026-09-16T11:45:00Z", end_at="2026-09-16T12:30:00Z",
        )
        approved = validate_success(api.approve_event(e2["id"], SCHEDULER), 200)
        assert approved["status"] == "APPROVED"

        # One minute before the 11:45 adjacency point collides with the
        # post-event buffer; the 31-minute span respects the 30-minute floor
        # (PRD section 3.4) so the tier-9 conflict is what surfaces.
        response = api.create_event_reservation(
            {
                "room_id": scn.room["id"],
                "title": "E3",
                "expected_attendance": 10,
                "start_at": "2026-09-16T11:44:00Z",
                "end_at": "2026-09-16T12:15:00Z",
                "expected_room_version": get_room(scn.room["id"])["version"],
            },
            make_org_requester_headers(scn.org["id"]),
        )
        validate_error(response, ApiErrorId.ERR_ROOM_NOT_AVAILABLE)


class TestOptimisticConcurrency:
    def test_stale_term_version_on_run_create_then_supersede(self, api):
        """PRD §2.8: "Creating a scheduling run requires `expected_term_version`
        carrying the client's last observed `version` of the target term window;
        if the term's current `version` has advanced beyond that observation,
        the creation is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.3: "Each term has exactly one live `DRAFT` run: creating a new
        run supersedes the prior `DRAFT`, moving it to `SUPERSEDED` and
        repointing the term's `current_draft_run_id` to the new run, and the
        term's `version` increments by one."

        Design: Corner/cross_cutting_layers/occ_stale_term_version_on_run_create
        """
        term = create_term()
        run1 = create_run(term["id"], expected_term_version=term["version"])
        assert run1["status"] == "DRAFT"

        stale = api.create_scheduling_run(
            {"term_id": term["id"], "expected_term_version": term["version"]},
            SCHEDULER,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        term_mid = get_term(term["id"])
        assert term_mid["current_draft_run_id"] == run1["id"]
        assert term_mid["version"] == term["version"] + 1

        run2 = create_run(term["id"], expected_term_version=term_mid["version"])
        assert run2["status"] == "DRAFT"
        assert get_run(run1["id"])["status"] == "SUPERSEDED"
        term_end = get_term(term["id"])
        assert term_end["current_draft_run_id"] == run2["id"]
        assert term_end["version"] == term_mid["version"] + 1

    def test_stale_room_version_on_reservation_create(self, api):
        """PRD §2.8: "Creating an event reservation requires
        `expected_room_version` carrying the client's last observed `version` of
        the target room; a mismatch with the room's current `version` is
        likewise rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_room_version_on_reservation_create
        """
        scn = setup_org_room(room_overrides={"capacity": 30})
        updated = validate_success(
            api.update_room(scn.room["id"], {"capacity": 40}, FACILITIES_MANAGER),
            200,
        )
        assert updated["version"] == scn.room["version"] + 1

        requester = make_org_requester_headers(scn.org["id"])

        def attempt(title, version):
            return api.create_event_reservation(
                {
                    "room_id": scn.room["id"],
                    "title": title,
                    "expected_attendance": 20,
                    "start_at": "2026-09-14T14:00:00Z",
                    "end_at": "2026-09-14T15:00:00Z",
                    "expected_room_version": version,
                },
                requester,
            )

        stale = attempt("Stale", scn.room["version"])
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        fresh = attempt("Fresh", updated["version"])
        assert validate_success(fresh, 201)["status"] == "REQUESTED"

        _, meta = validate_paginated(api.list_event_reservations(SCHEDULER))
        assert meta["total_count"] == 1, "only the retry persisted"


class TestRatePinning:
    def test_approval_pins_rates_against_later_room_edits(self, api):
        """PRD §2.7: "Rates are pinned onto each event at approval or rebooking
        time (§3.4), so later edits to a room's rate card never reprice an
        already-approved event."
        PRD §3.4: "`pinned_hourly_rate_cents` is the room's rate card entry for
        the requester's `org_type` and `pinned_peak_multiplier_bps` is the room's
        current multiplier, and later room edits never reprice this event."

        Design: Corner/cross_cutting_layers/rate_pin_freezes_approved_pricing_after_room_rate_edit
        """
        scn = setup_org_room()
        e1 = create_event(
            scn.org, scn.room["id"], title="E1", expected_attendance=5,
            start_at="2026-09-14T14:00:00Z", end_at="2026-09-14T16:00:00Z",
        )
        approve_event(e1["id"])

        validate_success(
            api.update_room(
                scn.room["id"], {"internal_hourly_rate_cents": 7000},
                FACILITIES_MANAGER,
            ),
            200,
        )

        e2 = create_event(
            scn.org, scn.room["id"], title="E2", expected_attendance=5,
            start_at="2026-09-15T14:00:00Z", end_at="2026-09-15T16:00:00Z",
        )
        approve_event(e2["id"])

        e1_after = get_event(e1["id"])
        assert e1_after["pinned_hourly_rate_cents"] == 5000
        inv1 = find_invoice_for_event(e1["id"])
        assert inv1["room_charge_cents"] == 10000, "two off-peak buckets at 5000"
        assert inv1["total_cents"] == 10000

        inv2 = find_invoice_for_event(e2["id"])
        assert inv2["room_charge_cents"] == 14000, "two off-peak buckets at 7000"
        assert inv2["total_cents"] == 14000
