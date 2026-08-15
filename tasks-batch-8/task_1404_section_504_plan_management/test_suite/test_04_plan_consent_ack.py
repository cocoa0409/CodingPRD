"""Plan drafting, parent consent, teacher acknowledgment, OCC on the plan, and
the cyclic review loops (PRD §2.7, §2.9, §3.3, §3.4, §3.6)."""
from datetime import datetime, timedelta

from test_helpers import (
    ApiErrorId,
    activate_plan,
    add_accommodation,
    create_draft_plan,
    create_student_for,
    get_plan_version,
    get_success_data,
    grant_plan_parent_consent,
    make_coordinator_headers,
    make_teacher_headers,
    pipeline_to_determination,
    schedule_review,
    setup_active_plan,
    setup_school_with_staff,
    start_review_now,
    submit_plan,
    submit_referral,
    validate_error,
    validate_success,
)


def _draft_plan_with_accommodation(api, train_teacher=True, num_teachers=1):
    """School + student + ELIGIBLE evaluation + DRAFT plan + one accommodation.

    Returns (ctx, plan, accommodation). The plan is left in DRAFT.
    """
    ctx = setup_school_with_staff(num_teachers=num_teachers, train_all=train_teacher)
    co = ctx["coordinator"]
    student = create_student_for(ctx["school"]["id"], co["id"])
    referral = submit_referral(student["id"], ctx["teacher"]["id"], role="Teacher")
    evaluation = pipeline_to_determination(student["id"], referral, co["id"])
    plan = create_draft_plan(student["id"], evaluation["id"], co["id"])
    accommodation = add_accommodation(plan["id"], co["id"], applies_to_testing=False)
    return ctx, plan, accommodation


def _draft_plan_no_accommodation(api):
    ctx = setup_school_with_staff()
    co = ctx["coordinator"]
    student = create_student_for(ctx["school"]["id"], co["id"])
    referral = submit_referral(student["id"], ctx["teacher"]["id"], role="Teacher")
    evaluation = pipeline_to_determination(student["id"], referral, co["id"])
    plan = create_draft_plan(student["id"], evaluation["id"], co["id"])
    return ctx, plan


def _plan_pending_teacher_ack(api, train_teacher=True, num_teachers=1):
    ctx, plan, accommodation = _draft_plan_with_accommodation(
        api, train_teacher=train_teacher, num_teachers=num_teachers
    )
    co = ctx["coordinator"]
    submit_plan(plan["id"], co["id"])
    grant_plan_parent_consent(plan["id"], co["id"])
    return ctx, plan, accommodation


class TestPlanPreconditions:
    def test_plan_submit_for_consent_without_accommodations_rejected(self, api):
        """PRD §3.4: "Submitting the plan for parent consent carries the OCC
        field `expected_plan_version` and checks, in order, that the plan is
        `DRAFT` (otherwise `ERR_PLAN_NOT_DRAFT`), that the plan carries at least
        one accommodation (otherwise `ERR_PLAN_HAS_NO_ACCOMMODATIONS`), that the
        linked evaluation's `determination_outcome` is `ELIGIBLE` (otherwise
        `ERR_PLAN_REQUIRES_ELIGIBLE_DETERMINATION`), that the student has no
        other plan in `DRAFT`, `PENDING_PARENT_CONSENT`, `PENDING_TEACHER_ACK`,
        `ACTIVE`, or `UNDER_ANNUAL_REVIEW` (otherwise
        `ERR_STUDENT_PLAN_ALREADY_OPEN`), and that `expected_plan_version`
        matches the plan's current `version` (otherwise
        `ERR_STALE_PLAN_VERSION`, HTTP 412)."

        Design: Corner/state_machines/plan_submit_for_consent_without_accommodations_rejected
        """
        ctx, plan = _draft_plan_no_accommodation(api)
        co = ctx["coordinator"]
        plan_v = get_plan_version(plan["id"], co["id"])
        resp = api.submit_plan_for_consent(
            plan["id"], {"expected_plan_version": plan_v}, make_coordinator_headers(co["id"])
        )
        validate_error(resp, ApiErrorId.ERR_PLAN_HAS_NO_ACCOMMODATIONS)

    def test_err_plan_not_draft_on_resubmit(self, api):
        """PRD §3.4: "Submitting the plan for parent consent carries the OCC
        field `expected_plan_version` and checks, in order, that the plan is
        `DRAFT` (otherwise `ERR_PLAN_NOT_DRAFT`), that the plan carries at least
        one accommodation (otherwise `ERR_PLAN_HAS_NO_ACCOMMODATIONS`), that the
        linked evaluation's `determination_outcome` is `ELIGIBLE` (otherwise
        `ERR_PLAN_REQUIRES_ELIGIBLE_DETERMINATION`), that the student has no
        other plan in `DRAFT`, `PENDING_PARENT_CONSENT`, `PENDING_TEACHER_ACK`,
        `ACTIVE`, or `UNDER_ANNUAL_REVIEW` (otherwise
        `ERR_STUDENT_PLAN_ALREADY_OPEN`), and that `expected_plan_version`
        matches the plan's current `version` (otherwise
        `ERR_STALE_PLAN_VERSION`, HTTP 412)."

        Design: Corner/errors/err_plan_not_draft_on_resubmit
        """
        ctx, plan, _accommodation = _draft_plan_with_accommodation(api)
        co = ctx["coordinator"]
        submit_plan(plan["id"], co["id"])  # plan now PENDING_PARENT_CONSENT
        plan_v2 = get_plan_version(plan["id"], co["id"])
        resp = api.submit_plan_for_consent(
            plan["id"], {"expected_plan_version": plan_v2}, make_coordinator_headers(co["id"])
        )
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_DRAFT)


