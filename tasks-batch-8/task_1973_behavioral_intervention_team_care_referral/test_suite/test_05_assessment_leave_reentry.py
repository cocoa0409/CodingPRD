"""Mandated assessment, leave-decision cascade, re-entry petition loops.

PRD §3.5 (assessment ordering, outcome recording, EXPIRED sweep) and §3.6
(leave grant/deny, re-entry petition and decision).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    complete_checkin,
    file_reentry_petition,
    get_case_version,
    get_scheduled_checkin,
    get_success_data,
    order_assessment,
    set_clock,
    setup_case_in_leave_decision,
    setup_case_in_mandated_assessment,
    setup_case_on_leave,
    setup_case_plan_active,
    setup_reentry_pending,
    setup_staff_group,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestNotClearedCascade:
    def test_not_cleared_fires_four_link_leave_decision_chain(self, api):
        """PRD §3.5: "`NOT_CLEARED` fires a four-link cascade in strict order:
        first the assessment completes with outcome `NOT_CLEARED`; second,
        caused by the first, the case moves to `LEAVE_DECISION` with `version`
        incremented by one; third, caused by the second, the system creates a
        `LeaveDecision` in `PENDING` naming the case and recording the
        assessment's `ordered_by` as the decision's `requested_by`, with
        `decided_by`, `decision`, `rationale`, and `decided_at` all null for
        now; fourth, caused by the third, the pending leave decision suspends
        follow-up cadence, cancelling every `SCHEDULED` check-in for the case."

        Design: Difficulty/transitive_cascade/not_cleared_outcome_to_leave_decision_chain
        """
        ctx = setup_staff_group(evaluator=True)
        setup_case_in_mandated_assessment(ctx, external_ref="S6001",
                                          due_at="2026-08-10T00:00:00Z")
        k1 = get_scheduled_checkin(ctx, ctx["case_id"])
        get_success_data(
            api.record_assessment_outcome(
                ctx["assessment"]["id"],
                {"outcome": "NOT_CLEARED",
                 "findings_summary": "does not meet criteria to remain enrolled"},
                ctx["ev_headers"],
            )
        )
        assessment = get_success_data(
            api.get_mandated_assessment(ctx["assessment"]["id"], ctx["chair_headers"])
        )
        assert assessment["status"] == "COMPLETED"
        case = get_success_data(api.get_care_case(ctx["case_id"], ctx["chair_headers"]))
        assert case["status"] == "LEAVE_DECISION"
        decisions, meta = validate_paginated(
            api.list_leave_decisions(ctx["chair_headers"], params={"case_id": ctx["case_id"]})
        )
        assert meta["total_count"] == 1
        assert decisions[0]["status"] == "PENDING"
        assert decisions[0]["requested_by"] == ctx["chair"]["id"]
        assert decisions[0]["decided_by"] is None
        checkin = get_success_data(
            api.get_follow_up_checkin(k1["id"], ctx["chair_headers"])
        )
        assert checkin["status"] == "CANCELLED"

    def test_not_cleared_requested_by_is_ordering_chair(self, api):
        """PRD §3.5: "`NOT_CLEARED` fires a four-link cascade in strict order:
        first the assessment completes with outcome `NOT_CLEARED`; second,
        caused by the first, the case moves to `LEAVE_DECISION` with `version`
        incremented by one; third, caused by the second, the system creates a
        `LeaveDecision` in `PENDING` naming the case and recording the
        assessment's `ordered_by` as the decision's `requested_by`, with
        `decided_by`, `decision`, `rationale`, and `decided_at` all null for
        now; fourth, caused by the third, the pending leave decision suspends
        follow-up cadence, cancelling every `SCHEDULED` check-in for the case."

        Design: Difficulty/transitive_cascade/not_cleared_outcome_to_leave_decision_chain
        """
        ctx = setup_staff_group(evaluator=True)
        setup_case_in_leave_decision(ctx, external_ref="S6001B")
        decision = ctx["leave_decision"]
        assert decision["requested_by"] == ctx["chair"]["id"]
        assert decision["status"] == "PENDING"
        assert decision["decision"] is None
        assert decision["decided_at"] is None


class TestAssessmentExpirySweep:
    def test_clock_sweep_expires_assessment_and_fires_cascade(self, api):
        """PRD §3.5: "When a sweep (§2.5) finds an assessment still `SCHEDULED`
        with `due_at` in the past, the assessment transitions to `EXPIRED` —
        terminal, like `COMPLETED` — and the identical four-link cascade
        follows: case to `LEAVE_DECISION`, `PENDING` leave decision created
        with the same `requested_by`, scheduled check-ins cancelled."

        Design: Corner/state_machines/assessment_expiry_auto_transition
        """
        ctx = setup_staff_group(evaluator=True)
        setup_case_in_mandated_assessment(ctx, external_ref="S0009",
                                          due_at="2026-08-05T00:00:00Z")
        k1 = get_scheduled_checkin(ctx, ctx["case_id"])
        set_clock(ctx, "2026-08-06T00:00:00Z")
        assessment = get_success_data(
            api.get_mandated_assessment(ctx["assessment"]["id"], ctx["chair_headers"])
        )
        assert assessment["status"] == "EXPIRED"
        case = get_success_data(api.get_care_case(ctx["case_id"], ctx["chair_headers"]))
        assert case["status"] == "LEAVE_DECISION"
        decisions, meta = validate_paginated(
            api.list_leave_decisions(ctx["chair_headers"], params={"case_id": ctx["case_id"]})
        )
        assert meta["total_count"] == 1
        assert decisions[0]["status"] == "PENDING"
        assert decisions[0]["requested_by"] == ctx["chair"]["id"]
        checkin = get_success_data(
            api.get_follow_up_checkin(k1["id"], ctx["chair_headers"])
        )
        assert checkin["status"] == "CANCELLED"


class TestAssessmentSlotOccupation:
    def test_second_assessment_while_slot_occupied_rejected(self, api):
        """PRD §3.5: "Four checks guard the order, surfacing in §2.10 order:
        the case must be `PLAN_ACTIVE` (`ERR_CASE_NOT_PLAN_ACTIVE`); the
        evaluator must differ from the ordering chair
        (`ERR_EVALUATOR_SAME_AS_ORDERER`, 400); `due_at` must be strictly later
        than now and no later than fourteen days from now
        (`ERR_ASSESSMENT_DUE_WINDOW_VIOLATION`, 422); and no other `SCHEDULED`
        assessment for the case may occupy the slot — the closed interval from
        the moment that earlier assessment was ordered through its `due_at`
        must not cover the current instant (`ERR_ASSESSMENT_ALREADY_PENDING`,
        409)."
        PRD §3.5: "the case advances to `MANDATED_ASSESSMENT` with its
        `version` incremented by one" — so while the first assessment still
        occupies its slot, the second order trips the rank-5 state gate
        (`ERR_CASE_NOT_PLAN_ACTIVE`) before the slot occupation check.

        Design: Difficulty/resource_temporal_overlap/assessment_slot_closed_interval_overlap
        """
        ctx = setup_staff_group(evaluator=True, dean=True)
        setup_case_plan_active(ctx, external_ref="S1002", category="SELF_HARM_RISK",
                               dims=(20, 20, 5, 5))
        a1 = get_success_data(order_assessment(ctx, ctx["case_id"], due_at="2026-08-10T00:00:00Z"))
        assert a1["status"] == "SCHEDULED"
        resp = order_assessment(ctx, ctx["case_id"], due_at="2026-08-12T00:00:00Z",
                                rationale="second while occupied")
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_PLAN_ACTIVE)

    def test_expired_assessment_releases_the_slot(self, api):
        """PRD §3.5: "When a sweep (§2.5) finds an assessment still `SCHEDULED`
        with `due_at` in the past, the assessment transitions to `EXPIRED` —
        terminal, like `COMPLETED` — and the identical four-link cascade
        follows: case to `LEAVE_DECISION`, `PENDING` leave decision created
        with the same `requested_by`, scheduled check-ins cancelled."
        PRD §3.6: "Denying leave moves the decision to `DENIED` (with
        `decided_by` and `decided_at` likewise recorded), returns the case to
        `PLAN_ACTIVE` with `version` incremented by one, and restarts follow-up
        cadence with a fresh check-in due exactly the current tier's cadence
        after the decision."

        Design: Difficulty/resource_temporal_overlap/assessment_slot_closed_interval_overlap
        """
        ctx = setup_staff_group(evaluator=True, dean=True)
        setup_case_plan_active(ctx, external_ref="S1002B", category="SELF_HARM_RISK",
                               dims=(20, 20, 5, 5))
        a1 = get_success_data(order_assessment(ctx, ctx["case_id"], due_at="2026-08-10T00:00:00Z"))
        # Advance past due_at: sweep expires a1 and fires the leave cascade.
        set_clock(ctx, "2026-08-11T00:00:00Z")
        a1_after = get_success_data(
            api.get_mandated_assessment(a1["id"], ctx["chair_headers"])
        )
        assert a1_after["status"] == "EXPIRED"
        decisions, meta = validate_paginated(
            api.list_leave_decisions(ctx["chair_headers"], params={"case_id": ctx["case_id"]})
        )
        assert meta["total_count"] == 1
        ld1 = decisions[0]
        assert ld1["status"] == "PENDING"
        denied = validate_success(
            api.decide_leave(ld1["id"], {"decision": "DENY_LEAVE",
                                         "rationale": "insufficient grounds"},
                             ctx["dean_headers"])
        )
        assert denied["status"] == "DENIED"
        a3 = get_success_data(order_assessment(ctx, ctx["case_id"], due_at="2026-08-20T00:00:00Z",
                                               rationale="third after release"))
        assert a3["status"] == "SCHEDULED"


class TestAssessmentDueWindow:
    def test_due_at_exactly_fourteen_days_accepted(self, api):
        """PRD §3.5: "`due_at` must be strictly later than now and no later
        than fourteen days from now (`ERR_ASSESSMENT_DUE_WINDOW_VIOLATION`,
        422)"

        Design: Corner/validations/assessment_due_window_boundary
        """
        ctx = setup_staff_group(evaluator=True)
        setup_case_plan_active(ctx, external_ref="S0019", category="SELF_HARM_RISK",
                               dims=(20, 20, 5, 5))
        # Default clock is 2026-08-01T00:00:00Z; +14 days exactly.
        a1 = get_success_data(order_assessment(ctx, ctx["case_id"],
                                               due_at="2026-08-15T00:00:00Z",
                                               rationale="exactly +14d"))
        assert a1["status"] == "SCHEDULED"

    def test_due_at_one_second_past_fourteen_days_rejected(self, api):
        """PRD §3.5: "`due_at` must be strictly later than now and no later
        than fourteen days from now (`ERR_ASSESSMENT_DUE_WINDOW_VIOLATION`,
        422)"

        Design: Corner/validations/assessment_due_window_boundary
        """
        ctx = setup_staff_group(evaluator=True)
        setup_case_plan_active(ctx, external_ref="S0020", category="SELF_HARM_RISK",
                               dims=(20, 20, 5, 5))
        resp = order_assessment(ctx, ctx["case_id"], due_at="2026-08-15T00:00:01Z",
                                rationale="one second past")
        validate_error(resp, ApiErrorId.ERR_ASSESSMENT_DUE_WINDOW_VIOLATION)


class TestEvaluatorSameAsOrderer:
    def test_evaluator_equal_to_orderer_rejected(self, api):
        """PRD §3.5: "Four checks guard the order, surfacing in §2.10 order:
        the case must be `PLAN_ACTIVE` (`ERR_CASE_NOT_PLAN_ACTIVE`); the
        evaluator must differ from the ordering chair
        (`ERR_EVALUATOR_SAME_AS_ORDERER`, 400); `due_at` must be strictly later
        than now and no later than fourteen days from now
        (`ERR_ASSESSMENT_DUE_WINDOW_VIOLATION`, 422); and no other `SCHEDULED`
        assessment for the case may occupy the slot — the closed interval from
        the moment that earlier assessment was ordered through its `due_at`
        must not cover the current instant (`ERR_ASSESSMENT_ALREADY_PENDING`,
        409)."

        Design: Corner/validations/evaluator_same_as_orderer_rejected
        """
        ctx = setup_staff_group(evaluator=True)
        setup_case_plan_active(ctx, external_ref="S0021", category="SELF_HARM_RISK",
                               dims=(20, 20, 5, 5))
        resp = api.create_mandated_assessment(
            {
                "case_id": ctx["case_id"],
                "evaluator_id": ctx["chair"]["id"],
                "due_at": "2026-08-10T00:00:00Z",
                "rationale": "self-assigned",
            },
            ctx["chair_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_EVALUATOR_SAME_AS_ORDERER)


class TestReentryDenialLoop:
    def test_denied_reentry_returns_case_to_on_leave(self, api):
        """PRD §3.6: "Denial is the quiet branch: `outcome` `DENIED` lands the
        evaluation in `DENIED` and returns the case to `ON_LEAVE` with
        `version` incremented by one — the re-entry denial loop, leaving the
        student on leave and free to petition again later."

        Design: Corner/state_machines/reentry_denied_returns_to_on_leave
        """
        ctx = setup_staff_group(evaluator=True, dean=True, dean2=True)
        setup_reentry_pending(ctx, external_ref="S0010")
        denied = validate_success(
            api.decide_reentry_evaluation(
                ctx["reentry"]["id"],
                {"outcome": "DENIED", "rationale": "insufficient treatment engagement"},
                ctx["dean2_headers"],
            )
        )
        assert denied["status"] == "DENIED"
        case = get_success_data(api.get_care_case(ctx["case_id"], ctx["chair_headers"]))
        assert case["status"] == "ON_LEAVE"
        student = get_success_data(api.get_student(ctx["student"]["id"], ctx["chair_headers"]))
        assert student["enrollment_status"] == "LEAVE_OF_ABSENCE"


class TestReentryConditionsRequired:
    def test_approval_without_conditions_rejected(self, api):
        """PRD §3.6: "Approving requires `outcome` `APPROVED_WITH_CONDITIONS`
        together with a non-empty `conditions` list — an approval with empty or
        missing conditions is rejected with `ERR_CONDITIONS_REQUIRED` (400) —
        and it fires the widest cascade in the system"

        Design: Corner/validations/conditions_required_on_reentry_approval
        """
        ctx = setup_staff_group(evaluator=True, dean=True, dean2=True)
        setup_reentry_pending(ctx, external_ref="S0022")
        resp = api.decide_reentry_evaluation(
            ctx["reentry"]["id"],
            {"outcome": "APPROVED_WITH_CONDITIONS", "rationale": "no conditions attached"},
            ctx["dean2_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CONDITIONS_REQUIRED)
        evaluation = get_success_data(
            api.get_reentry_evaluation(ctx["reentry"]["id"], ctx["chair_headers"])
        )
        assert evaluation["status"] == "PENDING"


class TestReentryAlreadyPending:
    def test_second_petition_while_pending_rejected(self, api):
        """PRD §3.6: "Only one petition may be live at a time: if a `PENDING`
        re-entry evaluation already exists for the case, the filing is rejected
        with `ERR_REENTRY_ALREADY_PENDING` (409)."
        PRD §3.6: "the case moves `ON_LEAVE` → `REENTRY_REVIEW` with `version`
        incremented by one" — so while the first petition is `PENDING` the case
        sits in `REENTRY_REVIEW`, and the second filing trips the rank-5 state
        gate ("files a re-entry evaluation against an `ON_LEAVE` case
        (`ERR_CASE_NOT_ON_LEAVE` otherwise)") before the rank-9
        pending-petition exclusion of §2.10.

        Design: Corner/errors/reentry_already_pending_rejected
        """
        ctx = setup_staff_group(evaluator=True, dean=True)
        setup_reentry_pending(ctx, external_ref="S0026")
        fresh_version = get_case_version(ctx, ctx["case_id"])
        resp = api.create_reentry_evaluation(
            {
                "case_id": ctx["case_id"],
                "expected_case_version": fresh_version,
                "petition_summary": "second",
            },
            ctx["cm_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_ON_LEAVE)


class TestLeaveDecisionRoleGate:
    def test_chair_cannot_decide_leave(self, api):
        """PRD §3.6: "A `PENDING` leave decision belongs to the
        `DeanOfStudents`, who submits a `decision` of `GRANT_LEAVE` or
        `DENY_LEAVE` with a `rationale`."
        PRD §2.10: "2. **Role authorization** — the caller's role listed for
        the endpoint; failures yield `ERR_FORBIDDEN` (403)."

        Design: Corner/rbac/chair_cannot_decide_leave
        """
        ctx = setup_staff_group(evaluator=True)
        setup_case_in_leave_decision(ctx, external_ref="S0031")
        resp = api.decide_leave(
            ctx["leave_decision"]["id"],
            {"decision": "GRANT_LEAVE", "rationale": "chair attempt"},
            ctx["chair_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
