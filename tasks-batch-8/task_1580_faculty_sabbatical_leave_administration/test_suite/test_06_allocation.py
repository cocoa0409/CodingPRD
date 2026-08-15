"""Cycle allocation: ranking tiebreaks, quota boundary, gate order."""
import pytest

from test_helpers import (
    TEST_USERS,
    close_cycle,
    create_coverage_plan,
    create_cycle,
    create_faculty,
    create_submitted_review,
    get_application,
    open_cycle,
    run_accruals,
    setup_department_with_chair,
    setup_reviewers,
    setup_submitted_sabbatical_application,
    submit_coverage_plan,
    approve_coverage_plan,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
PROVOST = TEST_USERS["provost_headers"]


class TestAllocationTiebreakAndQuotaBoundary:
    def test_allocation_tiebreak_created_at_and_quota_boundary(self, api):
        """PRD 3.6: "They are ordered by `composite_score` descending; ties
        break on the applicant's `lifetime_service_months` descending, and
        remaining ties break on the application's `created_at` ascending."
        PRD 3.6: "The quota boundary is inclusive: an application whose
        `final_rank` is exactly equal to `award_quota` is awarded."
        PRD 3.6: "once `awarded_count` has reached the cycle's `award_quota`,
        every remaining candidate becomes `NOT_AWARDED` with `award_outcome`
        `QUOTA_EXCEEDED`."

        Design: Corner/calculations/allocation_tiebreak_created_at_and_quota_boundary
        """
        base = setup_department_with_chair()
        dept, chair = base["department"], base["chair"]
        fa = create_faculty(dept["id"], employee_number="F100")
        fb = create_faculty(
            dept["id"], employee_number="F200", academic_rank="ASSISTANT_PROFESSOR",
            annual_base_salary=100000.00,
        )
        reviewers = setup_reviewers(count=3)
        run_accruals()
        cycle = open_cycle(create_cycle(award_quota=1)["id"])
        # A1 created strictly before A2; identical scores (90,90,90)x3 and
        # identical 72-month lifetimes leave created_at as the only tie-break.
        app_a = setup_submitted_sabbatical_application(fa["id"], cycle["id"])
        app_b = setup_submitted_sabbatical_application(fb["id"], cycle["id"])
        for reviewer in reviewers:
            create_submitted_review(app_a["id"], reviewer["id"], 90, 90, 90)
        for reviewer in reviewers:
            create_submitted_review(app_b["id"], reviewer["id"], 90, 90, 90)
        for app in (app_a, app_b):
            plan = create_coverage_plan(app["id"], chair["id"], 2)
            submit_coverage_plan(plan["id"], chair["id"])
            approve_coverage_plan(plan["id"])

        close_cycle(cycle["id"])
        allocated = validate_success(api.allocate_leave_cycle(cycle["id"], PROVOST))
        assert allocated["awarded_count"] == 1
        assert allocated["status"] == "ALLOCATED"

        after_a = get_application(app_a["id"])
        after_b = get_application(app_b["id"])
        assert after_a["composite_score"] == pytest.approx(90.00, abs=0.001)
        assert after_b["composite_score"] == pytest.approx(90.00, abs=0.001)
        # Rank exactly == quota (1) is awarded; rank quota+1 is not.
        assert after_a["final_rank"] == 1
        assert after_a["status"] == "AWARDED"
        assert after_a["award_outcome"] == "AWARDED"
        assert after_b["final_rank"] == 2
        assert after_b["status"] == "NOT_AWARDED"
        assert after_b["award_outcome"] == "QUOTA_EXCEEDED"

        # No CONSUME posts for a non-awarded application.
        fb_fresh = validate_success(api.get_faculty_member(fb["id"], ADMIN))
        assert fb_fresh["credit_balance"] == 72


class TestAllocationGateOrder:
    def test_allocation_gate_order_quorum_before_plan(self, api):
        """PRD 3.6: "Every candidate is then evaluated against four gates in
        this exact order, and the first failing gate decides its fate. An
        application without quorum becomes `NOT_AWARDED` with `award_outcome`
        `INCOMPLETE_REVIEWS`. One lacking a current coverage plan in `APPROVED`
        status becomes `NOT_AWARDED` with `award_outcome`
        `NO_APPROVED_COVERAGE`."

        Design: Corner/calculations/allocation_gate_order_quorum_before_plan
        """
        base = setup_department_with_chair()
        dept, chair = base["department"], base["chair"]
        fx = create_faculty(dept["id"], employee_number="F100")
        fy = create_faculty(
            dept["id"], employee_number="F200", academic_rank="ASSISTANT_PROFESSOR",
            annual_base_salary=100000.00,
        )
        fz = create_faculty(
            dept["id"], employee_number="F300", academic_rank="FULL_PROFESSOR",
            annual_base_salary=140000.00,
        )
        reviewers = setup_reviewers(count=3)
        run_accruals()
        cycle = open_cycle(create_cycle(award_quota=1)["id"])

        # X: only 2 reviews (no quorum) and no plan at all.
        app_x = setup_submitted_sabbatical_application(fx["id"], cycle["id"])
        # Y: quorum with composite 90.00, plan SUBMITTED but never APPROVED.
        app_y = setup_submitted_sabbatical_application(fy["id"], cycle["id"])
        # Z: quorum with composite 80.00, plan APPROVED.
        app_z = setup_submitted_sabbatical_application(fz["id"], cycle["id"])

        create_submitted_review(app_x["id"], reviewers[0]["id"], 95, 95, 95)
        create_submitted_review(app_x["id"], reviewers[1]["id"], 95, 95, 95)
        for reviewer in reviewers:
            create_submitted_review(app_y["id"], reviewer["id"], 90, 90, 90)
        for reviewer in reviewers:
            create_submitted_review(app_z["id"], reviewer["id"], 80, 80, 80)

        plan_y = create_coverage_plan(app_y["id"], chair["id"], 2)
        submit_coverage_plan(plan_y["id"], chair["id"])  # SUBMITTED only
        plan_z = create_coverage_plan(app_z["id"], chair["id"], 2)
        submit_coverage_plan(plan_z["id"], chair["id"])
        approve_coverage_plan(plan_z["id"])

        close_cycle(cycle["id"])
        validate_success(api.allocate_leave_cycle(cycle["id"], PROVOST))

        after_x = get_application(app_x["id"])
        after_y = get_application(app_y["id"])
        after_z = get_application(app_z["id"])

        # Quorum gate evaluated before the missing-plan gate for X.
        assert after_x["status"] == "NOT_AWARDED"
        assert after_x["award_outcome"] == "INCOMPLETE_REVIEWS"

        # Y tops the ranking (90.00 > 80.00) but its plan is not APPROVED.
        assert after_y["final_rank"] == 1
        assert after_y["status"] == "NOT_AWARDED"
        assert after_y["award_outcome"] == "NO_APPROVED_COVERAGE"

        # Z is fully gated and takes the award at rank 2.
        assert after_z["final_rank"] == 2
        assert after_z["status"] == "AWARDED"
        assert after_z["award_outcome"] == "AWARDED"
