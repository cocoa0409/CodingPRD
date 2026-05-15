"""Revision cycle, revision deadline, and sweep auto-withdraw (PRD §3.8)."""
from __future__ import annotations

import datetime as _dt

import pytest

from test_helpers import (
    ApiErrorId,
    MAJOR_REVISION_DAYS,
    MINOR_REVISION_DAYS,
    SECONDS_PER_DAY,
    SECONDS_PER_HOUR,
    advance_clock_to,
    api_client,
    iso_offset,
    make_associate_editor_headers,
    make_author_headers,
    make_reviewer_headers,
    register_reviewer,
    reinvite_reviewers_payload,
    setup_revision_required_manuscript,
    submit_revision_payload,
    validate_error,
    validate_success,
)


def test_revision_deadline_minor_is_thirty_days(api):
    """PRD §3.8: "The delta from the finalize instant is thirty days for
    MINOR_REVISION and sixty days for MAJOR_REVISION; the deadline is the
    finalize instant plus the appropriate delta."
    """
    state = setup_revision_required_manuscript(final_decision="MINOR_REVISION")
    manuscript = state["manuscript"]
    assert manuscript["revision_deadline_at"] is not None
    finalized_at = state["decision"]["finalized_at"]
    if finalized_at is not None:
        finalize_t = _dt.datetime.fromisoformat(
            finalized_at.replace("Z", "+00:00"))
        deadline_t = _dt.datetime.fromisoformat(
            manuscript["revision_deadline_at"].replace("Z", "+00:00"))
        delta_days = (deadline_t - finalize_t).total_seconds() / SECONDS_PER_DAY
        # Within tolerance of 30 days.
        assert abs(delta_days - MINOR_REVISION_DAYS) < 0.01, (
            f"MINOR_REVISION deadline must be ~30 days after finalize, got "
            f"{delta_days} days"
        )


def test_revision_deadline_major_is_sixty_days(api):
    """PRD §3.8: "The delta from the finalize instant is thirty days for
    MINOR_REVISION and sixty days for MAJOR_REVISION ..."
    """
    state = setup_revision_required_manuscript(final_decision="MAJOR_REVISION")
    manuscript = state["manuscript"]
    assert manuscript["revision_deadline_at"] is not None
    finalized_at = state["decision"]["finalized_at"]
    if finalized_at is not None:
        finalize_t = _dt.datetime.fromisoformat(
            finalized_at.replace("Z", "+00:00"))
        deadline_t = _dt.datetime.fromisoformat(
            manuscript["revision_deadline_at"].replace("Z", "+00:00"))
        delta_days = (deadline_t - finalize_t).total_seconds() / SECONDS_PER_DAY
        assert abs(delta_days - MAJOR_REVISION_DAYS) < 0.01


def test_revision_submit_advances_round_and_status(api):
    """PRD §3.8: "A successful revision submission increments the
    manuscript's revision_round by one, supersedes every prior-round
    DRAFT or SUBMITTED review, and advances the manuscript from
    REVISION_REQUIRED to REVISION_SUBMITTED."
    """
    state = setup_revision_required_manuscript()
    res = api.submit_revision(
        state["manuscript"]["id"],
        submit_revision_payload(),
        make_author_headers(state["author"]["id"]),
    )
    revised = validate_success(res, expected_status=200)
    assert revised["status"] == "REVISION_SUBMITTED"
    assert revised["revision_round"] == 1


def test_revision_submit_supersedes_prior_reviews(api):
    """PRD §3.8: "A successful revision submission ... supersedes every
    prior-round DRAFT or SUBMITTED review ..."
    PRD §3.6 (cascade): "when the parent manuscript transitions to
    REVISION_SUBMITTED at a higher revision_round, every prior-round
    DRAFT or SUBMITTED review is set to SUPERSEDED."
    """
    state = setup_revision_required_manuscript()
    api.submit_revision(
        state["manuscript"]["id"],
        submit_revision_payload(),
        make_author_headers(state["author"]["id"]),
    )
    # Fetch every prior-round review.
    for review in state["reviews"]:
        r_res = api.get_review(
            review["id"], make_reviewer_headers(state["reviewers"][0]["id"]),
        )
        body = r_res.json()
        if r_res.status_code >= 400:
            # Some implementations may forbid the original reviewer from
            # reading the review after supersession. Use platform admin.
            from test_helpers import TEST_USERS
            r_res = api.get_review(
                review["id"], TEST_USERS["platform_admin_headers"],
            )
            body = r_res.json()
        assert body["data"]["status"] == "SUPERSEDED", (
            f"Prior review {review['id']} should be SUPERSEDED after "
            f"revision submission; got {body['data']['status']}"
        )


def test_revision_submit_after_deadline_rejected(api):
    """PRD §3.8: "Submission is admissible only while the server clock is
    at or before revision_deadline_at; a clock past the deadline is
    rejected with ERR_REVISION_DEADLINE_PASSED."
    """
    state = setup_revision_required_manuscript()
    # Advance clock past revision_deadline_at.
    deadline = state["manuscript"]["revision_deadline_at"]
    advance_clock_to(iso_offset(deadline, SECONDS_PER_HOUR))
    res = api.submit_revision(
        state["manuscript"]["id"],
        submit_revision_payload(),
        make_author_headers(state["author"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_REVISION_DEADLINE_PASSED.value)


def test_sweep_auto_withdraws_overdue_revision(api, platform_admin_headers):
    """PRD §3.8: "any Manuscript in REVISION_REQUIRED whose
    revision_deadline_at has passed is moved to WITHDRAWN, with a
    REVISION_TIMEOUT_AUTO_WITHDRAW audit row."
    """
    state = setup_revision_required_manuscript()
    deadline = state["manuscript"]["revision_deadline_at"]
    advance_clock_to(iso_offset(deadline, SECONDS_PER_HOUR))
    sweep_res = api.run_sweep(platform_admin_headers)
    validate_success(sweep_res, expected_status=200)

    refetch = api.get_manuscript(
        state["manuscript"]["id"],
        make_author_headers(state["author"]["id"]),
    )
    refreshed = validate_success(refetch, expected_status=200)
    assert refreshed["status"] == "WITHDRAWN"


def test_reinvite_reviewers_returns_to_under_review(api):
    """PRD §3.8: "The action requires at least one new ReviewerInvitation
    to be created at the new revision_round and transitions the
    manuscript from REVISION_SUBMITTED back to UNDER_REVIEW."
    """
    state = setup_revision_required_manuscript()
    api.submit_revision(
        state["manuscript"]["id"], submit_revision_payload(),
        make_author_headers(state["author"]["id"]),
    )
    new_reviewer = register_reviewer(
        expertise_tags=[state["manuscript"]["topic_tag"]])
    res = api.reinvite_reviewers(
        state["manuscript"]["id"],
        reinvite_reviewers_payload(reviewer_ids=[new_reviewer["id"]]),
        make_associate_editor_headers(state["associate_editor"]["id"]),
    )
    manuscript = validate_success(res, expected_status=200)
    assert manuscript["status"] == "UNDER_REVIEW"
    assert manuscript["revision_round"] == 1