class TestTeacherAcknowledgment:
    def test_err_ack_ownership_mismatch_triggerable(self, api):
        """PRD §2.9: "A related ownership rule applies to teacher
        acknowledgments: only the teacher named on an acknowledgment row may
        respond to it — a caller whose `X-User-ID` does not map to the row's
        `staff_id` is rejected with `ERR_ACK_OWNERSHIP_MISMATCH` (HTTP 403)."

        Design: Corner/errors/err_ack_ownership_mismatch_triggerable
        """
        ctx, plan, _accommodation = _plan_pending_teacher_ack(api, num_teachers=2)
        co = ctx["coordinator"]
        t1, t2 = ctx["teachers"][0], ctx["teachers"][1]
        acks = get_success_data(api.list_teacher_acks(
            make_coordinator_headers(co["id"]),
            params={"plan_id": plan["id"], "staff_id": t1["id"]},
        ))
        assert len(acks) == 1, "exactly one ack row must exist for teacher T1"
        resp = api.acknowledge_teacher_ack(acks[0]["id"], make_teacher_headers(t2["id"]))
        validate_error(resp, ApiErrorId.ERR_ACK_OWNERSHIP_MISMATCH)

    def test_err_staff_training_not_current_triggerable(self, api):
        """PRD §3.4: "Acknowledging requires the row to be `PENDING` (otherwise
        `ERR_ACK_NOT_PENDING`), requires the caller to be the teacher named on
        the row (otherwise `ERR_ACK_OWNERSHIP_MISMATCH`), and requires the
        teacher's `current_training_status` to be `TRAINED_CURRENT` (otherwise
        `ERR_STAFF_TRAINING_NOT_CURRENT`)."

        Design: Corner/errors/err_staff_training_not_current_triggerable
        """
        # Teacher is UNTRAINED (no training records recorded).
        ctx, plan, _accommodation = _plan_pending_teacher_ack(api, train_teacher=False)
        co = ctx["coordinator"]
        teacher = ctx["teacher"]
        acks = get_success_data(api.list_teacher_acks(
            make_coordinator_headers(co["id"]),
            params={"plan_id": plan["id"], "staff_id": teacher["id"]},
        ))
        assert len(acks) == 1
        resp = api.acknowledge_teacher_ack(acks[0]["id"], make_teacher_headers(teacher["id"]))
        validate_error(resp, ApiErrorId.ERR_STAFF_TRAINING_NOT_CURRENT)

    def test_ack_flips_plan_visible_immediately(self, api):
        """PRD §3.4: "When that gate flips to true while the plan is
        `PENDING_TEACHER_ACK`, the plan activates automatically — no separate
        client call. Activation stamps `plan_effective_date` from the clock,
        sets `next_annual_review_due` to 365 days after the effective date, sets
        `next_re_evaluation_due` to three years after the `created_at` of the
        evaluation linked by the plan's `evaluation_id`, promotes every `DRAFT`
        accommodation on the plan to `ACTIVE`, moves the student `EVALUATING` →
        `PLAN_ACTIVE`, recomputes `has_active_504_plan` to true, and emits
        `PLAN_ACTIVATED`."

        Design: Corner/consistency_model/ack_flips_plan_visible_immediately
        """
        ctx, plan, _accommodation = _plan_pending_teacher_ack(api)
        co = ctx["coordinator"]
        acks = get_success_data(api.list_teacher_acks(
            make_coordinator_headers(co["id"]),
            params={"plan_id": plan["id"], "ack_status": "PENDING"},
        ))
        assert len(acks) == 1, "single-teacher school must fan out exactly one ack row"
        resp = api.acknowledge_teacher_ack(acks[0]["id"], make_teacher_headers(ctx["teacher"]["id"]))
        validate_success(resp)
        # No separate client call: the very next read shows the plan ACTIVE.
        final = validate_success(api.get_plan(plan["id"], make_coordinator_headers(co["id"])))
        assert final["plan_status"] == "ACTIVE", (
            f"plan must activate automatically on the final ack, got {final['plan_status']}"
        )
        assert final["plan_effective_date"] is not None, "activation must stamp plan_effective_date"


