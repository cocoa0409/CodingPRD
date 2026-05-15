"""Review lifecycle: patch, submit, decrement, supersede (PRD §3.6)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    complete_review_patch_payload,
    create_invitation_payload,
    invite_and_accept_reviewer,
    make_associate_editor_headers,
    make_reviewer_headers,
    patch_review_payload,
    register_reviewer,
    setup_two_submitted_reviews,
    setup_under_review_manuscript,
    submit_review_for_invitation,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import _discover_review_id_for_invitation


def _make_invitation_and_get_review_id(api, base, reviewer):
    """Helper: invite a reviewer, accept, and discover the new Review.id.

    Returns (invitation, review_id).
    """
    inv = invite_and_accept_reviewer(
        base["manuscript"], base["associate_editor"], reviewer,
    )
    review_id = _discover_review_id_for_invitation(
        base["manuscript"], inv, reviewer,
    )
    assert review_id is not None, (
        "Could not discover Review id from accept response, audit logs, "
        "or invitation row. Implementation must expose it via one of "
        "these paths."
    )
    return inv, review_id


def test_review_submit_decrements_active_assignments(api):
    """PRD §3.6: "A successful submit transitions the review from DRAFT
    to SUBMITTED, stamps submitted_at with the server clock, and
    decrements the reviewer's active_assignments by one."
    """
    base = setup_under_review_manuscript(topic_tag="ml")
    reviewer = register_reviewer(expertise_tags=["ml"])
    invitation, review_id = _make_invitation_and_get_review_id(
        api, base, reviewer,
    )
    # Patch all four fields and submit.
    headers = make_reviewer_headers(reviewer["id"])
    api.patch_review(
        review_id, complete_review_patch_payload(rating=5,
                                                 recommendation="ACCEPT"),
        headers,
    )
    res = api.submit_review(review_id, headers)
    submitted = validate_success(res, expected_status=200)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["submitted_at"] is not None

    r_res = api.get_reviewer(reviewer["id"], headers)
    refreshed = validate_success(r_res, expected_status=200)
    assert refreshed["active_assignments"] == 0


@pytest.mark.parametrize("bad_rating", [0, 6, -1])
def test_review_submit_with_invalid_rating_rejected(api, bad_rating):
    """PRD §3.6: "rating must lie in the closed interval from 1 to 5 ...
    A submission that fails any of these checks is rejected with
    ERR_REVIEW_INCOMPLETE."
    """
    base = setup_under_review_manuscript(topic_tag="ml")
    reviewer = register_reviewer(expertise_tags=["ml"])
    invitation, review_id = _make_invitation_and_get_review_id(
        api, base, reviewer,
    )
    headers = make_reviewer_headers(reviewer["id"])
    # Patch may itself reject the out-of-range rating per the PRD; either
    # the patch or the submit must fail. We try the patch first; if it
    # succeeds, the submit must fail.
    patch_res = api.patch_review(
        review_id,
        patch_review_payload(rating=bad_rating, recommendation="ACCEPT",
                             comments_to_author="x", comments_to_editor="y"),
        headers,
    )
    if patch_res.status_code >= 400:
        # PRD §3.6 constraint "rating is an integer at least 1 and at most
        # 5" — rejecting at PATCH is the strict reading, e.g. ERR_VALIDATION.
        body = patch_res.json()
        assert body["data"]["error_id"] in (
            "ERR_VALIDATION", "ERR_REVIEW_INCOMPLETE",
        )
        return
    res = api.submit_review(review_id, headers)
    validate_error(res, ApiErrorId.ERR_REVIEW_INCOMPLETE.value)


@pytest.mark.parametrize("missing", [
    "rating", "recommendation", "comments_to_author", "comments_to_editor",
])
def test_review_submit_with_missing_field_rejected(api, missing):
    """PRD §3.6: "All four review fields — rating, recommendation,
    comments_to_author, comments_to_editor — must be set ... A submission
    that fails any of these checks is rejected with ERR_REVIEW_INCOMPLETE."
    """
    base = setup_under_review_manuscript(topic_tag="ml")
    reviewer = register_reviewer(expertise_tags=["ml"])
    invitation, review_id = _make_invitation_and_get_review_id(
        api, base, reviewer,
    )
    fields = dict(
        rating=4, recommendation="ACCEPT",
        comments_to_author="a", comments_to_editor="b",
    )
    fields.pop(missing)
    headers = make_reviewer_headers(reviewer["id"])
    # PATCH only the present fields.
    api.patch_review(review_id, patch_review_payload(**fields), headers)
    res = api.submit_review(review_id, headers)
    validate_error(res, ApiErrorId.ERR_REVIEW_INCOMPLETE.value)


@pytest.mark.parametrize("blank_field", [
    "comments_to_author", "comments_to_editor",
])
def test_review_submit_with_blank_comments_rejected(api, blank_field):
    """PRD §3.6: "... and both comment strings must be non-empty. A
    submission that fails any of these checks is rejected with
    ERR_REVIEW_INCOMPLETE."
    """
    base = setup_under_review_manuscript(topic_tag="ml")
    reviewer = register_reviewer(expertise_tags=["ml"])
    invitation, review_id = _make_invitation_and_get_review_id(
        api, base, reviewer,
    )
    fields = dict(
        rating=4, recommendation="ACCEPT",
        comments_to_author="ok", comments_to_editor="ok",
    )
    fields[blank_field] = ""
    headers = make_reviewer_headers(reviewer["id"])
    api.patch_review(review_id, patch_review_payload(**fields), headers)
    res = api.submit_review(review_id, headers)
    validate_error(res, ApiErrorId.ERR_REVIEW_INCOMPLETE.value)


def test_review_patch_by_non_assigned_reviewer_rejected(api, reviewer_fallback_headers):
    """PRD §3.6: "Submission is admissible only when ... the reviewer_id
    on the parent invitation matches X-User-ID." Combined with §2.1
    ownership rule — a different reviewer cannot patch/submit.
    """
    base = setup_under_review_manuscript(topic_tag="ml")
    reviewer = register_reviewer(expertise_tags=["ml"])
    _, review_id = _make_invitation_and_get_review_id(api, base, reviewer)
    res = api.patch_review(
        review_id, complete_review_patch_payload(), reviewer_fallback_headers,
    )
    assert res.status_code in (403, 404)
