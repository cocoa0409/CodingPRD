"""Deduction lifecycle: legality rule, OCC amendment, void segregation, the
two-round appeal loop, appeal windows, and the cross-entity state gates."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    apply_safety_deduction,
    appeal_deduction,
    get_success_data,
    make_head_judge_headers,
    make_judge_headers,
    make_safety_judge_headers,
    make_team_coach_headers,
    mark_performance_performed,
    resolve_appeal,
    set_clock,
    setup_event_with_division,
    setup_live_event_with_checked_in_teams,
    setup_registered_team,
    submit_full_panel,
    submit_sheet_for_judge,
    validate_error,
    validate_paginated,
    validate_success,
)

DIRECTOR = TEST_USERS["event_director_headers"]


def _setup_performed(api):
    """Live event, one CHECKED_IN team, its performance PERFORMED."""
    ctx = setup_live_event_with_checked_in_teams(
        [{"coach_id": "coach-1", "name": "T1", "organization": "Gym1"}])
    perf = ctx["teams"][0]["performance"]
    mark_performance_performed(perf["id"], ctx["safety"]["id"], 150, 0)
    return ctx, perf


class TestCrossEntityGates:
    def test_score_sheet_submit_gated_by_performance_state(self, api):
        """PRD §3.5: "A `Judge` creates their own **ScoreSheet** against a
        `PERFORMED` or `SCORED` performance (the same
        `ERR_PERFORMANCE_NOT_PERFORMED` / `ERR_PERFORMANCE_INVALID_STATE`
        pair guards the state)"

        Design: Difficulty/cross_entity_state_dependency/score_sheet_submit_gated_by_performance_state
        """
        # Division scheduled, but the performance is still SCHEDULED (no
        # mark-performed), and the event is not LIVE.
        event, division, panel, head, safety = setup_event_with_division()
        team, athlete, entry = setup_registered_team(division, coach_id="coach-1")
        get_success_data(api.close_registration(event["id"], DIRECTOR))
        division = get_success_data(api.get_division(division["id"], DIRECTOR))
        get_success_data(api.generate_schedule(
            division["id"], division["version"], DIRECTOR))
        perfs, _ = validate_paginated(
            api.list_team_performances(team["id"], DIRECTOR))
        perf = perfs[0]
        assert perf["status"] == "SCHEDULED"

        resp = api.create_score_sheet(
            perf["id"],
            {"building_difficulty": 8.0, "building_execution": 8.0,
             "tumbling_difficulty": 8.0, "overall_impression": 8.0},
            make_judge_headers(panel[0]["id"]))
        validate_error(resp, ApiErrorId.ERR_PERFORMANCE_NOT_PERFORMED)

    def test_mark_performed_gated_by_team_checkin_state(self, api):
        """PRD §3.5: "The operation requires the performance to be
        `SCHEDULED` (otherwise `ERR_INVALID_STATE`), the owning event to be
        `LIVE` (`ERR_EVENT_NOT_LIVE`), and the team to be `CHECKED_IN`
        (`ERR_TEAM_NOT_CHECKED_IN`)."

        Design: Difficulty/cross_entity_state_dependency/mark_performed_gated_by_team_checkin_state
        """
        # Event LIVE but the team is only ROSTER_LOCKED (never checked in).
        event, division, panel, head, safety = setup_event_with_division()
        team, athlete, entry = setup_registered_team(division, coach_id="coach-1")
        from test_helpers import lock_roster
        lock_roster(team["id"], "coach-1")
        get_success_data(api.close_registration(event["id"], DIRECTOR))
        division = get_success_data(api.get_division(division["id"], DIRECTOR))
        get_success_data(api.generate_schedule(
            division["id"], division["version"], DIRECTOR))
        get_success_data(api.go_live(event["id"], DIRECTOR))
        perfs, _ = validate_paginated(
            api.list_team_performances(team["id"], DIRECTOR))
        perf = perfs[0]

        resp = api.mark_performed(
            perf["id"], {"actual_duration_seconds": 150, "boundary_violations": 0},
            make_safety_judge_headers(safety["id"]))
        validate_error(resp, ApiErrorId.ERR_TEAM_NOT_CHECKED_IN)


class TestLegalityRule:
    def test_safety_deduction_for_legal_skill_rejected(self, api):
        """PRD §3.5: "Routine legality is the gate: a `SAFETY` deduction is
        only valid when `skill_tier` exceeds the division's `level`; citing a
        skill at or below the division's level is legal at that level and is
        rejected with `ERR_SKILL_WITHIN_LEGAL_LIMIT`."
        PRD §3.5: "computes `points` as the quantity multiplied by the
        snapshotted rate, rounded half-up once to 2 decimal places."

        Design: Corner/validations/safety_deduction_for_legal_skill_rejected
        """
        ctx, perf = _setup_performed(api)
        safety = make_safety_judge_headers(ctx["safety"]["id"])

        # skill_tier 3 == division level 3: legal skill, rejected.
        resp = api.create_deduction(
            perf["id"], {"type": "SAFETY", "quantity": 1, "skill_tier": 3},
            safety)
        validate_error(resp, ApiErrorId.ERR_SKILL_WITHIN_LEGAL_LIMIT)

        # skill_tier 4 > 3: created, points = 1 x 2.0 = 2.00.
        created = validate_success(api.create_deduction(
            perf["id"], {"type": "SAFETY", "quantity": 1, "skill_tier": 4},
            safety), 201)
        assert created["points"] == pytest.approx(2.00, abs=0.001)
        assert created["rate_applied"] == pytest.approx(2.0, abs=0.001)


class TestTimeBoundary:
    def test_time_deduction_at_exact_limit_vs_one_second_over(self, api):
        """PRD §3.5: "If `actual_duration_seconds` exceeds the division's
        `routine_time_limit_seconds`, a `SYSTEM` deduction of `type` `TIME` is
        created with `quantity` equal to the number of full seconds over the
        limit and `rate_applied` snapshotted from the division's
        `time_deduction_per_second`."

        Design: Difficulty/boundary_precision_check/time_deduction_at_exact_limit_vs_one_second_over
        """
        ctx = setup_live_event_with_checked_in_teams([
            {"coach_id": "coach-a", "name": "TA", "organization": "GymA",
             "athlete_name": "Ann"},
            {"coach_id": "coach-b", "name": "TB", "organization": "GymB",
             "athlete_name": "Bob", "athlete_dob": "2010-06-01"},
        ])
        safety_id = ctx["safety"]["id"]
        perf_a = ctx["teams"][0]["performance"]
        perf_b = ctx["teams"][1]["performance"]

        # Exactly at the 150s limit: no TIME deduction.
        mark_performance_performed(perf_a["id"], safety_id, 150, 0)
        deductions_a, _ = validate_paginated(
            api.list_performance_deductions(perf_a["id"], DIRECTOR))
        assert deductions_a == []

        # One second over: one TIME deduction, quantity 1, 0.50 points.
        mark_performance_performed(perf_b["id"], safety_id, 151, 0)
        deductions_b, _ = validate_paginated(
            api.list_performance_deductions(perf_b["id"], DIRECTOR))
        assert len(deductions_b) == 1
        assert deductions_b[0]["type"] == "TIME"
        assert deductions_b[0]["quantity"] == 1
        assert deductions_b[0]["points"] == pytest.approx(0.50, abs=0.001)

    def test_boundary_deduction_created_per_occurrence(self, api):
        """PRD §3.5: "If `boundary_violations` is greater than zero, a
        `SYSTEM` deduction of `type` `BOUNDARY` is created with `quantity`
        equal to `boundary_violations` and `rate_applied` snapshotted from
        `boundary_deduction_points`."

        Design: Difficulty/boundary_precision_check/time_deduction_at_exact_limit_vs_one_second_over
        """
        ctx = setup_live_event_with_checked_in_teams(
            [{"coach_id": "coach-1", "name": "T1", "organization": "Gym1"}])
        perf = ctx["teams"][0]["performance"]

        # 3 boundary violations at the 0.25 default rate -> 0.75 points.
        mark_performance_performed(perf["id"], ctx["safety"]["id"], 150, 3)
        deductions, _ = validate_paginated(
            api.list_performance_deductions(perf["id"], DIRECTOR))
        assert len(deductions) == 1
        assert deductions[0]["type"] == "BOUNDARY"
        assert deductions[0]["quantity"] == 3
        assert deductions[0]["rate_applied"] == pytest.approx(0.25, abs=0.001)
        assert deductions[0]["points"] == pytest.approx(0.75, abs=0.001)
        assert deductions[0]["source"] == "SYSTEM"
        assert deductions[0]["applied_by_judge_id"] is None


class TestOccDeductionAmend:
    def test_occ_deduction_amend_stale_version(self, api):
        """PRD §2.5: "Amending an `APPLIED` deduction's quantity or skill
        tier requires `expected_deduction_version`, compared against the
        `Deduction`'s current `version`. A mismatch is rejected with
        `ERR_STALE_VERSION` (HTTP 412)"
        PRD §3.6: "a successful amendment recomputes `points` from the new
        quantity against the frozen `rate_applied`"

        Design: Corner/complexity_layers/occ_deduction_amend_stale_version
        """
        ctx, perf = _setup_performed(api)
        safety = make_safety_judge_headers(ctx["safety"]["id"])
        deduction = apply_safety_deduction(perf["id"], ctx["safety"]["id"])
        stale_version = deduction["version"]

        amended = validate_success(api.patch_deduction(
            deduction["id"],
            {"expected_deduction_version": stale_version, "quantity": 2},
            safety), 200)
        assert amended["points"] == pytest.approx(4.00, abs=0.001)
        assert amended["version"] == stale_version + 1

        resp = api.patch_deduction(
            deduction["id"],
            {"expected_deduction_version": stale_version, "quantity": 3},
            safety)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestSegregationOfDuties:
    def test_segregation_reviewer_scored_and_self_void(self, api):
        """PRD §3.6: "the acting head judge's `X-User-ID` (a `Judge.id`) must
        not equal the `judge_id` of any score sheet on the deduction's
        performance, and must not equal the deduction's
        `applied_by_judge_id`; either conflict is rejected with
        `ERR_REVIEWER_CONFLICT`."
        PRD §3.6: "a `HeadJudge` may **void** an `APPLIED` deduction outright
        — but not one they applied themselves: the acting head judge's
        `X-User-ID` must differ from the deduction's `applied_by_judge_id`
        (`ERR_SELF_VOID_FORBIDDEN`)"

        Design: Corner/validations/segregation_reviewer_scored_and_self_void
        """
        # 4-judge panel includes the judge who will later act as HeadJudge.
        ctx = setup_live_event_with_checked_in_teams(
            [{"coach_id": "coach-1", "name": "T1", "organization": "Gym1"}],
            panel_count=4)
        perf = ctx["teams"][0]["performance"]
        safety_id = ctx["safety"]["id"]
        # The panel's 4th judge doubles as the conflicted head judge.
        conflicted_head_id = ctx["panel"][3]["id"]

        mark_performance_performed(perf["id"], safety_id, 150, 0)
        deduction = apply_safety_deduction(perf["id"], safety_id)

        # Void attempted by the applier (acting as HeadJudge): forbidden.
        resp = api.void_deduction(
            deduction["id"], make_head_judge_headers(safety_id))
        validate_error(resp, ApiErrorId.ERR_SELF_VOID_FORBIDDEN)

        # The conflicted judge authors a sheet on the performance, then the
        # coach appeals; resolving by the sheet author is a reviewer conflict.
        submit_sheet_for_judge(perf["id"], conflicted_head_id, 8.0)
        appeal = appeal_deduction(deduction["id"], "coach-1")
        resp = api.resolve_appeal(
            appeal["id"], "ACCEPTED",
            make_head_judge_headers(conflicted_head_id))
        validate_error(resp, ApiErrorId.ERR_REVIEWER_CONFLICT)


class TestAppealCycle:
    def test_deduction_appeal_cycle_two_rounds(self, api):
        """PRD §3.6: "A coach whose round-1 appeal was `REJECTED` may
        escalate once: resubmitting the rejected appeal — again with a fresh
        `note` and `video_ref` — creates a new Appeal with `round` 2 in
        `SUBMITTED` status and moves the deduction from `UPHELD` back to
        `UNDER_APPEAL`."
        PRD §3.6: "A `decision` of `ACCEPTED` moves the appeal to `ACCEPTED`
        and the deduction to `OVERTURNED`, excluding it from all score
        variants"

        Design: Difficulty/non_linear_state_machine/deduction_appeal_cycle_two_rounds
        """
        ctx, perf = _setup_performed(api)
        head_id = ctx["head"]["id"]
        deduction = apply_safety_deduction(perf["id"], ctx["safety"]["id"])

        appeal1 = appeal_deduction(deduction["id"], "coach-1",
                                   note="round 1", video_ref="vid-1")
        assert appeal1["round"] == 1
        resolve_appeal(appeal1["id"], head_id, "REJECTED")
        state = get_success_data(api.get_deduction(deduction["id"], DIRECTOR))
        assert state["status"] == "UPHELD"

        appeal2 = validate_success(api.resubmit_appeal(
            appeal1["id"], {"note": "round 2", "video_ref": "vid-2"},
            make_team_coach_headers("coach-1")), 201)
        assert appeal2["round"] == 2
        state = get_success_data(api.get_deduction(deduction["id"], DIRECTOR))
        assert state["status"] == "UNDER_APPEAL"

        resolve_appeal(appeal2["id"], head_id, "ACCEPTED")
        state = get_success_data(api.get_deduction(deduction["id"], DIRECTOR))
        assert state["status"] == "OVERTURNED"

    def test_round_two_appeal_cannot_be_resubmitted(self, api):
        """PRD §3.6: "Resubmission is allowed only when the rejected appeal's
        `round` is 1; a round-2 appeal is terminal when rejected, and
        resubmitting it is rejected with `ERR_APPEAL_NOT_RESUBMITTABLE`."

        Design: Corner/errors/round_two_appeal_cannot_be_resubmitted
        """
        ctx, perf = _setup_performed(api)
        head_id = ctx["head"]["id"]
        coach = make_team_coach_headers("coach-1")
        deduction = apply_safety_deduction(perf["id"], ctx["safety"]["id"])

        appeal1 = appeal_deduction(deduction["id"], "coach-1",
                                   note="r1", video_ref="v1")
        resolve_appeal(appeal1["id"], head_id, "REJECTED")
        appeal2 = validate_success(api.resubmit_appeal(
            appeal1["id"], {"note": "r2", "video_ref": "v2"}, coach), 201)
        resolve_appeal(appeal2["id"], head_id, "REJECTED")

        resp = api.resubmit_appeal(
            appeal2["id"], {"note": "r3", "video_ref": "v3"}, coach)
        validate_error(resp, ApiErrorId.ERR_APPEAL_NOT_RESUBMITTABLE)

    def test_appeal_window_inclusive_then_closed(self, api):
        """PRD §3.6: "The appeal window is strict: the logical now must be no
        later than 45 minutes after the deduction's `created_at`, the boundary
        inclusive; outside it the request is `ERR_APPEAL_WINDOW_CLOSED`."

        Design: Corner/errors/appeal_window_inclusive_then_closed
        """
        ctx = setup_live_event_with_checked_in_teams([
            {"coach_id": "coach-a", "name": "TA", "organization": "GymA",
             "athlete_name": "Ann"},
            {"coach_id": "coach-b", "name": "TB", "organization": "GymB",
             "athlete_name": "Bob", "athlete_dob": "2010-06-01"},
        ])
        safety_id = ctx["safety"]["id"]
        perf_a = ctx["teams"][0]["performance"]
        perf_b = ctx["teams"][1]["performance"]

        # Both deductions are created at the default logical clock
        # (2026-08-01T00:00:00Z) by mark-performed.
        mark_performance_performed(perf_a["id"], safety_id, 151, 0)
        mark_performance_performed(perf_b["id"], safety_id, 152, 0)
        deductions_a, _ = validate_paginated(
            api.list_performance_deductions(perf_a["id"], DIRECTOR))
        deductions_b, _ = validate_paginated(
            api.list_performance_deductions(perf_b["id"], DIRECTOR))
        ded_a, ded_b = deductions_a[0], deductions_b[0]

        # Exactly created_at + 45:00 — the inclusive boundary — succeeds.
        set_clock("2026-08-01T00:45:00Z")
        validate_success(api.create_appeal(
            ded_a["id"], {"note": "at the boundary", "video_ref": "vid-a"},
            make_team_coach_headers("coach-a")), 201)

        # One minute later the window is closed.
        set_clock("2026-08-01T00:46:00Z")
        resp = api.create_appeal(
            ded_b["id"], {"note": "too late", "video_ref": "vid-b"},
            make_team_coach_headers("coach-b"))
        validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED)

    def test_appeal_on_voided_deduction_rejected(self, api):
        """PRD §3.6: "Appealing a deduction not in `APPLIED` status is
        `ERR_DEDUCTION_NOT_APPLIED`."

        Design: Corner/errors/appeal_on_voided_deduction_rejected
        """
        ctx, perf = _setup_performed(api)
        head_id = ctx["head"]["id"]
        deduction = apply_safety_deduction(perf["id"], ctx["safety"]["id"])

        get_success_data(api.void_deduction(
            deduction["id"], make_head_judge_headers(head_id)))
        resp = api.create_appeal(
            deduction["id"], {"note": "too late", "video_ref": "vid-1"},
            make_team_coach_headers("coach-1"))
        validate_error(resp, ApiErrorId.ERR_DEDUCTION_NOT_APPLIED)

    def test_confirm_official_blocked_while_appeal_pending(self, api):
        """PRD §3.7: "from `SCORED` with any deduction of the performance
        still `UNDER_APPEAL`, `ERR_PENDING_APPEALS`."

        Design: Corner/state_machines/confirm_official_blocked_while_appeal_pending
        """
        ctx, perf = _setup_performed(api)
        safety_id = ctx["safety"]["id"]
        head_id = ctx["head"]["id"]

        deduction = apply_safety_deduction(perf["id"], safety_id)
        submit_full_panel(perf["id"], ctx["panel"], 8.0)
        appeal_deduction(deduction["id"], "coach-1")

        resp = api.confirm_official(perf["id"], make_head_judge_headers(head_id))
        validate_error(resp, ApiErrorId.ERR_PENDING_APPEALS)
        state = get_success_data(api.get_performance(perf["id"], DIRECTOR))
        assert state["status"] == "SCORED"


class TestEventStateGates:
    def test_pre_live_checkin_and_blocked_finalize_state_errors(self, api):
        """PRD §3.3: "the event must be `LIVE` (else `ERR_EVENT_NOT_LIVE`)"
        PRD §3.9: "The director may finalize only when three conditions hold
        simultaneously: every performance of the event is in a terminal state
        (`OFFICIAL`, `EXCLUDED`, or `CANCELLED`); no appeal in `SUBMITTED`
        status exists for any deduction of the event; and no bid in `OFFERED`
        status exists for any division of the event. Any violation is rejected
        with `ERR_FINALIZE_BLOCKED`."

        Design: Corner/errors/pre_live_checkin_and_blocked_finalize_state_errors
        """
        from test_helpers import (
            generate_schedule,
            setup_locked_team_with_verified_music,
        )
        event, division, panel, head, safety = setup_event_with_division()
        team, athlete, entry = setup_locked_team_with_verified_music(
            division, coach_id="coach-1")
        coach = make_team_coach_headers("coach-1")

        # Check-in while the event is REGISTRATION_CLOSED: not live yet.
        get_success_data(api.close_registration(event["id"], DIRECTOR))
        resp = api.check_in_team(team["id"], [athlete["id"]], coach)
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_LIVE)

        # Schedule + go live, then finalize with a SCHEDULED (non-terminal)
        # performance: blocked.
        division = get_success_data(api.get_division(division["id"], DIRECTOR))
        generate_schedule(division["id"], division["version"])
        get_success_data(api.go_live(event["id"], DIRECTOR))
        resp = api.finalize_event(event["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_FINALIZE_BLOCKED)


class TestAppealCycleSecondAngle:
    def test_upheld_deduction_counts_in_all_variants(self, api):
        """PRD §3.6: "A `decision` of `REJECTED` moves the appeal to
        `REJECTED` and the deduction to `UPHELD`, where it remains counted in
        all score variants."
        PRD §3.6: "PROVISIONAL counts deductions in `APPLIED`, `UNDER_APPEAL`,
        or `UPHELD` status; OFFICIAL counts only `APPLIED` and `UPHELD`"

        Design: Difficulty/non_linear_state_machine/deduction_appeal_cycle_two_rounds
        """
        ctx, perf = _setup_performed(api)
        head_id = ctx["head"]["id"]
        deduction = apply_safety_deduction(perf["id"], ctx["safety"]["id"])
        submit_full_panel(perf["id"], ctx["panel"], 8.0)  # base 80.00

        appeal1 = appeal_deduction(deduction["id"], "coach-1",
                                   note="round 1", video_ref="vid-1")
        resolve_appeal(appeal1["id"], head_id, "REJECTED")
        state = get_success_data(api.get_deduction(deduction["id"], DIRECTOR))
        assert state["status"] == "UPHELD"

        # UPHELD counts in both variants: official 80.00 - 2.00 = 78.00.
        final = get_success_data(api.get_performance(perf["id"], DIRECTOR))
        assert final["provisional_score"] == pytest.approx(78.00, abs=0.001)
        official = validate_success(api.confirm_official(
            perf["id"], make_head_judge_headers(head_id)), 200)
        assert official["official_score"] == pytest.approx(78.00, abs=0.001)


class TestCrossEntitySecondAngles:
    def test_sheet_create_legal_after_mark_performed(self, api):
        """PRD §3.5: "A `Judge` creates their own **ScoreSheet** against a
        `PERFORMED` or `SCORED` performance"
        PRD §3.5: "A new sheet is born in `DRAFT`, its `judge_id` pinned to
        the acting `X-User-ID`, its `performance_id` taken from the path."

        Design: Difficulty/cross_entity_state_dependency/score_sheet_submit_gated_by_performance_state
        """
        ctx, perf = _setup_performed(api)
        sheet = validate_success(api.create_score_sheet(
            perf["id"],
            {"building_difficulty": 8.0, "building_execution": 8.0,
             "tumbling_difficulty": 8.0, "overall_impression": 8.0},
            make_judge_headers(ctx["panel"][0]["id"])), 201)
        assert sheet["status"] == "DRAFT"
        assert sheet["judge_id"] == ctx["panel"][0]["id"]
        assert sheet["performance_id"] == perf["id"]

    def test_mark_performed_succeeds_when_team_checked_in(self, api):
        """PRD §3.5: "Marking performed moves the performance from
        `SCHEDULED` to `PERFORMED`, increments its `version`"
        PRD §3.5: "The operation requires the performance to be `SCHEDULED`
        (otherwise `ERR_INVALID_STATE`), the owning event to be `LIVE`
        (`ERR_EVENT_NOT_LIVE`), and the team to be `CHECKED_IN`
        (`ERR_TEAM_NOT_CHECKED_IN`)."

        Design: Difficulty/cross_entity_state_dependency/mark_performed_gated_by_team_checkin_state
        """
        ctx = setup_live_event_with_checked_in_teams(
            [{"coach_id": "coach-1", "name": "T1", "organization": "Gym1"}])
        perf = ctx["teams"][0]["performance"]
        before = perf["version"]

        marked = validate_success(api.mark_performed(
            perf["id"], {"actual_duration_seconds": 150,
                         "boundary_violations": 0},
            make_safety_judge_headers(ctx["safety"]["id"])), 200)
        assert marked["status"] == "PERFORMED"
        assert marked["version"] == before + 1
