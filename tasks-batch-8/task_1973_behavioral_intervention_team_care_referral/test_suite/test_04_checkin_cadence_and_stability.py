"""Follow-up cadence, stability streaks, MISSED sweep, escalation cycle.

PRD §3.4 pins the tier cadence constants, the STABLE/ESCALATED branches, the
MISSED sweep grace rule, and the single-scheduled-check-in invariant.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    accumulate_stable_checkins,
    assert_timestamp_instant,
    complete_checkin,
    complete_stable,
    get_scheduled_checkin,
    get_success_data,
    score_case,
    set_clock,
    setup_case_plan_active,
    setup_staff_group,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCadenceConstants:
    def test_high_tier_checkin_due_seven_days_after_approval(self, api):
        """PRD §3.4: "While a plan is active, the team keeps touching the
        student on a schedule keyed to the case's current risk tier: an
        `IMMINENT` case is checked every 2 days, a `HIGH` case every 7 days, a
        `MODERATE` case every 14 days, and a `LOW` case every 30 days."
        PRD §3.3: "Finally, follow-up cadence resets: every `SCHEDULED`
        check-in for the case is `CANCELLED`, and one fresh check-in is
        created, due exactly the current tier's cadence (§3.4) after the
        approval instant."

        Design: Corner/calculations/cadence_constants_applied_high_tier
        """
        ctx = setup_staff_group()
        setup_case_plan_active(ctx, external_ref="S0013", category="SELF_HARM_RISK",
                               dims=(20, 20, 5, 5))
        case = get_success_data(api.get_care_case(ctx["case_id"], ctx["chair_headers"]))
        assert case["current_risk_tier"] == "HIGH"
        checkin = get_scheduled_checkin(ctx, ctx["case_id"])
        # Approval at the default clock 2026-08-01T00:00:00Z + 7 days.
        assert_timestamp_instant(checkin["due_at"], "2026-08-08T00:00:00Z")


class TestEscalationRetriageCycle:
    def test_escalated_checkin_returns_case_to_triaged(self, api):
        """PRD §3.4: "An `ESCALATED` outcome resets
        `consecutive_stable_checkins` to zero, creates no successor, supersedes
        the case's `ACTIVE` plan to `SUPERSEDED`, and pulls the case
        `PLAN_ACTIVE` → `TRIAGED`, forcing fresh triage before any new plan may
        be drafted."

        Design: Difficulty/non_linear_state_machine/care_case_escalation_retriage_cycle
        """
        ctx = setup_staff_group()
        setup_case_plan_active(ctx, external_ref="S5001", dims=(0, 0, 0, 0))
        complete_stable(ctx, ctx["case_id"])
        k2 = get_scheduled_checkin(ctx, ctx["case_id"])
        completed = get_success_data(
            complete_checkin(ctx, k2["id"], outcome="ESCALATED", note="deteriorating")
        )
        assert completed["status"] == "COMPLETED"
        case = get_success_data(api.get_care_case(ctx["case_id"], ctx["chair_headers"]))
        assert case["status"] == "TRIAGED"
        assert case["consecutive_stable_checkins"] == 0
        plan = get_success_data(
            api.get_intervention_plan(ctx["plan"]["id"], ctx["chair_headers"])
        )
        assert plan["status"] == "SUPERSEDED"

    def test_escalation_creates_no_successor_and_case_accepts_reassessment(self, api):
        """PRD §3.4: "An `ESCALATED` outcome resets
        `consecutive_stable_checkins` to zero, creates no successor, supersedes
        the case's `ACTIVE` plan to `SUPERSEDED`, and pulls the case
        `PLAN_ACTIVE` → `TRIAGED`, forcing fresh triage before any new plan may
        be drafted."
        PRD §3.2: "The first scoring also advances the case from `INTAKE` to
        `TRIAGED`; reassessments are a self-loop that leave the case in
        `TRIAGED`."

        Design: Difficulty/non_linear_state_machine/care_case_escalation_retriage_cycle
        """
        ctx = setup_staff_group()
        setup_case_plan_active(ctx, external_ref="S5001B", dims=(0, 0, 0, 0))
        k1 = get_scheduled_checkin(ctx, ctx["case_id"])
        get_success_data(complete_checkin(ctx, k1["id"], outcome="ESCALATED"))
        data, meta = validate_paginated(
            api.list_follow_up_checkins(
                ctx["chair_headers"],
                params={"case_id": ctx["case_id"], "status": "SCHEDULED"},
            )
        )
        assert meta["total_count"] == 0
        scoring = score_case(ctx, ctx["case_id"], mode="REASSESSMENT",
                             rationale="re-triage after escalation")
        # 0.6*0 + 0.4*0.0 = 0.0 LOW; case remains TRIAGED (re-enterable).
        assert scoring["score"] == pytest.approx(0.0, abs=1e-9)
        assert scoring["tier"] == "LOW"
        case = get_success_data(api.get_care_case(ctx["case_id"], ctx["chair_headers"]))
        assert case["status"] == "TRIAGED"


class TestSingleScheduledCheckinInvariant:
    def test_stable_completion_consumes_and_restores_the_slot(self, api):
        """PRD §3.4: "A `STABLE` outcome increments the case's
        `consecutive_stable_checkins` by one and schedules the successor
        check-in described above."
        PRD §3.4: "Four of the five anchor the new `due_at` to the scheduling
        moment plus the cadence for the case's `current_risk_tier`; the two
        exceptions are the `MISSED` sweep, whose successor is anchored to the
        missed check-in's own `due_at` plus the cadence rather than to the
        sweep instant, and re-entry approval, which uses a fixed seven-day
        horizon regardless of tier."

        Design: Difficulty/compensating_invariant/single_scheduled_checkin_per_case
        """
        ctx = setup_staff_group()
        setup_case_plan_active(ctx, external_ref="S1102", dims=(0, 0, 0, 0))
        k1 = get_scheduled_checkin(ctx, ctx["case_id"])
        assert_timestamp_instant(k1["due_at"], "2026-08-31T00:00:00Z")  # approval + 30 days at LOW
        completed = get_success_data(complete_checkin(ctx, k1["id"], outcome="STABLE"))
        assert completed["status"] == "COMPLETED"
        data, meta = validate_paginated(
            api.list_follow_up_checkins(
                ctx["chair_headers"],
                params={"case_id": ctx["case_id"], "status": "SCHEDULED"},
            )
        )
        assert meta["total_count"] == 1
        assert data[0]["id"] != k1["id"]

    def test_stable_completion_increments_streak_and_sets_completed_at(self, api):
        """PRD §3.4: "A `STABLE` outcome increments the case's
        `consecutive_stable_checkins` by one and schedules the successor
        check-in described above."
        PRD §3.4: "Completion may happen early — at or before `due_at` — and
        records an `outcome` of `STABLE` or `ESCALATED` together with a
        free-text `note`; the check-in lands in `COMPLETED` with `completed_at`
        set to the completion instant."

        Design: Difficulty/compensating_invariant/single_scheduled_checkin_per_case
        """
        ctx = setup_staff_group()
        setup_case_plan_active(ctx, external_ref="S1102B", dims=(0, 0, 0, 0))
        k1 = get_scheduled_checkin(ctx, ctx["case_id"])
        completed = get_success_data(complete_checkin(ctx, k1["id"], outcome="STABLE"))
        assert_timestamp_instant(completed["completed_at"], "2026-08-01T00:00:00Z")
        k2 = get_scheduled_checkin(ctx, ctx["case_id"])
        assert_timestamp_instant(k2["due_at"], "2026-08-31T00:00:00Z")  # completed_at + 30 days
        case = get_success_data(api.get_care_case(ctx["case_id"], ctx["chair_headers"]))
        assert case["consecutive_stable_checkins"] == 1


class TestCheckinIdempotency:
    def test_completing_same_checkin_twice_rejected(self, api):
        """PRD §3.4: "Completing a check-in is the assigned manager's job and
        nobody else's: the caller's `X-User-ID` must match the case's
        `assigned_case_manager_id` (`ERR_NOT_ASSIGNED_CASE_MANAGER`), the
        check-in must still be `SCHEDULED` (`ERR_CHECKIN_NOT_SCHEDULED`), and
        the case must be `PLAN_ACTIVE` (`ERR_CASE_NOT_PLAN_ACTIVE`)."

        Design: Corner/state_machines/checkin_complete_twice_returns_invalid_state
        """
        ctx = setup_staff_group()
        setup_case_plan_active(ctx, external_ref="S0008", dims=(0, 0, 0, 0))
        k1 = get_scheduled_checkin(ctx, ctx["case_id"])
        first = validate_success(complete_checkin(ctx, k1["id"], outcome="STABLE"))
        assert first["status"] == "COMPLETED"
        second = complete_checkin(ctx, k1["id"], outcome="STABLE", note="duplicate")
        validate_error(second, ApiErrorId.ERR_CHECKIN_NOT_SCHEDULED)
        data, meta = validate_paginated(
            api.list_follow_up_checkins(
                ctx["chair_headers"],
                params={"case_id": ctx["case_id"], "status": "SCHEDULED"},
            )
        )
        assert meta["total_count"] == 1


class TestMissedSweepGraceBoundary:
    def test_missed_fires_only_strictly_after_grace_day(self, api):
        """PRD §3.4: "When the logical clock passes more than one full day
        beyond a `SCHEDULED` check-in's `due_at`, the sweep marks it `MISSED` —
        `MISSED` is a status, never a recordable completion `outcome` — resets
        the case's `consecutive_stable_checkins` to zero, and schedules the
        anchored successor described above."

        Design: Corner/calculations/missed_checkin_grace_boundary
        """
        ctx = setup_staff_group()
        setup_case_plan_active(ctx, external_ref="S0014", dims=(0, 0, 0, 0))
        complete_stable(ctx, ctx["case_id"])
        k2 = get_scheduled_checkin(ctx, ctx["case_id"])
        assert_timestamp_instant(k2["due_at"], "2026-08-31T00:00:00Z")
        # At exactly due_at + 1 day the strictly-greater rule has not fired.
        set_clock(ctx, "2026-09-01T00:00:00Z")
        at_grace = get_success_data(
            api.get_follow_up_checkin(k2["id"], ctx["chair_headers"])
        )
        assert at_grace["status"] == "SCHEDULED"

    def test_one_second_past_grace_marks_missed_and_schedules_anchored_successor(self, api):
        """PRD §3.4: "When the logical clock passes more than one full day
        beyond a `SCHEDULED` check-in's `due_at`, the sweep marks it `MISSED` —
        `MISSED` is a status, never a recordable completion `outcome` — resets
        the case's `consecutive_stable_checkins` to zero, and schedules the
        anchored successor described above."
        PRD §3.4: "Four of the five anchor the new `due_at` to the scheduling
        moment plus the cadence for the case's `current_risk_tier`; the two
        exceptions are the `MISSED` sweep, whose successor is anchored to the
        missed check-in's own `due_at` plus the cadence rather than to the
        sweep instant, and re-entry approval, which uses a fixed seven-day
        horizon regardless of tier."

        Design: Corner/calculations/missed_checkin_grace_boundary
        """
        ctx = setup_staff_group()
        setup_case_plan_active(ctx, external_ref="S0014B", dims=(0, 0, 0, 0))
        complete_stable(ctx, ctx["case_id"])
        k2 = get_scheduled_checkin(ctx, ctx["case_id"])
        assert_timestamp_instant(k2["due_at"], "2026-08-31T00:00:00Z")
        set_clock(ctx, "2026-09-01T00:00:01Z")
        after = get_success_data(
            api.get_follow_up_checkin(k2["id"], ctx["chair_headers"])
        )
        assert after["status"] == "MISSED"
        k3 = get_scheduled_checkin(ctx, ctx["case_id"])
        # Anchored to the missed check-in's due_at + 30 days, not the sweep instant.
        assert_timestamp_instant(k3["due_at"], "2026-09-30T00:00:00Z")
        case = get_success_data(api.get_care_case(ctx["case_id"], ctx["chair_headers"]))
        assert case["consecutive_stable_checkins"] == 0


class TestClosureBoundary:
    def test_close_rejected_at_two_stable_checkins(self, api):
        """PRD §3.8: "A `BITChair` may close a case only when every element of
        the eligibility aggregate holds: the case is `PLAN_ACTIVE`
        (`ERR_CASE_NOT_PLAN_ACTIVE` otherwise); `consecutive_stable_checkins`
        is at least three — exactly three qualifies; `current_risk_tier` is
        `LOW`; no `SCHEDULED` mandated assessment exists for the case; no
        `PENDING` leave decision exists; and no `PENDING` re-entry evaluation
        exists."

        Design: Difficulty/boundary_precision_check/closure_at_exactly_three_stable_checkins
        """
        ctx = setup_staff_group()
        setup_case_plan_active(ctx, external_ref="S8003", dims=(0, 0, 0, 0))
        accumulate_stable_checkins(ctx, ctx["case_id"], 2)
        resp = api.close_care_case(ctx["case_id"], ctx["chair_headers"])
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_CLOSABLE)

    def test_close_succeeds_at_exactly_three_stable_checkins(self, api):
        """PRD §3.8: "A `BITChair` may close a case only when every element of
        the eligibility aggregate holds: the case is `PLAN_ACTIVE`
        (`ERR_CASE_NOT_PLAN_ACTIVE` otherwise); `consecutive_stable_checkins`
        is at least three — exactly three qualifies; `current_risk_tier` is
        `LOW`; no `SCHEDULED` mandated assessment exists for the case; no
        `PENDING` leave decision exists; and no `PENDING` re-entry evaluation
        exists."
        PRD §3.8: "Closure sets the case to `CLOSED`, stamps `closed_at` with
        the closing instant (null throughout the case's open life), increments
        `version` by one, and cancels every `SCHEDULED` check-in."

        Design: Difficulty/boundary_precision_check/closure_at_exactly_three_stable_checkins
        """
        ctx = setup_staff_group()
        setup_case_plan_active(ctx, external_ref="S8003B", dims=(0, 0, 0, 0))
        accumulate_stable_checkins(ctx, ctx["case_id"], 3)
        case = get_success_data(api.get_care_case(ctx["case_id"], ctx["chair_headers"]))
        assert case["consecutive_stable_checkins"] == 3
        assert case["current_risk_tier"] == "LOW"
        closed = validate_success(
            api.close_care_case(ctx["case_id"], ctx["chair_headers"])
        )
        assert closed["status"] == "CLOSED"
        assert_timestamp_instant(closed["closed_at"], "2026-08-01T00:00:00Z")


class TestAssignManagerOwnership:
    def test_reassignment_retargets_completion_ownership(self, api):
        """PRD §3.1: "A `BITChair` may assign or reassign a case's manager at
        any time by supplying a fresh `case_manager_id`; the case's
        `assigned_case_manager_id` updates and its `version` increments by
        one."
        PRD §3.4: "Completing a check-in is the assigned manager's job and
        nobody else's: the caller's `X-User-ID` must match the case's
        `assigned_case_manager_id` (`ERR_NOT_ASSIGNED_CASE_MANAGER`), the
        check-in must still be `SCHEDULED` (`ERR_CHECKIN_NOT_SCHEDULED`), and
        the case must be `PLAN_ACTIVE` (`ERR_CASE_NOT_PLAN_ACTIVE`)."

        Design: Corner/endpoints/assign_manager_retargets_completion_ownership
        """
        ctx = setup_staff_group(case_manager2=True)
        setup_case_plan_active(ctx, external_ref="S0024", dims=(0, 0, 0, 0))
        k1 = get_scheduled_checkin(ctx, ctx["case_id"])
        updated = validate_success(
            api.assign_case_manager(
                ctx["case_id"], {"case_manager_id": ctx["cm2"]["id"]},
                ctx["chair_headers"],
            )
        )
        assert updated["assigned_case_manager_id"] == ctx["cm2"]["id"]
        old_attempt = complete_checkin(ctx, k1["id"], outcome="STABLE", note="old manager")
        validate_error(old_attempt, ApiErrorId.ERR_NOT_ASSIGNED_CASE_MANAGER)
        new_attempt = validate_success(
            complete_checkin(ctx, k1["id"], outcome="STABLE", note="new manager",
                             completer="cm2")
        )
        assert new_attempt["status"] == "COMPLETED"
