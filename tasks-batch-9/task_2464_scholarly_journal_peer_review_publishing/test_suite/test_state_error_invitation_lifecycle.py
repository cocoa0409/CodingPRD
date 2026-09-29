"""Invitation-side refusals: an empty pool, a wrong-state review, a late acceptance and a stranger editor."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import ApiErrorId
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import SYSTEM_ADMIN_HEADERS, api_client

DUE_DAYS = 5
DEADLINE_INSTANT = "2026-08-06T00:00:00Z"
DEADLINE_STAMP = "2026-08-06T00:00:00.000Z"


def _list_invitations(manuscript_id):
    return get_success_data(
        api_client.list_review_invitations(
            SYSTEM_ADMIN_HEADERS, params={"manuscript_id": manuscript_id}
        )
    )


def _list_reviews(invitation_id):
    return get_success_data(
        api_client.list_reviews(invitation_id, SYSTEM_ADMIN_HEADERS)
    )


def _attempt_selector_invitation(manuscript_id, handling_headers):
    return api_client.create_review_invitation(
        f.review_invitation_payload(manuscript_id), handling_headers
    )


def _attempt_named_invitation(manuscript_id, reviewer_id, handling_headers):
    return api_client.create_review_invitation(
        f.review_invitation_payload(manuscript_id, reviewer_id=reviewer_id),
        handling_headers,
    )


def _attempt_review(invitation_id, reviewer_headers):
    return api_client.submit_review(
        invitation_id, f.review_payload("ACCEPT"), reviewer_headers
    )


def _attempt_acceptance(invitation_id, reviewer_headers):
    return api_client.respond_to_invitation(
        invitation_id, f.invitation_response_payload("ACCEPT"), reviewer_headers
    )


def _setup_single_ineligible_reviewer():
    """An under-review manuscript whose only society reviewer shares the author's affiliation."""
    world = fx.setup_under_review_manuscript()
    reviewer, reviewer_headers = fx.create_reviewer(
        affiliation=world["author"]["affiliation"]
    )
    world["reviewer"] = reviewer
    world["reviewer_headers"] = reviewer_headers
    return world


def _setup_open_invitation():
    """An under-review manuscript with one invitation still at `INVITED`."""
    world = fx.setup_under_review_manuscript()
    reviewer, reviewer_headers = fx.create_reviewer()
    world["reviewer"] = reviewer
    world["reviewer_headers"] = reviewer_headers
    world["invitation"] = fx.invite_reviewer(
        world["manuscript"]["id"],
        world["handling_headers"],
        reviewer_id=reviewer["id"],
        due_days=DUE_DAYS,
    )
    return world


def test_selector_refuses_when_the_only_reviewer_shares_the_authors_affiliation():
    """The affiliation exclusion empties the pool, and an empty pool has its own error.

    PRD: "An empty pool is refused with `ERR_NO_ELIGIBLE_REVIEWER`."

    Design: Corner/errors/reviewer_selector_with_no_eligible_reviewer_rejected
    """
    world = _setup_single_ineligible_reviewer()
    assert world["reviewer"]["affiliation"] == world["author"]["affiliation"]

    response = _attempt_selector_invitation(
        world["manuscript"]["id"], world["handling_headers"]
    )

    error = validate_error(
        response, ApiErrorId.ERR_NO_ELIGIBLE_REVIEWER.value, expected_status=409
    )
    assert error["error_id"] != ApiErrorId.ERR_REVIEWER_CONFLICT.value, (
        "no reviewer was named, so the refusal is about the pool and not about a conflict"
    )


def test_refused_selector_invitation_leaves_the_reviewer_untouched():
    """Nothing is created, so neither the invitation list nor the load counters move.

    PRD: "Creating the invitation raises that reviewer's `invited_count` by 1 and their `open_invitation_count` by 1, and re-runs both reliability variants for that reviewer."

    Design: Corner/errors/reviewer_selector_with_no_eligible_reviewer_rejected
    """
    world = _setup_single_ineligible_reviewer()

    _attempt_selector_invitation(world["manuscript"]["id"], world["handling_headers"])

    assert _list_invitations(world["manuscript"]["id"]) == []
    reviewer = fx.get_reviewer(world["reviewer"]["id"])
    a.assert_fields(reviewer, invited_count=0, open_invitation_count=0)


def test_review_against_an_invited_invitation_reports_the_invitation_gate():
    """The reviewer never accepted, so the invitation gate answers instead of a state error.

    PRD: "Only the reviewer named on the invitation may submit, and the invitation must be in state `ACCEPTED`: a submission against an invitation in any other state, including `INVITED`, is refused with `ERR_INVITATION_NOT_ACCEPTED` rather than with a generic state error."

    Design: Corner/errors/review_submission_on_an_invited_invitation_rejected
    """
    world = _setup_open_invitation()
    assert world["invitation"]["state"] == "INVITED"

    response = _attempt_review(world["invitation"]["id"], world["reviewer_headers"])

    error = validate_error(
        response, ApiErrorId.ERR_INVITATION_NOT_ACCEPTED.value, expected_status=409
    )
    assert error["error_id"] != ApiErrorId.ERR_INVALID_INVITATION_STATE.value, (
        "the invitation-state gate replaces the generic invalid-state answer here"
    )


