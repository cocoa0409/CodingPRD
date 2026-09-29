"""Resource temporal-overlap tests: the observer party slot uses half-open
windows with no buffer, while a remake team's session uses closed intervals
widened by a fifteen-minute changeover buffer.

Every test builds its own world from an empty database.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_trained_reviewer,
    observer_session_payload,
    remake_payload,
    setup_election,
    setup_received_envelopes,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["elections_admin_headers"]
CLERK = TEST_USERS["elections_clerk_headers"]
SUPERVISOR = TEST_USERS["canvass_supervisor_headers"]


def _session(observer_user_id, party_affiliation, station_area,
             window_start_at, window_end_at) -> dict:
    return observer_session_payload(
        observer_user_id,
        observer_name=f"Observer {observer_user_id}",
        organization=f"County {party_affiliation} Committee",
        party_affiliation=party_affiliation,
        station_area=station_area,
        window_start_at=window_start_at,
        window_end_at=window_end_at,
    )


def _setup_election_with_one_dem_session(api) -> dict:
    """One election in PRE_MAIL holding a single SCHEDULED DEM session at the
    INTAKE station over the half-open window [10:00, 12:00) on 2026-11-03."""
    election = setup_election(posture="PRE_MAIL", clock="2026-09-10T00:00:00Z")
    session = validate_success(
        api.create_observer_session(
            election["id"],
            _session("obs-dem-1", "DEM", "INTAKE",
                     "2026-11-03T10:00:00Z", "2026-11-03T12:00:00Z"),
            CLERK), 201)
    assert session["status"] == "SCHEDULED"
    return {"election": election, "session": session}


class TestObserverPartySlotHalfOpenWindows:
    """A per-party observer slot is contended under half-open geometry, so a
    window that begins exactly where another ends is free of conflict."""

    def test_touching_window_is_accepted_and_one_minute_encroachment_is_refused(self, api):
        """Touching endpoints therefore do not collide — a session ending at exactly the instant another begins is fine.

        Design: Difficulty/resource_temporal_overlap/observer_party_slot_half_open_window_adjacency
        """
        context = _setup_election_with_one_dem_session(api)
        election_id = context["election"]["id"]

        touching = validate_success(
            api.create_observer_session(
                election_id,
                _session("obs-dem-2", "DEM", "SIGNATURE_REVIEW",
                         "2026-11-03T12:00:00Z", "2026-11-03T14:00:00Z"),
                CLERK), 201)
        encroaching = api.create_observer_session(
            election_id,
            _session("obs-dem-3", "DEM", "SEPARATION",
                     "2026-11-03T11:59:00Z", "2026-11-03T13:00:00Z"),
            CLERK)

        assert touching["status"] == "SCHEDULED"
        validate_error(encroaching, ApiErrorId.ERR_OBSERVER_PARTY_SLOT_CONFLICT, 409)

    def test_station_area_does_not_partition_the_party_slot(self, api):
        """The per-party constraint allows at most one overlapping session per `party_affiliation` for the same election; a second overlapping session of the same party is rejected with `ERR_OBSERVER_PARTY_SLOT_CONFLICT`.

        Design: Difficulty/resource_temporal_overlap/observer_party_slot_half_open_window_adjacency
        """
        context = _setup_election_with_one_dem_session(api)

        # A different station_area, but the same party and an overlapping window.
        response = api.create_observer_session(
            context["election"]["id"],
            _session("obs-dem-3", "DEM", "SEPARATION",
                     "2026-11-03T11:59:00Z", "2026-11-03T13:00:00Z"),
            CLERK)

        validate_error(response, ApiErrorId.ERR_OBSERVER_PARTY_SLOT_CONFLICT, 409)
        rows, meta = validate_paginated(
            api.list_observer_sessions(
                ADMIN, params={"election_id": context["election"]["id"],
                               "party_affiliation": "DEM"}))
        assert meta["total_count"] == 1, "the refused session was never created"
        assert rows[0]["id"] == context["session"]["id"]

    def test_a_different_party_is_a_different_contended_resource(self, api):
        """Two capacity constraints protect the floor, and both use **half-open interval geometry**: a new window collides with an existing one when the new window's start is strictly before the existing window's end **and** the existing window's start is strictly before the new window's end.

        Design: Difficulty/resource_temporal_overlap/observer_party_slot_half_open_window_adjacency
        """
        context = _setup_election_with_one_dem_session(api)

        coincident = validate_success(
            api.create_observer_session(
                context["election"]["id"],
                _session("obs-rep-1", "REP", "INTAKE",
                         "2026-11-03T10:00:00Z", "2026-11-03T12:00:00Z"),
                CLERK), 201)

        assert coincident["status"] == "SCHEDULED"
        assert coincident["party_affiliation"] == "REP"

    def test_revoking_a_session_frees_its_window_for_the_same_party(self, api):
        """Sessions whose status is `REVOKED` are excluded from the occupancy set entirely.

        Design: Difficulty/resource_temporal_overlap/observer_party_slot_half_open_window_adjacency
        """
        context = _setup_election_with_one_dem_session(api)
        election_id = context["election"]["id"]
        validate_success(
            api.create_observer_session(
                election_id,
                _session("obs-dem-2", "DEM", "SIGNATURE_REVIEW",
                         "2026-11-03T12:00:00Z", "2026-11-03T14:00:00Z"),
                CLERK), 201)
        validate_error(
            api.create_observer_session(
                election_id,
                _session("obs-dem-3", "DEM", "SEPARATION",
                         "2026-11-03T11:59:00Z", "2026-11-03T13:00:00Z"),
                CLERK),
            ApiErrorId.ERR_OBSERVER_PARTY_SLOT_CONFLICT, 409)

        revoked = validate_success(
            api.revoke_observer_session(
                context["session"]["id"],
                {"revocation_reason_code": "CREDENTIAL_WITHDRAWN"}, SUPERVISOR), 200)
        rebooked = validate_success(
            api.create_observer_session(
                election_id,
                _session("obs-dem-4", "DEM", "INTAKE",
                         "2026-11-03T10:00:00Z", "2026-11-03T12:00:00Z"),
                CLERK), 201)

        assert revoked["status"] == "REVOKED"
        assert rebooked["status"] == "SCHEDULED"
        rows, meta = validate_paginated(
            api.list_observer_sessions(
                ADMIN, params={"election_id": election_id, "party_affiliation": "DEM"}))
        assert meta["total_count"] == 3, "the refused 11:59 session was never created"
        assert sorted(row["status"] for row in rows) == ["REVOKED", "SCHEDULED", "SCHEDULED"]


RK1_START = "2026-11-05T13:00:00Z"
RK1_END = "2026-11-05T14:00:00Z"


def _setup_open_remake_and_spare_envelopes(api) -> dict:
    """Four TRAINED reviewers in two bipartisan pairs, three SEALED envelopes
    carrying no signature reviews, and one OPEN remake held by the first pair
    over the closed session interval [13:00, 14:00] on 2026-11-05."""
    member_a = create_trained_reviewer(full_name="Ada Vance", party_affiliation="DEM")
    member_b = create_trained_reviewer(full_name="Bo Reyes", party_affiliation="REP")
    member_c = create_trained_reviewer(full_name="Cy Marsh", party_affiliation="DEM")
    member_d = create_trained_reviewer(full_name="Dot Peck", party_affiliation="REP")
    bundle = setup_received_envelopes(count=3, intake_at="2026-11-03T12:00:00Z",
                                    intake_channel="DROPBOX", posture="RECEIVING",
                                    clock="2026-09-10T00:00:00Z")
    first, second, third = bundle["envelopes"]
    held = validate_success(
        api.create_remake(
            first["id"],
            remake_payload(member_a["id"], member_b["id"], first["version"],
                           reason_code="DAMAGED",
                           session_start_at=RK1_START, session_end_at=RK1_END),
            SUPERVISOR), 201)
    assert held["status"] == "OPEN"
    return {"team": (member_a, member_b), "spare_team": (member_c, member_d),
            "held_remake": held, "envelopes": [first, second, third]}


class TestRemakeTeamClosedIntervalChangeoverBuffer:
    """A reviewer already seated on an OPEN remake is double-booked by any
    session whose start, pulled back fifteen minutes, still reaches the held
    session's end — so touching endpoints and the buffer edge both collide."""

    @pytest.mark.parametrize(
        "session_start_at,rationale",
        [
            pytest.param("2026-11-05T14:00:00Z",
                         "a 14:00 start touches the held 14:00 end",
                         id="touching-endpoints-collide"),
            pytest.param("2026-11-05T14:15:00Z",
                         "14:15 less fifteen minutes is exactly the held 14:00 end",
                         id="buffer-edge-collides"),
        ],
    )
    def test_touching_and_buffer_edge_starts_double_book_the_team(
        self, api, session_start_at, rationale,
    ):
        """Touching endpoints therefore **do** collide, and so does a gap of less than a quarter of an hour, because the team needs that long to clear one ballot off the table before the next arrives.

        Design: Difficulty/resource_temporal_overlap/remake_team_closed_interval_changeover_buffer
        """
        context = _setup_open_remake_and_spare_envelopes(api)
        member_a, member_b = context["team"]
        second = context["envelopes"][1]

        response = api.create_remake(
            second["id"],
            remake_payload(member_a["id"], member_b["id"], second["version"],
                           reason_code="UNREADABLE_MARKS",
                           session_start_at=session_start_at,
                           session_end_at="2026-11-05T15:00:00Z"),
            SUPERVISOR)

        assert response.status_code == 409, rationale
        validate_error(response, ApiErrorId.ERR_REMAKE_TEAM_DOUBLE_BOOKED, 409)
        envelope = validate_success(api.get_return_envelope(second["id"], SUPERVISOR), 200)
        assert envelope["custody_status"] == "SEALED"
        assert envelope["version"] == second["version"], \
            "a refused remake must not increment the envelope version"

    def test_one_minute_past_the_buffer_may_be_booked_by_the_same_team(self, api):
        """For either team member, the proposed session collides with any remake record in `OPEN` or `COMPLETED` on which that reviewer already sits when the proposed `session_start_at` reduced by fifteen minutes is at or before the existing session's `session_end_at` **and** the existing session's `session_start_at` is at or before the proposed `session_end_at` increased by fifteen minutes.

        Design: Difficulty/resource_temporal_overlap/remake_team_closed_interval_changeover_buffer
        """
        context = _setup_open_remake_and_spare_envelopes(api)
        member_a, member_b = context["team"]
        second = context["envelopes"][1]

        # 14:16 less fifteen minutes is 14:01, one minute clear of the 14:00 end.
        response = api.create_remake(
            second["id"],
            remake_payload(member_a["id"], member_b["id"], second["version"],
                           reason_code="UNREADABLE_MARKS",
                           session_start_at="2026-11-05T14:16:00Z",
                           session_end_at="2026-11-05T15:00:00Z"),
            SUPERVISOR)

        remake = validate_success(response, 201)
        assert remake["status"] == "OPEN"
        assert remake["original_envelope_id"] == second["id"]
        assert remake["remade_envelope_id"] is None
        assert remake["completed_at"] is None

    def test_a_disjoint_pair_may_work_a_fully_overlapping_window(self, api):
        """The double-booking test uses **closed-interval geometry widened by a changeover buffer**, which is deliberately the opposite of the observer geometry in §3.7.

        Design: Difficulty/resource_temporal_overlap/remake_team_closed_interval_changeover_buffer
        """
        context = _setup_open_remake_and_spare_envelopes(api)
        member_c, member_d = context["spare_team"]
        third = context["envelopes"][2]

        response = api.create_remake(
            third["id"],
            remake_payload(member_c["id"], member_d["id"], third["version"],
                           reason_code="TORN_ENVELOPE",
                           session_start_at="2026-11-05T13:30:00Z",
                           session_end_at="2026-11-05T14:30:00Z"),
            SUPERVISOR)

        remake = validate_success(response, 201)
        assert remake["status"] == "OPEN", \
            "the contended resource is the reviewer, not the remake floor"

    def test_refused_bookings_leave_the_team_holding_only_its_real_sessions(self, api):
        """A collision is rejected with `ERR_REMAKE_TEAM_DOUBLE_BOOKED`.

        Design: Difficulty/resource_temporal_overlap/remake_team_closed_interval_changeover_buffer
        """
        context = _setup_open_remake_and_spare_envelopes(api)
        member_a, member_b = context["team"]
        second = context["envelopes"][1]

        for refused_start in ("2026-11-05T14:00:00Z", "2026-11-05T14:15:00Z"):
            validate_error(
                api.create_remake(
                    second["id"],
                    remake_payload(member_a["id"], member_b["id"], second["version"],
                                   reason_code="UNREADABLE_MARKS",
                                   session_start_at=refused_start,
                                   session_end_at="2026-11-05T15:00:00Z"),
                    SUPERVISOR),
                ApiErrorId.ERR_REMAKE_TEAM_DOUBLE_BOOKED, 409)
        accepted = validate_success(
            api.create_remake(
                second["id"],
                remake_payload(member_a["id"], member_b["id"], second["version"],
                               reason_code="UNREADABLE_MARKS",
                               session_start_at="2026-11-05T14:16:00Z",
                               session_end_at="2026-11-05T15:00:00Z"),
                SUPERVISOR), 201)

        rows, meta = validate_paginated(
            api.list_remake_records(
                SUPERVISOR, params={"team_member_a_reviewer_id": member_a["id"]}))
        assert meta["total_count"] == 2, "the two refused bookings created nothing"
        assert {row["id"] for row in rows} == {context["held_remake"]["id"], accepted["id"]}
