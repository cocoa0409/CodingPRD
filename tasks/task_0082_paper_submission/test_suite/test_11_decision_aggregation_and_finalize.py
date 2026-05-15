"""Editor decision aggregation, finalize cascade, and round mismatch (PRD §3.7)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_aggregate_score_two_decimals,
    create_and_recommend_decision,
    create_decision_payload,
    finalize_decision,
    finalize_decision_payload,
    invite_and_accept_reviewer,
    make_associate_editor_headers,
    make_editor_in_chief_headers,
    register_editor,
    register_reviewer,
    setup_two_submitted_reviews,
    setup_under_review_manuscript,
    submit_review_for_invitation,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# DRAFT → RECOMMENDED — review-count gate (PRD §3.7)
# ---------------------------------------------------------------------------
def test_recommend_with_fewer_than_two_submitted_reviews_rejected(api):
    """PRD §3.7: "A recommend call with fewer than two submitted reviews
    is rejected with ERR_INSUFFICIENT_REVIEWS."
    """
    base = setup_under_review_manuscript(topic_tag="ml")
    # Submit exactly one review (count = 1, fails >= 2).
    reviewer1 = register_reviewer(expertise_tags=["ml"])
    inv1 = invite_and_accept_reviewer(
        base["manuscript"], base["associate_editor"], reviewer1,
    )
    submit_review_for_invitation(
        base["manuscript"], inv1, reviewer1,
        rating=4, recommendation="ACCEPT",
    )
    # Create draft decision.
    headers = make_associate_editor_headers(base["associate_editor"]["id"])
    dec_res = api.create_decision(
        base["manuscript"]["id"],
        create_decision_payload(recommendation_from_associate="ACCEPT"),
        headers,
    )
    decision = validate_success(dec_res, expected_status=201)
    rec_res = api.recommend_decision(
        base["manuscript"]["id"], decision["id"], headers,
    )
    validate_error(rec_res, ApiErrorId.ERR_INSUFFICIENT_REVIEWS.value)


# ---------------------------------------------------------------------------
# aggregated_category — plurality vote + lowest-index tie-break (PRD §3.7)
# ---------------------------------------------------------------------------
def test_aggregated_category_majority_vote(api):
    """PRD §3.7: "Each submitted review's recommendation is mapped to one
    of four positions — ACCEPT first, MINOR_REVISION second,
    MAJOR_REVISION third, REJECT fourth. The system counts the reviews
    falling into each of the four positions, then picks the position with
    the highest count."
    Two MAJOR_REVISION + one ACCEPT → MAJOR_REVISION.
    """
    base = setup_under_review_manuscript(topic_tag="ml")
    reviewers = [register_reviewer(expertise_tags=["ml"]) for _ in range(3)]
    _, _ = setup_two_submitted_reviews(
        manuscript=base["manuscript"],
        associate_editor=base["associate_editor"],
        reviewers=reviewers[:2],
        ratings=(4, 4),
        recommendations=("MAJOR_REVISION", "MAJOR_REVISION"),
    )
    # Add a third reviewer with ACCEPT.
    third_inv = invite_and_accept_reviewer(
        base["manuscript"], base["associate_editor"], reviewers[2],
    )
    submit_review_for_invitation(
        base["manuscript"], third_inv, reviewers[2],
        rating=4, recommendation="ACCEPT",
    )
    decision = create_and_recommend_decision(
        base["manuscript"], base["associate_editor"],
        recommendation_from_associate="ACCEPT",
    )
    assert decision["aggregated_category"] == "MAJOR_REVISION"


def test_aggregated_category_tie_break_picks_lowest_index(api):
    """PRD §3.7: "When two or more positions tie at the highest count,
    the tie is broken by preferring the earlier position in the listed
    order — that is, ACCEPT beats MINOR_REVISION, which beats
    MAJOR_REVISION, which beats REJECT."
    Two-way tie between ACCEPT and REJECT → ACCEPT wins.
    """
    base = setup_under_review_manuscript(topic_tag="ml")
    reviewers = [register_reviewer(expertise_tags=["ml"]) for _ in range(2)]
    setup_two_submitted_reviews(
        manuscript=base["manuscript"],
        associate_editor=base["associate_editor"],
        reviewers=reviewers,
        ratings=(4, 2),
        recommendations=("ACCEPT", "REJECT"),
    )
    decision = create_and_recommend_decision(
        base["manuscript"], base["associate_editor"],
        recommendation_from_associate="ACCEPT",
    )
    assert decision["aggregated_category"] == "ACCEPT"


# ---------------------------------------------------------------------------
# aggregate_score — pinned rounding order (PRD §3.7)
# ---------------------------------------------------------------------------
def test_aggregate_score_pinned_round_per_reviewer_then_average(api):
    """PRD §3.7: "The order of operations is pinned: first, each
    reviewer's weighted rating is rounded individually to two decimal
    places using round-half-up; second, those rounded per-reviewer values
    are summed and divided by the number of submitted reviews; third, the
    result of that division is again rounded to two decimal places using
    round-half-up."

    Worked example from §3.7: 2 reviewers, ratings=[3,4], both
    MAJOR_REVISION (weight=0.835).
    Order A (pinned):
      weighted_1 = round(3*0.835, 2) = round(2.505, 2) = 2.51  (half-up)
      weighted_2 = round(4*0.835, 2) = round(3.34,  2) = 3.34
      aggregate = round((2.51+3.34)/2, 2) = round(2.925, 2) = 2.93
    """
    base = setup_under_review_manuscript(topic_tag="ml")
    reviewers = [register_reviewer(expertise_tags=["ml"]) for _ in range(2)]
    setup_two_submitted_reviews(
        manuscript=base["manuscript"],
        associate_editor=base["associate_editor"],
        reviewers=reviewers,
        ratings=(3, 4),
        recommendations=("MAJOR_REVISION", "MAJOR_REVISION"),
    )
    decision = create_and_recommend_decision(
        base["manuscript"], base["associate_editor"],
        recommendation_from_associate="MAJOR_REVISION",
    )
    assert decision["aggregate_score"] == 2.93, (
        f"aggregate_score must be 2.93 with the pinned round-per-reviewer"
        f"-then-average order; got {decision['aggregate_score']}"
    )
    assert_aggregate_score_two_decimals(decision["aggregate_score"])


def test_aggregate_score_two_decimal_precision(api):
    """PRD §2.9: "The aggregate_score on an EditorDecision is computed to
    two decimal places using round-half-up at every rounding step."
    """
    base = setup_under_review_manuscript(topic_tag="ml")
    reviewers = [register_reviewer(expertise_tags=["ml"]) for _ in range(2)]
    setup_two_submitted_reviews(
        manuscript=base["manuscript"],
        associate_editor=base["associate_editor"],
        reviewers=reviewers,
        ratings=(5, 5),
        recommendations=("ACCEPT", "ACCEPT"),
    )
    decision = create_and_recommend_decision(
        base["manuscript"], base["associate_editor"],
        recommendation_from_associate="ACCEPT",
    )
    assert_aggregate_score_two_decimals(decision["aggregate_score"])


# ---------------------------------------------------------------------------
# Finalize cascade (PRD §3.7)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("final_decision,expected_status", [
    ("ACCEPT", "ACCEPTED"),
    ("REJECT", "REJECTED"),
    ("MINOR_REVISION", "REVISION_REQUIRED"),
    ("MAJOR_REVISION", "REVISION_REQUIRED"),
])
def test_finalize_cascades_manuscript_status(api, final_decision, expected_status):
    """PRD §3.7: "a final_decision of ACCEPT advances UNDER_REVIEW →
    ACCEPTED; a final_decision of REJECT advances UNDER_REVIEW →
    REJECTED; and a final_decision of MINOR_REVISION or MAJOR_REVISION
    advances UNDER_REVIEW → REVISION_REQUIRED."
    """
    base = setup_under_review_manuscript(topic_tag="ml")
    eic = register_editor("EDITOR_IN_CHIEF")
    reviewers = [register_reviewer(expertise_tags=["ml"]) for _ in range(2)]
    setup_two_submitted_reviews(
        manuscript=base["manuscript"],
        associate_editor=base["associate_editor"],
        reviewers=reviewers,
    )
    decision = create_and_recommend_decision(
        base["manuscript"], base["associate_editor"],
        recommendation_from_associate=final_decision
        if final_decision != "TRANSFER" else "ACCEPT",
    )
    finalize_decision(
        base["manuscript"], decision, eic, final_decision=final_decision,
    )
    refetch = api.get_manuscript(
        base["manuscript"]["id"], make_editor_in_chief_headers(eic["id"]),
    )
    manuscript = validate_success(refetch, expected_status=200)
    assert manuscript["status"] == expected_status


def test_finalize_marks_decision_finalized(api):
    """PRD §3.7: "The finalize step sets EditorDecision.status to
    FINALIZED, stamps finalized_at ..."
    """
    base = setup_under_review_manuscript(topic_tag="ml")
    eic = register_editor("EDITOR_IN_CHIEF")
    reviewers = [register_reviewer(expertise_tags=["ml"]) for _ in range(2)]
    setup_two_submitted_reviews(
        manuscript=base["manuscript"],
        associate_editor=base["associate_editor"],
        reviewers=reviewers,
    )
    decision = create_and_recommend_decision(
        base["manuscript"], base["associate_editor"],
        recommendation_from_associate="ACCEPT",
    )
    finalized = finalize_decision(
        base["manuscript"], decision, eic, final_decision="ACCEPT",
    )
    assert finalized["status"] == "FINALIZED"
    assert finalized["finalized_at"] is not None


def test_finalize_with_blank_decision_letter_rejected(api):
    """PRD §3.7: "The finalize request carries final_decision ... and a
    non-empty decision_letter_body."
    """
    base = setup_under_review_manuscript(topic_tag="ml")
    eic = register_editor("EDITOR_IN_CHIEF")
    reviewers = [register_reviewer(expertise_tags=["ml"]) for _ in range(2)]
    setup_two_submitted_reviews(
        manuscript=base["manuscript"],
        associate_editor=base["associate_editor"],
        reviewers=reviewers,
    )
    decision = create_and_recommend_decision(
        base["manuscript"], base["associate_editor"],
        recommendation_from_associate="ACCEPT",
    )
    res = api.finalize_decision(
        base["manuscript"]["id"], decision["id"],
        finalize_decision_payload(final_decision="ACCEPT",
                                  decision_letter_body=""),
        make_editor_in_chief_headers(eic["id"]),
    )
    validate_error(res, ApiErrorId.ERR_VALIDATION.value)


def test_compiled_reviewer_comments_in_submitted_order(api):
    """PRD §3.7: "The recommend step also compiles
    compiled_reviewer_comments by concatenating the comments_to_author
    strings from the submitted reviews in submitted_at ascending order."
    """
    base = setup_under_review_manuscript(topic_tag="ml")
    reviewers = [register_reviewer(expertise_tags=["ml"]) for _ in range(2)]
    inv1 = invite_and_accept_reviewer(
        base["manuscript"], base["associate_editor"], reviewers[0],
    )
    submit_review_for_invitation(
        base["manuscript"], inv1, reviewers[0],
        rating=4, recommendation="ACCEPT", comments_to_author="FIRST",
    )
    inv2 = invite_and_accept_reviewer(
        base["manuscript"], base["associate_editor"], reviewers[1],
    )
    submit_review_for_invitation(
        base["manuscript"], inv2, reviewers[1],
        rating=4, recommendation="ACCEPT", comments_to_author="SECOND",
    )
    decision = create_and_recommend_decision(
        base["manuscript"], base["associate_editor"],
        recommendation_from_associate="ACCEPT",
    )
    compiled = decision.get("compiled_reviewer_comments", "")
    assert isinstance(compiled, str)
    first_idx = compiled.find("FIRST")
    second_idx = compiled.find("SECOND")
    assert first_idx >= 0 and second_idx >= 0, (
        "compiled_reviewer_comments must include both reviewers' "
        f"comments_to_author strings; got {compiled!r}"
    )
    assert first_idx < second_idx, (
        "Comments must be concatenated in submitted_at ascending order "
        "(first-submitted review first)."
    )
