"""Plan suspension guards and the one-open-plan / one-open-review capacity
rules (PRD §3.4, §3.5, §3.6)."""
from test_helpers import (
    ApiErrorId,
    create_draft_plan,
    create_student_for,
    get_student_version,
    make_coordinator_headers,
    pipeline_to_determination,
    schedule_review,
    setup_active_plan,
    setup_school_with_staff,
    start_review_now,
    submit_referral,
    suspend_plan_with_low_compliance,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


def _draft_plan_ctx(api):
    ctx = setup_school_with_staff()
    co = ctx["coordinator"]
    student = create_student_for(ctx["school"]["id"], co["id"])
    referral = submit_referral(student["id"], ctx["teacher"]["id"], role="Teacher")
    evaluation = pipeline_to_determination(student["id"], referral, co["id"])
    plan = create_draft_plan(student["id"], evaluation["id"], co["id"])
    return ctx, student, evaluation, plan


class TestPlanSuspension:
    def test_state_precondition_plan_not_active(self, api):
        """PRD §3.5: "A coordinator may suspend an `ACTIVE` plan (otherwise
        `ERR_PLAN_NOT_ACTIVE`) by supplying a `justification`, but only when
        suspension is warranted: either the plan's
        `implementation_compliance_pct` is strictly below 60, or the school's
        `school_posture` is `AUDIT_HOLD` — otherwise the request is rejected
        with `ERR_NO_SUSPENSION_JUSTIFICATION` (HTTP 422)."

        Design: Corner/validations/state_precondition_plan_not_active
        """
        ctx, student, evaluation, plan = _draft_plan_ctx(api)
        resp = api.suspend_plan(
            plan["id"], {"justification": "premature"},
            make_coordinator_headers(ctx["coordinator"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_ACTIVE)

    def test_plan_suspension_no_justification(self, api):
        """PRD §3.5: "A coordinator may suspend an `ACTIVE` plan (otherwise
        `ERR_PLAN_NOT_ACTIVE`) by supplying a `justification`, but only when
        suspension is warranted: either the plan's
        `implementation_compliance_pct` is strictly below 60, or the school's
        `school_posture` is `AUDIT_HOLD` — otherwise the request is rejected
        with `ERR_NO_SUSPENSION_JUSTIFICATION` (HTTP 422)."
        PRD §3.5: "an empty window yields a ratio of 1.0, i.e. 100 percent."

        Design: Corner/validations/plan_suspension_no_justification
        """
        ctx = setup_active_plan(activate_at="2026-01-01T00:00:00Z")
        # No implementation logs: compliance ratio is 1.0 (100%), and the
        # school's posture is OPERATIONAL — neither justification holds.
        resp = api.suspend_plan(
            ctx["plan"]["id"], {"justification": "no valid reason"},
            make_coordinator_headers(ctx["coordinator"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NO_SUSPENSION_JUSTIFICATION)


class TestPlanLifetimeOverlap:
    def test_second_plan_rejected_while_first_is_draft(self, api):
        """PRD §3.4: "Drafting is rejected with `ERR_STUDENT_PLAN_ALREADY_OPEN`
        whenever the student already has any plan whose status is neither
        `TERMINATED` nor `EXITED_TO_IEP` — even a suspended plan blocks a new
        draft."

        Design: Difficulty/resource_temporal_overlap/plan_lifetime_no_overlap_per_student
        """
        ctx, student, evaluation, plan1 = _draft_plan_ctx(api)
        co = ctx["coordinator"]
        stu_v2 = get_student_version(student["id"], co["id"])
        resp = api.create_plan(
            {"student_id": student["id"], "evaluation_id": evaluation["id"],
             "expected_student_version": stu_v2},
            make_coordinator_headers(co["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STUDENT_PLAN_ALREADY_OPEN)
        plan1_after = validate_success(api.get_plan(plan1["id"], make_coordinator_headers(co["id"])))
        assert plan1_after["plan_status"] == "DRAFT", "the existing plan must be unaffected"

    def test_second_plan_rejected_while_first_is_suspended(self, api):
        """PRD §3.4: "Drafting is rejected with `ERR_STUDENT_PLAN_ALREADY_OPEN`
        whenever the student already has any plan whose status is neither
        `TERMINATED` nor `EXITED_TO_IEP` — even a suspended plan blocks a new
        draft."
        PRD §3.5: "Suspension moves the plan to `SUSPENDED`, moves the student
        `PLAN_ACTIVE` → `PLAN_SUSPENDED`, sets `has_active_504_plan` to false
        because a suspended plan does not count, and emits `PLAN_SUSPENDED`."

        Design: Difficulty/resource_temporal_overlap/plan_lifetime_no_overlap_per_student
        """
        ctx = setup_active_plan(activate_at="2026-01-01T00:00:00Z")
        co = ctx["coordinator"]
        suspended = suspend_plan_with_low_compliance(ctx)
        assert suspended["plan_status"] == "SUSPENDED"
        stu_v = get_student_version(ctx["student"]["id"], co["id"])
        resp = api.create_plan(
            {"student_id": ctx["student"]["id"], "evaluation_id": ctx["evaluation"]["id"],
             "expected_student_version": stu_v},
            make_coordinator_headers(co["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STUDENT_PLAN_ALREADY_OPEN)


class TestReviewOpenCapacity:
    def test_second_review_rejected_while_first_is_scheduled(self, api):
        """PRD §3.6: "Scheduling a review — a coordinator or district director
        naming the `plan_id`, a `review_type` of `ANNUAL`, `RE_EVALUATION`,
        `PARENT_REQUESTED`, or `DISTRICT_AUDIT`, and a `scheduled_for` instant —
        requires the plan to be `ACTIVE` (otherwise `ERR_PLAN_NOT_ACTIVE`) and
        requires that no review for the plan already sit in `SCHEDULED` or
        `IN_PROGRESS` (otherwise `ERR_REVIEW_ALREADY_SCHEDULED`)."

        Design: Difficulty/resource_temporal_overlap/review_open_capacity_one_per_plan
        """
        ctx = setup_active_plan(activate_at="2026-01-01T00:00:00Z")
        co = ctx["coordinator"]
        review1 = schedule_review(ctx["plan"]["id"], co["id"], "2026-06-01T00:00:00Z",
                                  review_type="ANNUAL")
        # R2's scheduled_for is disjoint from R1's — capacity is still exhausted.
        # NOTE (§2.8 precedence silence): scheduling R1 moved the plan to
        # UNDER_ANNUAL_REVIEW, so R2 violates BOTH the plan-ACTIVE state
        # precondition (§2.8 item 6 -> ERR_PLAN_NOT_ACTIVE) and the
        # one-open-review capacity rule (§3.6 -> ERR_REVIEW_ALREADY_SCHEDULED).
        # PRD names both errors for this scenario but never orders the
        # unlisted capacity check against the item-6 state check, so either
        # error is a faithful rejection; the rule under test is that the
        # second review is rejected at all.
        resp = api.create_review(
            {"plan_id": ctx["plan"]["id"], "review_type": "PARENT_REQUESTED",
             "scheduled_for": "2026-06-15T00:00:00Z"},
            make_coordinator_headers(co["id"]),
        )
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_REVIEW_ALREADY_SCHEDULED, ApiErrorId.ERR_PLAN_NOT_ACTIVE]
        )
        review1_after = validate_success(api.get_review(review1["id"], make_coordinator_headers(co["id"])))
        assert review1_after["review_status"] == "SCHEDULED", "the existing review must be unaffected"

    def test_second_review_rejected_while_first_is_in_progress(self, api):
        """PRD §3.6: "Scheduling a review — a coordinator or district director
        naming the `plan_id`, a `review_type` of `ANNUAL`, `RE_EVALUATION`,
        `PARENT_REQUESTED`, or `DISTRICT_AUDIT`, and a `scheduled_for` instant —
        requires the plan to be `ACTIVE` (otherwise `ERR_PLAN_NOT_ACTIVE`) and
        requires that no review for the plan already sit in `SCHEDULED` or
        `IN_PROGRESS` (otherwise `ERR_REVIEW_ALREADY_SCHEDULED`)."

        Design: Difficulty/resource_temporal_overlap/review_open_capacity_one_per_plan
        """
        ctx = setup_active_plan(activate_at="2026-01-01T00:00:00Z")
        co = ctx["coordinator"]
        review1 = schedule_review(ctx["plan"]["id"], co["id"], "2026-06-01T00:00:00Z",
                                  review_type="ANNUAL")
        start_review_now(review1["id"], co["id"])  # now IN_PROGRESS
        # Same §2.8 precedence silence as the SCHEDULED variant above: with the
        # first review open the plan sits in UNDER_ANNUAL_REVIEW, so both
        # ERR_PLAN_NOT_ACTIVE (state precondition, §2.8 item 6) and
        # ERR_REVIEW_ALREADY_SCHEDULED (capacity rule, §3.6) apply and PRD does
        # not order them.
        resp = api.create_review(
            {"plan_id": ctx["plan"]["id"], "review_type": "PARENT_REQUESTED",
             "scheduled_for": "2026-06-15T00:00:00Z"},
            make_coordinator_headers(co["id"]),
        )
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_REVIEW_ALREADY_SCHEDULED, ApiErrorId.ERR_PLAN_NOT_ACTIVE]
        )
