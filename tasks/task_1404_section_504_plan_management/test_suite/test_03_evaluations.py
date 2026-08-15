"""Eligibility evaluation workflow: consent gating, determination guards,
segregation of duties, and the 60-day determination deadline (PRD §2.8, §2.9,
§3.3, §3.4)."""
from test_helpers import (
    ApiErrorId,
    create_draft_plan,
    create_student_for,
    drive_evaluation_to_consent_received,
    get_plan_version,
    initiate_evaluation,
    make_coordinator_headers,
    pipeline_to_determination,
    add_accommodation,
    get_success_data,
    set_clock,
    setup_school_with_staff,
    start_evaluation_now,
    start_referral_review,
    submit_referral,
    validate_error,
    validate_success,
)


def _referral_under_review(api, school, co, student, submitter_id, submitter_role="Teacher"):
    referral = submit_referral(student["id"], submitter_id, role=submitter_role)
    start_referral_review(referral["id"], co["id"])
    return referral


class TestEvaluationConsentGates:
    def test_err_evaluation_not_initiated_on_request_consent(self, api):
        """PRD §3.3: "Requesting parent consent moves an `INITIATED` evaluation
        (otherwise `ERR_EVALUATION_NOT_INITIATED`) to `CONSENT_PENDING` and
        creates the linked ParentConsentRecord: its `consent_scope` is
        `RE_EVALUATION` when `supersedes_evaluation_id` is set and
        `INITIAL_PLAN` otherwise, and its `evaluation_id` points at this
        evaluation."

        Design: Corner/errors/err_evaluation_not_initiated_on_request_consent
        """
        ctx = setup_school_with_staff()
        co = ctx["coordinator"]
        student = create_student_for(ctx["school"]["id"], co["id"])
        referral = _referral_under_review(api, ctx["school"], co, student, ctx["teacher"]["id"])
        evaluation = initiate_evaluation(referral["id"], co["id"])
        co_headers = make_coordinator_headers(co["id"])
        validate_success(api.request_evaluation_consent(evaluation["id"], co_headers), expected_status=201)
        # Second request-consent: evaluation is now CONSENT_PENDING, not INITIATED.
        resp = api.request_evaluation_consent(evaluation["id"], co_headers)
        validate_error(resp, ApiErrorId.ERR_EVALUATION_NOT_INITIATED)

    def test_err_evaluation_not_ready_to_start(self, api):
        """PRD §3.3: "Starting the evaluation requires `CONSENT_RECEIVED`
        (otherwise `ERR_EVALUATION_NOT_READY_TO_START`); it stamps
        `evaluation_started_at` from the clock and computes the
        `determination_deadline` as sixty calendar days later."

        Design: Corner/errors/err_evaluation_not_ready_to_start
        """
        ctx = setup_school_with_staff()
        co = ctx["coordinator"]
        student = create_student_for(ctx["school"]["id"], co["id"])
        referral = _referral_under_review(api, ctx["school"], co, student, ctx["teacher"]["id"])
        evaluation = initiate_evaluation(referral["id"], co["id"])
        co_headers = make_coordinator_headers(co["id"])
        validate_success(api.request_evaluation_consent(evaluation["id"], co_headers), expected_status=201)
        # Evaluation is CONSENT_PENDING — consent not yet recorded.
        resp = api.start_evaluation(evaluation["id"], co_headers)
        validate_error(resp, ApiErrorId.ERR_EVALUATION_NOT_READY_TO_START)


