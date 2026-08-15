"""Grant execution: activation gates, fellowship offsets, completion vs
curtailment branches, medical cascade, completion 3-hop chain, capacity."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate_grant_at,
    complete_grant_at,
    create_application,
    create_coverage_plan,
    create_cycle,
    create_department,
    create_faculty,
    create_fellowship_payload,
    create_submitted_review,
    decide_application,
    get_application,
    get_success_data,
    grant_for_application,
    make_department_chair_headers,
    make_faculty_headers,
    open_cycle,
    run_accruals,
    set_clock,
    setup_department_with_chair,
    setup_full_award,
    setup_professional_grant,
    setup_reviewers,
    setup_submitted_sabbatical_application,
    submit_application,
    submit_coverage_plan,
    approve_coverage_plan,
    close_cycle,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
PROVOST = TEST_USERS["provost_headers"]


class TestGrantInvalidTransitions:
    def test_grant_invalid_transitions_rejected(self, api):
        """PRD 3.8: "A `LeaveAdministrator` completes a grant only from
        `ACTIVE` (`ERR_INVALID_GRANT_STATE`)"
        PRD 3.8: "the grant must be `ACTIVE` (`ERR_INVALID_GRANT_STATE`)"
        PRD 3.8: "the clock must have reached the grant's `start_date`
        (`ERR_GRANT_START_NOT_REACHED`)"

        Design: Corner/state_machines/grant_invalid_transitions_rejected
        """
        ctx = setup_professional_grant()  # grant SCHEDULED 2027-01-01..2027-07-01
        grant = ctx["grant"]
        # Clock stays at the 2026-08-01 startup default, before the window.

        complete = api.complete_leave_grant(grant["id"], ADMIN)
        validate_error(complete, ApiErrorId.ERR_INVALID_GRANT_STATE)

        curtail = api.curtail_leave_grant(
            grant["id"], {"actual_return_date": "2027-03-01T00:00:00Z"}, ADMIN
        )
        validate_error(curtail, ApiErrorId.ERR_INVALID_GRANT_STATE)

        early_activate = api.activate_leave_grant(grant["id"], ADMIN)
        validate_error(early_activate, ApiErrorId.ERR_GRANT_START_NOT_REACHED)


class TestFellowshipStateGates:
    def test_fellowship_state_gates_rejected(self, api):
        """PRD 3.8: "A `LeaveAdministrator` verifies a `REPORTED` fellowship —
        any other from-state is `ERR_INVALID_FELLOWSHIP_STATE`"
        PRD 3.8: "The reporting faculty member may decline their own fellowship
        from either `REPORTED` or `VERIFIED` (`ERR_NOT_RESOURCE_OWNER` for
        non-owners, `ERR_INVALID_FELLOWSHIP_STATE` from any other state; the
        `version` increments)."

        Design: Corner/state_machines/fellowship_state_gates_rejected
        """
        dept = create_department()
        faculty = create_faculty(dept["id"])
        cycle = create_cycle()  # DRAFT cycle is fine: reporting needs only ownership
        app = create_application(
            faculty["id"], leave_type="SABBATICAL", cycle_id=cycle["id"],
            proposed_start_date="2027-03-01T00:00:00Z",
            proposed_end_date="2027-09-01T00:00:00Z",
        )
        fel_a = get_success_data(
            api.create_external_fellowship(
                create_fellowship_payload(
                    app["id"], amount=5000.00,
                    window_start_date="2027-03-01T00:00:00Z",
                    window_end_date="2027-07-01T00:00:00Z",
                ),
                make_faculty_headers(faculty["id"]),
            )
        )
        fel_b = get_success_data(
            api.create_external_fellowship(
                create_fellowship_payload(
                    app["id"], amount=6000.00,
                    window_start_date="2027-03-01T00:00:00Z",
                    window_end_date="2027-07-01T00:00:00Z",
                ),
                make_faculty_headers(faculty["id"]),
            )
        )

        verified = validate_success(api.verify_external_fellowship(fel_a["id"], ADMIN))
        assert verified["status"] == "VERIFIED"
        reverify = api.verify_external_fellowship(fel_a["id"], ADMIN)
        validate_error(reverify, ApiErrorId.ERR_INVALID_FELLOWSHIP_STATE)

        get_success_data(api.verify_external_fellowship(fel_b["id"], ADMIN))
        declined = validate_success(
            api.decline_external_fellowship(fel_b["id"], make_faculty_headers(faculty["id"]))
        )
        assert declined["status"] == "DECLINED"
        verify_declined = api.verify_external_fellowship(fel_b["id"], ADMIN)
        validate_error(verify_declined, ApiErrorId.ERR_INVALID_FELLOWSHIP_STATE)


class TestFellowshipOverlapBoundary:
    def _setup(self, api):
        """Faculty (72 credits) with an UNDER_REVIEW sabbatical application
        window 2027-03-01..2027-09-01 (184 days)."""
        dept = create_department()
        faculty = create_faculty(dept["id"])
        run_accruals()
        cycle = open_cycle(create_cycle()["id"])
        app = setup_submitted_sabbatical_application(
            faculty["id"], cycle["id"],
            start="2027-03-01T00:00:00Z", end="2027-09-01T00:00:00Z",
        )
        return faculty, app

    def test_exactly_half_overlap_verifies(self, api):
        """PRD 3.8: "A `LeaveAdministrator` verifies a `REPORTED` fellowship —
        any other from-state is `ERR_INVALID_FELLOWSHIP_STATE` — only when its
        half-open overlap with the application's proposed window covers at
        least fifty percent of that window's days, failing with
        `ERR_FELLOWSHIP_OVERLAP_INSUFFICIENT`"

        Design: Difficulty/boundary_precision_check/fellowship_exactly_half_overlap_vs_one_day_short
        """
        faculty, app = self._setup(api)
        # 2027-03-01..2027-06-01 = 92 days of a 184-day window: exactly 50%.
        fel = get_success_data(
            api.create_external_fellowship(
                create_fellowship_payload(
                    app["id"], amount=5000.00,
                    window_start_date="2027-03-01T00:00:00Z",
                    window_end_date="2027-06-01T00:00:00Z",
                ),
                make_faculty_headers(faculty["id"]),
            )
        )
        verified = validate_success(api.verify_external_fellowship(fel["id"], ADMIN))
        assert verified["status"] == "VERIFIED"

    def test_one_day_short_of_half_rejected(self, api):
        """PRD 3.8: "only when its half-open overlap with the application's
        proposed window covers at least fifty percent of that window's days,
        failing with `ERR_FELLOWSHIP_OVERLAP_INSUFFICIENT`"

        Design: Difficulty/boundary_precision_check/fellowship_exactly_half_overlap_vs_one_day_short
        """
        faculty, app = self._setup(api)
        # 2027-03-01..2027-05-31 = 91 days of a 184-day window: below 50%.
        fel = get_success_data(
            api.create_external_fellowship(
                create_fellowship_payload(
                    app["id"], amount=6000.00,
                    window_start_date="2027-03-01T00:00:00Z",
                    window_end_date="2027-05-31T00:00:00Z",
                ),
                make_faculty_headers(faculty["id"]),
            )
        )
        resp = api.verify_external_fellowship(fel["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_FELLOWSHIP_OVERLAP_INSUFFICIENT)


class TestSalaryTierFellowshipWaterfall:
    def _setup_two_fellowship_award(self, api):
        """2-semester 75% award with two VERIFIED fellowships queued."""
        ctx = setup_full_award(
            courses_to_cover=5, award_quota=1, faculty_rank="FULL_PROFESSOR",
            semesters=2, salary_pct=75,
            start="2027-01-01T00:00:00Z", end="2028-01-01T00:00:00Z",
        )
        faculty, app = ctx["faculty"], ctx["application"]
        # Reported (and thus created) in this order; both windows meet the
        # 50% overlap rule against the 365-day grant window.
        fel1 = get_success_data(
            api.create_external_fellowship(
                create_fellowship_payload(
                    app["id"], name="NEH Fellowship", amount=25000.00,
                    window_start_date="2027-01-01T00:00:00Z",
                    window_end_date="2027-07-03T00:00:00Z",  # 183 days
                ),
                make_faculty_headers(faculty["id"]),
            )
        )
        fel2 = get_success_data(
            api.create_external_fellowship(
                create_fellowship_payload(
                    app["id"], name="Mellon Grant", amount=40000.00,
                    window_start_date="2027-06-01T00:00:00Z",
                    window_end_date="2028-01-01T00:00:00Z",  # 214 days
                ),
                make_faculty_headers(faculty["id"]),
            )
        )
        get_success_data(api.verify_external_fellowship(fel1["id"], ADMIN))
        get_success_data(api.verify_external_fellowship(fel2["id"], ADMIN))
        ctx["fellowships"] = (fel1, fel2)
        return ctx

    def test_grant_salary_tier_and_offset_cap(self, api):
        """PRD 3.8: "First, `gross_salary` is the member's `annual_base_salary`
        multiplied by the grant's `salary_pct` divided by one hundred,
        multiplied by the grant's length in months (its `duration_semesters`
        times six) divided by twelve, the whole result rounded half-up to two
        decimal places"
        PRD 3.8: "Second, the fellowship offset cap is fifty percent of that
        gross, rounded half-up to two decimal places. Third,
        `fellowship_offset_total` is filled from the fellowship waterfall
        below, bounded by the cap. Fourth, `net_salary` is the gross minus the
        total offset."

        Design: Difficulty/combinatorial_formula/salary_tier_fellowship_cap_waterfall
        """
        ctx = self._setup_two_fellowship_award(api)
        grant = activate_grant_at(ctx["grant"]["id"], "2027-01-01T00:00:00Z")
        # 120000.00 * 0.75 * 12/12 = 90000.00; cap 45000.00.
        assert grant["gross_salary"] == pytest.approx(90000.00, abs=0.005)
        assert grant["fellowship_offset_total"] == pytest.approx(45000.00, abs=0.005)
        assert grant["net_salary"] == pytest.approx(45000.00, abs=0.005)

    def test_fellowship_waterfall_consumes_oldest_first_to_cap(self, api):
        """PRD 3.8: "Eligible fellowships are consumed oldest first by
        `created_at` (timestamps are unique at three fractional digits, so
        ties cannot occur): each receives an `applied_offset` equal to the
        lesser of its own `amount` and the remaining cap, the remaining cap
        shrinks by that amount, and the fellowship moves `VERIFIED` →
        `APPLIED`."

        Design: Difficulty/combinatorial_formula/salary_tier_fellowship_cap_waterfall
        """
        ctx = self._setup_two_fellowship_award(api)
        fel1, fel2 = ctx["fellowships"]
        activate_grant_at(ctx["grant"]["id"], "2027-01-01T00:00:00Z")

        fel1_after = validate_success(api.get_external_fellowship(fel1["id"], ADMIN))
        fel2_after = validate_success(api.get_external_fellowship(fel2["id"], ADMIN))
        assert fel1_after["status"] == "APPLIED"
        assert fel1_after["applied_offset"] == pytest.approx(25000.00, abs=0.005)
        # Cap remainder 45000.00 - 25000.00 = 20000.00 bounds the second award.
        assert fel2_after["status"] == "APPLIED"
        assert fel2_after["applied_offset"] == pytest.approx(20000.00, abs=0.005)


class TestDepartmentLeaveCapacity:
    def _setup_three_scheduled(self, api):
        """One department, three faculty with SCHEDULED professional grants
        for the same window 2027-01-01..2027-07-01."""
        dept = create_department()
        grants = []
        for i, (rank, salary) in enumerate(
            (("ASSOCIATE_PROFESSOR", 120000.00), ("ASSISTANT_PROFESSOR", 100000.00),
             ("FULL_PROFESSOR", 140000.00))
        ):
            faculty = create_faculty(
                dept["id"], academic_rank=rank, annual_base_salary=salary,
                hire_date="2020-08-01T00:00:00Z",
            )
            app = create_application(
                faculty["id"], leave_type="PROFESSIONAL",
                requested_duration_semesters=1, requested_salary_pct=100,
                proposed_start_date="2027-01-01T00:00:00Z",
                proposed_end_date="2027-07-01T00:00:00Z",
            )
            submit_application(app["id"], faculty["id"])
            decide_application(app["id"], "APPROVED")
            grants.append(grant_for_application(app["id"]))
        return dept, grants

    def test_first_two_activations_succeed(self, api):
        """PRD 3.8: "the department's active-leave capacity must hold — on
        every calendar day of the new grant's half-open window, counting other
        `ACTIVE` grants of faculty from the same department whose windows
        contain that day, the count must stay below two, the department's
        maximum simultaneous active leaves, or activation fails with
        `ERR_DEPARTMENT_LEAVE_CAPACITY`."

        Design: Difficulty/resource_temporal_overlap/department_active_leave_capacity
        """
        _dept, grants = self._setup_three_scheduled(api)
        set_clock("2027-01-01T00:00:00Z")
        first = validate_success(api.activate_leave_grant(grants[0]["id"], ADMIN))
        second = validate_success(api.activate_leave_grant(grants[1]["id"], ADMIN))
        assert first["status"] == "ACTIVE"
        assert second["status"] == "ACTIVE"

    def test_third_overlapping_activation_rejected(self, api):
        """PRD 3.8: "the count must stay below two, the department's maximum
        simultaneous active leaves, or activation fails with
        `ERR_DEPARTMENT_LEAVE_CAPACITY`."

        Design: Difficulty/resource_temporal_overlap/department_active_leave_capacity
        """
        _dept, grants = self._setup_three_scheduled(api)
        set_clock("2027-01-01T00:00:00Z")
        get_success_data(api.activate_leave_grant(grants[0]["id"], ADMIN))
        get_success_data(api.activate_leave_grant(grants[1]["id"], ADMIN))
        third = api.activate_leave_grant(grants[2]["id"], ADMIN)
        validate_error(third, ApiErrorId.ERR_DEPARTMENT_LEAVE_CAPACITY)


class TestGrantBranchDivergentSideEffects:
    def _setup_two_active_grants(self, api):
        """Two faculty in one department, each awarded in a quota-2 cycle:
        A with a 5-course plan, B with a 3-course plan; both grants ACTIVE."""
        base = setup_department_with_chair()
        dept, chair = base["department"], base["chair"]
        fa = create_faculty(dept["id"], employee_number="F100")
        fb = create_faculty(
            dept["id"], employee_number="F200", academic_rank="ASSISTANT_PROFESSOR",
            annual_base_salary=100000.00,
        )
        reviewers = setup_reviewers(count=3)
        run_accruals()
        cycle = open_cycle(create_cycle(award_quota=2)["id"])

        app_a = setup_submitted_sabbatical_application(fa["id"], cycle["id"])
        app_b = setup_submitted_sabbatical_application(fb["id"], cycle["id"])
        for reviewer in reviewers:
            create_submitted_review(app_a["id"], reviewer["id"], 90, 85, 95)
        for reviewer in reviewers:
            create_submitted_review(app_b["id"], reviewer["id"], 80, 90, 70)
        plan_a = create_coverage_plan(app_a["id"], chair["id"], 5)
        submit_coverage_plan(plan_a["id"], chair["id"])
        approve_coverage_plan(plan_a["id"])
        plan_b = create_coverage_plan(app_b["id"], chair["id"], 3)
        submit_coverage_plan(plan_b["id"], chair["id"])
        approve_coverage_plan(plan_b["id"])

        close_cycle(cycle["id"])
        validate_success(api.allocate_leave_cycle(cycle["id"], PROVOST))
        grant_a = grant_for_application(app_a["id"])
        grant_b = grant_for_application(app_b["id"])
        set_clock("2027-01-01T00:00:00Z")
        activate_grant_at_grant = get_success_data(
            api.activate_leave_grant(grant_a["id"], ADMIN)
        )
        get_success_data(api.activate_leave_grant(grant_b["id"], ADMIN))
        return {
            "department": dept, "chair": chair, "fa": fa, "fb": fb,
            "app_a": app_a, "app_b": app_b, "plan_a": plan_a, "plan_b": plan_b,
            "grant_a": grant_a, "grant_b": grant_b,
        }

    def test_completed_branch_settles_full_and_creates_report(self, api):
        """PRD 3.8: "Hop one: the application's `CONFIRMED` coverage plan
        becomes `SETTLED` with `final_cost` equal to the full
        `provisional_cost`."
        PRD 3.8: "For sabbatical and professional grants only, completion also
        creates a service obligation (`IN_PROGRESS`, with `required_months`
        equal to `actual_months` and `last_credited_month` initialized to the
        month before the grant's end month) and an accomplishment report in
        `DUE` status whose `due_date` falls ninety days after the grant's
        `end_date`"

        Design: Difficulty/non_linear_state_machine/grant_branch_divergent_side_effects
        """
        ctx = self._setup_two_active_grants(api)
        complete_grant_at(ctx["grant_a"]["id"], "2027-07-01T00:00:00Z")

        plan_a = validate_success(api.get_coverage_plan(ctx["plan_a"]["id"], ADMIN))
        assert plan_a["status"] == "SETTLED"
        assert plan_a["final_cost"] == pytest.approx(40000.00, abs=0.005)

        obligations, _ = validate_paginated(
            api.list_service_obligations(ADMIN, params={"faculty_id": ctx["fa"]["id"]})
        )
        assert len(obligations) == 1
        assert obligations[0]["required_months"] == 6

        reports, _ = validate_paginated(
            api.list_accomplishment_reports(ADMIN, params={"faculty_id": ctx["fa"]["id"]})
        )
        assert len(reports) == 1
        assert reports[0]["status"] == "DUE"

    def test_curtailed_branch_prorates_restores_and_skips_report(self, api):
        """PRD 3.8: "A `RESTORE` ledger entry of plus six credits per unused
        month — the planned months (semesters times six) minus the months
        actually served — posts to the faculty member. The sabbatical coverage
        plan settles `CONFIRMED` → `SETTLED` with a pro-rated `final_cost`: the
        `provisional_cost` multiplied by the ratio of actual months to planned
        months, rounded half-up to two decimal places"
        PRD 3.8: "For sabbatical and professional leaves a service obligation
        is created with `required_months` equal to the curtailed
        `actual_months` — but no accomplishment report is ever created on
        curtailment."

        Design: Difficulty/non_linear_state_machine/grant_branch_divergent_side_effects
        """
        ctx = self._setup_two_active_grants(api)
        # B curtails at 2027-05-01: 4 whole months served of 6 planned.
        set_clock("2027-05-01T00:00:00Z")
        curtailed = validate_success(
            api.curtail_leave_grant(
                ctx["grant_b"]["id"], {"actual_return_date": "2027-05-01T00:00:00Z"}, ADMIN
            )
        )
        assert curtailed["status"] == "CURTAILED"
        assert curtailed["actual_months"] == 4

        plan_b = validate_success(api.get_coverage_plan(ctx["plan_b"]["id"], ADMIN))
        assert plan_b["status"] == "SETTLED"
        # round(24000.00 * 4/6, 2) = 16000.00
        assert plan_b["final_cost"] == pytest.approx(16000.00, abs=0.005)

        obligations, _ = validate_paginated(
            api.list_service_obligations(ADMIN, params={"faculty_id": ctx["fb"]["id"]})
        )
        assert len(obligations) == 1
        assert obligations[0]["required_months"] == 4

        # 72 earned - 36 consumed + 12 restored (2 unused months * 6).
        fb_fresh = validate_success(api.get_faculty_member(ctx["fb"]["id"], ADMIN))
        assert fb_fresh["credit_balance"] == 48

        reports, _ = validate_paginated(
            api.list_accomplishment_reports(ADMIN, params={"faculty_id": ctx["fb"]["id"]})
        )
        assert reports == []


class TestMedicalApprovalCancelsSabbatical:
    def _setup_medical_cascade(self, api):
        """Awarded sabbatical (grant SCHEDULED 2027-01-01..2027-07-01, 3-course
        plan CONFIRMED) plus an UNDER_REVIEW overlapping MEDICAL application."""
        ctx = setup_full_award(courses_to_cover=3, award_quota=1)
        faculty = ctx["faculty"]
        medical = create_application(
            faculty["id"], leave_type="MEDICAL",
            requested_duration_semesters=1, requested_salary_pct=0,
            proposed_start_date="2027-03-01T00:00:00Z",
            proposed_end_date="2027-09-01T00:00:00Z",
        )
        submit_application(medical["id"], faculty["id"])
        ctx["medical"] = medical
        return ctx

    def test_medical_approval_cancels_sabbatical_grant_and_rescinds(self, api):
        """PRD 3.7: "Any overlapping `SCHEDULED` sabbatical grant of the same
        faculty member is cancelled, and cancellation is a full unwind: a
        `RESTORE` ledger entry of plus thirty-six credits per
        `duration_semesters` posts to the faculty member, the cancelled grant's
        `CONFIRMED` coverage plan becomes `RELEASED` (the department's
        `reserved_amount` decreases by the plan's `provisional_cost`,
        `spent_amount` is untouched, and the posture is recomputed), the
        cancelled grant's own application moves `AWARDED` → `RESCINDED` with
        its `funding_status` falling to `COVERAGE_RELEASED`, and any of its
        `VERIFIED` external fellowships become `DECLINED`."

        Design: Difficulty/transitive_cascade/medical_approval_cancels_sabbatical_chain
        """
        ctx = self._setup_medical_cascade(api)
        approved = validate_success(
            api.decide_leave_application(ctx["medical"]["id"], {"decision": "APPROVED"}, PROVOST)
        )
        assert approved["status"] == "APPROVED"

        medical_grant = grant_for_application(ctx["medical"]["id"])
        assert medical_grant["status"] == "SCHEDULED"

        sab_grant = validate_success(api.get_leave_grant(ctx["grant"]["id"], ADMIN))
        assert sab_grant["status"] == "CANCELLED"

        sab_app = get_application(ctx["application"]["id"])
        assert sab_app["status"] == "RESCINDED"
        assert sab_app["funding_status"] == "COVERAGE_RELEASED"

    def test_medical_approval_releases_plan_and_restores_credits(self, api):
        """PRD 3.7: "the cancelled grant's `CONFIRMED` coverage plan becomes
        `RELEASED` (the department's `reserved_amount` decreases by the plan's
        `provisional_cost`, `spent_amount` is untouched, and the posture is
        recomputed)"
        PRD 3.2: "a cancellation restores the full thirty-six per semester"

        Design: Difficulty/transitive_cascade/medical_approval_cancels_sabbatical_chain
        """
        ctx = self._setup_medical_cascade(api)
        validate_success(
            api.decide_leave_application(ctx["medical"]["id"], {"decision": "APPROVED"}, PROVOST)
        )

        faculty = ctx["faculty"]
        fresh = validate_success(api.get_faculty_member(faculty["id"], ADMIN))
        assert fresh["credit_balance"] == 72  # 72 - 36 consumed + 36 restored

        plan = validate_success(api.get_coverage_plan(ctx["plan"]["id"], ADMIN))
        assert plan["status"] == "RELEASED"

        dept = validate_success(api.get_department(ctx["department"]["id"], ADMIN))
        assert dept["reserved_amount"] == pytest.approx(0.00, abs=0.005)
        assert dept["spent_amount"] == pytest.approx(0.00, abs=0.005)
        assert dept["posture"] == "OPEN"


class TestCompletionPostureChain:
    def _setup_frozen_department(self, api):
        """Engineering pool 160000.00 driven to exactly 0.95 utilization:
        F2's approved 14-course plan (112000.00) in a second OPEN cycle plus
        F's awarded 5-course plan (40000.00); F's grant ACTIVE."""
        base = setup_department_with_chair()
        dept, chair = base["department"], base["chair"]
        faculty = create_faculty(dept["id"], employee_number="F100")
        f2 = create_faculty(
            dept["id"], employee_number="F200", academic_rank="ASSISTANT_PROFESSOR",
            annual_base_salary=100000.00,
        )
        f3 = create_faculty(
            dept["id"], employee_number="F300", academic_rank="FULL_PROFESSOR",
            annual_base_salary=140000.00,
        )
        reviewers = setup_reviewers(count=3)
        run_accruals()

        # Second cycle (stays OPEN) carrying F2's approved 14-course plan.
        cycle2 = open_cycle(
            create_cycle(award_quota=1, name="AY2028 Sabbaticals",
                         academic_year="2028-2029")["id"]
        )
        app2 = setup_submitted_sabbatical_application(
            f2["id"], cycle2["id"], start="2028-01-01T00:00:00Z",
            end="2028-07-01T00:00:00Z",
        )
        plan2 = create_coverage_plan(app2["id"], chair["id"], 14)
        submit_coverage_plan(plan2["id"], chair["id"])
        approve_coverage_plan(plan2["id"])

        # F3 holds an UNDER_REVIEW application with a DRAFT plan to probe the
        # posture gate before/after the flip.
        app3 = setup_submitted_sabbatical_application(
            f3["id"], cycle2["id"], start="2028-01-01T00:00:00Z",
            end="2028-07-01T00:00:00Z",
        )
        plan3 = create_coverage_plan(app3["id"], chair["id"], 1)

        # F's own award pipeline in a first cycle.
        cycle1 = open_cycle(create_cycle(award_quota=1)["id"])
        app1 = setup_submitted_sabbatical_application(faculty["id"], cycle1["id"])
        for reviewer, (m, c, s) in zip(reviewers, ((80, 90, 70), (90, 85, 95), (70, 60, 80))):
            create_submitted_review(app1["id"], reviewer["id"], m, c, s)
        plan1 = create_coverage_plan(app1["id"], chair["id"], 5)
        submit_coverage_plan(plan1["id"], chair["id"])
        approve_coverage_plan(plan1["id"])
        close_cycle(cycle1["id"])
        validate_success(api.allocate_leave_cycle(cycle1["id"], PROVOST))
        grant1 = grant_for_application(app1["id"])
        set_clock("2027-01-01T00:00:00Z")
        get_success_data(api.activate_leave_grant(grant1["id"], ADMIN))
        return {
            "department": dept, "chair": chair, "faculty": faculty,
            "plan1": plan1, "plan3": plan3, "grant1": grant1,
        }

    def test_completion_cascade_recomputes_buckets_and_posture(self, api):
        """PRD 3.8: "Hop one: the application's `CONFIRMED` coverage plan
        becomes `SETTLED` with `final_cost` equal to the full
        `provisional_cost`. Hop two: the department's `reserved_amount`
        decreases by the `provisional_cost` while its `spent_amount` increases
        by the `final_cost`, and `available_amount` is recomputed. Hop three:
        the department's posture is recomputed and persisted — a settlement can
        flip a `FROZEN` department back to `CONSTRAINED` or `OPEN`, re-enabling
        plan submissions there."

        Design: Difficulty/transitive_cascade/complete_grant_plan_dept_posture_chain
        """
        ctx = self._setup_frozen_department(api)
        dept_id = ctx["department"]["id"]

        pre = validate_success(api.get_department(dept_id, ADMIN))
        # 112000.00 + 40000.00 = 152000.00 of 160000.00: exactly 0.95.
        assert pre["reserved_amount"] == pytest.approx(152000.00, abs=0.005)
        assert pre["posture"] == "FROZEN"

        complete_grant_at(ctx["grant1"]["id"], "2027-07-01T00:00:00Z")

        plan1 = validate_success(api.get_coverage_plan(ctx["plan1"]["id"], ADMIN))
        assert plan1["status"] == "SETTLED"
        assert plan1["final_cost"] == pytest.approx(40000.00, abs=0.005)

        post = validate_success(api.get_department(dept_id, ADMIN))
        assert post["reserved_amount"] == pytest.approx(112000.00, abs=0.005)
        assert post["spent_amount"] == pytest.approx(40000.00, abs=0.005)
        # PRD 3.1 compares the committed total (reserved plus spent) against
        # the pool: a full-term settlement moves 40000.00 from reserved to
        # spent, so committed stays 152000.00 of 160000.00 — exactly 0.95,
        # an inclusive boundary -> FROZEN persists.
        assert post["posture"] == "FROZEN"
        assert post["available_amount"] == pytest.approx(8000.00, abs=0.005)

    def test_settlement_reenables_plan_submission(self, api):
        """PRD 3.8: "a settlement can flip a `FROZEN` department back to
        `CONSTRAINED` or `OPEN`, re-enabling plan submissions there."
        PRD 3.8: "The sabbatical coverage plan settles `CONFIRMED` → `SETTLED`
        with a pro-rated `final_cost` ... the department's buckets and posture
        recompute as at completion, with the difference between provisional
        and final flowing back into `available_amount`."
        PRD 3.1: "A `FROZEN` department cannot move coverage plans forward —
        both plan submission and plan approval are rejected with
        `ERR_DEPARTMENT_FROZEN`"

        The flip requires settlement to shrink the committed total, which only
        the pro-rated (curtailment) branch does: curtailing at 3 of 6 months
        settles final_cost 20000.00 against provisional 40000.00, dropping
        committed from 152000.00 (0.95 -> FROZEN) to 132000.00 (0.825 ->
        CONSTRAINED).

        Design: Difficulty/transitive_cascade/complete_grant_plan_dept_posture_chain
        """
        ctx = self._setup_frozen_department(api)
        dept_id = ctx["department"]["id"]

        frozen = api.submit_coverage_plan(
            ctx["plan3"]["id"], make_department_chair_headers(ctx["chair"]["id"])
        )
        validate_error(frozen, ApiErrorId.ERR_DEPARTMENT_FROZEN)

        set_clock("2027-04-01T00:00:00Z")
        curtailed = validate_success(
            api.curtail_leave_grant(
                ctx["grant1"]["id"], {"actual_return_date": "2027-04-01T00:00:00Z"}, ADMIN
            )
        )
        assert curtailed["status"] == "CURTAILED"

        post = validate_success(api.get_department(dept_id, ADMIN))
        assert post["posture"] == "CONSTRAINED"

        submitted = validate_success(
            api.submit_coverage_plan(
                ctx["plan3"]["id"], make_department_chair_headers(ctx["chair"]["id"])
            )
        )
        assert submitted["status"] == "SUBMITTED"


class TestImmediateConsistency:
    def test_immediate_side_effects_visible_same_request(self, api):
        """PRD 2.4: "All side effects triggered by a request take effect
        atomically within that request: if any part of the operation fails, no
        part of it is persisted."
        PRD 3.7: "It then creates a leave grant in `SCHEDULED` status carrying
        the proposed window and terms, with salary figures deferred to
        activation exactly as in the sabbatical case, and the application moves
        to `APPROVED`, terminal."

        Design: Corner/consistency_model/immediate_side_effects_visible_same_request
        """
        dept = create_department()
        faculty = create_faculty(dept["id"])
        app = create_application(
            faculty["id"], leave_type="PROFESSIONAL",
            requested_duration_semesters=1, requested_salary_pct=100,
            proposed_start_date="2027-01-01T00:00:00Z",
            proposed_end_date="2027-07-01T00:00:00Z",
        )
        submit_application(app["id"], faculty["id"])

        decided = validate_success(
            api.decide_leave_application(app["id"], {"decision": "APPROVED"}, PROVOST)
        )
        assert decided["status"] == "APPROVED"

        grants, _ = validate_paginated(
            api.list_leave_grants(ADMIN, params={"application_id": app["id"]})
        )
        assert len(grants) == 1
        assert grants[0]["status"] == "SCHEDULED"
        assert grants[0]["start_date"].startswith("2027-01-01")
