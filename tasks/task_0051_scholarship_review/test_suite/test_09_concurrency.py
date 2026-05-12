"""Concurrency / race-condition tests.

PRD §2.9 enumerates each race precisely with its expected error_id.
We use run_race + the framework's race assertions to verify exactly-one
winner semantics. Where PRD names a specific loser error_id (e.g.,
ERR_DUPLICATE_APPLICATION_SAME, ERR_SCORE_OVER_QUOTA,
ERR_REVIEWERS_ALREADY_ASSIGNED), we assert that id literally.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    assign_reviewers_payload,
    close_and_review,
    create_application,
    create_open_scholarship,
    create_reviewer_set,
    create_submitted_application,
    dept_review_pass,
    make_reviewer_headers,
    make_student_headers,
    new_student_id,
    rule_objection_payload,
    run_race,
    setup_application_under_review,
    setup_announced_with_one_awarded,
    setup_dept_approved_plan,
    submit_score_payload,
    validate_error,
    validate_error_is_one_of,
)


class TestConcurrentSubmit:

    def test_concurrent_submit_same_student_serializes_with_duplicate_error(
        self,
    ):
        """PRD §2.9: "Two concurrent submit calls by the same student on
        the same scholarship serialise on the uniqueness of
        (scholarship_id, student_id) in SUBMITTED status — exactly one
        application reaches SUBMITTED, and the loser receives
        ERR_DUPLICATE_APPLICATION_SAME."

        Claim: two concurrent /submit on two DRAFT apps by the same
        student -> exactly one succeeds, loser is
        ERR_DUPLICATE_APPLICATION_SAME.
        """
        sch, _ = create_open_scholarship(
            category="MERIT", required_materials=["TRANSCRIPT"],
            gpa_threshold_x100=0,
        )
        sid = new_student_id()
        headers = make_student_headers(sid)
        # Two DRAFT applications by same student.
        app1, _ = create_application(
            sch["id"], student_headers=headers,
            uploaded_materials=["TRANSCRIPT"],
        )
        app2, _ = create_application(
            sch["id"], student_headers=headers,
            uploaded_materials=["TRANSCRIPT"],
        )
        results = run_race(
            lambda: api_client.submit_application(
                sch["id"], app1["id"], headers,
            ),
            lambda: api_client.submit_application(
                sch["id"], app2["id"], headers,
            ),
        )
        outcome = assert_race_outcome(results, 1, 1)
        loser_resp = outcome["failures"][0]
        validate_error(
            loser_resp,
            ApiErrorId.ERR_DUPLICATE_APPLICATION_SAME.value,
        )


class TestConcurrentScoreOverQuota:

    def test_concurrent_third_score_yields_over_quota_on_loser(self):
        """PRD §2.9: "Two concurrent score submissions that would each be
        the third score for the same application serialise on the count
        of Score rows; exactly one is recorded as the third, and the
        loser is rejected with ERR_SCORE_OVER_QUOTA."

        Claim: two concurrent third-score submits -> exactly one wins,
        loser carries ERR_SCORE_OVER_QUOTA.
        """
        state = setup_application_under_review()
        # Submit two of three scores serially.
        r1, r2, r3 = state["reviewers"]
        from test_helpers import submit_score
        submit_score(
            state["scholarship"]["id"], state["application"]["id"], r1,
            {"core": 50},
        )
        submit_score(
            state["scholarship"]["id"], state["application"]["id"], r2,
            {"core": 50},
        )
        # Now r3 and r1 race the third score. r1 will be a duplicate
        # reviewer attempt, but per PRD §2.9 the SAME error
        # (ERR_SCORE_OVER_QUOTA) covers both "fourth" and "duplicate from
        # same reviewer". We instead use the SAME-reviewer r3 twice OR
        # one different reviewer that the application hasn't been
        # assigned to.
        # To keep the race semantics clean, use r3 twice — both submit
        # the third score. Implementation must serialise on count==2.
        results = run_race(
            lambda: api_client.submit_score(
                state["scholarship"]["id"],
                state["application"]["id"],
                submit_score_payload(criterion_scores={"core": 50}),
                make_reviewer_headers(r3["id"]),
            ),
            lambda: api_client.submit_score(
                state["scholarship"]["id"],
                state["application"]["id"],
                submit_score_payload(criterion_scores={"core": 60}),
                make_reviewer_headers(r3["id"]),
            ),
        )
        outcome = assert_race_outcome(results, 1, 1)
        loser_resp = outcome["failures"][0]
        validate_error(
            loser_resp, ApiErrorId.ERR_SCORE_OVER_QUOTA.value,
        )


class TestConcurrentAssignReviewers:

    def test_concurrent_assign_reviewers_loser_is_already_assigned(self):
        """PRD §2.9: "Two concurrent assign-reviewers calls for the same
        application serialise on the existence of any ReviewerAssignment
        for the application; exactly one set of three assignments is
        created, and the loser receives ERR_REVIEWERS_ALREADY_ASSIGNED."

        Claim: two parallel assign-reviewers calls -> exactly one wins,
        loser carries ERR_REVIEWERS_ALREADY_ASSIGNED.
        """
        # Build scholarship + DEPT_PRELIM_PASSED app.
        student_dept = "STU-ASSIGN"
        sch, _ = create_open_scholarship(
            category="MERIT", required_materials=["TRANSCRIPT"],
            department_code=student_dept,
            gpa_threshold_x100=0,
        )
        app, _ = create_submitted_application(
            sch, student_department_code=student_dept,
            uploaded_materials=["TRANSCRIPT"],
        )
        close_and_review(sch)
        dept_review_pass(
            sch["id"], app["id"],
            dept_code=student_dept,
            uploaded_materials=["TRANSCRIPT"],
        )
        # Two distinct sets of three reviewers each.
        set_a = create_reviewer_set(3, department_code="REV-A")
        set_b = create_reviewer_set(3, department_code="REV-B")
        results = run_race(
            lambda: api_client.assign_reviewers(
                sch["id"], app["id"],
                assign_reviewers_payload(
                    reviewer_ids=[r["id"] for r in set_a],
                ),
                ADMIN,
            ),
            lambda: api_client.assign_reviewers(
                sch["id"], app["id"],
                assign_reviewers_payload(
                    reviewer_ids=[r["id"] for r in set_b],
                ),
                ADMIN,
            ),
        )
        outcome = assert_race_outcome(results, 1, 1)
        loser_resp = outcome["failures"][0]
        validate_error(
            loser_resp,
            ApiErrorId.ERR_REVIEWERS_ALREADY_ASSIGNED.value,
        )


class TestConcurrentObjectionRule:

    def test_concurrent_rulings_on_same_objection_loser_is_invalid_state(
        self,
    ):
        """PRD §2.9: "Two concurrent rulings on the same Objection
        likewise serialise on the objection's status, and the loser
        receives ERR_INVALID_STATE."

        Claim: two parallel /rule calls on same PENDING objection ->
        exactly one wins, loser carries ERR_INVALID_STATE.
        """
        state = setup_announced_with_one_awarded()
        # Create an objection.
        sid = new_student_id("objector")
        from test_helpers import create_objection_payload, create_objection
        objection = create_objection(
            state["scholarship"]["id"],
            state["application"]["id"],
            objector_student_id=sid,
            reason_code="MATERIAL_FALSE",
        )
        results = run_race(
            lambda: api_client.rule_objection(
                state["scholarship"]["id"], objection["id"],
                rule_objection_payload(
                    decision="DISMISS", ruling_comment="dismiss",
                ),
                ADMIN,
            ),
            lambda: api_client.rule_objection(
                state["scholarship"]["id"], objection["id"],
                rule_objection_payload(
                    decision="DISMISS", ruling_comment="dismiss 2",
                ),
                ADMIN,
            ),
        )
        outcome = assert_race_outcome(results, 1, 1)
        loser_resp = outcome["failures"][0]
        validate_error(
            loser_resp, ApiErrorId.ERR_INVALID_STATE.value,
        )
