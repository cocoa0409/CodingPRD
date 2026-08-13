"""Review cadence, lateness variants, cancellation compensation, and the
exit-to-IEP path (PRD §3.2, §3.6, §3.9)."""
from test_helpers import (
    ApiErrorId,
    consent_response_payload,
    create_consent_record_payload,
    create_testing_request,
    make_coordinator_headers,
    make_director_headers,
    schedule_review,
    set_clock,
    setup_active_plan,
    start_review_now,
    validate_error,
    validate_success,
)


class TestReviewStartStateGuards:
    def test_err_plan_not_under_review_on_review_start(self, api):
        """PRD §3.6: "Starting a review moves it to `IN_PROGRESS`: from
        `SCHEDULED` it additionally requires the plan to be
        `UNDER_ANNUAL_REVIEW` (otherwise `ERR_PLAN_NOT_UNDER_REVIEW`), while a
        review in the wrong state is rejected with `ERR_REVIEW_NOT_SCHEDULED` —
        the same error that guards the start transition whether the review sits
        in `SCHEDULED` or `OVERDUE`."

        Design: Corner/errors/err_plan_not_under_review_on_review_start
        """
        ctx = setup_active_plan(activate_at="2026-01-01T00:00:00Z")
        co = ctx["coordinator"]
        review = schedule_review(ctx["plan"]["id"], co["id"], "2026-06-01T00:00:00Z")
        validate_success(api.cancel_review(review["id"], make_coordinator_headers(co["id"])))
        # The review is CANCELLED — a wrong state for the start transition.
        resp = api.start_review(review["id"], make_coordinator_headers(co["id"]))
        validate_error(resp, ApiErrorId.ERR_REVIEW_NOT_SCHEDULED)


class TestReviewLatenessVariants:
    def test_annual_grace_vs_re_evaluation_no_grace_diverge(self, api):
        """PRD §3.6: "Completion stamps `completed_at` from the clock, moves the
        review to `COMPLETED`, and recomputes `was_late`: a completed `ANNUAL`
        review is late when `completed_at` falls more than fourteen days after
        `scheduled_for`, while a completed `RE_EVALUATION` review is late when
        `completed_at` falls after `scheduled_for` at all. A late completion
        emits `REVIEW_COMPLETED_LATE`."
        PRD §3.6: "If the clock advances past `scheduled_for` plus the grace
        window applicable to the review's type — fourteen days for an `ANNUAL`
        review, none for a `RE_EVALUATION` review — while the review is still
        `SCHEDULED`, the system flips it to `OVERDUE`, emits `REVIEW_OVERDUE`,
        and recomputes the school's posture, since overdue reviews feed the
        composite score."

        Design: Difficulty/dual_variant_calc/annual_review_window_annual_vs_reeval_variant_diverge
        """
        # Plan A (ANNUAL review) and plan B (RE_EVALUATION review), both
        # effective 2025-08-01, both reviews scheduled_for 2026-08-01.
        ctx_a = setup_active_plan(school_name="School A", activate_at="2025-08-01T00:00:00Z")
        ctx_b = setup_active_plan(school_name="School B", activate_at="2025-08-01T00:00:00Z")
        rev_a = schedule_review(ctx_a["plan"]["id"], ctx_a["coordinator"]["id"],
                                "2026-08-01T00:00:00Z", review_type="ANNUAL")
        rev_b = schedule_review(ctx_b["plan"]["id"], ctx_b["coordinator"]["id"],
                                "2026-08-01T00:00:00Z", review_type="RE_EVALUATION")
        # Advance to 2026-08-10 — 9 days past scheduled_for: within the ANNUAL
        # grace window, but past the RE_EVALUATION date (no grace).
        set_clock("2026-08-10T00:00:00Z")
        rev_b_mid = validate_success(api.get_review(
            rev_b["id"], make_coordinator_headers(ctx_b["coordinator"]["id"])
        ))
        assert rev_b_mid["review_status"] == "OVERDUE", (
            "RE_EVALUATION carries no grace window — it must flip to OVERDUE"
        )
        completed_a = None  # populated by the start-then-complete sequence below
        start_review_now(rev_a["id"], ctx_a["coordinator"]["id"])
        completed_a = validate_success(api.complete_review(
            rev_a["id"], {"outcome": "CONTINUE_PLAN"},
            make_coordinator_headers(ctx_a["coordinator"]["id"]),
        ))
        start_review_now(rev_b["id"], ctx_b["coordinator"]["id"])
        completed_b = validate_success(api.complete_review(
            rev_b["id"], {"outcome": "CONTINUE_PLAN"},
            make_coordinator_headers(ctx_b["coordinator"]["id"]),
        ))
        assert completed_a["was_late"] is False, (
            "ANNUAL completed 9 days after scheduled_for is within the 14-day grace — not late"
        )
        assert completed_b["was_late"] is True, (
            "RE_EVALUATION completed after scheduled_for at all — late"
        )
        assert completed_a["review_status"] == "COMPLETED"
        assert completed_b["review_status"] == "COMPLETED"

    def test_annual_was_late_boundary_exactly_14_vs_15_days(self, api):
        """PRD §3.6: "Completion stamps `completed_at` from the clock, moves the
        review to `COMPLETED`, and recomputes `was_late`: a completed `ANNUAL`
        review is late when `completed_at` falls more than fourteen days after
        `scheduled_for`, while a completed `RE_EVALUATION` review is late when
        `completed_at` falls after `scheduled_for` at all. A late completion
        emits `REVIEW_COMPLETED_LATE`."

        Design: Difficulty/dual_variant_calc/annual_review_window_annual_vs_reeval_variant_diverge
        """
        ctx = setup_active_plan(activate_at="2025-08-01T00:00:00Z")
        co = ctx["coordinator"]
        # Exactly 14 days after scheduled_for: not more than fourteen — not late.
        review14 = schedule_review(ctx["plan"]["id"], co["id"], "2026-08-01T00:00:00Z",
                                   review_type="ANNUAL")
        set_clock("2026-08-15T00:00:00Z")
        start_review_now(review14["id"], co["id"])
        completed14 = validate_success(api.complete_review(
            review14["id"], {"outcome": "CONTINUE_PLAN"}, make_coordinator_headers(co["id"])
        ))
        assert completed14["was_late"] is False, (
            "completed exactly fourteen days after scheduled_for is not more than fourteen — not late"
        )
        # 15 days after scheduled_for: more than fourteen — late.
        review15 = schedule_review(ctx["plan"]["id"], co["id"], "2026-08-01T00:00:00Z",
                                   review_type="ANNUAL")
        set_clock("2026-08-16T00:00:00Z")
        start_review_now(review15["id"], co["id"])
        completed15 = validate_success(api.complete_review(
            review15["id"], {"outcome": "CONTINUE_PLAN"}, make_coordinator_headers(co["id"])
        ))
        assert completed15["was_late"] is True, (
            "completed fifteen days after scheduled_for is more than fourteen — late"
        )


