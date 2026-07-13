"""Session parallel axes, OCC on instructor assignment, seniority, start gates
(PRD §2.6, §3.1, §3.4)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assign_instructor_payload,
    assign_session_instructor,
    make_instructor,
    make_session,
    make_tunnel,
    setup_running_session,
    setup_staffed_session,
    validate_error,
    validate_success,
)

FRONTDESK = TEST_USERS["frontdesk_headers"]
MANAGER = TEST_USERS["manager_headers"]


class TestParallelAxes:
    """op_status and staffing_status evolve independently on the same row."""

    def test_op_axis_unchanged_by_staffing(self, api):
        """PRD §3.4: "A session evolves along two independent axes. The **operational
        axis** `op_status` moves through `OPEN`, `RUNNING`, `CLOSED`, and `CANCELLED`;
        the **staffing axis** `staffing_status` is either `UNSTAFFED` or `STAFFED`, and
        evolves independently of the operational axis on the same row."
        PRD §3.4: "On success the session's `instructor_id` is set, `staffing_status`
        becomes `STAFFED`, and `version` increments by one."

        Design: Difficulty/non_linear_state_machine/session_parallel_op_and_staffing_axes
        """
        tunnel = make_tunnel(api)
        instructor = make_instructor(api)
        session = make_session(api, tunnel["id"])
        assigned = assign_session_instructor(api, session["id"], instructor["id"], session["version"])
        assert assigned["op_status"] == "OPEN", assigned["op_status"]
        assert assigned["staffing_status"] == "STAFFED", assigned["staffing_status"]

    def test_op_axis_advances_on_start(self, api):
        """PRD §3.4: "Starting a session, done by an `Instructor` or `FrontDesk`,
        advances `op_status` from `OPEN` to `RUNNING`."
        PRD §3.4: "the **staffing axis** `staffing_status` is either `UNSTAFFED` or
        `STAFFED`, and evolves independently of the operational axis on the same row."

        Design: Difficulty/non_linear_state_machine/session_parallel_op_and_staffing_axes
        """
        ctx = setup_running_session(api)
        assert ctx["session"]["op_status"] == "RUNNING", ctx["session"]["op_status"]
        assert ctx["session"]["staffing_status"] == "STAFFED", ctx["session"]["staffing_status"]


class TestOptimisticConcurrency:
    """assign-instructor is the one OCC-guarded operation."""

    def _setup(self, api):
        tunnel = make_tunnel(api)
        ia = make_instructor(api, name="IvyA")
        ib = make_instructor(api, name="IvyB")
        session = make_session(api, tunnel["id"])
        return tunnel, ia, ib, session

    def test_stale_version_rejected(self, api):
        """PRD §2.6: "two strictly sequential assign calls that both carry the version
        observed before the first call will see the first succeed and the second
        rejected with `ERR_STALE_VERSION`, because the first call advanced the
        session's `version` out from under the second."

        Design: Corner/cross_cutting_complexity_layers/session_assign_stale_version_returns_412
        """
        _, ia, ib, session = self._setup(api)
        v0 = session["version"]
        assign_session_instructor(api, session["id"], ia["id"], v0)  # advances version
        resp = api.assign_instructor(
            session["id"], assign_instructor_payload(ib["id"], v0), FRONTDESK
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)

    def test_reassign_correct_version_supersedes(self, api):
        """PRD §3.4: "Reassigning an already-staffed session is legitimate: a fresh
        assignment supersedes the prior one, running the same version check and the
        same conflict check against the new instructor, again setting `instructor_id`
        and again incrementing `version`."

        Design: Corner/cross_cutting_complexity_layers/session_reassign_correct_version_succeeds
        """
        _, ia, ib, session = self._setup(api)
        first = assign_session_instructor(api, session["id"], ia["id"], session["version"])
        v1 = first["version"]
        second = assign_session_instructor(api, session["id"], ib["id"], v1)
        assert second["instructor_id"] == ib["id"], second["instructor_id"]
        assert second["version"] == v1 + 1, (second["version"], v1)


def test_instructor_tier_upgrade_on_second_close(api):
    """PRD §3.1: "The `sessions_completed` counter tracks how many sessions this
    instructor has closed; each session close increments it by one, and once it
    reaches two or more the instructor's `tier` upgrades from `JUNIOR` to `SENIOR`."

    Design: Corner/cross_cutting_complexity_layers/instructor_tier_upgrade_on_second_close
    """
    t1 = make_tunnel(api, name="T1")
    t2 = make_tunnel(api, name="T2")
    instructor = make_instructor(api)
    s1 = make_session(api, t1["id"], start_utc="2026-05-10T10:00:00Z", end_utc="2026-05-10T10:30:00Z")
    assign_session_instructor(api, s1["id"], instructor["id"], s1["version"])
    validate_success(api.start_session(s1["id"], FRONTDESK), 200)
    validate_success(api.close_session(s1["id"], FRONTDESK), 200)
    s2 = make_session(api, t2["id"], start_utc="2026-05-10T11:00:00Z", end_utc="2026-05-10T11:30:00Z")
    assign_session_instructor(api, s2["id"], instructor["id"], s2["version"])
    validate_success(api.start_session(s2["id"], FRONTDESK), 200)
    validate_success(api.close_session(s2["id"], FRONTDESK), 200)
    reread = validate_success(api.get_instructor(instructor["id"], MANAGER), 200)
    assert reread["sessions_completed"] == 2, reread["sessions_completed"]
    assert reread["tier"] == "SENIOR", reread["tier"]


def test_start_running_session_returns_invalid_state(api):
    """PRD §2.10: "**State** — the target resource must be in a valid state for the
    requested transition (session operational or staffing axis, flight status, or
    booking status), else `ERR_INVALID_STATE` (409)."
    PRD §3.4: "Starting a session, done by an `Instructor` or `FrontDesk`, advances
    `op_status` from `OPEN` to `RUNNING`."

    Design: Corner/state_machines/start_session_from_running_returns_invalid_state
    """
    ctx = setup_running_session(api)
    resp = api.start_session(ctx["session"]["id"], FRONTDESK)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestSessionStartRequiresOperationalTunnel:
    """Session start's validity depends on the Tunnel's status."""

    def _setup_maintenance(self, api):
        ctx = setup_staffed_session(api)
        validate_success(
            api.tunnel_maintenance(ctx["tunnel"]["id"], {"mode": "MAINTENANCE"}, MANAGER), 200
        )
        return ctx

    def test_maintenance_blocks_start(self, api):
        """PRD §3.4: "It requires that the session already be `STAFFED`, failing with
        `ERR_SESSION_NOT_STAFFED`, and that the underlying tunnel's `status` be
        `OPERATIONAL`, failing with `ERR_TUNNEL_NOT_OPERATIONAL`."

        Design: Difficulty/cross_entity_state_dependency/session_start_requires_operational_tunnel
        """
        ctx = self._setup_maintenance(api)
        resp = api.start_session(ctx["session"]["id"], FRONTDESK)
        validate_error(resp, ApiErrorId.ERR_TUNNEL_NOT_OPERATIONAL.value)

    def test_session_stays_open_after_blocked_start(self, api):
        """PRD §3.4: "It requires ... that the underlying tunnel's `status` be
        `OPERATIONAL`, failing with `ERR_TUNNEL_NOT_OPERATIONAL`."
        PRD §3.4: "Starting a session ... advances `op_status` from `OPEN` to
        `RUNNING`."

        Design: Difficulty/cross_entity_state_dependency/session_start_requires_operational_tunnel
        """
        ctx = self._setup_maintenance(api)
        api.start_session(ctx["session"]["id"], FRONTDESK)
        reread = validate_success(api.get_session(ctx["session"]["id"], FRONTDESK), 200)
        assert reread["op_status"] == "OPEN", reread["op_status"]