class TestPlanOccVersion:
    def test_occ_plan_version_increments_on_submit(self, api):
        """PRD §3.5: "A new accommodation starts in `DRAFT` and flips to `ACTIVE`
        automatically when its parent plan activates; adding one increments the
        plan's `version` by 1, which is precisely the write the plan-submission
        OCC guard protects against."
        PRD §3.4: "A successful submission moves the plan to
        `PENDING_PARENT_CONSENT`, creates a ParentConsentRecord with
        `consent_scope` `INITIAL_PLAN` and this plan's id, and increments the
        plan's `version` by 1."

        Design: Corner/cross_cutting_layers/occ_plan_version_increments_on_submit
        """
        ctx = setup_school_with_staff()
        co = ctx["coordinator"]
        student = create_student_for(ctx["school"]["id"], co["id"])
        referral = submit_referral(student["id"], ctx["teacher"]["id"], role="Teacher")
        evaluation = pipeline_to_determination(student["id"], referral, co["id"])
        plan = create_draft_plan(student["id"], evaluation["id"], co["id"])
        plan_v0 = plan["version"]
        add_accommodation(plan["id"], co["id"], applies_to_testing=False)
        plan_v_pre = get_plan_version(plan["id"], co["id"])
        assert plan_v_pre == plan_v0 + 1, (
            f"adding an accommodation must bump plan version by 1 ({plan_v0} -> {plan_v_pre})"
        )
        submitted = validate_success(api.submit_plan_for_consent(
            plan["id"], {"expected_plan_version": plan_v_pre}, make_coordinator_headers(co["id"])
        ))
        assert submitted["version"] == plan_v_pre + 1, (
            f"submit-for-consent must bump plan version by 1 ({plan_v_pre} -> {submitted['version']})"
        )
        assert submitted["plan_status"] == "PENDING_PARENT_CONSENT"


class TestPlanReviewCycleLoop:
    def test_modify_plan_cycles_plan_back_to_draft(self, api):
        """PRD §3.6: "With `MODIFY_PLAN`, the plan re-enters `DRAFT` in a cyclic
        revision loop — `ACTIVE` → `UNDER_ANNUAL_REVIEW` → `DRAFT`.
        Accommodations remain in whatever states they hold, and accommodations
        may be added or removed while the plan is back in draft. The plan must
        then re-traverse the full activation pipeline — consent submission,
        parent consent, teacher acknowledgments, automatic activation — and the
        student's `section_504_status` remains `PLAN_ACTIVE` until the plan
        exits `DRAFT` again."

        Design: Difficulty/non_linear_state_machine/plan_modify_plan_review_cycle_loop
        """
        ctx = setup_active_plan(activate_at="2026-01-01T00:00:00Z")
        co = ctx["coordinator"]
        plan = ctx["plan"]
        review = schedule_review(plan["id"], co["id"], "2026-06-01T00:00:00Z", review_type="ANNUAL")
        start_review_now(review["id"], co["id"])
        completed = validate_success(api.complete_review(
            review["id"], {"outcome": "MODIFY_PLAN"}, make_coordinator_headers(co["id"])
        ))
        assert completed["review_status"] == "COMPLETED"
        plan_after = validate_success(api.get_plan(plan["id"], make_coordinator_headers(co["id"])))
        assert plan_after["plan_status"] == "DRAFT", (
            f"MODIFY_PLAN must cycle the plan back to DRAFT, got {plan_after['plan_status']}"
        )
        student_after = validate_success(api.get_student(ctx["student"]["id"], make_coordinator_headers(co["id"])))
        assert student_after["section_504_status"] == "PLAN_ACTIVE", (
            "student status remains PLAN_ACTIVE until the plan exits DRAFT again"
        )

    def test_modify_plan_retraverses_activation_pipeline(self, api):
        """PRD §3.6: "With `MODIFY_PLAN`, the plan re-enters `DRAFT` in a cyclic
        revision loop — `ACTIVE` → `UNDER_ANNUAL_REVIEW` → `DRAFT`.
        Accommodations remain in whatever states they hold, and accommodations
        may be added or removed while the plan is back in draft. The plan must
        then re-traverse the full activation pipeline — consent submission,
        parent consent, teacher acknowledgments, automatic activation — and the
        student's `section_504_status` remains `PLAN_ACTIVE` until the plan
        exits `DRAFT` again."

        Design: Difficulty/non_linear_state_machine/plan_modify_plan_review_cycle_loop
        """
        ctx = setup_active_plan(activate_at="2026-01-01T00:00:00Z")
        co = ctx["coordinator"]
        plan = ctx["plan"]
        review = schedule_review(plan["id"], co["id"], "2026-06-01T00:00:00Z", review_type="ANNUAL")
        start_review_now(review["id"], co["id"])
        validate_success(api.complete_review(
            review["id"], {"outcome": "MODIFY_PLAN"}, make_coordinator_headers(co["id"])
        ))
        # The plan is DRAFT again and must re-traverse the activation pipeline.
        reactivated = activate_plan(plan["id"], co["id"])
        assert reactivated["plan_status"] == "ACTIVE", (
            f"after MODIFY_PLAN the plan must re-traverse to ACTIVE, got {reactivated['plan_status']}"
        )