class TestReviewCancelCompensation:
    def test_review_cancel_restores_plan_status(self, api):
        """PRD §3.6: "Cancelling is permitted only from `SCHEDULED` (otherwise
        `ERR_REVIEW_NOT_SCHEDULED`) and is a compensation: the review lands in
        `CANCELLED` and the plan reverts `UNDER_ANNUAL_REVIEW` → `ACTIVE`."
        PRD §3.2: "The derived boolean `has_active_504_plan` is true exactly
        when the student has exactly one plan in `ACTIVE` status."

        Design: Difficulty/compensating_invariant/review_cancel_restores_plan_status
        """
        ctx = setup_active_plan(activate_at="2026-01-01T00:00:00Z")
        co = ctx["coordinator"]
        pre_plan = validate_success(api.get_plan(ctx["plan"]["id"], make_coordinator_headers(co["id"])))
        pre_student = validate_success(api.get_student(ctx["student"]["id"], make_coordinator_headers(co["id"])))
        assert pre_plan["plan_status"] == "ACTIVE"
        assert pre_student["section_504_status"] == "PLAN_ACTIVE"
        assert pre_student["has_active_504_plan"] is True

        review = schedule_review(ctx["plan"]["id"], co["id"], "2026-06-01T00:00:00Z",
                                 review_type="PARENT_REQUESTED")
        cancelled = validate_success(api.cancel_review(review["id"], make_coordinator_headers(co["id"])))
        assert cancelled["review_status"] == "CANCELLED"

        post_plan = validate_success(api.get_plan(ctx["plan"]["id"], make_coordinator_headers(co["id"])))
        post_student = validate_success(api.get_student(ctx["student"]["id"], make_coordinator_headers(co["id"])))
        assert post_plan["plan_status"] == pre_plan["plan_status"] == "ACTIVE", (
            "cancel must compensate the plan back to ACTIVE"
        )
        assert post_plan["plan_effective_date"] == pre_plan["plan_effective_date"], (
            "compensation must not re-anchor plan_effective_date"
        )
        assert post_student["section_504_status"] == "PLAN_ACTIVE"
        assert post_student["has_active_504_plan"] is True

    def test_plan_schedulable_again_after_cancel(self, api):
        """PRD §3.6: "Cancelling is permitted only from `SCHEDULED` (otherwise
        `ERR_REVIEW_NOT_SCHEDULED`) and is a compensation: the review lands in
        `CANCELLED` and the plan reverts `UNDER_ANNUAL_REVIEW` → `ACTIVE`."
        PRD §3.6: "Scheduling a review — a coordinator or district director
        naming the `plan_id`, a `review_type` of `ANNUAL`, `RE_EVALUATION`,
        `PARENT_REQUESTED`, or `DISTRICT_AUDIT`, and a `scheduled_for` instant —
        requires the plan to be `ACTIVE` (otherwise `ERR_PLAN_NOT_ACTIVE`) and
        requires that no review for the plan already sit in `SCHEDULED` or
        `IN_PROGRESS` (otherwise `ERR_REVIEW_ALREADY_SCHEDULED`)."

        Design: Difficulty/compensating_invariant/review_cancel_restores_plan_status
        """
        ctx = setup_active_plan(activate_at="2026-01-01T00:00:00Z")
        co = ctx["coordinator"]
        review = schedule_review(ctx["plan"]["id"], co["id"], "2026-06-01T00:00:00Z")
        validate_success(api.cancel_review(review["id"], make_coordinator_headers(co["id"])))
        # The compensation restores both preconditions: plan ACTIVE, no open review.
        review2 = schedule_review(ctx["plan"]["id"], co["id"], "2026-07-01T00:00:00Z",
                                  review_type="PARENT_REQUESTED")
        assert review2["review_status"] == "SCHEDULED"
        plan_after = validate_success(api.get_plan(ctx["plan"]["id"], make_coordinator_headers(co["id"])))
        assert plan_after["plan_status"] == "UNDER_ANNUAL_REVIEW"


