"""The cyclic policy review loop.

A policy may be kicked back and re-submitted indefinitely, and the second pair of
hands is always measured against the latest submitter.
"""

from test_helpers import (
    COMPLIANCE_APPROVER,
    COMPLIANCE_APPROVER_USER_ID,
    PRIVACY_OFFICER,
    PRIVACY_OFFICER_ALT,
    PRIVACY_OFFICER_ALT_USER_ID,
    PRIVACY_OFFICER_USER_ID,
    assert_instant_equals,
    assert_is_null,
    create_jurisdiction,
    create_policy,
    create_program,
    publish_policy,
    validate_success,
)


def test_kick_back_increments_the_revision_count_and_clears_the_submitter(api):
    """Sending an in-review policy back to draft records the revision.

    PRD §3.3: "A `ComplianceApprover` may kick a policy back, `IN_REVIEW` →
    `DRAFT`, which increments `revision_count` by 1 and clears
    `submitted_by_user_id` back to null so that the next submission re-stamps it
    — the officer who re-submits after a kick-back may be a different person, and
    separation of duties must be measured against the *latest* submitter."

    Design: Difficulty/non_linear_state_machine/policy_review_kickback_cycle_increments_revision_count_and_restamps_submitter
    """
    program = create_program(api)
    jurisdiction = create_jurisdiction(api, program["id"])
    policy = create_policy(api, program["id"], [jurisdiction["id"]])

    assert policy["status"] == "DRAFT"
    assert policy["revision_count"] == 0
    assert_is_null(policy["submitted_by_user_id"], "submitted_by_user_id on a fresh draft")

    submitted = validate_success(
        api.transition_policy(policy["id"], {"to_status": "IN_REVIEW"}, PRIVACY_OFFICER)
    )
    assert submitted["status"] == "IN_REVIEW"
    assert submitted["submitted_by_user_id"] == PRIVACY_OFFICER_USER_ID
    assert submitted["revision_count"] == 0

    kicked_back = validate_success(
        api.transition_policy(policy["id"], {"to_status": "DRAFT"}, COMPLIANCE_APPROVER)
    )

    assert kicked_back["status"] == "DRAFT"
    assert kicked_back["revision_count"] == 1
    assert_is_null(kicked_back["submitted_by_user_id"], "submitted_by_user_id after a kick-back")
    assert_is_null(kicked_back["published_at"], "published_at after a kick-back")


def test_re_submission_restamps_the_submitter_and_publication_records_the_approver(api):
    """After a kick-back a second officer re-submits and the approver publishes.

    PRD §3.3: "On success, `published_at` is stamped from the current logical
    clock and `published_by_user_id` from the acting `X-User-ID`, and then a
    four-hop cascade runs:"

    The revision counter survives the second pass through the loop at 1, the
    submitter is re-stamped to the officer who actually re-submitted, and
    publication by a different user is accepted.

    Design: Difficulty/non_linear_state_machine/policy_review_kickback_cycle_increments_revision_count_and_restamps_submitter
    """
    program = create_program(api)
    jurisdiction = create_jurisdiction(api, program["id"])
    policy = create_policy(api, program["id"], [jurisdiction["id"]])

    validate_success(api.transition_policy(policy["id"], {"to_status": "IN_REVIEW"}, PRIVACY_OFFICER))
    validate_success(api.transition_policy(policy["id"], {"to_status": "DRAFT"}, COMPLIANCE_APPROVER))
    resubmitted = validate_success(
        api.transition_policy(policy["id"], {"to_status": "IN_REVIEW"}, PRIVACY_OFFICER_ALT)
    )

    assert resubmitted["status"] == "IN_REVIEW"
    assert resubmitted["submitted_by_user_id"] == PRIVACY_OFFICER_ALT_USER_ID
    assert resubmitted["revision_count"] == 1

    published = publish_policy(api, program["id"], policy["id"])

    assert published["status"] == "PUBLISHED"
    assert published["revision_count"] == 1, "publication does not touch the revision counter"
    assert published["submitted_by_user_id"] == PRIVACY_OFFICER_ALT_USER_ID
    assert published["published_by_user_id"] == COMPLIANCE_APPROVER_USER_ID
    assert_instant_equals(published["published_at"], "2026-08-01T00:00:00.000Z", "published_at")