class TestReEvaluationChain:
    def test_re_evaluation_review_creates_superseding_evaluation(self, api):
        """PRD §3.6: "When the type is `RE_EVALUATION`, `next_re_evaluation_due`
        is set to three years after `completed_at`, and a brand-new
        EligibilityEvaluation is created in `INITIATED` whose
        `supersedes_evaluation_id` is the plan's current `evaluation_id`; the
        plan's `evaluation_id` switches over to the new evaluation once that
        evaluation reaches `DETERMINATION_MADE` with an `ELIGIBLE` outcome."
        PRD §3.3: "Evaluations are listed with `student_id`, `referral_id`,
        `supersedes_evaluation_id`, and `evaluation_status` filters."

        Design: Difficulty/non_linear_state_machine/evaluation_re_evaluation_self_chain
        """
        ctx = setup_active_plan(activate_at="2026-01-01T00:00:00Z")
        co = ctx["coordinator"]
        plan = ctx["plan"]
        eval1 = ctx["evaluation"]
        review = schedule_review(plan["id"], co["id"], "2026-06-01T00:00:00Z",
                                 review_type="RE_EVALUATION")
        start_review_now(review["id"], co["id"])
        validate_success(api.complete_review(
            review["id"], {"outcome": "CONTINUE_PLAN"}, make_coordinator_headers(co["id"])
        ))
        plan_after = validate_success(api.get_plan(plan["id"], make_coordinator_headers(co["id"])))
        assert plan_after["plan_status"] == "ACTIVE", "CONTINUE_PLAN returns the plan to ACTIVE"
        chain = get_success_data(api.list_evaluations(
            make_coordinator_headers(co["id"]),
            params={"student_id": ctx["student"]["id"], "supersedes_evaluation_id": eval1["id"]},
        ))
        assert len(chain) == 1, "a re-evaluation review must create exactly one superseding evaluation"
        assert chain[0]["evaluation_status"] == "INITIATED", (
            f"the new evaluation restarts the chain in INITIATED, got {chain[0]['evaluation_status']}"
        )
        assert chain[0]["id"] != eval1["id"]

    def test_re_evaluation_review_reanchors_next_re_evaluation_due(self, api):
        """PRD §3.6: "When the type is `RE_EVALUATION`, `next_re_evaluation_due`
        is set to three years after `completed_at`, and a brand-new
        EligibilityEvaluation is created in `INITIATED` whose
        `supersedes_evaluation_id` is the plan's current `evaluation_id`; the
        plan's `evaluation_id` switches over to the new evaluation once that
        evaluation reaches `DETERMINATION_MADE` with an `ELIGIBLE` outcome."
        PRD §3.3: "Cadence tracking for re-evaluation keys off the `created_at`
        of the student's most recent evaluation in `DETERMINATION_MADE`:
        re-evaluation becomes due once at least 1095 whole days (three years of
        365 days) have elapsed since that anchor."

        Design: Difficulty/non_linear_state_machine/evaluation_re_evaluation_self_chain
        """
        ctx = setup_active_plan(activate_at="2026-01-01T00:00:00Z")
        co = ctx["coordinator"]
        plan = ctx["plan"]
        review = schedule_review(plan["id"], co["id"], "2026-06-01T00:00:00Z",
                                 review_type="RE_EVALUATION")
        start_review_now(review["id"], co["id"])
        completed = validate_success(api.complete_review(
            review["id"], {"outcome": "CONTINUE_PLAN"}, make_coordinator_headers(co["id"])
        ))
        plan_after = validate_success(api.get_plan(plan["id"], make_coordinator_headers(co["id"])))
        completed_at = datetime.fromisoformat(completed["completed_at"].replace("Z", "+00:00"))
        due = datetime.fromisoformat(plan_after["next_re_evaluation_due"].replace("Z", "+00:00"))
        # "three years" of the re-evaluation cadence is 3 * 365 = 1095 days (PRD §3.3).
        assert due == completed_at + timedelta(days=1095), (
            f"next_re_evaluation_due must be completed_at + 1095 days "
            f"({completed_at.isoformat()} + 1095d != {due.isoformat()})"
        )
