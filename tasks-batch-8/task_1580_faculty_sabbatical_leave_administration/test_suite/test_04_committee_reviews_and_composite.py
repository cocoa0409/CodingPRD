"""Committee review rules, per-product rounding, drop-lowest, revision loop."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_application,
    create_cycle,
    create_department,
    create_faculty,
    create_review_payload,
    create_submitted_review,
    get_application,
    get_success_data,
    make_committee_member_headers,
    make_faculty_headers,
    open_cycle,
    run_accruals,
    setup_reviewers,
    setup_submitted_sabbatical_application,
    submit_application,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
PROVOST = TEST_USERS["provost_headers"]


def _setup_under_review_application(api, review_scores=None):
    """Dept + applicant (72 credits after one run) + reviewers in a second
    department + OPEN cycle + one UNDER_REVIEW sabbatical application."""
    dept = create_department()
    faculty = create_faculty(dept["id"])
    reviewers = setup_reviewers(count=len(review_scores or ()))
    run_accruals()
    cycle = open_cycle(create_cycle()["id"])
    app = setup_submitted_sabbatical_application(faculty["id"], cycle["id"])
    return dept, faculty, reviewers, cycle, app


class TestReviewerConflictAndDuplicate:
    def test_reviewer_conflict_and_duplicate_rejected(self, api):
        """PRD 3.4: "the reviewer may not be the applicant and may not belong
        to the applicant's department (`ERR_REVIEWER_CONFLICT`), and a reviewer
        may hold at most one review per application in any status, draft
        included (`ERR_DUPLICATE_REVIEW`)."

        Design: Corner/validations/reviewer_conflict_and_duplicate_rejected
        """
        dept = create_department()
        faculty = create_faculty(dept["id"])
        same_dept = create_faculty(
            dept["id"], academic_rank="FULL_PROFESSOR",
            hire_date="2015-08-01T00:00:00Z", annual_base_salary=130000.00,
        )
        reviewers = setup_reviewers(count=1)
        run_accruals()
        cycle = open_cycle(create_cycle()["id"])
        app = setup_submitted_sabbatical_application(faculty["id"], cycle["id"])

        self_review = api.create_committee_review(
            create_review_payload(app["id"], 80, 80, 80),
            make_committee_member_headers(faculty["id"]),
        )
        validate_error(self_review, ApiErrorId.ERR_REVIEWER_CONFLICT)

        same_dept_review = api.create_committee_review(
            create_review_payload(app["id"], 80, 80, 80),
            make_committee_member_headers(same_dept["id"]),
        )
        validate_error(same_dept_review, ApiErrorId.ERR_REVIEWER_CONFLICT)

        reviewer = reviewers[0]
        get_success_data(
            api.create_committee_review(
                create_review_payload(app["id"], 80, 80, 80),
                make_committee_member_headers(reviewer["id"]),
            )
        )
        duplicate = api.create_committee_review(
            create_review_payload(app["id"], 90, 90, 90),
            make_committee_member_headers(reviewer["id"]),
        )
        validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_REVIEW)


class TestPerProductRoundingOrder:
    def test_weighted_total_rounds_each_product_before_summing(self, api):
        """PRD 3.4: "its `weighted_total` is computed immediately: forty-five
        percent of the merit score, thirty-five percent of the curriculum
        score, and twenty percent of the feasibility score, with each of the
        three products individually rounded half-up to two decimal places
        before the products are summed."

        Design: Difficulty/combinatorial_formula/composite_score_per_product_rounding_order
        """
        dept = create_department()
        faculty = create_faculty(dept["id"])
        reviewers = setup_reviewers(count=1)
        run_accruals()
        cycle = open_cycle(create_cycle()["id"])
        app = setup_submitted_sabbatical_application(faculty["id"], cycle["id"])

        review = validate_success(
            api.create_committee_review(
                create_review_payload(app["id"], 10.5, 10.5, 10.5),
                make_committee_member_headers(reviewers[0]["id"]),
            ),
            expected_status=201,
        )
        # round(4.725)=4.73 + round(3.675)=3.68 + round(2.10)=2.10 -> 10.51,
        # not the 10.50 a sum-then-round order would produce.
        assert review["weighted_total"] == pytest.approx(10.51, abs=0.001)
        assert review["status"] == "DRAFT"

    def test_composite_score_matches_per_product_rounding(self, api):
        """PRD 3.4: "Each submission recomputes the application's committee
        aggregates over its `SUBMITTED` reviews only — drafts never count."
        PRD 3.4: "`quorum_met` becomes true once that count reaches three."

        Design: Difficulty/combinatorial_formula/composite_score_per_product_rounding_order
        """
        dept = create_department()
        faculty = create_faculty(dept["id"])
        reviewers = setup_reviewers(count=3)
        run_accruals()
        cycle = open_cycle(create_cycle()["id"])
        app = setup_submitted_sabbatical_application(faculty["id"], cycle["id"])

        for reviewer in reviewers:
            create_submitted_review(app["id"], reviewer["id"], 10.5, 10.5, 10.5)

        fresh = get_application(app["id"])
        assert fresh["composite_score"] == pytest.approx(10.51, abs=0.001)
        assert fresh["submitted_review_count"] == 3
        assert fresh["quorum_met"] is True


class TestDropLowestAtFourReviews:
    def test_composite_drop_lowest_at_four_reviews(self, api):
        """PRD 3.4: "The `composite_score` applies a drop-lowest rule: when at
        least four submitted reviews exist, exactly one review carrying the
        minimum `weighted_total` is discarded (if several reviews share that
        minimum any of them may be dropped — the resulting sum is identical);
        the composite is then the sum of the kept `weighted_total` values
        divided by the number of kept reviews, rounded half-up to two decimal
        places."

        Design: Corner/calculations/composite_drop_lowest_at_four_reviews
        """
        dept = create_department()
        faculty = create_faculty(dept["id"])
        reviewers = setup_reviewers(count=4)
        run_accruals()
        cycle = open_cycle(create_cycle()["id"])
        app = setup_submitted_sabbatical_application(faculty["id"], cycle["id"])

        scores = ((80, 90, 70), (90, 85, 95), (70, 60, 80), (100, 90, 95))
        for reviewer, (m, c, f) in zip(reviewers, scores):
            create_submitted_review(app["id"], reviewer["id"], m, c, f)

        fresh = get_application(app["id"])
        # Weighted totals 81.50 / 89.25 / 68.50 / 95.50; 68.50 dropped.
        # (81.50 + 89.25 + 95.50) / 3 = 88.75
        assert fresh["composite_score"] == pytest.approx(88.75, abs=0.001)
        assert fresh["submitted_review_count"] == 4
        assert fresh["quorum_met"] is True


class TestApplicationRevisionLoop:
    def _setup_with_one_submitted_review(self, api):
        dept = create_department()
        faculty = create_faculty(dept["id"])
        reviewers = setup_reviewers(count=1)
        run_accruals()
        cycle = open_cycle(create_cycle()["id"])
        app = setup_submitted_sabbatical_application(faculty["id"], cycle["id"])
        create_submitted_review(app["id"], reviewers[0]["id"], 80, 90, 70)
        return faculty, app

    def test_revision_loop_returns_to_under_review(self, api):
        """PRD 3.3: "Submitting moves an application from `DRAFT` — or from
        `REVISION_REQUESTED`, since the cycle has a revision loop — to
        `UNDER_REVIEW`."
        PRD 3.3: "requesting revision moves `UNDER_REVIEW` →
        `REVISION_REQUESTED` (any other from-state is
        `ERR_INVALID_APPLICATION_STATE`) and increments the `version`."

        Design: Difficulty/non_linear_state_machine/application_revision_cycle_loop
        """
        faculty, app = self._setup_with_one_submitted_review(api)
        revised = validate_success(api.request_application_revision(app["id"], PROVOST))
        assert revised["status"] == "REVISION_REQUESTED"

        resubmitted = validate_success(
            api.submit_leave_application(app["id"], make_faculty_headers(faculty["id"]))
        )
        assert resubmitted["status"] == "UNDER_REVIEW"

    def test_submitted_reviews_and_composite_survive_the_loop(self, api):
        """PRD 3.3: "When a previously-revised application is resubmitted, its
        existing `SUBMITTED` reviews persist, and the recomputed composite
        therefore comes out unchanged."
        PRD 2.4: "The `version` is an integer that starts at 1 when the
        resource is created and increments by exactly one on every mutation of
        that resource — including mutations caused as side effects of another
        resource's transition."

        Design: Difficulty/non_linear_state_machine/application_revision_cycle_loop
        """
        faculty, app = self._setup_with_one_submitted_review(api)
        before = get_application(app["id"])
        # (80,90,70) -> 36.00 + 31.50 + 14.00 = 81.50
        assert before["composite_score"] == pytest.approx(81.50, abs=0.001)

        get_success_data(api.request_application_revision(app["id"], PROVOST))
        get_success_data(
            api.submit_leave_application(app["id"], make_faculty_headers(faculty["id"]))
        )

        after = get_application(app["id"])
        assert after["status"] == "UNDER_REVIEW"
        assert after["composite_score"] == pytest.approx(81.50, abs=0.001)
        assert after["submitted_review_count"] == 1
        # create 1, submit 2, review-submit recompute 3, request-revision 4,
        # resubmit 5 (side-effect recomputes are mutations too).
        assert after["version"] == 5