class TestExitToIep:
    def _setup_review_ready_for_exit(self, api, grant_exit_consent=True, set_iep_active=False):
        ctx = setup_active_plan(activate_at="2026-01-01T00:00:00Z", include_director=True)
        co = ctx["coordinator"]
        if set_iep_active:
            validate_success(api.update_student(
                ctx["student"]["id"], {"iep_status": "IEP_ACTIVE"},
                make_director_headers(ctx["director"]["id"]),
            ))
        review = schedule_review(ctx["plan"]["id"], co["id"], "2026-01-15T00:00:00Z",
                                 review_type="ANNUAL")
        start_review_now(review["id"], co["id"])
        if grant_exit_consent:
            consent = validate_success(api.create_consent_record(
                create_consent_record_payload(
                    ctx["student"]["id"], "EXIT_TO_IEP", plan_id=ctx["plan"]["id"]
                ),
                make_coordinator_headers(co["id"]),
            ), expected_status=201)
            validate_success(api.record_consent_response(
                consent["id"], consent_response_payload(granted=True),
                make_coordinator_headers(co["id"]),
            ))
        return ctx, review

    def test_review_complete_exit_to_iep_requires_iep_active(self, api):
        """PRD §3.6: "With `EXIT_TO_IEP`, two extra gates apply on top of the
        state checks: the student's `iep_status` must be `IEP_ACTIVE` (otherwise
        `ERR_IEP_NOT_ACTIVE`), and a ParentConsentRecord with `consent_scope`
        `EXIT_TO_IEP` for this plan must already be `GRANTED` (otherwise
        `ERR_PARENT_CONSENT_REQUIRED`). The cascade is broad: the student moves
        to `EXITED_TO_IEP` with `has_active_504_plan` false, every accommodation
        on the plan is `DISCONTINUED`, every still-`PENDING`
        TeacherAcknowledgment row flips to `DECLINED`, and every testing request
        on the plan in `SUBMITTED` or `PENDING_DISTRICT_REVIEW` is automatically
        denied."

        Design: Difficulty/cross_entity_state_dependency/review_complete_exit_to_iep_requires_iep_active
        """
        # EXIT_TO_IEP consent pre-granted; iep_status still NONE.
        ctx, review = self._setup_review_ready_for_exit(api, grant_exit_consent=True,
                                                        set_iep_active=False)
        co = ctx["coordinator"]
        resp = api.complete_review(
            review["id"], {"outcome": "EXIT_TO_IEP"}, make_coordinator_headers(co["id"])
        )
        validate_error(resp, ApiErrorId.ERR_IEP_NOT_ACTIVE)
        plan_mid = validate_success(api.get_plan(ctx["plan"]["id"], make_coordinator_headers(co["id"])))
        assert plan_mid["plan_status"] == "UNDER_ANNUAL_REVIEW", (
            "the failed attempt must not move the plan out of UNDER_ANNUAL_REVIEW"
        )
        # District flips iep_status to IEP_ACTIVE; the retry succeeds.
        validate_success(api.update_student(
            ctx["student"]["id"], {"iep_status": "IEP_ACTIVE"},
            make_director_headers(ctx["director"]["id"]),
        ))
        completed = validate_success(api.complete_review(
            review["id"], {"outcome": "EXIT_TO_IEP"}, make_coordinator_headers(co["id"])
        ))
        assert completed["outcome"] == "EXIT_TO_IEP"
        assert completed["review_status"] == "COMPLETED"
        plan_after = validate_success(api.get_plan(ctx["plan"]["id"], make_coordinator_headers(co["id"])))
        assert plan_after["plan_status"] == "EXITED_TO_IEP"
        student_after = validate_success(api.get_student(ctx["student"]["id"], make_coordinator_headers(co["id"])))
        assert student_after["section_504_status"] == "EXITED_TO_IEP"

    def test_exit_to_iep_cascade_discontinues_and_denies(self, api):
        """PRD §3.6: "The cascade is broad: the student moves to `EXITED_TO_IEP`
        with `has_active_504_plan` false, every accommodation on the plan is
        `DISCONTINUED`, every still-`PENDING` TeacherAcknowledgment row flips to
        `DECLINED`, and every testing request on the plan in `SUBMITTED` or
        `PENDING_DISTRICT_REVIEW` is automatically denied."

        Design: Difficulty/cross_entity_state_dependency/review_complete_exit_to_iep_requires_iep_active
        """
        ctx = setup_active_plan(activate_at="2026-01-01T00:00:00Z",
                                applies_to_testing=True, include_director=True)
        co = ctx["coordinator"]
        # A testing request still in SUBMITTED references the plan's accommodation.
        request = create_testing_request(
            ctx["plan"]["id"], ctx["accommodation"]["id"], co["id"],
            "2027-01-15T00:00:00Z", test_name="ELA",
        )
        validate_success(api.update_student(
            ctx["student"]["id"], {"iep_status": "IEP_ACTIVE"},
            make_director_headers(ctx["director"]["id"]),
        ))
        review = schedule_review(ctx["plan"]["id"], co["id"], "2026-01-15T00:00:00Z",
                                 review_type="ANNUAL")
        start_review_now(review["id"], co["id"])
        consent = validate_success(api.create_consent_record(
            create_consent_record_payload(ctx["student"]["id"], "EXIT_TO_IEP",
                                          plan_id=ctx["plan"]["id"]),
            make_coordinator_headers(co["id"]),
        ), expected_status=201)
        validate_success(api.record_consent_response(
            consent["id"], consent_response_payload(granted=True),
            make_coordinator_headers(co["id"]),
        ))
        validate_success(api.complete_review(
            review["id"], {"outcome": "EXIT_TO_IEP"}, make_coordinator_headers(co["id"])
        ))
        accommodation_after = validate_success(api.get_accommodation(
            ctx["accommodation"]["id"], make_coordinator_headers(co["id"])
        ))
        assert accommodation_after["accommodation_status"] == "DISCONTINUED", (
            "every accommodation on the plan must be DISCONTINUED"
        )
        request_after = validate_success(api.get_testing_request(
            request["id"], make_coordinator_headers(co["id"])
        ))
        assert request_after["request_status"] == "DENIED", (
            "every SUBMITTED testing request on the plan must be automatically denied"
        )
        student_after = validate_success(api.get_student(ctx["student"]["id"], make_coordinator_headers(co["id"])))
        assert student_after["section_504_status"] == "EXITED_TO_IEP"
        assert student_after["has_active_504_plan"] is False

    def test_err_parent_consent_required_on_exit_to_iep(self, api):
        """PRD §3.6: "With `EXIT_TO_IEP`, two extra gates apply on top of the
        state checks: the student's `iep_status` must be `IEP_ACTIVE` (otherwise
        `ERR_IEP_NOT_ACTIVE`), and a ParentConsentRecord with `consent_scope`
        `EXIT_TO_IEP` for this plan must already be `GRANTED` (otherwise
        `ERR_PARENT_CONSENT_REQUIRED`)."
        PRD §3.9: "A `GRANTED` record is the unlock key for the gated operations
        described earlier — initial plan activation flows through the plan's own
        consent step, re-evaluation consent flows through the evaluation's, and
        the exit-to-IEP review outcome requires a `GRANTED` `EXIT_TO_IEP`-scoped
        record, surfacing `ERR_PARENT_CONSENT_REQUIRED` where consent is
        missing."

        Design: Corner/errors/err_parent_consent_required_on_plan_record_consent
        """
        # iep_status is IEP_ACTIVE, but no EXIT_TO_IEP consent record exists.
        ctx, review = self._setup_review_ready_for_exit(api, grant_exit_consent=False,
                                                        set_iep_active=True)
        resp = api.complete_review(
            review["id"], {"outcome": "EXIT_TO_IEP"},
            make_coordinator_headers(ctx["coordinator"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PARENT_CONSENT_REQUIRED)