class TestDeterminationGuards:
    def test_err_segregation_of_duties_evaluation(self, api):
        """PRD §2.9: "First, the coordinator who records an eligibility
        determination must not be the staff member who submitted the originating
        referral (`submitted_by_staff_id`)."

        Design: Corner/errors/err_segregation_of_duties_evaluation
        """
        ctx = setup_school_with_staff()
        co = ctx["coordinator"]
        student = create_student_for(ctx["school"]["id"], co["id"])
        # Referral submitted BY the coordinator (allowed role), so the same
        # coordinator determining violates segregation of duties.
        referral = _referral_under_review(api, ctx["school"], co, student, co["id"],
                                          submitter_role="Section504Coordinator")
        evaluation = initiate_evaluation(referral["id"], co["id"])
        drive_evaluation_to_consent_received(evaluation["id"], co["id"])
        start_evaluation_now(evaluation["id"], co["id"])
        resp = api.determine_evaluation(
            evaluation["id"],
            {"determination_outcome": "ELIGIBLE", "disability_impairment_found": True,
             "major_life_activity_affected": True},
            make_coordinator_headers(co["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    def test_determine_requires_in_progress_state_with_late_clock(self, api):
        """PRD §3.3: "Recording the determination requires the evaluation to be
        `EVALUATION_IN_PROGRESS` (otherwise `ERR_EVALUATION_NOT_IN_PROGRESS`)
        and accepts `determination_outcome` (`ELIGIBLE` or `NOT_ELIGIBLE`)
        together with the two disability-definition prongs
        `disability_impairment_found` and `major_life_activity_affected`, both
        booleans defaulting to false; the determining coordinator is recorded as
        `determined_by_staff_id`."
        PRD §2.8: "When several checks could reject the same request, the server
        evaluates them in a fixed priority order so the surfaced error is
        deterministic rather than an accident of implementation."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_determine
        """
        set_clock("2026-05-01T00:00:00Z")
        ctx = setup_school_with_staff(clock_initial="2026-05-01T00:00:00Z", trained_at="2026-05-02T00:00:00Z")
        co = ctx["coordinator"]
        student = create_student_for(ctx["school"]["id"], co["id"])
        referral = _referral_under_review(api, ctx["school"], co, student, ctx["teacher"]["id"])
        evaluation = initiate_evaluation(referral["id"], co["id"])
        drive_evaluation_to_consent_received(evaluation["id"], co["id"])
        # Intentionally skip /start: evaluation sits in CONSENT_RECEIVED.
        # Advance the clock 92 days so that, had the evaluation started at
        # setup, a determination would now be past the 60-day window.
        set_clock("2026-08-01T00:00:00Z")
        resp = api.determine_evaluation(
            evaluation["id"],
            {"determination_outcome": "NOT_ELIGIBLE", "disability_impairment_found": False,
             "major_life_activity_affected": False},
            make_coordinator_headers(co["id"]),
        )
        err = validate_error(resp, ApiErrorId.ERR_EVALUATION_NOT_IN_PROGRESS)
        assert err["error_id"] == "ERR_EVALUATION_NOT_IN_PROGRESS"
        assert err["error_id"] != "ERR_DETERMINATION_DEADLINE_MISSED"

    def test_determine_on_initiated_evaluation_rejected(self, api):
        """PRD §3.3: "Recording the determination requires the evaluation to be
        `EVALUATION_IN_PROGRESS` (otherwise `ERR_EVALUATION_NOT_IN_PROGRESS`)
        and accepts `determination_outcome` (`ELIGIBLE` or `NOT_ELIGIBLE`)
        together with the two disability-definition prongs
        `disability_impairment_found` and `major_life_activity_affected`, both
        booleans defaulting to false; the determining coordinator is recorded as
        `determined_by_staff_id`."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_determine
        """
        ctx = setup_school_with_staff()
        co = ctx["coordinator"]
        student = create_student_for(ctx["school"]["id"], co["id"])
        referral = _referral_under_review(api, ctx["school"], co, student, ctx["teacher"]["id"])
        evaluation = initiate_evaluation(referral["id"], co["id"])
        # Determine directly from INITIATED — consent never requested.
        resp = api.determine_evaluation(
            evaluation["id"],
            {"determination_outcome": "ELIGIBLE", "disability_impairment_found": True,
             "major_life_activity_affected": True},
            make_coordinator_headers(co["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_EVALUATION_NOT_IN_PROGRESS)


class TestDeterminationDeadlineBoundary:
    """60 days after evaluation_started_at is timely; 61 is late (PRD §3.3)."""

    def _prepare_started_evaluation(self, api, ctx, ref_suffix):
        co = ctx["coordinator"]
        student = create_student_for(ctx["school"]["id"], co["id"], student_external_ref=f"STU-{ref_suffix}")
        referral = _referral_under_review(api, ctx["school"], co, student, ctx["teacher"]["id"])
        evaluation = initiate_evaluation(referral["id"], co["id"])
        drive_evaluation_to_consent_received(evaluation["id"], co["id"], parent_ref=f"parent-{ref_suffix}")
        return student, evaluation

    def test_determination_deadline_60_vs_61_days(self, api):
        """PRD §3.3: "Three further guards apply, in the precedence order of
        §2.8. The determining staff member must differ from the referral's
        `submitted_by_staff_id` — a violation is `ERR_SEGREGATION_OF_DUTIES`. If
        `supersedes_evaluation_id` is set, that prior evaluation must already be
        in `DETERMINATION_MADE`, otherwise `ERR_PRIOR_EVALUATION_OPEN`. And the
        timeliness rule forbids denying late: counting whole days from
        `evaluation_started_at`, a determination made when more than 60 days
        have elapsed is rejected with `ERR_DETERMINATION_DEADLINE_MISSED` (HTTP
        422) if the outcome is `NOT_ELIGIBLE`, while a late `ELIGIBLE`
        determination is allowed but recorded via a `REVIEW_COMPLETED_LATE`
        audit event."

        Design: Difficulty/boundary_precision_check/determination_deadline_60_vs_61_days
        """
        set_clock("2026-05-15T00:00:00Z")
        ctx = setup_school_with_staff(clock_initial="2026-05-15T00:00:00Z", trained_at="2026-05-16T00:00:00Z")
        co = ctx["coordinator"]
        stu1, eval1 = self._prepare_started_evaluation(api, ctx, "D1")
        stu2, eval2 = self._prepare_started_evaluation(api, ctx, "D2")
        stu3, eval3 = self._prepare_started_evaluation(api, ctx, "D3")
        # Start all three evaluations at 2026-06-01.
        set_clock("2026-06-01T00:00:00Z")
        from test_helpers import start_evaluation_now
        for ev in (eval1, eval2, eval3):
            start_evaluation_now(ev["id"], co["id"])
        co_headers = make_coordinator_headers(co["id"])

        # Boundary A: clock = 2026-07-31 — exactly 60 whole days after start.
        set_clock("2026-07-31T00:00:00Z")
        resp1 = api.determine_evaluation(
            eval1["id"],
            {"determination_outcome": "NOT_ELIGIBLE", "disability_impairment_found": False,
             "major_life_activity_affected": False},
            co_headers,
        )
        e1 = validate_success(resp1)
        assert e1["evaluation_status"] == "DETERMINATION_MADE", (
            "60 days is timely (not more than 60) — NOT_ELIGIBLE must be accepted"
        )

        # Boundary B: clock = 2026-08-01 — 61 whole days after start.
        set_clock("2026-08-01T00:00:00Z")
        resp2 = api.determine_evaluation(
            eval2["id"],
            {"determination_outcome": "NOT_ELIGIBLE", "disability_impairment_found": False,
             "major_life_activity_affected": False},
            co_headers,
        )
        validate_error(resp2, ApiErrorId.ERR_DETERMINATION_DEADLINE_MISSED)

        resp3 = api.determine_evaluation(
            eval3["id"],
            {"determination_outcome": "ELIGIBLE", "disability_impairment_found": True,
             "major_life_activity_affected": True},
            co_headers,
        )
        e3 = validate_success(resp3)
        assert e3["evaluation_status"] == "DETERMINATION_MADE"
        assert e3["determination_outcome"] == "ELIGIBLE", (
            "a late ELIGIBLE determination is allowed (with audit)"
        )

    def test_late_eligible_determination_emits_review_completed_late(self, api):
        """PRD §3.3: "And the timeliness rule forbids denying late: counting
        whole days from `evaluation_started_at`, a determination made when more
        than 60 days have elapsed is rejected with
        `ERR_DETERMINATION_DEADLINE_MISSED` (HTTP 422) if the outcome is
        `NOT_ELIGIBLE`, while a late `ELIGIBLE` determination is allowed but
        recorded via a `REVIEW_COMPLETED_LATE` audit event."
        PRD §3.3: "Either way, `DETERMINATION_MADE` is emitted."

        Design: Difficulty/boundary_precision_check/determination_deadline_60_vs_61_days
        """
        from test_helpers import start_evaluation_now
        set_clock("2026-05-15T00:00:00Z")
        ctx = setup_school_with_staff(clock_initial="2026-05-15T00:00:00Z", trained_at="2026-05-16T00:00:00Z")
        co = ctx["coordinator"]
        student, evaluation = self._prepare_started_evaluation(api, ctx, "L1")
        set_clock("2026-06-01T00:00:00Z")
        start_evaluation_now(evaluation["id"], co["id"])
        set_clock("2026-08-01T00:00:00Z")  # 61 days — late
        co_headers = make_coordinator_headers(co["id"])
        determined = validate_success(api.determine_evaluation(
            evaluation["id"],
            {"determination_outcome": "ELIGIBLE", "disability_impairment_found": True,
             "major_life_activity_affected": True},
            co_headers,
        ))
        assert determined["evaluation_status"] == "DETERMINATION_MADE"
        from test_helpers import get_success_data
        late_events = get_success_data(api.list_audit_events(
            co_headers,
            params={"school_id": ctx["school"]["id"], "event_type": "REVIEW_COMPLETED_LATE",
                    "entity_ref": evaluation["id"]},
        ))
        assert len(late_events) == 1, (
            f"late ELIGIBLE determination must be recorded via REVIEW_COMPLETED_LATE, found {len(late_events)}"
        )
        made_events = get_success_data(api.list_audit_events(
            co_headers,
            params={"school_id": ctx["school"]["id"], "event_type": "DETERMINATION_MADE",
                    "entity_ref": evaluation["id"]},
        ))
        assert len(made_events) == 1, "DETERMINATION_MADE must be emitted"


class TestPlanSubmitRequiresEligibleDetermination:
    def test_submit_plan_linked_to_not_eligible_determination_rejected(self, api):
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

        Design: Difficulty/cross_entity_state_dependency/plan_submit_requires_eligible_determination
        """
        ctx = setup_school_with_staff(clock_initial="2026-08-01T00:00:00Z")
        co = ctx["coordinator"]
        student = create_student_for(ctx["school"]["id"], co["id"])
        referral = submit_referral(student["id"], ctx["teacher"]["id"], role="Teacher")
        evaluation = pipeline_to_determination(
            student["id"], referral, co["id"],
            determination_outcome="NOT_ELIGIBLE",
            disability_impairment_found=False,
            major_life_activity_affected=False,
        )
        plan = create_draft_plan(student["id"], evaluation["id"], co["id"])
        add_accommodation(plan["id"], co["id"], applies_to_testing=False)
        plan_v = get_plan_version(plan["id"], co["id"])
        resp = api.submit_plan_for_consent(
            plan["id"], {"expected_plan_version": plan_v}, make_coordinator_headers(co["id"])
        )
        validate_error(resp, ApiErrorId.ERR_PLAN_REQUIRES_ELIGIBLE_DETERMINATION)
        plan_after = validate_success(api.get_plan(plan["id"], make_coordinator_headers(co["id"])))
        assert plan_after["plan_status"] == "DRAFT", "the transition must be blocked"

    def test_submit_plan_with_eligible_determination_creates_initial_consent(self, api):
        """PRD §3.4: "A successful submission moves the plan to
        `PENDING_PARENT_CONSENT`, creates a ParentConsentRecord with
        `consent_scope` `INITIAL_PLAN` and this plan's id, and increments the
        plan's `version` by 1."
        PRD §3.9: "Every record is stamped `requested_at` and opens in
        `REQUESTED`; the `consent_status` vocabulary is `REQUESTED`, `GRANTED`,
        `DENIED`, and `REVOKED`, with `responded_at` null until the parent
        responds."

        Design: Difficulty/cross_entity_state_dependency/plan_submit_requires_eligible_determination
        """
        ctx = setup_school_with_staff(clock_initial="2026-08-01T00:00:00Z")
        co = ctx["coordinator"]
        student = create_student_for(ctx["school"]["id"], co["id"])
        referral = submit_referral(student["id"], ctx["teacher"]["id"], role="Teacher")
        evaluation = pipeline_to_determination(student["id"], referral, co["id"])
        plan = create_draft_plan(student["id"], evaluation["id"], co["id"])
        add_accommodation(plan["id"], co["id"], applies_to_testing=False)
        plan_v = get_plan_version(plan["id"], co["id"])
        submitted = validate_success(api.submit_plan_for_consent(
            plan["id"], {"expected_plan_version": plan_v}, make_coordinator_headers(co["id"])
        ))
        assert submitted["plan_status"] == "PENDING_PARENT_CONSENT"
        assert submitted["version"] == plan_v + 1
        records = get_success_data(api.list_consent_records(
            make_coordinator_headers(co["id"]),
            params={"plan_id": plan["id"], "consent_scope": "INITIAL_PLAN"},
        ))
        assert len(records) == 1, "submission must create exactly one INITIAL_PLAN consent record"
        assert records[0]["consent_status"] == "REQUESTED"
        assert records[0]["plan_id"] == plan["id"]
