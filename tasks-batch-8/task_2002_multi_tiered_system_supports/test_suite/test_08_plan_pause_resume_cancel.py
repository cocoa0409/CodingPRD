"""Plan hold and abandonment paths: the pause/resume cycle, the tier guard on
pausing, and the cancellation gate (PRD §3.7, §3.8)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_second_window_screening,
    committed_minutes,
    convene_meeting,
    create_team_meeting,
    get_plan,
    pause_plan,
    propose_movement,
    ratify_movement,
    record_probe,
    resume_plan,
    set_clock,
    setup_active_plan,
    validate_error,
)

LEAD = TEST_USERS["team_lead_headers"]


class TestPauseResumeCycle:
    def test_pause_resume_cycle_is_reentrant(self, api):
        """PRD §3.8: "Pausing transitions the plan from `ACTIVE` to `PAUSED`,
        subtracts its `weekly_minute_cost` from the interventionist's
        `committed_minutes_per_week`, and increments the plan's `version` by
        one."
        PRD §3.8: "Resuming reverses it: the same two roles may return a `PAUSED`
        plan to `ACTIVE`, subject to a fresh capacity check against the
        interventionist's ledger (`ERR_CAPACITY_EXCEEDED` if the headroom is
        gone), after which the minutes are re-committed and the plan's `version`
        increments again."

        The cycle is legal repeatedly: ACTIVE -> PAUSED -> ACTIVE -> PAUSED ->
        ACTIVE, with the version advancing by exactly one per transition and the
        ledger netting to the plan's cost after the final resume.

        Design: Difficulty/non_linear_state_machine/student_plan_pause_resume_cycle
        """
        ctx = setup_active_plan(api, tier="TIER_2")

        versions = [ctx["plan"]["version"]]
        statuses = []
        for action in (pause_plan, resume_plan, pause_plan, resume_plan):
            plan = action(api, ctx)
            statuses.append(plan["status"])
            versions.append(plan["version"])

        assert statuses == ["PAUSED", "ACTIVE", "PAUSED", "ACTIVE"], (
            "the ACTIVE<->PAUSED cycle must be re-entrant")
        for earlier, later in zip(versions, versions[1:]):
            assert later == earlier + 1, (
                f"each transition increments plan version by 1 ({earlier} -> {later})")
        assert committed_minutes(api, ctx) == 90, (
            "decrement on pause and increment on resume net to the plan cost")

    def test_pause_releases_and_resume_recommits_minutes(self, api):
        """PRD §3.8: "Pausing transitions the plan from `ACTIVE` to `PAUSED`,
        subtracts its `weekly_minute_cost` from the interventionist's
        `committed_minutes_per_week`, and increments the plan's `version` by
        one."
        PRD §3.8: "Resuming reverses it: the same two roles may return a `PAUSED`
        plan to `ACTIVE`, subject to a fresh capacity check against the
        interventionist's ledger (`ERR_CAPACITY_EXCEEDED` if the headroom is
        gone), after which the minutes are re-committed and the plan's `version`
        increments again."

        Design: Difficulty/non_linear_state_machine/student_plan_pause_resume_cycle
        """
        ctx = setup_active_plan(api, tier="TIER_2")
        assert committed_minutes(api, ctx) == 90

        paused = pause_plan(api, ctx)
        assert paused["status"] == "PAUSED"
        assert committed_minutes(api, ctx) == 0, "pause releases the plan's minutes"

        resumed = resume_plan(api, ctx)
        assert resumed["status"] == "ACTIVE"
        assert committed_minutes(api, ctx) == 90, "resume re-commits the minutes"
        assert resumed["version"] == paused["version"] + 1


class TestPauseTierGuard:
    def test_pause_rejected_after_tier_move_cascade(self, api):
        """PRD §3.8: "An `InterventionistRole` or a `TeamLead` may pause a plan,
        but only while the student's `current_tier` still equals the plan's
        `tier_at_start` — a student whose tier has moved no longer fits the
        plan's premise."
        PRD §3.7: "Any `ACTIVE` plan whose `tier_at_start` no longer matches the
        student's new tier cascades to `EXIT_MOVED`, releasing its
        `weekly_minute_cost` from the interventionist's
        `committed_minutes_per_week`."

        Once the ratified move to TIER_3 has cascaded the TIER_2 plan to
        EXIT_MOVED, a pause attempt is rejected with ERR_INVALID_STATE.

        Design: Difficulty/cross_entity_state_dependency/plan_pause_requires_student_tier_unchanged
        """
        ctx = setup_active_plan(api, tier="TIER_2")
        d_id, s_id = ctx["district"]["id"], ctx["school"]["id"]
        st_id, plan_id = ctx["student"]["id"], ctx["plan"]["id"]
        # Second screening window produces TIER_3 evidence; ratify the move.
        add_second_window_screening(api, ctx, raw_score=60)
        movement = propose_movement(api, d_id, s_id, st_id, "TIER_3",
                                    rationale="WINTER screen")
        meeting = create_team_meeting(api, d_id, s_id, scheduled_on="2026-12-20")
        convene_meeting(api, d_id, s_id, meeting["id"])
        ratify_movement(api, d_id, s_id, meeting["id"], movement["id"], st_id)

        plan = get_plan(api, d_id, s_id, st_id, plan_id)
        assert plan["status"] == "EXIT_MOVED", "ratify cascades the plan"
        resp = api.pause_plan(d_id, s_id, st_id, plan_id,
                              {"expected_plan_version": plan["version"]}, LEAD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_pause_allowed_while_student_tier_unchanged(self, api):
        """PRD §3.8: "An `InterventionistRole` or a `TeamLead` may pause a plan,
        but only while the student's `current_tier` still equals the plan's
        `tier_at_start` — a student whose tier has moved no longer fits the
        plan's premise."

        While the tier is unchanged the guard passes and the pause succeeds.

        Design: Difficulty/cross_entity_state_dependency/plan_pause_requires_student_tier_unchanged
        """
        ctx = setup_active_plan(api, tier="TIER_2")
        paused = pause_plan(api, ctx)
        assert paused["status"] == "PAUSED"
        assert committed_minutes(api, ctx) == 0


class TestCancellationGate:
    def test_cancel_active_plan_with_probe_rejected(self, api):
        """PRD §3.8: "A `TeamLead` may cancel an `ACTIVE` plan only while no
        progress probe exists on it yet; the cancellation releases its committed
        minutes."
        PRD §2.5: "Fifth are state preconditions: the target resource must be in
        the state the operation requires — the window `CLOSED` for scoring, the
        plan `ACTIVE` for probes, sessions, and exits, the meeting `CONVENED` for
        ratification, and so on — with violations rejected as `ERR_INVALID_STATE`
        (HTTP 409)."

        A plan that already has a probe cannot be cancelled.

        Design: Corner/state_machines/plan_cancel_blocked_after_first_probe
        """
        ctx = setup_active_plan(api, tier="TIER_2")
        d_id, s_id = ctx["district"]["id"], ctx["school"]["id"]
        set_clock(api, "2026-08-18T00:00:00Z")
        record_probe(api, ctx, "2026-08-18", 85)

        plan = get_plan(api, d_id, s_id, ctx["student"]["id"], ctx["plan"]["id"])
        resp = api.cancel_plan(
            d_id, s_id, ctx["student"]["id"], plan["id"],
            {"expected_plan_version": plan["version"]}, LEAD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