def test_refused_review_stores_no_review_and_closes_no_invitation():
    """None of the submission's effects on the invitation or the reviewer happened.

    PRD: "Submission then closes the invitation and updates the reviewer: the invitation moves `ACCEPTED → SUBMITTED` with `closed_reason` `REVIEW_SUBMITTED`, the reviewer's `submitted_count` rises by 1, their `late_days_total` rises by this review's `days_late`, and their `open_invitation_count` falls by 1."

    Design: Corner/errors/review_submission_on_an_invited_invitation_rejected
    """
    world = _setup_open_invitation()

    _attempt_review(world["invitation"]["id"], world["reviewer_headers"])

    assert _list_reviews(world["invitation"]["id"]) == []
    invitation = fx.get_invitation(world["invitation"]["id"])
    a.assert_fields(invitation, state="INVITED", version=world["invitation"]["version"])
    assert invitation.get("closed_reason") is None
    reviewer = fx.get_reviewer(world["reviewer"]["id"])
    a.assert_fields(reviewer, submitted_count=0, open_invitation_count=1)
    manuscript = fx.get_manuscript(world["manuscript"]["id"])
    a.assert_fields(manuscript, status="UNDER_REVIEW", submitted_review_count=0)


def test_acceptance_at_the_deadline_instant_is_refused_as_expired():
    """The clock stands exactly on `due_at`, which is already too late to accept.

    PRD: "An acceptance is additionally time-bounded: it is permitted only while the current clock instant is strictly before the invitation's `due_at`, so an attempt to accept at or after the deadline is refused with `ERR_INVITATION_EXPIRED`."

    Design: Corner/errors/acceptance_at_the_due_date_rejected_as_expired
    """
    world = _setup_open_invitation()
    assert world["invitation"]["due_at"] == DEADLINE_STAMP
    fx.set_clock(DEADLINE_INSTANT)

    response = _attempt_acceptance(world["invitation"]["id"], world["reviewer_headers"])

    validate_error(
        response, ApiErrorId.ERR_INVITATION_EXPIRED.value, expected_status=409
    )


def test_refused_late_acceptance_leaves_the_invitation_open_and_unanswered():
    """The refusal is not an expiry either: only the sweep may close the invitation.

    PRD: "`ACCEPT` moves the invitation `INVITED → ACCEPTED`, sets `responded_at` to the current clock instant, raises the reviewer's `accepted_count` by 1, and re-runs both reliability variants."

    Design: Corner/errors/acceptance_at_the_due_date_rejected_as_expired
    """
    world = _setup_open_invitation()
    fx.set_clock(DEADLINE_INSTANT)

    _attempt_acceptance(world["invitation"]["id"], world["reviewer_headers"])

    invitation = fx.get_invitation(world["invitation"]["id"])
    a.assert_fields(
        invitation,
        state="INVITED",
        due_at=DEADLINE_STAMP,
        version=world["invitation"]["version"],
    )
    assert invitation.get("responded_at") is None
    reviewer = fx.get_reviewer(world["reviewer"]["id"])
    a.assert_fields(
        reviewer, accepted_count=0, expired_count=0, open_invitation_count=1
    )


def test_invitation_from_an_editor_without_the_active_assignment_is_refused():
    """A second handling editor of the same journal holds no assignment, so he cannot invite.

    PRD: "Only the editor holding the manuscript's `ACTIVE` assignment may invite; otherwise the refusal is `ERR_ASSIGNMENT_NOT_ACTIVE`."

    Design: Corner/errors/invitation_by_an_editor_without_an_active_assignment_rejected
    """
    world = fx.setup_under_review_manuscript(handling_editor_count=2)
    reviewer, _headers = fx.create_reviewer()
    outsider_headers = world["handlings"][1]["headers"]

    response = _attempt_named_invitation(
        world["manuscript"]["id"], reviewer["id"], outsider_headers
    )

    validate_error(
        response, ApiErrorId.ERR_ASSIGNMENT_NOT_ACTIVE.value, expected_status=409
    )
    assert _list_invitations(world["manuscript"]["id"]) == []


def test_the_holder_of_the_active_assignment_may_issue_the_same_invitation():
    """The identical body succeeds from the editor the assignment names.

    PRD: "The invitation begins at `INVITED`, records `selected_by` as `EXPLICIT` when the request named a reviewer and `SELECTOR` when the server chose one, and carries `reminder_count` 0, `last_reminder_at` absent, `responded_at` absent, `decline_reason` absent and `closed_reason` absent."

    Design: Corner/errors/invitation_by_an_editor_without_an_active_assignment_rejected
    """
    world = fx.setup_under_review_manuscript(handling_editor_count=2)
    reviewer, _headers = fx.create_reviewer()
    _attempt_named_invitation(
        world["manuscript"]["id"], reviewer["id"], world["handlings"][1]["headers"]
    )

    invitation = validate_success(
        _attempt_named_invitation(
            world["manuscript"]["id"], reviewer["id"], world["handling_headers"]
        ),
        expected_status=201,
    )

    a.assert_fields(
        invitation, state="INVITED", selected_by="EXPLICIT", reminder_count=0
    )
    reviewer_row = fx.get_reviewer(reviewer["id"])
    a.assert_fields(reviewer_row, invited_count=1, open_invitation_count=1)
