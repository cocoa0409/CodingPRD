"""Employment authorization lifecycle, OPT windows, period overlap, and
unemployment accounting claims (PRD §3.5)."""
from test_helpers import (
    ApiErrorId,
    assert_employment_authorization,
    assert_employment_period,
    create_authorization,
    get_authorization,
    make_student_headers,
    report_period,
    set_clock,
    setup_active_student,
    setup_opt_post_approved,
    transition_authorization,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestRecommendReviseLoop:
    """DRAFT -> RECOMMENDED -> DRAFT -> RECOMMENDED -> APPROVED (CPT)."""

    def _setup(self):
        ctx = setup_active_student()
        auth = create_authorization(
            ctx["student"]["id"], auth_type="CPT", employer_name="Acme Corp",
            hours_per_week=20, start_date="2026-09-01", end_date="2026-12-11",
        )
        return auth

    def test_recommend_revise_recommend_loop(self, api, dso_headers):
        """PRD §3.5: "**RECOMMEND** (DSO) moves `DRAFT` to `RECOMMENDED`."
        PRD §3.5: "**REVISE** (DSO) returns a `RECOMMENDED` authorization to
        `DRAFT` for correction."

        Design: Difficulty/non_linear_state_machine/employment_authorization_recommend_revise_loop
        """
        auth = self._setup()
        assert auth["status"] == "DRAFT"

        rec1 = transition_authorization(auth["id"], "RECOMMEND")
        assert rec1["status"] == "RECOMMENDED"
        back = transition_authorization(auth["id"], "REVISE")
        assert back["status"] == "DRAFT", "REVISE loops back to DRAFT"
        rec2 = transition_authorization(auth["id"], "RECOMMEND")
        assert rec2["status"] == "RECOMMENDED"

    def test_cpt_adjudicated_directly_from_recommended(self, api, dso_headers):
        """PRD §3.5: "The two training flavors adjudicate from different states:
        a `CPT` authorization moves directly from `RECOMMENDED` to `APPROVED`,
        while an OPT authorization must pass through `FILED` — adjudicating an
        OPT authorization still in `RECOMMENDED`, or a CPT authorization from
        `FILED`, is rejected with `ERR_AUTH_INVALID_STATE`."

        Design: Difficulty/non_linear_state_machine/employment_authorization_recommend_revise_loop
        """
        auth = self._setup()
        transition_authorization(auth["id"], "RECOMMEND")
        transition_authorization(auth["id"], "REVISE")
        transition_authorization(auth["id"], "RECOMMEND")
        approved = transition_authorization(auth["id"], "ADJUDICATE", outcome="APPROVED")
        assert_employment_authorization(approved)
        assert approved["status"] == "APPROVED"


def test_employment_file_from_draft_returns_auth_invalid_state(
    api, dso_headers,
):
    """PRD §3.5: "**FILE** (the student, and only on their own authorization —
    otherwise `ERR_RESOURCE_NOT_OWNED`) moves `RECOMMENDED` to `FILED` and
    records the `uscis_receipt_number`."
    PRD §2.9: "Violations surface as the transition-specific errors
    (`ERR_RECORD_NOT_DRAFT`, `ERR_RECORD_NOT_ACTIVE`, `ERR_RECORD_NOT_TERMINATED`,
    `ERR_ENROLLMENT_NOT_REGISTERABLE`, `ERR_RCL_NOT_REQUESTED`,
    `ERR_AUTH_INVALID_STATE`, `ERR_VIOLATION_INVALID_STATE`, `ERR_I20_NOT_DRAFT`,
    `ERR_DOCUMENT_ALREADY_REVIEWED`, `ERR_TRANSFER_NOT_CANCELLABLE`,
    `ERR_EXTENSION_NOT_REQUESTED`, HTTP 409)."

    Design: Corner/state_machines/employment_file_from_draft_returns_auth_invalid_state
    """
    ctx = setup_active_student()
    auth = create_authorization(
        ctx["student"]["id"], auth_type="OPT_PRE", hours_per_week=20,
        start_date="2027-01-11", end_date="2027-05-31",
    )
    assert auth["status"] == "DRAFT"
    resp = api.transition_employment_authorization(
        auth["id"],
        {"action": "FILE", "uscis_receipt_number": "IOE1234567890"},
        make_student_headers(ctx["student"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_AUTH_INVALID_STATE, 409)


def test_opt_file_before_window_returns_opt_window_closed(api, dso_headers):
    """PRD §3.5: "The clock date at filing must lie within the window from 90
    days before `program_end_date` through 60 days after it, inclusive
    (otherwise `ERR_OPT_WINDOW_CLOSED`)."

    Design: Corner/validations/opt_file_before_window_returns_opt_window_closed
    """
    ctx = setup_active_student(
        program_start_date="2025-08-25", program_end_date="2026-12-18",
    )
    auth = create_authorization(
        ctx["student"]["id"], auth_type="OPT_POST", hours_per_week=40,
        start_date="2026-12-19", end_date="2027-12-18",
    )
    transition_authorization(auth["id"], "RECOMMEND")
    # Clock 2026-08-01 precedes the filing window (program_end - 90 days).
    resp = api.transition_employment_authorization(
        auth["id"],
        {"action": "FILE", "uscis_receipt_number": "IOE1234567890"},
        make_student_headers(ctx["student"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_OPT_WINDOW_CLOSED, 409)
    assert get_authorization(auth["id"])["status"] == "RECOMMENDED"


def test_cpt_end_beyond_program_end_returns_auth_window_invalid(api, dso_headers):
    """PRD §3.5: "for `CPT` and `OPT_PRE`, the `end_date` must fall on or
    before the record's `program_end_date` (otherwise `ERR_AUTH_WINDOW_INVALID`)".

    Design: Corner/validations/cpt_end_beyond_program_end_returns_auth_window_invalid
    """
    ctx = setup_active_student()  # program ends 2027-05-31
    auth = create_authorization(
        ctx["student"]["id"], auth_type="CPT", employer_name="Acme Corp",
        hours_per_week=20, start_date="2026-09-01", end_date="2027-06-30",
    )
    resp = api.transition_employment_authorization(
        auth["id"], {"action": "RECOMMEND"}, dso_headers,
    )
    validate_error(resp, ApiErrorId.ERR_AUTH_WINDOW_INVALID, 409)
    assert get_authorization(auth["id"])["status"] == "DRAFT"


class TestOptUnemploymentSettledVsAsOf:
    """Dual-variant counters: settled horizon yesterday vs as-of horizon today."""

    def _setup(self):
        return setup_opt_post_approved(
            eval_clock="2026-07-15T00:00:00Z",
            program_start_date="2025-08-25",
            program_end_date="2026-05-31",
            auth_start_date="2026-06-01",
            auth_end_date="2027-05-31",
            file_clock="2026-04-01T00:00:00Z",
            clock="2026-01-10T00:00:00Z",
            funding_cents=3000000,
            funding_issue_date="2026-01-05",
            i20_overrides={"tuition_cents": 1800000, "living_cents": 900000,
                           "insurance_cents": 200000, "other_cents": 100000},
            term_code="2026-SPRING",
            term_start_date="2026-01-12",
            term_end_date="2026-05-08",
        )

    def test_settled_counts_through_yesterday(self, api, dso_headers):
        """PRD §3.5: "`unemployment_days_settled` counts through yesterday only:
        the elapsed figure is the number of days from the authorization's
        `start_date` through yesterday inclusive — zero if yesterday precedes
        the start — and the covered figure is the number of distinct calendar
        days lying within at least one employment period, clipped to the span
        from the authorization's `start_date` through the same horizon, with an
        ongoing period contributing through the horizon. The settled counter is
        elapsed minus covered."

        Design: Difficulty/dual_variant_calc/opt_unemployment_settled_vs_as_of
        """
        ctx = self._setup()
        auth = get_authorization(ctx["authorization"]["id"])
        assert_employment_authorization(auth)
        # 2026-06-01 through 2026-07-14 inclusive = 44 elapsed days, 0 covered.
        assert auth["unemployment_days_settled"] == 44

    def test_as_of_counts_the_uncovered_current_day(self, api, dso_headers):
        """PRD §3.5: "`unemployment_days_as_of` is the same computation with
        today as the horizon, so it counts an uncovered current day and
        therefore runs exactly one day ahead of the settled figure whenever
        today is uncovered."

        Design: Difficulty/dual_variant_calc/opt_unemployment_settled_vs_as_of
        """
        ctx = self._setup()
        auth = get_authorization(ctx["authorization"]["id"])
        assert auth["unemployment_days_settled"] == 44
        assert auth["unemployment_days_as_of"] == 45
        assert auth["unemployment_days_as_of"] - auth["unemployment_days_settled"] == 1


class TestEmploymentPeriodDayCoverageAdjacency:
    """Day-coverage overlap semantics on periods of one authorization."""

    def _setup(self):
        return setup_opt_post_approved(eval_clock="2027-03-05T00:00:00Z")

    def test_period_sharing_calendar_day_rejected_but_adjacency_allowed(
        self, api, dso_headers,
    ):
        """PRD §3.5: "Periods of one authorization follow day-coverage
        semantics: no two periods may share a calendar day, while a period
        starting exactly one day after another period's end is permitted as
        zero-gap adjacency; a violation is rejected with
        `ERR_EMPLOYMENT_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/employment_period_day_coverage_adjacency
        """
        ctx = self._setup()
        auth_id = ctx["authorization"]["id"]
        student_id = ctx["student"]["id"]

        p1 = report_period(auth_id, student_id, "Acme Corp", "2027-01-01", "2027-01-31")
        assert_employment_period(p1)

        # Shares 2027-01-15..2027-01-31 with p1 -> rejected.
        resp = api.create_employment_period(
            auth_id,
            {"employer_name": "Beta LLC", "start_date": "2027-01-15",
             "end_date": "2027-02-15", "hours_per_week": 40},
            make_student_headers(student_id),
        )
        validate_error(resp, ApiErrorId.ERR_EMPLOYMENT_PERIOD_OVERLAP, 409)

        # Starts exactly one day after p1 ends -> zero-gap adjacency, allowed.
        p3 = report_period(auth_id, student_id, "Beta LLC", "2027-02-01", "2027-02-28")
        assert_employment_period(p3)

    def test_covered_days_reconcile_settled_unemployment(self, api, dso_headers):
        """PRD §3.5: "For either variant, elapsed always equals covered plus
        unemployment, and adding then deleting a period leaves the counters
        unchanged."
        PRD §3.5: "The settled counter is elapsed minus covered."

        Design: Difficulty/resource_temporal_overlap/employment_period_day_coverage_adjacency
        """
        ctx = self._setup()
        auth_id = ctx["authorization"]["id"]
        student_id = ctx["student"]["id"]

        report_period(auth_id, student_id, "Acme Corp", "2027-01-01", "2027-01-31")
        report_period(auth_id, student_id, "Beta LLC", "2027-02-01", "2027-02-28")

        auth = get_authorization(auth_id)
        # Elapsed 2026-12-19..2027-03-04 = 76 days; covered 31 + 28 = 59.
        assert auth["unemployment_days_settled"] == 76 - 59


class TestUnemploymentBudgetConservedUnderAddRemove:
    """Reporting then deleting a period restores the settled counter exactly."""

    def _setup(self):
        return setup_opt_post_approved(eval_clock="2027-03-05T00:00:00Z")

    def test_adding_period_reduces_settled_unemployment(self, api, dso_headers):
        """PRD §3.5: "For either variant, elapsed always equals covered plus
        unemployment, and adding then deleting a period leaves the counters
        unchanged."

        Design: Difficulty/compensating_invariant/unemployment_budget_conserved_under_period_add_remove
        """
        ctx = self._setup()
        auth_id = ctx["authorization"]["id"]
        assert get_authorization(auth_id)["unemployment_days_settled"] == 76

        report_period(auth_id, ctx["student"]["id"], "Acme Corp",
                      "2027-01-01", "2027-01-31")
        auth = get_authorization(auth_id)
        # 31 covered days; 76 - 31 = 45.
        assert auth["unemployment_days_settled"] == 45

    def test_deleting_period_restores_settled_unemployment(self, api, dso_headers):
        """PRD §3.5: "For either variant, elapsed always equals covered plus
        unemployment, and adding then deleting a period leaves the counters
        unchanged."
        PRD §3.5: "An erroneously reported period may be deleted by a DSO, and
        both reporting and deletion recompute the authorization's unemployment
        counters."

        Design: Difficulty/compensating_invariant/unemployment_budget_conserved_under_period_add_remove
        """
        ctx = self._setup()
        auth_id = ctx["authorization"]["id"]
        before = get_authorization(auth_id)["unemployment_days_settled"]
        assert before == 76

        period = report_period(auth_id, ctx["student"]["id"], "Acme Corp",
                               "2027-01-01", "2027-01-31")
        assert get_authorization(auth_id)["unemployment_days_settled"] == 45

        resp = api.delete_employment_period(period["id"], dso_headers)
        assert resp.status_code == 204, (
            f"period deletion returns 204 No Content, got {resp.status_code}"
        )
        after = get_authorization(auth_id)["unemployment_days_settled"]
        assert after == before, (
            f"add-then-delete must restore the counter exactly: {before} -> {after}"
        )


class TestUnemploymentLimitBoundary:
    """The sweep opens UNEMPLOYMENT_LIMIT_EXCEEDED only past 90 settled days."""

    def _setup(self, eval_clock):
        return setup_opt_post_approved(eval_clock=eval_clock)

    def test_unemployment_day_90_opens_no_violation(self, api, dso_headers):
        """PRD §3.5: "The clock sweep watches the settled counter: when
        `unemployment_days_settled` exceeds 90 days, the system opens an
        `UNEMPLOYMENT_LIMIT_EXCEEDED` violation in `OPEN` status for the
        student."

        Design: Difficulty/boundary_precision_check/unemployment_day_90_safe_91_violates
        """
        # Settled horizon 2027-03-18: elapsed 2026-12-19..2027-03-18 = 90 days.
        ctx = self._setup("2027-03-19T00:00:00Z")
        auth = get_authorization(ctx["authorization"]["id"])
        assert auth["unemployment_days_settled"] == 90

        violations, meta = validate_paginated(
            api.list_status_violations(ctx["student"]["id"], dso_headers)
        )
        assert meta["total_count"] == 0, (
            "90 settled days is not over the 90-day limit; no violation expected"
        )

    def test_unemployment_day_91_opens_violation(self, api, dso_headers):
        """PRD §3.5: "The clock sweep watches the settled counter: when
        `unemployment_days_settled` exceeds 90 days, the system opens an
        `UNEMPLOYMENT_LIMIT_EXCEEDED` violation in `OPEN` status for the
        student."
        PRD §3.9: "The system also opens violations on its own in two places
        already described: the registration-deadline sweep opens
        `FAILURE_TO_ENROLL`, and the unemployment sweep opens
        `UNEMPLOYMENT_LIMIT_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/unemployment_day_90_safe_91_violates
        """
        # Settled horizon 2027-03-19: elapsed = 91 days > 90.
        ctx = self._setup("2027-03-20T00:00:00Z")
        auth = get_authorization(ctx["authorization"]["id"])
        assert auth["unemployment_days_settled"] == 91

        violations, meta = validate_paginated(
            api.list_status_violations(ctx["student"]["id"], dso_headers)
        )
        assert meta["total_count"] == 1
        assert violations[0]["violation_type"] == "UNEMPLOYMENT_LIMIT_EXCEEDED"
        assert violations[0]["status"] == "OPEN"
