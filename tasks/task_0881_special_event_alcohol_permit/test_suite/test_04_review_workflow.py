"""Multi-agency review: the revision cycle, the conditional-approval branch,
and the review-count conservation invariant.

Difficulty: non_linear_state_machine, transitive_cascade, compensating_invariant.
"""
from test_helpers import validate_success, fixtures
from test_helpers.test_users import TEST_USERS

APPLICANT = TEST_USERS["applicant_headers"]
CLERK = TEST_USERS["clerk_headers"]


def test_revision_cycle_returns_to_under_review(api):
    """PRD §3.5: "The applicant then resubmits, moving the application from
    `REVISIONS_REQUESTED` back to `UNDER_REVIEW` (the application must be
    `REVISIONS_REQUESTED`, else `ERR_INVALID_STATE`), closing the revision loop."

    Design: Difficulty/non_linear_state_machine/application_revision_cycle
    """
    ctx = fixtures.create_under_review_application(api)
    app_id = ctx["application"]["id"]
    validate_success(api.request_revisions(app_id, CLERK))
    data = validate_success(api.resubmit_application(app_id, APPLICANT))
    assert data["status"] == "UNDER_REVIEW"
    assert data["pending_review_count"] == 3


def test_revision_cycle_may_repeat(api):
    """PRD §3.5: "The applicant then resubmits, moving the application from
    `REVISIONS_REQUESTED` back to `UNDER_REVIEW` (the application must be
    `REVISIONS_REQUESTED`, else `ERR_INVALID_STATE`), closing the revision loop.
    This cycle may repeat."

    Design: Difficulty/non_linear_state_machine/application_revision_cycle
    """
    ctx = fixtures.create_under_review_application(api)
    app_id = ctx["application"]["id"]
    validate_success(api.request_revisions(app_id, CLERK))
    validate_success(api.resubmit_application(app_id, APPLICANT))
    # Second lap around the same cycle.
    validate_success(api.request_revisions(app_id, CLERK))
    data = validate_success(api.resubmit_application(app_id, APPLICANT))
    assert data["status"] == "UNDER_REVIEW"


def test_approve_with_conditions_records_review_conditions(api):
    """PRD §3.5: "An `APPROVE_WITH_CONDITIONS` decision moves the review to
    `APPROVED_WITH_CONDITIONS`. It behaves exactly like `APPROVE` for quorum purposes ...
    but it additionally requires a non-empty `conditions` text (else `ERR_VALIDATION`),
    stores that text on the review, and sets the application's `has_conditions` to true."

    Design: Difficulty/non_linear_state_machine/agency_review_conditional_branch
    """
    ctx = fixtures.create_under_review_application(api)
    app_id = ctx["application"]["id"]
    r0 = ctx["reviews"][0]
    review = fixtures.decide_review(api, r0["id"], app_id, "APPROVE_WITH_CONDITIONS",
                                    conditions="No glass bottles")
    assert review["status"] == "APPROVED_WITH_CONDITIONS"
    assert review["conditions"] == "No glass bottles"


def test_approve_with_conditions_sets_application_flag(api):
    """PRD §3.5: "An `APPROVE_WITH_CONDITIONS` decision moves the review to
    `APPROVED_WITH_CONDITIONS`. It behaves exactly like `APPROVE` for quorum purposes —
    it too increments `approved_review_count` by one and decrements `pending_review_count`
    by one and advances the application's `version` by one ... and sets the application's
    `has_conditions` to true."

    Design: Difficulty/non_linear_state_machine/agency_review_conditional_branch
    """
    ctx = fixtures.create_under_review_application(api)
    app_id = ctx["application"]["id"]
    fixtures.decide_review(api, ctx["reviews"][0]["id"], app_id, "APPROVE_WITH_CONDITIONS",
                           conditions="No glass bottles")
    app = fixtures.get_application(api, app_id)
    assert app["has_conditions"] is True
    assert app["approved_review_count"] == 1


