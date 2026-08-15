"""Maintenance responsibility assignments and work-order coordination: windows,
flagging, responsibility matching, revocation fallback (PRD §2.5, §3.7)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_assignment,
    create_crossing,
    create_diagnostic_review_payload,
    create_locality,
    create_maintenance_assignment_payload,
    create_maintenance_work_order_payload,
    create_team,
    create_work_order,
    get_success_data,
    make_local_authority_headers,
    setup_locality_and_crossing,
    setup_railroad_work_order,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
RAILROAD = TEST_USERS["railroad_headers"]


class TestWorkWindowOverlap:
    def test_half_open_overlap_and_adjacency(self, api, admin_headers):
        """PRD §3.7: "windows on the same crossing must not overlap under
        half-open semantics — two orders that merely touch, one ending exactly
        when the other begins, are allowed, while a true overlap with a
        non-terminal order on the crossing is rejected with
        `ERR_WORK_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/work_window_half_open_overlap
        """
        locality, crossing = setup_locality_and_crossing(
            {"dot_crossing_number": "DOT-800001"}
        )
        create_assignment(crossing["id"], category="SIGNAL", responsible_party="RAILROAD")

        wo1 = create_work_order(
            crossing["id"],
            RAILROAD,
            window_start="2026-09-01T08:00:00Z",
            window_end="2026-09-01T12:00:00Z",
            fouls_track=False,
        )
        assert wo1["status"] == "PLANNED"

        # Adjacent at 12:00 — allowed under half-open [start, end) semantics.
        wo2 = create_work_order(
            crossing["id"],
            RAILROAD,
            window_start="2026-09-01T12:00:00Z",
            window_end="2026-09-01T14:00:00Z",
            fouls_track=False,
        )
        assert wo2["status"] == "PLANNED"

        # [11:00, 13:00) truly overlaps both existing windows.
        resp = api.create_maintenance_work_order(
            create_maintenance_work_order_payload(
                crossing_id=crossing["id"],
                window_start="2026-09-01T11:00:00Z",
                window_end="2026-09-01T13:00:00Z",
                fouls_track=False,
            ),
            RAILROAD,
        )
        validate_error(resp, ApiErrorId.ERR_WORK_WINDOW_OVERLAP, expected_status=409)

    def test_fully_contained_window_rejected(self, api, admin_headers):
        """PRD §3.7: "windows on the same crossing must not overlap under
        half-open semantics — two orders that merely touch, one ending exactly
        when the other begins, are allowed, while a true overlap with a
        non-terminal order on the crossing is rejected with
        `ERR_WORK_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/work_window_half_open_overlap
        """
        locality, crossing = setup_locality_and_crossing(
            {"dot_crossing_number": "DOT-800002"}
        )
        create_assignment(crossing["id"], category="SIGNAL", responsible_party="RAILROAD")
        create_work_order(
            crossing["id"],
            RAILROAD,
            window_start="2026-09-01T08:00:00Z",
            window_end="2026-09-01T12:00:00Z",
            fouls_track=False,
        )
        resp = api.create_maintenance_work_order(
            create_maintenance_work_order_payload(
                crossing_id=crossing["id"],
                window_start="2026-09-01T09:00:00Z",
                window_end="2026-09-01T10:00:00Z",
                fouls_track=False,
            ),
            RAILROAD,
        )
        validate_error(resp, ApiErrorId.ERR_WORK_WINDOW_OVERLAP, expected_status=409)


class TestTeamScheduleBuffer:
    def test_reviews_within_two_days_rejected_exactly_two_allowed(
        self, api, admin_headers
    ):
        """PRD §3.2: "the team must not already have a non-`CANCELLED` review
        whose `scheduled_date` is less than 2 days from the requested date — the
        office requires at least a two-day buffer between a team's engagements,
        and a tighter spacing is rejected with `ERR_TEAM_SCHEDULE_BUFFER`."

        Design: Difficulty/resource_temporal_overlap/team_review_date_buffer
        """
        locality = create_locality(locality_name="Buffer City")
        team = create_team(team_name="Team Delta")
        crossing = create_crossing(locality["id"], dot_crossing_number="DOT-800101")

        r1 = get_success_data(
            api.create_diagnostic_review(
                create_diagnostic_review_payload(
                    crossing_id=crossing["id"],
                    team_id=team["id"],
                    scheduled_date="2026-09-10",
                ),
                ADMIN,
            )
        )
        assert r1["status"] == "SCHEDULED"

        # Exactly 2 days later — the buffer is satisfied at equality.
        r2 = get_success_data(
            api.create_diagnostic_review(
                create_diagnostic_review_payload(
                    crossing_id=crossing["id"],
                    team_id=team["id"],
                    scheduled_date="2026-09-12",
                ),
                ADMIN,
            )
        )
        assert r2["status"] == "SCHEDULED"

        # 1 day from both existing reviews — a tighter spacing is rejected.
        resp = api.create_diagnostic_review(
            create_diagnostic_review_payload(
                crossing_id=crossing["id"],
                team_id=team["id"],
                scheduled_date="2026-09-11",
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_TEAM_SCHEDULE_BUFFER, expected_status=409)

    def test_buffer_applies_to_dates_before_an_existing_review(
        self, api, admin_headers
    ):
        """PRD §3.2: "the team must not already have a non-`CANCELLED` review
        whose `scheduled_date` is less than 2 days from the requested date — the
        office requires at least a two-day buffer between a team's engagements,
        and a tighter spacing is rejected with `ERR_TEAM_SCHEDULE_BUFFER`."

        Design: Difficulty/resource_temporal_overlap/team_review_date_buffer
        """
        locality = create_locality(locality_name="Buffer City 2")
        team = create_team(team_name="Team Delta 2")
        crossing = create_crossing(locality["id"], dot_crossing_number="DOT-800102")
        get_success_data(
            api.create_diagnostic_review(
                create_diagnostic_review_payload(
                    crossing_id=crossing["id"],
                    team_id=team["id"],
                    scheduled_date="2026-09-10",
                ),
                ADMIN,
            )
        )
        # One day BEFORE the existing review is equally inside the buffer.
        resp = api.create_diagnostic_review(
            create_diagnostic_review_payload(
                crossing_id=crossing["id"],
                team_id=team["id"],
                scheduled_date="2026-09-09",
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_TEAM_SCHEDULE_BUFFER, expected_status=409)


class TestSafetyBeatsTemporalPriority:
    def test_missing_flagging_plan_beats_window_overlap(self, api, railroad_headers):
        """PRD §2.9: "The ordering is observable. Because safety (step 6) outranks
        temporal rules (step 9), a work order that both lacks a required flagging
        plan and overlaps another window is rejected with
        `ERR_FLAGGING_PLAN_REQUIRED`, not `ERR_WORK_WINDOW_OVERLAP`."

        Design: Difficulty/priority_pair_validation_conflict/work_order_safety_beats_temporal
        """
        locality, crossing, _asg, _wo = setup_railroad_work_order(
            {"dot_crossing_number": "DOT-500101"},
            {
                "window_start": "2026-09-01T08:00:00Z",
                "window_end": "2026-09-01T12:00:00Z",
                "fouls_track": False,
            },
        )
        # Both violations: fouls_track true without flagging_vendor (safety) AND
        # [11:00,13:00) overlaps the existing [08:00,12:00) window (temporal).
        resp = api.create_maintenance_work_order(
            create_maintenance_work_order_payload(
                crossing_id=crossing["id"],
                window_start="2026-09-01T11:00:00Z",
                window_end="2026-09-01T13:00:00Z",
                fouls_track=True,
            ),
            railroad_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FLAGGING_PLAN_REQUIRED, expected_status=422)

    def test_fouls_track_without_flagging_vendor_rejected_on_clean_window(
        self, api, railroad_headers
    ):
        """PRD §3.7: "Work that fouls the track is flagged at creation:
        `fouls_track` set to `true` requires a `flagging_vendor` reference naming
        the railroad flagging provider, and its absence is rejected with
        `ERR_FLAGGING_PLAN_REQUIRED`."

        Design: Difficulty/priority_pair_validation_conflict/work_order_safety_beats_temporal
        """
        locality, crossing = setup_locality_and_crossing(
            {"dot_crossing_number": "DOT-500102"}
        )
        create_assignment(crossing["id"], category="SIGNAL", responsible_party="RAILROAD")
        resp = api.create_maintenance_work_order(
            create_maintenance_work_order_payload(
                crossing_id=crossing["id"],
                window_start="2026-09-02T08:00:00Z",
                window_end="2026-09-02T12:00:00Z",
                fouls_track=True,
            ),
            railroad_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FLAGGING_PLAN_REQUIRED, expected_status=422)


class TestBeginWorkGates:
    def test_fouling_work_requires_flagging_confirmation_first(
        self, api, railroad_headers
    ):
        """PRD §3.7: "when `fouls_track` is true the order must have reached
        `FLAGGING_CONFIRMED` first (else `ERR_FLAGGING_NOT_CONFIRMED`)".
        PRD §3.7: "Railroad flagging is confirmed before fouling work begins: a
        `RailroadMaintainer` whose `X-User-ID` equals the crossing's
        `railroad_code` — flagging is always provided by the operating railroad —
        moves the order `PLANNED` → `FLAGGING_CONFIRMED`".

        Design: Corner/state_machines/work_order_fouling_requires_flagging_confirmation
        """
        locality, crossing, _asg, wo = setup_railroad_work_order(
            {"dot_crossing_number": "DOT-020041"},
            {
                # The window contains the startup logical clock 2026-08-01T00:00:00Z.
                "window_start": "2026-07-31T00:00:00Z",
                "window_end": "2026-08-02T00:00:00Z",
                "fouls_track": True,
                "flagging_vendor": "BNSF-flagging-desk",
            },
        )
        # IN_WORK straight from PLANNED on a fouling order: rejected.
        resp = api.transition_maintenance_work_order(
            wo["id"], {"to_status": "IN_WORK"}, railroad_headers
        )
        validate_error(resp, ApiErrorId.ERR_FLAGGING_NOT_CONFIRMED, expected_status=409)

        confirmed = get_success_data(
            api.transition_maintenance_work_order(
                wo["id"], {"to_status": "FLAGGING_CONFIRMED"}, railroad_headers
            )
        )
        assert confirmed["status"] == "FLAGGING_CONFIRMED"

        in_work = get_success_data(
            api.transition_maintenance_work_order(
                wo["id"], {"to_status": "IN_WORK"}, railroad_headers
            )
        )
        assert in_work["status"] == "IN_WORK"

    def test_begin_work_outside_window_rejected_until_clock_advances(
        self, api, admin_headers, railroad_headers
    ):
        """PRD §3.7: "the logical clock must fall within the half-open window —
        at or after `window_start` and before `window_end` (else
        `ERR_OUTSIDE_WORK_WINDOW`)". PRD §2.5: "At server startup the logical
        clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to
        wall-clock time thereafter. The clock moves only when a
        `ProgramAdministrator` invokes the test-driving clock capability with a
        `to_iso8601` instant".

        Design: Corner/state_machines/begin_work_outside_window_rejected
        """
        locality, crossing, _asg, wo = setup_railroad_work_order(
            {"dot_crossing_number": "DOT-020051"},
            {
                "window_start": "2026-09-01T08:00:00Z",
                "window_end": "2026-09-01T12:00:00Z",
                "fouls_track": False,
            },
        )
        # Default clock 2026-08-01 is outside the September window.
        resp = api.transition_maintenance_work_order(
            wo["id"], {"to_status": "IN_WORK"}, railroad_headers
        )
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_WORK_WINDOW, expected_status=409)

        get_success_data(api.set_clock("2026-09-01T09:00:00Z", admin_headers))
        in_work = get_success_data(
            api.transition_maintenance_work_order(
                wo["id"], {"to_status": "IN_WORK"}, railroad_headers
            )
        )
        assert in_work["status"] == "IN_WORK"


class TestAssignmentCardinality:
    def test_create_supersedes_and_revoke_reinstates_fallback(
        self, api, admin_headers
    ):
        """PRD §3.7: "Exactly one assignment per crossing-and-category pair is
        `ACTIVE` at all times: creating a new assignment for a pair automatically
        moves the pair's previous `ACTIVE` row to `SUPERSEDED`." and "the
        superseded row with the most recent `updated_at` (ties broken by the most
        recent `created_at`) is reinstated to `ACTIVE`, so the pair again has
        exactly one active row and the revoked row ends `REVOKED`."

        Design: Difficulty/compensating_invariant/assignment_transfer_revoke_restores_cardinality
        """
        locality, crossing = setup_locality_and_crossing(
            {"dot_crossing_number": "DOT-900101"}
        )
        a1 = create_assignment(
            crossing["id"],
            category="SIGNAL",
            responsible_party="RAILROAD",
            effective_from="2026-08-01",
        )
        assert a1["status"] == "ACTIVE"

        a2 = create_assignment(
            crossing["id"],
            category="SIGNAL",
            responsible_party="ROAD_AUTHORITY",
            effective_from="2026-09-01",
        )
        assert a2["status"] == "ACTIVE"
        a1_mid = get_success_data(api.get_maintenance_assignment(a1["id"], ADMIN))
        assert a1_mid["status"] == "SUPERSEDED"

        a2_final = get_success_data(api.revoke_maintenance_assignment(a2["id"], ADMIN))
        assert a2_final["status"] == "REVOKED"

        rows, meta = validate_paginated(
            api.list_maintenance_assignments(
                ADMIN,
                params={
                    "crossing_id": crossing["id"],
                    "category": "SIGNAL",
                    "status": "ACTIVE",
                },
            )
        )
        assert meta["total_count"] == 1, "exactly one ACTIVE row per (crossing, category)"
        assert rows[0]["id"] == a1["id"], "the fallback selector reinstated the original"

    def test_transfer_leaves_exactly_one_active_row_per_pair(self, api, admin_headers):
        """PRD §3.7: "Exactly one assignment per crossing-and-category pair is
        `ACTIVE` at all times: creating a new assignment for a pair automatically
        moves the pair's previous `ACTIVE` row to `SUPERSEDED`."

        Design: Difficulty/compensating_invariant/assignment_transfer_revoke_restores_cardinality
        """
        locality, crossing = setup_locality_and_crossing(
            {"dot_crossing_number": "DOT-900102"}
        )
        a1 = create_assignment(
            crossing["id"],
            category="SURFACE",
            responsible_party="RAILROAD",
            effective_from="2026-08-01",
        )
        a2 = create_assignment(
            crossing["id"],
            category="SURFACE",
            responsible_party="ROAD_AUTHORITY",
            effective_from="2026-09-01",
        )
        rows, meta = validate_paginated(
            api.list_maintenance_assignments(
                ADMIN,
                params={
                    "crossing_id": crossing["id"],
                    "category": "SURFACE",
                    "status": "ACTIVE",
                },
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == a2["id"]
        a1_after = get_success_data(api.get_maintenance_assignment(a1["id"], ADMIN))
        assert a1_after["status"] == "SUPERSEDED"

    def test_revoke_without_fallback_rejected(self, api, admin_headers):
        """PRD §3.7: "a `ProgramAdministrator` revoking the `ACTIVE` row requires
        at least one `SUPERSEDED` row to exist for the same pair (else
        `ERR_NO_FALLBACK_ASSIGNMENT`)".

        Design: Corner/validations/assignment_revoke_without_fallback_rejected
        """
        locality, crossing = setup_locality_and_crossing(
            {"dot_crossing_number": "DOT-040071"}
        )
        a1 = create_assignment(
            crossing["id"], category="SIGNAL", responsible_party="RAILROAD"
        )
        resp = api.revoke_maintenance_assignment(a1["id"], admin_headers)
        validate_error(resp, ApiErrorId.ERR_NO_FALLBACK_ASSIGNMENT, expected_status=409)
        after = get_success_data(api.get_maintenance_assignment(a1["id"], ADMIN))
        assert after["status"] == "ACTIVE"


class TestResponsibilityGapAndMismatch:
    def test_gap_then_mismatch_then_matching_party_succeeds(self, api, admin_headers):
        """PRD §3.7: "the server copies `responsible_party` onto the order from
        the pair's `ACTIVE` assignment — when no such assignment exists, creation
        is rejected with `ERR_RESPONSIBILITY_GAP`. The creator must match that
        responsible party: a `RAILROAD`-responsible order is created by a
        `RailroadMaintainer` whose `X-User-ID` equals the crossing's
        `railroad_code`, and a `ROAD_AUTHORITY`-responsible order by a
        `LocalAuthority` whose `X-User-ID` equals the crossing's
        `road_authority_locality_id`; a mismatch is `ERR_RESPONSIBILITY_MISMATCH`."

        Design: Corner/rbac/responsibility_gap_and_mismatch
        """
        locality, crossing = setup_locality_and_crossing(
            {"dot_crossing_number": "DOT-060041"}
        )
        loc_headers = make_local_authority_headers(locality["id"])
        wo_payload = create_maintenance_work_order_payload(
            crossing_id=crossing["id"],
            category="SURFACE",
            window_start="2026-09-05T08:00:00Z",
            window_end="2026-09-05T12:00:00Z",
            fouls_track=False,
        )
        # No assignment exists for (crossing, SURFACE).
        resp = api.create_maintenance_work_order(wo_payload, loc_headers)
        validate_error(resp, ApiErrorId.ERR_RESPONSIBILITY_GAP, expected_status=409)

        create_assignment(
            crossing["id"], category="SURFACE", responsible_party="ROAD_AUTHORITY"
        )
        # The railroad user does not match ROAD_AUTHORITY responsibility.
        resp2 = api.create_maintenance_work_order(wo_payload, RAILROAD)
        validate_error(resp2, ApiErrorId.ERR_RESPONSIBILITY_MISMATCH, expected_status=403)

        created = get_success_data(api.create_maintenance_work_order(wo_payload, loc_headers))
        assert created["status"] == "PLANNED"
        assert created["responsible_party"] == "ROAD_AUTHORITY"


class TestWorkOrderRequestShape:
    def test_window_end_not_after_start_rejected(self, api, railroad_headers):
        """PRD §3.7: "The order specifies `window_start` (inclusive) and
        `window_end` (exclusive) as ISO 8601 UTC instants, with `window_end`
        required to be after `window_start` (else `ERR_INVALID_REQUEST`)".

        Design: Corner/validations/work_order_window_inverted_rejected
        """
        locality, crossing = setup_locality_and_crossing(
            {"dot_crossing_number": "DOT-040031"}
        )
        create_assignment(crossing["id"], category="SIGNAL", responsible_party="RAILROAD")
        resp = api.create_maintenance_work_order(
            create_maintenance_work_order_payload(
                crossing_id=crossing["id"],
                window_start="2026-09-01T12:00:00Z",
                window_end="2026-09-01T08:00:00Z",
                fouls_track=False,
            ),
            railroad_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
