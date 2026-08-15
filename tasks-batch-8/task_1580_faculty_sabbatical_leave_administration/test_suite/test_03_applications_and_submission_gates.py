"""Leave application creation rules, cycle gates, and the submit gate chain."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    activate_grant_at,
    complete_grant_at,
    create_accrual_ledger_entry_payload,
    create_application,
    create_cycle,
    create_department,
    create_faculty,
    decide_application,
    get_success_data,
    grant_for_application,
    make_faculty_headers,
    open_cycle,
    run_accruals,
    separate_faculty,
    set_clock,
    setup_full_award,
    setup_professional_grant,
    setup_submitted_sabbatical_application,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
PROVOST = TEST_USERS["provost_headers"]


class TestApplicationInitialState:
    def test_application_born_draft(self, api):
        """PRD 3.3: "A new application is born `DRAFT` with `funding_status`
        `NONE`, its `composite_score` and `final_rank` and `award_outcome` all
        null, `submitted_review_count` zero, and `quorum_met` false."
        PRD 2.4: "The `version` is an integer that starts at 1 when the
        resource is created"

        Design: Corner/state_machines/application_initial_state_draft
        """
        dept = create_department()
        faculty = create_faculty(dept["id"])
        cycle = create_cycle()
        app = create_application(faculty["id"], leave_type="SABBATICAL", cycle_id=cycle["id"])
        assert app["status"] == "DRAFT"
        assert app["funding_status"] == "NONE"
        assert app["composite_score"] is None
        assert app["submitted_review_count"] == 0
        assert app["quorum_met"] is False
        assert app["version"] == 1


class TestCycleTransitions:
    def test_cycle_invalid_from_transitions_rejected(self, api):
        """PRD 3.6: "Once a cycle is `CLOSED`, the `ProvostOffice` runs the
        allocation — attempting it from any other state is
        `ERR_CYCLE_NOT_CLOSED`."
        PRD 3.3: "each transition requires its stated from-state (anything else
        is `ERR_INVALID_CYCLE_STATE`)"
        PRD 3.6: "finalizing from any other state is `ERR_CYCLE_NOT_ALLOCATED`"

        Design: Corner/state_machines/cycle_invalid_from_transitions_rejected
        """
        cycle = open_cycle(create_cycle()["id"])

        allocate_from_open = api.allocate_leave_cycle(cycle["id"], PROVOST)
        validate_error(allocate_from_open, ApiErrorId.ERR_CYCLE_NOT_CLOSED)

        open_from_open = api.open_leave_cycle(cycle["id"], PROVOST)
        validate_error(open_from_open, ApiErrorId.ERR_INVALID_CYCLE_STATE)

        get_success_data(api.close_leave_cycle(cycle["id"], PROVOST))
        finalize_from_closed = api.finalize_leave_cycle(cycle["id"], PROVOST)
        validate_error(finalize_from_closed, ApiErrorId.ERR_CYCLE_NOT_ALLOCATED)


class TestApplicationCreationTypeCombos:
    @pytest.mark.parametrize(
        "leave_type,cycle_id,semesters,salary_pct,start,end,expected_error",
        [
            # 1-semester sabbatical pays only 100
            ("SABBATICAL", "cycle", 1, 75, "2027-01-01T00:00:00Z", "2027-07-01T00:00:00Z",
             ApiErrorId.ERR_INVALID_DURATION_SALARY_COMBO),
            # 2-semester sabbatical pays 50 or 75
            ("SABBATICAL", "cycle", 2, 100, "2027-01-01T00:00:00Z", "2028-01-01T00:00:00Z",
             ApiErrorId.ERR_INVALID_DURATION_SALARY_COMBO),
            # professional is fixed at 100
            ("PROFESSIONAL", None, 1, 50, "2027-01-01T00:00:00Z", "2027-07-01T00:00:00Z",
             ApiErrorId.ERR_INVALID_DURATION_SALARY_COMBO),
            # cycle_id forbidden for non-sabbatical
            ("MEDICAL", "cycle", 1, 0, "2027-01-01T00:00:00Z", "2027-07-01T00:00:00Z",
             ApiErrorId.ERR_INVALID_REQUEST),
            # cycle_id required for sabbatical
            ("SABBATICAL", None, 1, 100, "2027-01-01T00:00:00Z", "2027-07-01T00:00:00Z",
             ApiErrorId.ERR_INVALID_REQUEST),
        ],
    )
    def test_application_create_invalid_type_combos_rejected(
        self, api, leave_type, cycle_id, semesters, salary_pct, start, end, expected_error
    ):
        """PRD 3.3: "The `cycle_id` field is required exactly when the leave
        type is `SABBATICAL` and forbidden for every other type; violating
        either direction is `ERR_INVALID_REQUEST`."
        PRD 3.3: "a one-semester sabbatical pays only 100 percent, a
        two-semester sabbatical pays 50 or 75 percent, professional leave
        always pays 100 percent, and medical or personal leave pays 0 percent.
        Any other combination is rejected with
        `ERR_INVALID_DURATION_SALARY_COMBO`."

        Design: Corner/validations/application_create_invalid_type_combos_rejected
        """
        dept = create_department()
        faculty = create_faculty(dept["id"])
        cycle = create_cycle()
        payload = {
            "leave_type": leave_type,
            "requested_duration_semesters": semesters,
            "requested_salary_pct": salary_pct,
            "proposed_start_date": start,
            "proposed_end_date": end,
        }
        if cycle_id == "cycle":
            payload["cycle_id"] = cycle["id"]
        resp = api.create_leave_application(payload, make_faculty_headers(faculty["id"]))
        validate_error(resp, expected_error)


class TestApplicationCreationDateRange:
    @pytest.mark.parametrize(
        "start,end",
        [
            ("2027-07-01T00:00:00Z", "2027-01-01T00:00:00Z"),  # end <= start
            ("2027-01-01T00:00:00Z", "2027-06-15T00:00:00Z"),  # not exactly 6 months
        ],
    )
    def test_application_create_invalid_date_range_rejected(self, api, start, end):
        """PRD 3.3: "the end must be strictly after the start, and the end must
        equal the start plus the requested number of semesters times six
        calendar months — with violations rejected as `ERR_INVALID_DATE_RANGE`."

        Design: Corner/validations/application_create_invalid_date_range_rejected
        """
        dept = create_department()
        faculty = create_faculty(dept["id"])
        cycle = create_cycle()
        resp = api.create_leave_application(
            {
                "leave_type": "SABBATICAL",
                "cycle_id": cycle["id"],
                "requested_duration_semesters": 1,
                "requested_salary_pct": 100,
                "proposed_start_date": start,
                "proposed_end_date": end,
            },
            make_faculty_headers(faculty["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE)


class TestApplicationNotFound:
    def test_application_get_not_found_returns_404(self, api):
        """PRD 2.9: "the first missing reference yields its corresponding
        error: ... `ERR_APPLICATION_NOT_FOUND`"

        Design: Corner/entities/application_get_not_found_returns_404
        """
        resp = api.get_leave_application(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_FOUND)


class TestApplicationTerminalLockdown:
    def test_withdrawn_application_rejects_all_transitions(self, api):
        """PRD 3.3: "Submitting moves an application from `DRAFT` — or from
        `REVISION_REQUESTED`, since the cycle has a revision loop — to
        `UNDER_REVIEW`. Only the owning faculty member may submit
        (`ERR_NOT_RESOURCE_OWNER`), and only from those two states
        (`ERR_INVALID_APPLICATION_STATE`)."
        PRD 3.3: "requesting revision moves `UNDER_REVIEW` →
        `REVISION_REQUESTED` (any other from-state is
        `ERR_INVALID_APPLICATION_STATE`)"
        PRD 3.7: "Invoking the decision on a sabbatical application is rejected
        with `ERR_SABBATICAL_REQUIRES_ALLOCATION` — sabbaticals are decided
        only by the allocation run"

        Design: Corner/state_machines/application_terminal_lockdown_withdrawn
        """
        dept = create_department()
        faculty = create_faculty(dept["id"])
        run_accruals()
        cycle = open_cycle(create_cycle()["id"])
        app1 = setup_submitted_sabbatical_application(faculty["id"], cycle["id"])
        get_success_data(
            api.withdraw_leave_application(app1["id"], make_faculty_headers(faculty["id"]))
        )
        app2 = setup_submitted_sabbatical_application(faculty["id"], cycle["id"])

        resubmit = api.submit_leave_application(app1["id"], make_faculty_headers(faculty["id"]))
        validate_error(resubmit, ApiErrorId.ERR_INVALID_APPLICATION_STATE)

        revise = api.request_application_revision(app1["id"], PROVOST)
        validate_error(revise, ApiErrorId.ERR_INVALID_APPLICATION_STATE)

        decide_sabbatical = api.decide_leave_application(app2["id"], {"decision": "APPROVED"}, PROVOST)
        validate_error(decide_sabbatical, ApiErrorId.ERR_SABBATICAL_REQUIRES_ALLOCATION)


class TestSubmitRequiresCycleOpen:
    def test_submit_rejected_while_cycle_draft_then_succeeds_when_open(self, api):
        """PRD 3.3: "For a sabbatical the referenced cycle must be `OPEN`, else
        `ERR_CYCLE_NOT_OPEN`."

        Design: Difficulty/cross_entity_state_dependency/submit_requires_cycle_open
        """
        dept = create_department()
        faculty = create_faculty(dept["id"])
        run_accruals()
        cycle = create_cycle()  # stays DRAFT
        app = create_application(
            faculty["id"], leave_type="SABBATICAL", cycle_id=cycle["id"],
        )
        blocked = api.submit_leave_application(app["id"], make_faculty_headers(faculty["id"]))
        validate_error(blocked, ApiErrorId.ERR_CYCLE_NOT_OPEN)

        open_cycle(cycle["id"])
        submitted = validate_success(
            api.submit_leave_application(app["id"], make_faculty_headers(faculty["id"]))
        )
        assert submitted["status"] == "UNDER_REVIEW"

    def test_submit_rejected_when_cycle_closed(self, api):
        """PRD 3.3: "For a sabbatical the referenced cycle must be `OPEN`, else
        `ERR_CYCLE_NOT_OPEN`."

        Design: Difficulty/cross_entity_state_dependency/submit_requires_cycle_open
        """
        dept = create_department()
        faculty = create_faculty(dept["id"])
        run_accruals()
        cycle = open_cycle(create_cycle()["id"])
        get_success_data(api.close_leave_cycle(cycle["id"], PROVOST))
        app = create_application(
            faculty["id"], leave_type="SABBATICAL", cycle_id=cycle["id"],
        )
        blocked = api.submit_leave_application(app["id"], make_faculty_headers(faculty["id"]))
        validate_error(blocked, ApiErrorId.ERR_CYCLE_NOT_OPEN)


class TestServiceMonthsBoundary:
    def test_exactly_72_certified_months_submits(self, api):
        """PRD 3.3: "A sabbatical demands at least seventy-two certified
        service months on `lifetime_service_months`
        (`ERR_INSUFFICIENT_SERVICE_MONTHS`)"

        Design: Difficulty/boundary_precision_check/service_months_exactly_72_vs_71
        """
        dept = create_department()
        exact = create_faculty(dept["id"], hire_date="2020-08-01T00:00:00Z")
        run_accruals()
        cycle = open_cycle(create_cycle()["id"])
        app = create_application(
            exact["id"], leave_type="SABBATICAL", cycle_id=cycle["id"],
        )
        submitted = validate_success(
            api.submit_leave_application(app["id"], make_faculty_headers(exact["id"]))
        )
        assert submitted["status"] == "UNDER_REVIEW"

    def test_71_certified_months_rejected(self, api):
        """PRD 3.3: "A sabbatical demands at least seventy-two certified
        service months on `lifetime_service_months`
        (`ERR_INSUFFICIENT_SERVICE_MONTHS`)"

        Design: Difficulty/boundary_precision_check/service_months_exactly_72_vs_71
        """
        dept = create_department()
        short = create_faculty(dept["id"], hire_date="2020-09-01T00:00:00Z")
        run_accruals()
        cycle = open_cycle(create_cycle()["id"])
        app = create_application(
            short["id"], leave_type="SABBATICAL", cycle_id=cycle["id"],
        )
        resp = api.submit_leave_application(app["id"], make_faculty_headers(short["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_SERVICE_MONTHS)


class TestStateBeatsFiscal:
    def _setup_low_balance_faculty(self, api):
        """Faculty with 72 lifetime months but credit balance 12 (< 36)."""
        dept = create_department()
        faculty = create_faculty(dept["id"], hire_date="2020-08-01T00:00:00Z")
        run_accruals()  # 72 EARN
        get_success_data(
            api.create_accrual_ledger_entry(
                create_accrual_ledger_entry_payload(
                    faculty["id"], credits_delta=-60, affects_lifetime=False
                ),
                ADMIN,
            )
        )
        return dept, faculty

    def test_closed_cycle_and_low_credits_yields_cycle_error(self, api):
        """PRD 2.9: "When a request would violate several rules at once, the
        server evaluates checks in a fixed order and surfaces the error from
        the earliest failing tier."
        PRD 2.9 tier 7 lists "the cycle gates `ERR_CYCLE_NOT_OPEN`" ahead of
        tier 11's "Sabbatical credit sufficiency at submission
        (`ERR_INSUFFICIENT_SABBATICAL_CREDITS`)".

        Design: Difficulty/priority_pair_validation_conflict/cycle_state_beats_credit_fiscal
        """
        _dept, faculty = self._setup_low_balance_faculty(api)
        cycle = open_cycle(create_cycle()["id"])
        get_success_data(api.close_leave_cycle(cycle["id"], PROVOST))
        app = create_application(
            faculty["id"], leave_type="SABBATICAL", cycle_id=cycle["id"],
        )
        # Both the CLOSED-cycle state gate and the 12 < 36 credit gate fail;
        # the state tier is evaluated first.
        resp = api.submit_leave_application(app["id"], make_faculty_headers(faculty["id"]))
        validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_OPEN)

    def test_open_cycle_and_low_credits_yields_credit_error(self, api):
        """PRD 3.3: "a sabbatical submission requires a `credit_balance` of at
        least thirty-six credits per requested semester, failing with
        `ERR_INSUFFICIENT_SABBATICAL_CREDITS` (HTTP 402)."

        Design: Difficulty/priority_pair_validation_conflict/cycle_state_beats_credit_fiscal
        """
        _dept, faculty = self._setup_low_balance_faculty(api)
        cycle = open_cycle(create_cycle()["id"])
        app = create_application(
            faculty["id"], leave_type="SABBATICAL", cycle_id=cycle["id"],
        )
        # With the cycle OPEN, the fiscal condition surfaces on its own.
        resp = api.submit_leave_application(app["id"], make_faculty_headers(faculty["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_SABBATICAL_CREDITS)


class TestDuplicateBeatsWindowOverlap:
    def _setup(self, api):
        """Faculty with an ACTIVE professional grant 2026-09-01..2027-03-01,
        an adjacent sabbatical A1 UNDER_REVIEW, and an overlapping DRAFT A2."""
        dept = create_department()
        faculty = create_faculty(dept["id"], hire_date="2020-08-01T00:00:00Z")
        run_accruals()
        cycle = open_cycle(create_cycle()["id"])

        pro = create_application(
            faculty["id"], leave_type="PROFESSIONAL",
            requested_duration_semesters=1, requested_salary_pct=100,
            proposed_start_date="2026-09-01T00:00:00Z",
            proposed_end_date="2027-03-01T00:00:00Z",
        )
        submit_application(pro["id"], faculty["id"])
        decide_application(pro["id"], "APPROVED")
        pro_grant = grant_for_application(pro["id"])

        # A1 must be submitted before A2 exists: PRD 3.3's duplicate gate
        # ("No other application of the same faculty member may sit in DRAFT,
        # UNDER_REVIEW, or REVISION_REQUESTED") fires at submission, so
        # submitting A1 while A2 sits in DRAFT would itself be rejected.
        a1 = create_application(
            faculty["id"], leave_type="SABBATICAL", cycle_id=cycle["id"],
            proposed_start_date="2027-03-01T00:00:00Z",
            proposed_end_date="2027-09-01T00:00:00Z",
        )
        submit_application(a1["id"], faculty["id"])
        # A2's window overlaps the grant; it must be created while the grant
        # is still SCHEDULED, since creation checks overlap only against
        # ACTIVE grants (PRD 2.9 tier 10: "overlap against active grants").
        a2 = create_application(
            faculty["id"], leave_type="SABBATICAL", cycle_id=cycle["id"],
            proposed_start_date="2027-01-01T00:00:00Z",
            proposed_end_date="2027-07-01T00:00:00Z",
        )
        activate_grant_at(pro_grant["id"], "2026-09-01T00:00:00Z")
        return faculty, a1, a2

    def test_duplicate_and_overlap_yields_duplicate_error(self, api):
        """PRD 2.9: "the server evaluates checks in a fixed order and surfaces
        the error from the earliest failing tier." Tier 9 includes "No second
        in-flight application per faculty (`ERR_DUPLICATE_ACTIVE_APPLICATION`)"
        ahead of tier 10's "overlap against active grants under half-open
        semantics (`ERR_LEAVE_WINDOW_OVERLAP`)".

        Design: Difficulty/priority_pair_validation_conflict/duplicate_constraint_beats_window_temporal
        """
        faculty, _a1, a2 = self._setup(api)
        # A2 fails both the duplicate gate (A1 UNDER_REVIEW) and the window
        # overlap gate (ACTIVE grant 2026-09-01..2027-03-01); the constraint
        # tier is evaluated first.
        resp = api.submit_leave_application(a2["id"], make_faculty_headers(faculty["id"]))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_APPLICATION)

    def test_overlap_surfaces_once_duplicate_cleared(self, api):
        """PRD 3.3: "the proposed window must not overlap any `ACTIVE` grant of
        the same faculty under half-open semantics — adjacency is allowed
        (`ERR_LEAVE_WINDOW_OVERLAP`)"
        PRD 3.3: "resubmitting the same application never counts as its own
        duplicate."

        Design: Difficulty/priority_pair_validation_conflict/duplicate_constraint_beats_window_temporal
        """
        faculty, a1, a2 = self._setup(api)
        get_success_data(
            api.withdraw_leave_application(a1["id"], make_faculty_headers(faculty["id"]))
        )
        resp = api.submit_leave_application(a2["id"], make_faculty_headers(faculty["id"]))
        validate_error(resp, ApiErrorId.ERR_LEAVE_WINDOW_OVERLAP)


class TestOverdueReportBlocksSubmit:
    def _setup_overdue(self, api):
        ctx = setup_full_award(courses_to_cover=3, award_quota=1)
        faculty = ctx["faculty"]
        grant = ctx["grant"]
        activate_grant_at(grant["id"], grant["start_date"])
        complete_grant_at(grant["id"], grant["end_date"])
        set_clock("2027-09-30T00:00:00Z")  # report due 2027-09-29 -> OVERDUE
        reports, _ = validate_paginated(
            api.list_accomplishment_reports(ADMIN, params={"faculty_id": faculty["id"]})
        )
        assert reports[0]["status"] == "OVERDUE"
        medical = create_application(
            faculty["id"], leave_type="MEDICAL",
            requested_duration_semesters=1, requested_salary_pct=0,
            proposed_start_date="2028-01-01T00:00:00Z",
            proposed_end_date="2028-07-01T00:00:00Z",
        )
        return faculty, reports[0], medical

    def test_submit_blocked_while_report_overdue(self, api):
        """PRD 3.3: "The faculty member must carry no `OVERDUE` accomplishment
        report (`ERR_OVERDUE_REPORT_BLOCKS`)"
        PRD 2.5: "Every accomplishment report still in `DUE` status whose
        `due_date` has passed flips to `OVERDUE`"

        Design: Difficulty/cross_entity_state_dependency/submit_blocked_by_overdue_report
        """
        faculty, _report, medical = self._setup_overdue(api)
        resp = api.submit_leave_application(medical["id"], make_faculty_headers(faculty["id"]))
        validate_error(resp, ApiErrorId.ERR_OVERDUE_REPORT_BLOCKS)

    def test_submit_succeeds_after_late_report_submission(self, api):
        """PRD 3.9: "while any report of a faculty member is `OVERDUE`, accrual
        runs skip that member entirely and their new application submissions
        are rejected with `ERR_OVERDUE_REPORT_BLOCKS`."
        PRD 3.9: "submitting from `OVERDUE` sets `submitted_late` true"

        Design: Difficulty/cross_entity_state_dependency/submit_blocked_by_overdue_report
        """
        faculty, report, medical = self._setup_overdue(api)
        late = validate_success(
            api.submit_accomplishment_report(
                report["id"], {"report_text": "Accomplishments narrative."},
                make_faculty_headers(faculty["id"]),
            )
        )
        assert late["submitted_late"] is True
        submitted = validate_success(
            api.submit_leave_application(medical["id"], make_faculty_headers(faculty["id"]))
        )
        assert submitted["status"] == "UNDER_REVIEW"


class TestDefaultedRepaymentBlocks:
    def test_defaulted_repayment_blocks_new_application(self, api):
        """PRD 3.9: "A `DEFAULTED` repayment is a standing block: its faculty
        member cannot submit new leave applications while it stands
        (`ERR_DEFAULTED_REPAYMENT_BLOCKS`)."
        PRD 2.5: "every repayment obligation in `ACTIVE` status whose
        `due_date` has passed while its `amount_outstanding` remains above
        zero flips to `DEFAULTED`"

        Design: Corner/validations/defaulted_repayment_blocks_new_application
        """
        ctx = setup_professional_grant()
        faculty = ctx["faculty"]
        activate_grant_at(ctx["grant"]["id"], "2027-01-01T00:00:00Z")
        complete_grant_at(ctx["grant"]["id"], "2027-07-01T00:00:00Z")

        reports, _ = validate_paginated(
            api.list_accomplishment_reports(ADMIN, params={"faculty_id": faculty["id"]})
        )
        # Submit the report on time so only the DEFAULTED gate can fire.
        set_clock("2027-07-15T00:00:00Z")
        get_success_data(
            api.submit_accomplishment_report(
                reports[0]["id"], {"report_text": "On-time accomplishments."},
                make_faculty_headers(faculty["id"]),
            )
        )

        set_clock("2027-08-01T00:00:00Z")
        separate_faculty(faculty["id"], "2027-08-01T00:00:00Z")

        # due_date = created_at + 365 days; 2028-08-02 is past it.
        set_clock("2028-08-02T00:00:00Z")
        repayments, _ = validate_paginated(
            api.list_repayment_obligations(ADMIN, params={"faculty_id": faculty["id"]})
        )
        assert repayments[0]["status"] == "DEFAULTED"
        assert repayments[0]["amount_outstanding"] == pytest.approx(60000.00, abs=0.005)

        medical = create_application(
            faculty["id"], leave_type="MEDICAL",
            requested_duration_semesters=1, requested_salary_pct=0,
            proposed_start_date="2029-01-01T00:00:00Z",
            proposed_end_date="2029-07-01T00:00:00Z",
        )
        resp = api.submit_leave_application(medical["id"], make_faculty_headers(faculty["id"]))
        validate_error(resp, ApiErrorId.ERR_DEFAULTED_REPAYMENT_BLOCKS)


class TestFacultyWindowAdjacency:
    def _setup(self, api):
        """Faculty A (Engineering) and B (Humanities) each with an ACTIVE
        professional grant 2026-09-01..2027-03-01; A holds an adjacent medical
        application, B an overlapping one."""
        dept_a = create_department(name="Engineering")
        dept_b = create_department(name="Humanities", pool=50000.00)
        fa = create_faculty(dept_a["id"], hire_date="2020-08-01T00:00:00Z")
        fb = create_faculty(dept_b["id"], hire_date="2020-08-01T00:00:00Z",
                            academic_rank="ASSISTANT_PROFESSOR",
                            annual_base_salary=100000.00)
        run_accruals()

        grants = {}
        for f, dept in ((fa, dept_a), (fb, dept_b)):
            app = create_application(
                f["id"], leave_type="PROFESSIONAL",
                requested_duration_semesters=1, requested_salary_pct=100,
                proposed_start_date="2026-09-01T00:00:00Z",
                proposed_end_date="2027-03-01T00:00:00Z",
            )
            submit_application(app["id"], f["id"])
            decide_application(app["id"], "APPROVED")
            grants[f["id"]] = grant_for_application(app["id"])

        # New applications created before activation so creation-time readings
        # of the overlap rule cannot interfere; the submit gate is under test.
        adj = create_application(
            fa["id"], leave_type="MEDICAL",
            requested_duration_semesters=1, requested_salary_pct=0,
            proposed_start_date="2027-03-01T00:00:00Z",
            proposed_end_date="2027-09-01T00:00:00Z",
        )
        ovl = create_application(
            fb["id"], leave_type="MEDICAL",
            requested_duration_semesters=1, requested_salary_pct=0,
            proposed_start_date="2027-01-01T00:00:00Z",
            proposed_end_date="2027-07-01T00:00:00Z",
        )
        activate_grant_at(grants[fa["id"]]["id"], "2026-09-01T00:00:00Z")
        activate_grant_at(grants[fb["id"]]["id"], "2026-09-01T00:00:00Z")
        return fa, fb, adj, ovl

    def test_adjacent_window_is_allowed(self, api):
        """PRD 2.6: "Two windows in which one ends exactly when the other
        begins are adjacent, not overlapping, and adjacency never triggers an
        overlap rejection."
        PRD 3.3: "the proposed window must not overlap any `ACTIVE` grant of
        the same faculty under half-open semantics — adjacency is allowed
        (`ERR_LEAVE_WINDOW_OVERLAP`)"

        Design: Difficulty/resource_temporal_overlap/faculty_window_half_open_adjacency
        """
        fa, _fb, adj, _ovl = self._setup(api)
        submitted = validate_success(
            api.submit_leave_application(adj["id"], make_faculty_headers(fa["id"]))
        )
        assert submitted["status"] == "UNDER_REVIEW"

    def test_overlapping_window_is_rejected(self, api):
        """PRD 3.3: "the proposed window must not overlap any `ACTIVE` grant of
        the same faculty under half-open semantics — adjacency is allowed
        (`ERR_LEAVE_WINDOW_OVERLAP`)"

        Design: Difficulty/resource_temporal_overlap/faculty_window_half_open_adjacency
        """
        _fa, fb, _adj, ovl = self._setup(api)
        resp = api.submit_leave_application(ovl["id"], make_faculty_headers(fb["id"]))
        validate_error(resp, ApiErrorId.ERR_LEAVE_WINDOW_OVERLAP)
