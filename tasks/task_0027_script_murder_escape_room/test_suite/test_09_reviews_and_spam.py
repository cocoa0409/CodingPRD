"""Review submission, spam scoring, moderation lifecycle, and aggregation."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    ReviewStatus,
    SHORT_COMMENT_THRESHOLD,
    SPAM_SIGNAL_HARD_BLOCK,
    SPAM_SIGNAL_SOFT,
    add_minutes,
    advance_clock_to,
    assert_review,
    create_review_payload,
    get_review,
    make_player_headers,
    moderate_review,
    moderate_review_payload,
    patch_review_payload,
    setup_review_pending_moderation,
    setup_slot_at_completed,
    setup_slot_with_confirmed_booking,
    submit_review,
    validate_error,
    validate_success,
)


# ─── §3.9 Eligibility ─────────────────────────────────────────────────────

def test_review_requires_settled_booking(api):
    """PRD §3.9: "The booking must be in `SETTLED` (otherwise `ERR_REVIEW_NOT_ELIGIBLE`)."

    Claim: submitting a review for a CONFIRMED (not SETTLED) booking is rejected with ERR_REVIEW_NOT_ELIGIBLE.
    """
    state = setup_slot_with_confirmed_booking(seat_count=2)
    headers = make_player_headers(state["lead_player"]["id"])
    payload = create_review_payload(theme_score=5, venue_score=5, host_score=5, comment="A normal comment that is long enough to avoid the short-comment heuristic.")
    resp = api.create_review(state["booking"]["id"], payload, headers)
    validate_error(resp, ApiErrorId.ERR_REVIEW_NOT_ELIGIBLE.value)


def test_review_duplicate_rejected(api):
    """PRD §3.9: "the player must not have a prior review for the same booking (otherwise `ERR_REVIEW_DUPLICATE`)."

    Claim: a second review by the same author on the same booking yields ERR_REVIEW_DUPLICATE.
    """
    state = setup_review_pending_moderation()
    headers = make_player_headers(state["lead_player"]["id"])
    payload = create_review_payload(theme_score=4, venue_score=4, host_score=4, comment="Trying to submit again to see what happens here.")
    resp = api.create_review(state["booking"]["id"], payload, headers)
    validate_error(resp, ApiErrorId.ERR_REVIEW_DUPLICATE.value)


# ─── §3.9 Submission initial state ─────────────────────────────────────────

def test_review_initial_state_pending_moderation(api):
    """PRD §3.9: "The review enters `PENDING_MODERATION` with `moderation_round` initialised to 0."

    Claim: a fresh review's status is PENDING_MODERATION and moderation_round==0 (assuming spam_signal_count < SPAM_SIGNAL_HARD_BLOCK).
    """
    state = setup_review_pending_moderation(comment="A nicely written comment of moderate length to avoid the short-comment heuristic.")
    review = state["review"]
    assert_review(review)
    assert review["moderation_round"] == 0
    assert review["status"] == ReviewStatus.PENDING_MODERATION.value


# ─── §3.9 Spam scoring ────────────────────────────────────────────────────

def test_short_comment_increments_spam_count(api):
    """PRD §3.9: "Step 1: if the comment's length is below `SHORT_COMMENT_THRESHOLD` (50 characters), increment the count by 1."

    Claim: a < 50-char comment yields spam_signal_count >= 1.
    """
    state = setup_slot_at_completed(seat_count=2)
    review = submit_review(
        state["booking"], state["lead_player"],
        theme_score=4, venue_score=4, host_score=4,
        comment="short",  # 5 chars < 50
    )
    assert review["spam_signal_count"] >= 1


def test_score_spread_signal_increments(api):
    """PRD §3.9: "Step 3: if the difference between the maximum and the minimum of `theme_score` and `venue_score` is at or above `SCORE_SPREAD_THRESHOLD` (3), increment by 1."

    Claim: a comment with theme_score=5 and venue_score=1 contributes a spread signal (count >= 1).
    """
    state = setup_slot_at_completed(seat_count=2)
    review = submit_review(
        state["booking"], state["lead_player"],
        theme_score=5, venue_score=1, host_score=3,
        comment="A long enough comment to avoid the short-comment heuristic exactly.",
    )
    # Just spread (no short comment, no resubmit, no prior REJECTED with mod_round>=1, no repeat).
    assert review["spam_signal_count"] >= 1


# ─── §3.9 Moderation lifecycle ────────────────────────────────────────────

def test_moderate_approve_publishes(api):
    """PRD §3.9: "An `APPROVE` decision moves the review to `PUBLISHED`."

    Claim: APPROVE moves PENDING_MODERATION -> PUBLISHED.
    """
    state = setup_review_pending_moderation(comment="A perfectly normal length comment that is well above the short-comment threshold here.")
    published = moderate_review(state["review"], "APPROVE")
    assert published["status"] == ReviewStatus.PUBLISHED.value


def test_moderate_reject_records_rejected(api):
    """PRD §3.9: "A `REJECT` decision moves the review to `REJECTED`."

    Claim: REJECT moves PENDING_MODERATION -> REJECTED.
    """
    state = setup_review_pending_moderation(comment="A perfectly normal length comment that is well above the short-comment threshold here.")
    rejected = moderate_review(state["review"], "REJECT")
    assert rejected["status"] == ReviewStatus.REJECTED.value


def test_moderate_hide_after_published(api):
    """PRD §3.9: "A `HIDE` decision is only valid against a `PUBLISHED` review and moves it to `HIDDEN`."

    Claim: APPROVE then HIDE moves PUBLISHED -> HIDDEN.
    """
    state = setup_review_pending_moderation(comment="A perfectly normal length comment that is well above the short-comment threshold here.")
    moderate_review(state["review"], "APPROVE")
    hidden = moderate_review(state["review"], "HIDE")
    assert hidden["status"] == ReviewStatus.HIDDEN.value


def test_revise_rejected_review(api):
    """PRD §3.9: "The author may revise a `REJECTED` review by patching `comment`, `theme_score`, `host_score`, or `venue_score`; the request requires `X-User-ID` to equal `author_player_id` (otherwise `ERR_INSUFFICIENT_PERMISSIONS`)."
    PRD §3.9: "On revise, `moderation_round` is incremented by 1 and the review moves to `REVISED`."

    Claim: PATCH /reviews/{id} on a REJECTED review by its author moves it to REVISED with moderation_round bumped by 1.
    """
    state = setup_review_pending_moderation(comment="A perfectly normal length comment that is well above the short-comment threshold here.")
    moderate_review(state["review"], "REJECT")
    headers = make_player_headers(state["lead_player"]["id"])
    revised = validate_success(api.patch_review(state["review"]["id"], patch_review_payload(comment="Revised: a more thoughtful explanation of the experience this time around."), headers))
    assert revised["status"] == ReviewStatus.REVISED.value
    assert revised["moderation_round"] == state["review"]["moderation_round"] + 1


def test_resubmit_revised_review(api):
    """PRD §3.9: "Resubmitting moves the review from `REVISED` back to `PENDING_MODERATION`, requires the same author identity check, and recomputes `spam_signal_count` against the new content."

    Claim: POST /reviews/{id}/resubmit moves REVISED -> PENDING_MODERATION.
    """
    state = setup_review_pending_moderation(comment="A perfectly normal length comment that is well above the short-comment threshold here.")
    moderate_review(state["review"], "REJECT")
    headers = make_player_headers(state["lead_player"]["id"])
    validate_success(api.patch_review(state["review"]["id"], patch_review_payload(comment="Revised: a different explanation here, well over fifty characters in total."), headers))
    resubmitted = validate_success(api.resubmit_review(state["review"]["id"], headers))
    assert resubmitted["status"] == ReviewStatus.PENDING_MODERATION.value


def test_revise_not_authored_by_caller_rejected(api):
    """PRD §3.9: "the request requires `X-User-ID` to equal `author_player_id` (otherwise `ERR_INSUFFICIENT_PERMISSIONS`)."

    Claim: a different player attempting to revise another's review is rejected with ERR_INSUFFICIENT_PERMISSIONS.
    """
    from test_helpers import create_player
    state = setup_review_pending_moderation(comment="A perfectly normal length comment that is well above the short-comment threshold here.")
    moderate_review(state["review"], "REJECT")
    other = create_player()
    resp = api.patch_review(state["review"]["id"], patch_review_payload(comment="Trying to hijack this review with new text from a different player here."), make_player_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)
