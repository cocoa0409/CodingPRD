"""Stream scheduling, simulcast rights, and consistency scoring."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_grant,
    assert_instant_equals,
    assert_stream,
    create_channel,
    create_simulcast_grant,
    create_stream,
    create_stream_payload,
    create_verified_channel,
    end_stream,
    get_channel,
    get_success_data,
    make_creator_headers,
    set_clock,
    start_stream,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


class TestStreamSchedulingShape:
    def test_stream_create_inverted_window_rejected(self, api):
        """PRD §2.9: "**Request well-formedness.** The body must parse,
        required fields must be present, enums must be in their declared sets,
        and integer and temporal ranges must hold: a `TIMEOUT` action carries
        `duration_minutes` between 1 and 10,080 minutes (one week) inclusive
        while a `BAN` must omit it, a stream's `scheduled_end` is strictly
        after its `scheduled_start`, a grant's `window_end` is strictly after
        its `window_start`, and a deliverable's `due_at` lies within its
        deal's flight — otherwise `ERR_INVALID_REQUEST`."

        Design: Corner/entities/stream_create_inverted_window_rejected
        """
        channel = create_channel(handle="corner_inv", home_platform="TWITCH")
        resp = api.create_stream(
            channel["id"],
            create_stream_payload(title="bad",
                                  scheduled_start="2026-08-10T11:00:00Z",
                                  scheduled_end="2026-08-10T10:00:00Z"),
            make_creator_headers(channel["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        _streams, meta = validate_paginated(api.list_streams(
            channel["id"], make_creator_headers(channel["id"])))
        assert meta["total_count"] == 0, "no stream may be persisted"


class TestStreamWindowOverlap:
    def _channel_with_first_stream(self, handle):
        channel = create_channel(handle=handle, home_platform="TWITCH")
        set_clock("2026-08-01T00:00:00Z")
        first = create_stream(channel["id"], title="S1",
                              scheduled_start="2026-08-10T10:00:00Z",
                              scheduled_end="2026-08-10T11:00:00Z")
        return channel, first

    def test_stream_schedule_adjacent_window_allowed(self, api):
        """PRD §3.8: "Scheduling is exclusive within the channel: no other
        stream of the channel in `SCHEDULED` or `LIVE` status may have a
        half-open window intersecting the new one, though adjacency is
        expressly allowed — a new stream may begin at the exact instant a
        sibling ends. A violation is rejected with
        `ERR_STREAM_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/stream_schedule_half_open_adjacency
        """
        channel, first = self._channel_with_first_stream("ov_strm")
        adjacent = validate_success(api.create_stream(
            channel["id"],
            create_stream_payload(title="S2",
                                  scheduled_start="2026-08-10T11:00:00Z",
                                  scheduled_end="2026-08-10T12:00:00Z"),
            make_creator_headers(channel["id"])), 201)
        assert_stream(adjacent)
        assert adjacent["stream_status"] == "SCHEDULED", (
            "start == sibling end is adjacency, allowed under half-open "
            "semantics")

    def test_stream_schedule_proper_intersection_rejected(self, api):
        """PRD §3.8: "Scheduling is exclusive within the channel: no other
        stream of the channel in `SCHEDULED` or `LIVE` status may have a
        half-open window intersecting the new one, though adjacency is
        expressly allowed — a new stream may begin at the exact instant a
        sibling ends. A violation is rejected with
        `ERR_STREAM_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/stream_schedule_half_open_adjacency
        """
        channel, _first = self._channel_with_first_stream("ov_strm2")
        create_stream(channel["id"], title="S2",
                      scheduled_start="2026-08-10T11:00:00Z",
                      scheduled_end="2026-08-10T12:00:00Z")

        overlap = api.create_stream(
            channel["id"],
            create_stream_payload(title="S3",
                                  scheduled_start="2026-08-10T10:30:00Z",
                                  scheduled_end="2026-08-10T11:30:00Z"),
            make_creator_headers(channel["id"]))
        validate_error(overlap, ApiErrorId.ERR_STREAM_WINDOW_CONFLICT)


class TestSimulcastGrants:
    def test_simulcast_grant_deny_terminal_lockdown(self, api):
        """PRD §3.8: "Denial moves a `REQUESTED` grant to the terminal
        `DENIED`; revocation moves an `APPROVED` grant to the terminal
        `REVOKED`; and ops step 4 expires an `APPROVED` grant whose
        `window_end` has been reached or passed, moving it to `EXPIRED`."
        PRD §2.9: "**State admissibility.** The target entity must be in a
        state that admits the requested transition — wrong-from-state,
        terminal lockdown, and duplicate or repeat triggers all fail here with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/simulcast_grant_deny_terminal_lockdown
        """
        channel = create_channel(handle="sm_deny", home_platform="YOUTUBE")
        grant = create_simulcast_grant(
            channel["id"], platform="KICK",
            window_start="2026-08-10T00:00:00Z",
            window_end="2026-08-12T00:00:00Z")
        denied = get_success_data(api.transition_simulcast_grant(
            grant["id"], {"action": "DENY"}, ADMIN))
        assert denied["grant_status"] == "DENIED"

        resp = api.transition_simulcast_grant(grant["id"], {"action": "APPROVE"},
                                              ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        grants = get_success_data(api.list_simulcast_grants(
            channel["id"], make_creator_headers(channel["id"])))
        assert [g for g in grants
                if g["id"] == grant["id"]][0]["grant_status"] == "DENIED"

    def _channel_with_approved_grant_a(self, handle):
        """STANDARD channel with grant A (KICK, 2026-08-10..2026-08-12)
        APPROVED."""
        channel, _form = create_verified_channel(handle,
                                                 home_platform="YOUTUBE")
        set_clock("2026-08-01T00:00:00Z")
        grant_a = create_simulcast_grant(
            channel["id"], platform="KICK",
            window_start="2026-08-10T00:00:00Z",
            window_end="2026-08-12T00:00:00Z")
        approve_grant(grant_a["id"])
        return channel, grant_a

    def test_simulcast_buffer_exactly_24h_allowed(self, api):
        """PRD §3.8: "Approval belongs to a `PlatformAdmin` and is guarded
        twice: the channel's posture must not be `SUSPENDED`
        (`ERR_CHANNEL_SUSPENDED`), and the **buffer rule** must hold — for
        every other `APPROVED` grant on the same channel and platform, the two
        windows must be separated by at least twenty-four hours in both
        directions, meaning either the new `window_start` falls at least
        twenty-four hours after the other's `window_end`, or the other's
        `window_start` falls at least twenty-four hours after the new
        `window_end`; a violation is rejected with
        `ERR_SIMULCAST_BUFFER_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/simulcast_approval_24h_buffer
        """
        channel, _grant_a = self._channel_with_approved_grant_a("ov_sim")
        grant_b = create_simulcast_grant(
            channel["id"], platform="KICK",
            window_start="2026-08-13T00:00:00Z",
            window_end="2026-08-14T00:00:00Z")

        approved = validate_success(api.transition_simulcast_grant(
            grant_b["id"], {"action": "APPROVE"}, ADMIN), 200)
        assert approved["grant_status"] == "APPROVED", (
            "window_start 2026-08-13 is exactly 24h after the other's "
            "window_end 2026-08-12 — 'at least' is inclusive")

    def test_simulcast_buffer_12h_gap_rejected(self, api):
        """PRD §3.8: "Approval belongs to a `PlatformAdmin` and is guarded
        twice: the channel's posture must not be `SUSPENDED`
        (`ERR_CHANNEL_SUSPENDED`), and the **buffer rule** must hold — for
        every other `APPROVED` grant on the same channel and platform, the two
        windows must be separated by at least twenty-four hours in both
        directions, meaning either the new `window_start` falls at least
        twenty-four hours after the other's `window_end`, or the other's
        `window_start` falls at least twenty-four hours after the new
        `window_end`; a violation is rejected with
        `ERR_SIMULCAST_BUFFER_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/simulcast_approval_24h_buffer
        """
        channel, _grant_a = self._channel_with_approved_grant_a("ov_sim2")
        grant_b = create_simulcast_grant(
            channel["id"], platform="KICK",
            window_start="2026-08-13T00:00:00Z",
            window_end="2026-08-14T00:00:00Z")
        approve_grant(grant_b["id"])
        grant_c = create_simulcast_grant(
            channel["id"], platform="KICK",
            window_start="2026-08-13T12:00:00Z",
            window_end="2026-08-15T12:00:00Z")

        resp = api.transition_simulcast_grant(grant_c["id"],
                                              {"action": "APPROVE"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_SIMULCAST_BUFFER_CONFLICT)

        grants = get_success_data(api.list_simulcast_grants(
            channel["id"], make_creator_headers(channel["id"])))
        assert [g for g in grants
                if g["id"] == grant_c["id"]][0]["grant_status"] == "REQUESTED", (
                    "the 12h gap to the newly APPROVED grant B violates the "
                    "24h buffer in both directions")


class TestSimulcastStartCoverage:
    def _simulcast_scenario(self, handle):
        """STANDARD channel; KICK grant (2026-08-01..2026-08-31) REQUESTED;
        simulcast stream scheduled 2026-08-10 10:00-11:00; clock at the
        scheduled start."""
        channel, _form = create_verified_channel(handle)
        set_clock("2026-08-01T00:00:00Z")
        grant = create_simulcast_grant(channel["id"], platform="KICK")
        stream = create_stream(channel["id"], title="Sim",
                               scheduled_start="2026-08-10T10:00:00Z",
                               scheduled_end="2026-08-10T11:00:00Z",
                               simulcast=True)
        set_clock("2026-08-10T10:00:00Z")
        return channel, grant, stream

    def test_simulcast_start_without_approved_grant_rejected(self, api):
        """PRD §3.8: "A simulcast start additionally requires an `APPROVED`
        simulcast grant for the channel whose closed window fully covers the
        scheduled window from `scheduled_start` through `scheduled_end`;
        without one the start is rejected with
        `ERR_SIMULCAST_GRANT_MISSING`."

        Design: Difficulty/cross_entity_state_dependency/simulcast_start_requires_covering_grant
        """
        channel, _grant, stream = self._simulcast_scenario("ce_sim")

        resp = api.transition_stream(stream["id"], {"action": "START"},
                                     make_creator_headers(channel["id"]))
        validate_error(resp, ApiErrorId.ERR_SIMULCAST_GRANT_MISSING)

        current = get_success_data(api.get_stream(
            stream["id"], make_creator_headers(channel["id"])))
        assert current["stream_status"] == "SCHEDULED", (
            "a merely REQUESTED grant does not cover the start")

    def test_simulcast_start_succeeds_with_covering_grant(self, api):
        """PRD §3.8: "A simulcast start additionally requires an `APPROVED`
        simulcast grant for the channel whose closed window fully covers the
        scheduled window from `scheduled_start` through `scheduled_end`;
        without one the start is rejected with
        `ERR_SIMULCAST_GRANT_MISSING`."
        PRD §3.8: "Starting stamps `actual_start` and computes
        `punctuality_minutes_late` — null until then — as the whole minutes by
        which `actual_start` followed `scheduled_start`, or zero when the
        stream started on time or early."

        Design: Difficulty/cross_entity_state_dependency/simulcast_start_requires_covering_grant
        """
        channel, grant, stream = self._simulcast_scenario("ce_sim2")
        approve_grant(grant["id"])

        started = validate_success(api.transition_stream(
            stream["id"], {"action": "START"},
            make_creator_headers(channel["id"])), 200)
        assert started["stream_status"] == "LIVE"
        assert_instant_equals(started["actual_start"], "2026-08-10T10:00:00Z",
                              label="actual_start")
        assert started["punctuality_minutes_late"] == 0


class TestConsistencyScore:
    def test_consistency_score_vacuous_schedule(self, api):
        """PRD §3.8: "The **scheduled count** covers the window's streams in
        `LIVE`, `ENDED`, `NO_SHOW`, or `CANCELLED` status; when there are
        none, the score is a vacuous perfect 10,000 basis points."

        Design: Corner/calculations/consistency_score_vacuous_schedule
        """
        channel = create_channel(handle="calc_vac", home_platform="TWITCH")
        channel_now = get_channel(channel["id"])
        assert channel_now["consistency_score_bps"] == 10000, (
            "zero scheduled streams in the window score a vacuous perfect")

    def _two_stream_scenario(self, handle):
        """S1 scheduled 2026-08-10 10:00-11:00 started on time, ended after
        60 minutes; S2 scheduled 2026-08-12 10:00-11:00 started 15 minutes
        late, ended after 30 minutes."""
        channel = create_channel(handle=handle, home_platform="TWITCH")
        set_clock("2026-08-01T00:00:00Z")
        s1 = create_stream(channel["id"], title="S1",
                           scheduled_start="2026-08-10T10:00:00Z",
                           scheduled_end="2026-08-10T11:00:00Z")
        s2 = create_stream(channel["id"], title="S2",
                           scheduled_start="2026-08-12T10:00:00Z",
                           scheduled_end="2026-08-12T11:00:00Z")
        set_clock("2026-08-10T10:00:00Z")
        start_stream(s1["id"], channel["id"])
        set_clock("2026-08-10T11:00:00Z")
        end_stream(s1["id"], channel["id"], peak_viewers=100, avg_viewers=80)
        set_clock("2026-08-12T10:15:00Z")
        start_stream(s2["id"], channel["id"])
        set_clock("2026-08-12T10:45:00Z")
        end_stream(s2["id"], channel["id"], peak_viewers=50, avg_viewers=40)
        set_clock("2026-08-13T00:00:00Z")
        return channel, s1, s2

    def test_consistency_score_multi_input_blend(self, api):
        """PRD §3.8: "Punctuality enters as a factor: the mean
        `punctuality_minutes_late` over the `ENDED` streams — zero when none
        ended — is divided by the thirty-minute tolerance, that quotient is
        subtracted from one, and the result is floored at zero. Duration
        enters the same way: over the `ENDED` streams, each stream's actual
        duration (`actual_end` minus `actual_start`) is divided by its
        scheduled duration (`scheduled_end` minus `scheduled_start`), the
        ratios are averaged — one when none ended — and the average is capped
        at one. The score is then ten thousand times the attendance rate times
        the weighted blend of the three components: a base weight of one-half,
        plus three-tenths of the punctuality factor, plus two-tenths of the
        duration factor."

        Design: Difficulty/combinatorial_formula/consistency_score_multi_input_nonlinear
        """
        channel, _s1, _s2 = self._two_stream_scenario("cf_cons")
        score = get_channel(channel["id"])["consistency_score_bps"]
        # attendance 2/2 = 1.0; avg late 7.5 -> punctuality factor 0.75;
        # duration ratios 1.0 and 0.5 -> factor 0.75;
        # 10000 * 1.0 * (0.5 + 0.3*0.75 + 0.2*0.75) = 8750.
        assert score == 8750

    def test_consistency_score_records_punctuality_per_stream(self, api):
        """PRD §3.8: "Starting stamps `actual_start` and computes
        `punctuality_minutes_late` — null until then — as the whole minutes by
        which `actual_start` followed `scheduled_start`, or zero when the
        stream started on time or early."
        PRD §3.8: "Otherwise the attendance rate is the share of the
        scheduled count whose status is `ENDED`."

        Design: Difficulty/combinatorial_formula/consistency_score_multi_input_nonlinear
        """
        channel, s1, s2 = self._two_stream_scenario("cf_cons2")
        first = get_success_data(api.get_stream(s1["id"], ADMIN))
        second = get_success_data(api.get_stream(s2["id"], ADMIN))
        assert first["stream_status"] == "ENDED"
        assert second["stream_status"] == "ENDED"
        assert first["punctuality_minutes_late"] == 0, "started on time"
        assert second["punctuality_minutes_late"] == 15, (
            "started at 10:15 against a 10:00 schedule")


class TestLogicalClock:
    def test_clock_default_startup_value(self, api):
        """PRD §2.5: "At startup the clock reads exactly
        2026-08-01T00:00:00Z, and it never falls back to wall time."
        PRD §3.8: "Starting stamps `actual_start` and computes
        `punctuality_minutes_late` — null until then — as the whole minutes by
        which `actual_start` followed `scheduled_start`, or zero when the
        stream started on time or early."

        Design: Corner/cross_cutting/clock_default_startup_value
        """
        # The clock is never set in this test: the server boots at the fixed
        # startup instant.
        channel = create_channel(handle="cc_clk", home_platform="TWITCH")
        stream = create_stream(channel["id"], title="S",
                               scheduled_start="2026-08-01T00:00:00Z",
                               scheduled_end="2026-08-01T01:00:00Z")

        started = validate_success(api.transition_stream(
            stream["id"], {"action": "START"},
            make_creator_headers(channel["id"])), 200)
        assert_instant_equals(started["actual_start"], "2026-08-01T00:00:00Z",
                              label="actual_start (default logical clock)")
        assert started["punctuality_minutes_late"] == 0
