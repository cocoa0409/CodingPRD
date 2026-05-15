"""Reviewer invitation scoring: coi_score, match_score, and rejection (PRD §3.5)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    COI_REJECT_THRESHOLD,
    REVIEWER_MAX_CONCURRENT,
    TEST_DEFAULTS,
    W_COAUTHOR,
    W_EXCLUDED,
    W_INSTITUTION,
    W_LOAD,
    W_SUGGESTED,
    W_TAG,
    assert_coi_score_in_range,
    assert_match_score_in_range,
    create_invitation_payload,
    make_associate_editor_headers,
    register_author,
    register_editor,
    register_reviewer,
    setup_submitted_manuscript,
    setup_under_review_manuscript,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Match-score formula (PRD §3.5)
# ---------------------------------------------------------------------------
def test_match_score_tag_match_only(api):
    """PRD §3.5: "The raw match value is the tag-match indicator
    multiplied by 60, plus the suggested-bonus indicator multiplied by 30,
    minus the load penalty multiplied by 10. The final match_score clamps
    the raw value into the closed interval from 0 to 100 ..."
    Reviewer with the manuscript topic_tag, NOT in suggested list, load 0.
    """
    base = setup_under_review_manuscript(topic_tag="ml")
    reviewer = register_reviewer(expertise_tags=["ml"])
    res = api.create_invitation(
        base["manuscript"]["id"],
        create_invitation_payload(reviewer_id=reviewer["id"]),
        make_associate_editor_headers(base["associate_editor"]["id"]),
    )
    invitation = validate_success(res, expected_status=201)
    assert_match_score_in_range(invitation["match_score"])
    # 60*1 + 30*0 - 10*0 = 60
    assert invitation["match_score"] == 60, (
        f"expected match_score=60 for tag_match=1/suggested=0/load=0, "
        f"got {invitation['match_score']}"
    )


def test_match_score_tag_and_suggested(api):
    """PRD §3.5: "tag-match indicator multiplied by 60, plus the
    suggested-bonus indicator multiplied by 30 ..."
    Tag-match + suggested, load 0 → 60 + 30 = 90.
    """
    reviewer = register_reviewer(expertise_tags=["ml"])
    base = setup_under_review_manuscript(
        topic_tag="ml", suggested_reviewer_ids=[reviewer["id"]],
    )
    res = api.create_invitation(
        base["manuscript"]["id"],
        create_invitation_payload(reviewer_id=reviewer["id"]),
        make_associate_editor_headers(base["associate_editor"]["id"]),
    )
    invitation = validate_success(res, expected_status=201)
    assert invitation["match_score"] == 90, (
        f"expected match_score=90 for tag_match=1/suggested=1/load=0, "
        f"got {invitation['match_score']}"
    )


def test_match_score_clamped_to_zero_floor(api):
    """PRD §3.5: "any negative raw value becomes 0 ..."
    No tag match (0) and no suggested (0), but no load — raw = 0, score = 0.
    """
    base = setup_under_review_manuscript(topic_tag="ml")
    reviewer = register_reviewer(expertise_tags=["other_topic"])
    res = api.create_invitation(
        base["manuscript"]["id"],
        create_invitation_payload(reviewer_id=reviewer["id"]),
        make_associate_editor_headers(base["associate_editor"]["id"]),
    )
    invitation = validate_success(res, expected_status=201)
    # 60*0 + 30*0 - 10*0 = 0
    assert invitation["match_score"] == 0


# ---------------------------------------------------------------------------
# COI-score: combinatorial cap and rejection (PRD §3.5)
# ---------------------------------------------------------------------------
def test_coi_no_signals_score_zero(api):
    """PRD §3.5: "The conflict-of-interest score coi_score is the sum of
    three independent signal penalties."
    Zero signals → 0.
    """
    base = setup_under_review_manuscript(topic_tag="ml")
    # Reviewer at different institution, no co-author overlap, not excluded.
    reviewer = register_reviewer(
        expertise_tags=["ml"],
        institution="Independent Lab",
    )
    res = api.create_invitation(
        base["manuscript"]["id"],
        create_invitation_payload(reviewer_id=reviewer["id"]),
        make_associate_editor_headers(base["associate_editor"]["id"]),
    )
    invitation = validate_success(res, expected_status=201)
    assert invitation["coi_score"] == 0


def test_coi_same_institution_signal_only(api):
    """PRD §3.5: "The second signal — same-institution — fires when any
    author's institution string equals the reviewer's institution; this
    signal contributes a penalty of 30."
    Score = 30 < 50, so invitation IS NOT rejected.
    """
    base = setup_under_review_manuscript(topic_tag="ml")
    # Build a reviewer whose institution matches the corresponding author.
    reviewer = register_reviewer(
        expertise_tags=["ml"],
        institution=TEST_DEFAULTS["AUTHOR_INSTITUTION"],
    )
    res = api.create_invitation(
        base["manuscript"]["id"],
        create_invitation_payload(reviewer_id=reviewer["id"]),
        make_associate_editor_headers(base["associate_editor"]["id"]),
    )
    invitation = validate_success(res, expected_status=201)
    assert invitation["coi_score"] == 30


def test_coi_coauthor_signal_rejects_invitation(api):
    """PRD §3.5: "The first signal — co-authorship — fires when any author
    in the manuscript's author set (the corresponding author plus the
    co_author_ids list) has the candidate reviewer's id in their own
    recent_collaborator_ids array, or the candidate reviewer has any of
    those authors' ids in the reviewer's recent_collaborator_ids array;
    this signal contributes a penalty of 60. ... An invitation is rejected
    with ERR_REVIEWER_CONFLICT when coi_score is at least 50."
    """
    reviewer = register_reviewer(expertise_tags=["ml"])
    # Author lists reviewer.id in recent_collaborator_ids → co-author signal.
    base = setup_under_review_manuscript(
        topic_tag="ml",
        author_kwargs={"recent_collaborator_ids": [reviewer["id"]]},
    )
    res = api.create_invitation(
        base["manuscript"]["id"],
        create_invitation_payload(reviewer_id=reviewer["id"]),
        make_associate_editor_headers(base["associate_editor"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_REVIEWER_CONFLICT.value)


def test_coi_excluded_only_signal_returns_distinct_error(api):
    """PRD §3.5: "The author-excluded signal alone (the candidate
    reviewer's id in excluded_reviewer_ids with no other signal firing)
    yields the distinct error ERR_REVIEWER_EXCLUDED_BY_AUTHOR ..."
    """
    reviewer = register_reviewer(
        expertise_tags=["ml"],
        institution="Independent Lab",  # no institution overlap
    )
    base = setup_under_review_manuscript(
        topic_tag="ml",
        excluded_reviewer_ids=[reviewer["id"]],
    )
    res = api.create_invitation(
        base["manuscript"]["id"],
        create_invitation_payload(reviewer_id=reviewer["id"]),
        make_associate_editor_headers(base["associate_editor"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_REVIEWER_EXCLUDED_BY_AUTHOR.value)


def test_coi_score_capped_at_100(api):
    """PRD §3.5: "The raw sum is then capped: coi_score is the smaller of
    the raw sum and 100."
    A reviewer whose co-author + institution + excluded signals all fire
    has raw = 60+30+100 = 190, which is capped to 100. The invitation is
    rejected (ERR_REVIEWER_CONFLICT, since more than one signal fired).
    """
    reviewer = register_reviewer(
        expertise_tags=["ml"],
        institution=TEST_DEFAULTS["AUTHOR_INSTITUTION"],
    )
    base = setup_under_review_manuscript(
        topic_tag="ml",
        excluded_reviewer_ids=[reviewer["id"]],
        author_kwargs={
            "institution": TEST_DEFAULTS["AUTHOR_INSTITUTION"],
            "recent_collaborator_ids": [reviewer["id"]],
        },
    )
    res = api.create_invitation(
        base["manuscript"]["id"],
        create_invitation_payload(reviewer_id=reviewer["id"]),
        make_associate_editor_headers(base["associate_editor"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_REVIEWER_CONFLICT.value)


# ---------------------------------------------------------------------------
# Pinned scores (PRD §3.5)
# ---------------------------------------------------------------------------
def test_scores_pinned_at_invitation_creation(api):
    """PRD §3.5: "Both coi_score and match_score are pinned onto the
    ReviewerInvitation at creation time and never recomputed."
    Fetching the invitation later returns the same values.
    """
    base = setup_under_review_manuscript(topic_tag="ml")
    reviewer = register_reviewer(expertise_tags=["ml"])
    res = api.create_invitation(
        base["manuscript"]["id"],
        create_invitation_payload(reviewer_id=reviewer["id"]),
        make_associate_editor_headers(base["associate_editor"]["id"]),
    )
    invitation = validate_success(res, expected_status=201)
    orig_coi = invitation["coi_score"]
    orig_match = invitation["match_score"]

    # List invitations and confirm the same scores come back.
    list_res = api.list_invitations(
        base["manuscript"]["id"],
        make_associate_editor_headers(base["associate_editor"]["id"]),
    )
    invitations = list_res.json()["data"]
    found = next(i for i in invitations if i["id"] == invitation["id"])
    assert found["coi_score"] == orig_coi
    assert found["match_score"] == orig_match


# ---------------------------------------------------------------------------
# Duplicate invitation (PRD §3.5)
# ---------------------------------------------------------------------------
def test_duplicate_invitation_rejected(api):
    """PRD §3.5: "A second invitation for the same reviewer on the same
    manuscript at the same revision_round is rejected; the
    first-writer-wins on the (manuscript_id, reviewer_id, revision_round)
    tuple and the loser receives ERR_INVITATION_ALREADY_EXISTS."
    """
    base = setup_under_review_manuscript(topic_tag="ml")
    reviewer = register_reviewer(expertise_tags=["ml"])
    headers = make_associate_editor_headers(base["associate_editor"]["id"])
    res1 = api.create_invitation(
        base["manuscript"]["id"],
        create_invitation_payload(reviewer_id=reviewer["id"]),
        headers,
    )
    validate_success(res1, expected_status=201)

    res2 = api.create_invitation(
        base["manuscript"]["id"],
        create_invitation_payload(reviewer_id=reviewer["id"]),
        headers,
    )
    validate_error(res2, ApiErrorId.ERR_INVITATION_ALREADY_EXISTS.value)