def test_request_revisions_zeroes_approval_counts(api):
    """PRD §2.8: "When a clerk sends an application back for revisions, every
    `AgencyReview` on that application that is not already `PENDING` is reset to `PENDING`,
    and each reset review has its `conditions` and `recorded_by` cleared; the application's
    review counts are recomputed so that `pending_review_count` equals `total_review_count`,
    `approved_review_count` and `rejected_review_count` return to zero, and `has_conditions`
    returns to false."

    Design: Difficulty/transitive_cascade/revisions_reset_reviews
    """
    ctx = fixtures.create_under_review_application(api)
    app_id = ctx["application"]["id"]
    fixtures.decide_review(api, ctx["reviews"][0]["id"], app_id, "APPROVE")
    data = validate_success(api.request_revisions(app_id, CLERK))
    assert data["status"] == "REVISIONS_REQUESTED"
    assert data["approved_review_count"] == 0


def test_request_revisions_resets_decided_review_to_pending(api):
    """PRD §2.8: "every `AgencyReview` on that application that is not already `PENDING`
    is reset to `PENDING`, and each reset review has its `conditions` and `recorded_by`
    cleared; the application's review counts are recomputed so that `pending_review_count`
    equals `total_review_count`".

    Design: Difficulty/transitive_cascade/revisions_reset_reviews
    """
    ctx = fixtures.create_under_review_application(api)
    app_id = ctx["application"]["id"]
    r0 = ctx["reviews"][0]
    fixtures.decide_review(api, r0["id"], app_id, "APPROVE")
    validate_success(api.request_revisions(app_id, CLERK))
    review = validate_success(api.get_agency_review(r0["id"], CLERK))
    assert review["status"] == "PENDING"
    app = fixtures.get_application(api, app_id)
    assert app["pending_review_count"] == 3


def test_reset_restores_full_pending_count(api):
    """PRD §3.5: "Opening review creates one `AgencyReview` row, each `PENDING`, for each
    of the three required agencies ... so that `total_review_count` becomes 3."
    PRD §2.8: "the application's review counts are recomputed so that `pending_review_count`
    equals `total_review_count`, `approved_review_count` and `rejected_review_count` return
    to zero".

    Design: Difficulty/compensating_invariant/revision_reset_conserves_review_count
    """
    ctx = fixtures.create_under_review_application(api)
    app_id = ctx["application"]["id"]
    reviews = ctx["reviews"]
    fixtures.decide_review(api, reviews[0]["id"], app_id, "APPROVE")
    fixtures.decide_review(api, reviews[1]["id"], app_id, "APPROVE")
    fixtures.decide_review(api, reviews[2]["id"], app_id, "REJECT")
    data = validate_success(api.request_revisions(app_id, CLERK))
    assert data["total_review_count"] == 3
    assert data["pending_review_count"] == 3
    assert data["approved_review_count"] == 0
    assert data["rejected_review_count"] == 0


def test_review_counts_sum_to_total_before_and_after_reset(api):
    """PRD §3.5: "Correspondingly `pending_review_count` is set to 3 while
    `approved_review_count` and `rejected_review_count` are set to zero."
    PRD §2.8: "the application's review counts are recomputed so that
    `pending_review_count` equals `total_review_count`, `approved_review_count` and
    `rejected_review_count` return to zero".

    The three counts partition total_review_count both before and after the reset.

    Design: Difficulty/compensating_invariant/revision_reset_conserves_review_count
    """
    ctx = fixtures.create_under_review_application(api)
    app_id = ctx["application"]["id"]
    reviews = ctx["reviews"]
    fixtures.decide_review(api, reviews[0]["id"], app_id, "APPROVE")
    fixtures.decide_review(api, reviews[1]["id"], app_id, "APPROVE")
    fixtures.decide_review(api, reviews[2]["id"], app_id, "REJECT")
    before = fixtures.get_application(api, app_id)
    assert (before["pending_review_count"] + before["approved_review_count"]
            + before["rejected_review_count"]) == before["total_review_count"]
    after = validate_success(api.request_revisions(app_id, CLERK))
    assert (after["pending_review_count"] + after["approved_review_count"]
            + after["rejected_review_count"]) == after["total_review_count"]
