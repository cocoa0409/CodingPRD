"""Tunnel turnaround buffers, instructor overlaps, and session windows (PRD §3.4)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assign_instructor_payload,
    assign_session_instructor,
    make_instructor,
    make_session,
    make_tunnel,
    validate_error,
    validate_paginated,
    validate_success,
)

FRONTDESK = TEST_USERS["frontdesk_headers"]


class TestTunnelTurnaroundBuffer:
    """A second session inside the turnaround buffer on the same tunnel is rejected."""

    def _setup(self, api):
        tunnel = make_tunnel(api, turnaround_minutes=15)
        make_session(api, tunnel["id"], start_utc="2026-05-10T10:00:00Z", end_utc="2026-05-10T10:30:00Z")
        return tunnel

    def test_turnaround_buffer_conflict(self, api):
        """PRD §3.4: "The scheduler then checks the tunnel's calendar — the new session
        may neither overlap another session on the same tunnel nor fall within that
        tunnel's `turnaround_minutes` buffer of one; a violation yields
        `ERR_SESSION_TIME_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/tunnel_turnaround_buffer_conflict
        """
        tunnel = self._setup(api)
        resp = api.create_session(
            {"tunnel_id": tunnel["id"], "start_utc": "2026-05-10T10:40:00Z",
             "end_utc": "2026-05-10T11:00:00Z", "capacity": 4},
            FRONTDESK,
        )
        validate_error(resp, ApiErrorId.ERR_SESSION_TIME_CONFLICT.value)

    def test_no_conflicting_session_persisted(self, api):
        """PRD §3.4: "The scheduler then checks the tunnel's calendar — the new session
        may neither overlap another session on the same tunnel nor fall within that
        tunnel's `turnaround_minutes` buffer of one; a violation yields
        `ERR_SESSION_TIME_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/tunnel_turnaround_buffer_conflict
        """
        tunnel = self._setup(api)
        api.create_session(
            {"tunnel_id": tunnel["id"], "start_utc": "2026-05-10T10:40:00Z",
             "end_utc": "2026-05-10T11:00:00Z", "capacity": 4},
            FRONTDESK,
        )
        _, meta = validate_paginated(api.list_sessions(FRONTDESK, params={"tunnel_id": tunnel["id"]}))
        assert meta["total_count"] == 1, meta["total_count"]


class TestInstructorOverlap:
    """The same instructor cannot hold two overlapping sessions."""

    def _setup(self, api):
        t1 = make_tunnel(api, name="T1")
        t2 = make_tunnel(api, name="T2")
        instructor = make_instructor(api)
        s_a = make_session(api, t1["id"], start_utc="2026-05-10T10:00:00Z", end_utc="2026-05-10T10:30:00Z")
        assign_session_instructor(api, s_a["id"], instructor["id"], s_a["version"])
        s_b = make_session(api, t2["id"], start_utc="2026-05-10T10:15:00Z", end_utc="2026-05-10T10:45:00Z")
        return instructor, s_b

    def test_instructor_overlap_rejected(self, api):
        """PRD §3.4: "It then requires that the chosen instructor have no other
        non-cancelled session overlapping the half-open interval from `start_utc` to
        `end_utc` — sessions that merely abut are allowed — failing with
        `ERR_INSTRUCTOR_TIME_CONFLICT` otherwise."

        Design: Difficulty/resource_temporal_overlap/instructor_overlap_conflict_adjacency_allowed
        """
        instructor, s_b = self._setup(api)
        resp = api.assign_instructor(
            s_b["id"], assign_instructor_payload(instructor["id"], s_b["version"]), FRONTDESK
        )
        validate_error(resp, ApiErrorId.ERR_INSTRUCTOR_TIME_CONFLICT.value)

    def test_session_stays_unstaffed_after_conflict(self, api):
        """PRD §3.4: "It then requires that the chosen instructor have no other
        non-cancelled session overlapping the half-open interval from `start_utc` to
        `end_utc` — sessions that merely abut are allowed — failing with
        `ERR_INSTRUCTOR_TIME_CONFLICT` otherwise."
        PRD §3.4: "On success the session's `instructor_id` is set, `staffing_status`
        becomes `STAFFED`, and `version` increments by one."

        Design: Difficulty/resource_temporal_overlap/instructor_overlap_conflict_adjacency_allowed
        """
        instructor, s_b = self._setup(api)
        api.assign_instructor(
            s_b["id"], assign_instructor_payload(instructor["id"], s_b["version"]), FRONTDESK
        )
        reread = validate_success(api.get_session(s_b["id"], FRONTDESK), 200)
        assert reread["staffing_status"] == "UNSTAFFED", reread["staffing_status"]


def test_session_end_before_start_returns_invalid_window(api):
    """PRD §3.4: "The window is validated first: `end_utc` must be strictly later than
    `start_utc` and the duration must be at least fifteen minutes, or the request is
    rejected with `ERR_INVALID_SESSION_WINDOW`."

    Design: Corner/validations/session_end_before_start_returns_invalid_window
    """
    tunnel = make_tunnel(api)
    resp = api.create_session(
        {"tunnel_id": tunnel["id"], "start_utc": "2026-05-10T10:30:00Z",
         "end_utc": "2026-05-10T10:00:00Z", "capacity": 4},
        FRONTDESK,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_SESSION_WINDOW.value)
