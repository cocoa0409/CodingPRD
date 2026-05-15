"""Application creation, basic transitions, and the cyclic revision loop.

Covers PRD §3.3 (creation), §3.6 (DRAFT → SUBMITTED → DRAFT revision
loop, withdraw), §3.7 (begin-review, decide).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_application,
    assert_version_incremented_by_one,
    create_applicant,
    create_application,
    create_program,
    create_university,
    make_applicant_headers,
    NON_EXISTENT_UUID,
    setup_application_ready_to_submit,
    setup_applicant_with_application,
    setup_submitted_application,
    setup_under_review_application,
    submit_application,
    validate_error,
    validate_success,
    withdraw_application,
    withdraw_submission,
)


# ---------------------------------------------------------------------------
# Application create (PRD §3.3)
# ---------------------------------------------------------------------------
class TestApplicationCreate:

    def test_create_application_returns_draft(self, api):
        """PRD §3.3: "A successful creation produces an Application in
        DRAFT with essay_id null, submitted_at null, admission_decision_at
        null, enrollment_deadline null, and status set to DRAFT."
        """
        applicant, uni, prog, app = setup_applicant_with_application()
        assert_application(app)
        assert app["status"] == "DRAFT"
        assert app.get("essay_id") is None
        assert app.get("submitted_at") is None
        assert app.get("admission_decision_at") is None
        assert app.get("enrollment_deadline") is None

    def test_create_application_default_required_recommendation_count_is_two(
        self, api,
    ):
        """PRD §3.3: "an optional required_recommendation_count defaults
        to 2 and must be either 2 or 3."
        """
        applicant = create_applicant()
        uni = create_university()
        prog = create_program(uni["id"])
        res = api.create_application(
            {
                "applicant_id": applicant["id"],
                "program_id": prog["id"],
                "round": "REGULAR_DECISION",
            },
            make_applicant_headers(applicant["id"]),
        )
        data = validate_success(res, expected_status=201)
        assert data["required_recommendation_count"] == 2

    def test_create_application_invalid_round_yields_err_validation(
        self, api,
    ):
        """PRD §3.3: "The request is rejected with ERR_VALIDATION when
        round is not one of the three named values..."
        """
        applicant = create_applicant()
        uni = create_university()
        prog = create_program(uni["id"])
        res = api.create_application(
            {
                "applicant_id": applicant["id"],
                "program_id": prog["id"],
                "round": "DEFERRED_DECISION",  # invalid enum
            },
            make_applicant_headers(applicant["id"]),
        )
        validate_error(res, ApiErrorId.ERR_VALIDATION.value)

    def test_create_application_invalid_required_recommendation_count(
        self, api,
    ):
        """PRD §3.3: "...or when required_recommendation_count is
        anything other than 2 or 3."
        """
        applicant = create_applicant()
        uni = create_university()
        prog = create_program(uni["id"])
        res = api.create_application(
            {
                "applicant_id": applicant["id"],
                "program_id": prog["id"],
                "round": "REGULAR_DECISION",
                "required_recommendation_count": 4,
            },
            make_applicant_headers(applicant["id"]),
        )
        validate_error(res, ApiErrorId.ERR_VALIDATION.value)

    def test_create_application_missing_applicant_yields_not_found(
        self, api,
    ):
        """PRD §2.6: "Missing Applicant ... records produce
        ERR_APPLICANT_NOT_FOUND.\""""
        uni = create_university()
        prog = create_program(uni["id"])
        # Use fallback applicant headers — non-ownership-tied existence
        # path-resolution check.
        from test_helpers import TEST_USERS
        res = api.create_application(
            {
                "applicant_id": NON_EXISTENT_UUID,
                "program_id": prog["id"],
                "round": "REGULAR_DECISION",
            },
            TEST_USERS["applicant_headers_fallback"],
        )
        validate_error(res, ApiErrorId.ERR_APPLICANT_NOT_FOUND.value)

    def test_create_application_missing_program_yields_not_found(self, api):
        """PRD §2.6: "Missing Program records produce ERR_PROGRAM_NOT_FOUND."
        """
        applicant = create_applicant()
        res = api.create_application(
            {
                "applicant_id": applicant["id"],
                "program_id": NON_EXISTENT_UUID,
                "round": "REGULAR_DECISION",
            },
            make_applicant_headers(applicant["id"]),
        )
        validate_error(res, ApiErrorId.ERR_PROGRAM_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# Submit transition (PRD §3.6)
# ---------------------------------------------------------------------------
class TestSubmitTransition:

    def test_submit_sets_submitted_at_and_status(self, api):
        """PRD §3.6: "On success, submitted_at is set to the current
        clock, status becomes SUBMITTED..."
        """
        ctx = setup_application_ready_to_submit(round_="REGULAR_DECISION")
        res = api.submit_application(
            ctx["application"]["id"],
            make_applicant_headers(ctx["applicant"]["id"]),
        )
        data = validate_success(res)
        assert data["status"] == "SUBMITTED"
        assert data["submitted_at"] is not None

    def test_submit_increments_version(self, api):
        """PRD §2.4: every successful mutation increments version by one."""
        ctx = setup_application_ready_to_submit(round_="REGULAR_DECISION")
        before = ctx["application"]
        res = api.submit_application(
            before["id"],
            make_applicant_headers(ctx["applicant"]["id"]),
        )
        data = validate_success(res)
        assert_version_incremented_by_one(before, data)


# ---------------------------------------------------------------------------
# Cyclic revision loop: SUBMITTED → DRAFT → SUBMITTED (PRD §3.6)
# ---------------------------------------------------------------------------
class TestRevisionLoop:

    def test_withdraw_submission_returns_application_to_draft(self, api):
        """PRD §3.6: "The applicant may pull a submitted application
        back to DRAFT while it has not yet entered review — the
        revision loop SUBMITTED → DRAFT."
        """
        ctx = setup_submitted_application(round_="REGULAR_DECISION")
        res = api.withdraw_submission(
            ctx["application"]["id"],
            make_applicant_headers(ctx["applicant"]["id"]),
        )
        data = validate_success(res)
        assert data["status"] == "DRAFT"

    def test_withdraw_submission_clears_submitted_at(self, api):
        """PRD §3.6: "On a successful revision-withdraw, submitted_at
        is cleared..."
        """
        ctx = setup_submitted_application(round_="REGULAR_DECISION")
        res = api.withdraw_submission(
            ctx["application"]["id"],
            make_applicant_headers(ctx["applicant"]["id"]),
        )
        data = validate_success(res)
        assert data.get("submitted_at") is None

    def test_withdraw_submission_after_begin_review_yields_invalid_state(
        self, api,
    ):
        """PRD §3.6: "This transition is rejected with ERR_INVALID_STATE
        when an admissions officer has already begun review..."
        """
        ctx = setup_under_review_application(round_="REGULAR_DECISION")
        res = api.withdraw_submission(
            ctx["application"]["id"],
            make_applicant_headers(ctx["applicant"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_cyclic_submit_withdraw_submit_loops_correctly(self, api):
        """PRD §3.6: "The applicant may pull a submitted application
        back to DRAFT while it has not yet entered review — the
        revision loop SUBMITTED → DRAFT."

        Claim: SUBMITTED → DRAFT → SUBMITTED is a valid 2-step loop;
        the second submit increments version monotonically.
        """
        ctx = setup_submitted_application(round_="REGULAR_DECISION")
        app_v1 = ctx["application"]
        # First withdraw-submission
        app_v2 = withdraw_submission(
            ctx["applicant"]["id"], app_v1["id"],
        )
        assert app_v2["status"] == "DRAFT"
        assert app_v2["version"] > app_v1["version"]
        # Re-submit
        app_v3 = submit_application(
            ctx["applicant"]["id"], app_v1["id"],
        )
        assert app_v3["status"] == "SUBMITTED"
        assert app_v3["version"] > app_v2["version"]


# ---------------------------------------------------------------------------
# Withdraw (PRD §3.3, §3.6)
# ---------------------------------------------------------------------------
class TestWithdraw:

    def test_withdraw_draft_application(self, api):
        """PRD §3.3: "The applicant withdraws an in-flight application
        at any time before terminal closure; the transition out of
        DRAFT or SUBMITTED to WITHDRAWN is unconditional from the
        state machine's perspective..."
        """
        applicant, uni, prog, app = setup_applicant_with_application()
        res = api.withdraw_application(
            app["id"], make_applicant_headers(applicant["id"]),
        )
        data = validate_success(res)
        assert data["status"] == "WITHDRAWN"

    def test_withdraw_submitted_application(self, api):
        """PRD §3.3: "the transition out of DRAFT or SUBMITTED to
        WITHDRAWN is unconditional from the state machine's perspective."
        """
        ctx = setup_submitted_application(round_="REGULAR_DECISION")
        res = api.withdraw_application(
            ctx["application"]["id"],
            make_applicant_headers(ctx["applicant"]["id"]),
        )
        data = validate_success(res)
        assert data["status"] == "WITHDRAWN"


# ---------------------------------------------------------------------------
# Read / list (PRD §4)
# ---------------------------------------------------------------------------
class TestApplicationRead:

    def test_get_application_not_found(self, api, platform_admin_headers):
        """PRD §2.6: "Missing ... Application records produce ...
        ERR_APPLICATION_NOT_FOUND.\""""
        res = api.get_application(NON_EXISTENT_UUID, platform_admin_headers)
        validate_error(res, ApiErrorId.ERR_APPLICATION_NOT_FOUND.value)
