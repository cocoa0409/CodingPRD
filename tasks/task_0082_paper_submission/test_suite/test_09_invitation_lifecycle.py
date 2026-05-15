"""Reviewer invitation lifecycle: accept, decline, withdraw, expire, capacity (PRD §3.5)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    INVITATION_RESPONSE_DAYS,
    REVIEW_DEADLINE_DAYS,
    REVIEWER_MAX_CONCURRENT,
    SECONDS_PER_DAY,
    SECONDS_PER_HOUR,
    advance_clock_by_seconds,
    advance_clock_to,
    create_invitation_payload,
    invite_and_accept_reviewer,
    iso_offset,
    make_associate_editor_headers,
    make_reviewer_headers,
    register_reviewer,
    setup_reviewer_at_load_cap,
    setup_under_review_manuscript,
    validate_error,
    validate_success,
)


def test_accept_invitation_creates_draft_review(api):
    """PRD §3.5: "On a successful acceptance, the system creates a
    Review row in DRAFT with review_deadline_at set to twenty-one days
    after the server clock, copies the manuscript_id and revision_round
    onto the Review for query convenience, and increments the reviewer's
    active_assignments by one."
    """
    base = setup_under_review_manuscript(topic_tag="ml")
    reviewer = register_reviewer(expertise_tags=["ml"])
    inv = invite_and_accept_reviewer(
        base["manuscript"], base["associate_editor"], reviewer,
    )
    assert inv["status"] == "ACCEPTED"

    # Reviewer.active_assignments incremented to 1.
    r_res = api.get_reviewer(reviewer["id"], make_reviewer_headers(reviewer["id"]))
    refreshed = validate_success(r_res, expected_status=200)
    assert refreshed["active_assignments"] == 1


def test_decline_invitation_does_not_increment_assignments(api):
    """PRD §3.5: "A decline simply sets the invitation to DECLINED and
    appends an INVITATION_DECLINED audit row." It does NOT increment
    active_assignments (no Review row is created).
    """
    base = setup_under_review_manuscript(topic_tag="ml")
    reviewer = register_reviewer(expertise_tags=["ml"])
    inv_res = api.create_invitation(
        base["manuscript"]["id"],
        create_invitation_payload(reviewer_id=reviewer["id"]),
        make_associate_editor_headers(base["associate_editor"]["id"]),
    )
    invitation = validate_success(inv_res, expected_status=201)
    dec_res = api.decline_invitation(
        base["manuscript"]["id"], invitation["id"],
        make_reviewer_headers(reviewer["id"]),
    )
    declined = validate_success(dec_res, expected_status=200)
    assert declined["status"] == "DECLINED"

    r_res = api.get_reviewer(reviewer["id"], make_reviewer_headers(reviewer["id"]))
    refreshed = validate_success(r_res, expected_status=200)
    assert refreshed["active_assignments"] == 0


def test_associate_editor_withdraws_pending_invitation(api):
    """PRD §3.5: "The associate editor may also withdraw an invitation
    that is still PENDING, in which case the row transitions to
    WITHDRAWN; the caller must own the associate-editor seat —
    Manuscript.associate_editor_id must equal X-User-ID."
    """
    base = setup_under_review_manuscript(topic_tag="ml")
    reviewer = register_reviewer(expertise_tags=["ml"])
    inv_res = api.create_invitation(
        base["manuscript"]["id"],
        create_invitation_payload(reviewer_id=reviewer["id"]),
        make_associate_editor_headers(base["associate_editor"]["id"]),
    )
    invitation = validate_success(inv_res, expected_status=201)
    w_res = api.withdraw_invitation(
        base["manuscript"]["id"], invitation["id"],
        make_associate_editor_headers(base["associate_editor"]["id"]),
    )
    withdrawn = validate_success(w_res, expected_status=200)
    assert withdrawn["status"] == "WITHDRAWN"


def test_accept_after_deadline_passed_rejected(api, platform_admin_headers):
    """PRD §3.5: "Acceptance is admissible only while the manuscript is in
    UNDER_REVIEW and the current server clock is at or before
    response_deadline_at; a clock past the deadline returns
    ERR_INVITATION_DEADLINE_PASSED."
    """
    base = setup_under_review_manuscript(topic_tag="ml")
    reviewer = register_reviewer(expertise_tags=["ml"])
    inv_res = api.create_invitation(
        base["manuscript"]["id"],
        create_invitation_payload(reviewer_id=reviewer["id"]),
        make_associate_editor_headers(base["associate_editor"]["id"]),
    )
    invitation = validate_success(inv_res, expected_status=201)
    # Advance clock past response_deadline_at.
    deadline = invitation["response_deadline_at"]
    advance_clock_to(iso_offset(deadline, 60 * 60))  # +1 hour past deadline
    res = api.accept_invitation(
        base["manuscript"]["id"], invitation["id"],
        make_reviewer_headers(reviewer["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVITATION_DEADLINE_PASSED.value)


def test_accept_pushes_load_above_cap_rejected(api):
    """PRD §3.5: "An acceptance that would push the count past three is
    rejected with ERR_REVIEWER_OVERLOADED."
    """
    state = setup_reviewer_at_load_cap(topic_tag="ml")
    reviewer = state["reviewer"]
    # Reviewer currently at REVIEWER_MAX_CONCURRENT == 3. Build a 4th
    # invitation and try to accept.
    base = setup_under_review_manuscript(topic_tag="ml")
    inv_res = api.create_invitation(
        base["manuscript"]["id"],
        create_invitation_payload(reviewer_id=reviewer["id"]),
        make_associate_editor_headers(base["associate_editor"]["id"]),
    )
    invitation = validate_success(inv_res, expected_status=201)
    res = api.accept_invitation(
        base["manuscript"]["id"], invitation["id"],
        make_reviewer_headers(reviewer["id"]),
    )
    validate_error(res, ApiErrorId.ERR_REVIEWER_OVERLOADED.value)


def test_sweep_expires_overdue_pending_invitations(api, platform_admin_headers):
    """PRD §3.8: "any ReviewerInvitation still in PENDING whose
    response_deadline_at has passed is moved to EXPIRED, with an
    INVITATION_EXPIRED audit row."
    """
    base = setup_under_review_manuscript(topic_tag="ml")
    reviewer = register_reviewer(expertise_tags=["ml"])
    inv_res = api.create_invitation(
        base["manuscript"]["id"],
        create_invitation_payload(reviewer_id=reviewer["id"]),
        make_associate_editor_headers(base["associate_editor"]["id"]),
    )
    invitation = validate_success(inv_res, expected_status=201)
    # Advance clock and sweep.
    advance_clock_to(iso_offset(invitation["response_deadline_at"], 3600))
    sweep_res = api.run_sweep(platform_admin_headers)
    validate_success(sweep_res, expected_status=200)

    # Refetch invitation status via list endpoint.
    list_res = api.list_invitations(
        base["manuscript"]["id"],
        make_associate_editor_headers(base["associate_editor"]["id"]),
    )
    invitations = list_res.json()["data"]
    found = next(i for i in invitations if i["id"] == invitation["id"])
    assert found["status"] == "EXPIRED"


def test_accept_by_wrong_reviewer_rejected(api, reviewer_fallback_headers):
    """PRD §3.5: "A reviewer accepts or declines from the row whose
    reviewer_id matches X-User-ID."
    A reviewer-role caller whose X-User-ID does NOT equal the invitation's
    reviewer_id must be rejected (ownership check).
    """
    base = setup_under_review_manuscript(topic_tag="ml")
    reviewer = register_reviewer(expertise_tags=["ml"])
    inv_res = api.create_invitation(
        base["manuscript"]["id"],
        create_invitation_payload(reviewer_id=reviewer["id"]),
        make_associate_editor_headers(base["associate_editor"]["id"]),
    )
    invitation = validate_success(inv_res, expected_status=201)
    res = api.accept_invitation(
        base["manuscript"]["id"], invitation["id"],
        reviewer_fallback_headers,
    )
    assert res.status_code in (403, 404), (
        f"Expected 403/404 for wrong reviewer owner, got {res.status_code}: {res.text}"
    )
