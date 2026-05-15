"""Manuscript withdrawal cascades (PRD §3.2)."""
from __future__ import annotations

import pytest

from test_helpers import (
    api_client,
    create_invitation_payload,
    invite_and_accept_reviewer,
    make_associate_editor_headers,
    make_author_headers,
    register_author,
    register_reviewer,
    setup_submitted_manuscript,
    setup_under_review_manuscript,
    validate_success,
)


def test_withdraw_from_draft_transitions_to_withdrawn(api):
    """PRD §3.2: "A withdrawal initiated by the author is admissible from
    DRAFT, SUBMITTED, or UNDER_REVIEW. From DRAFT no cascade is needed
    and only an audit row with action WITHDRAWN_BY_AUTHOR is appended."
    """
    from test_helpers import create_manuscript_in_draft
    author = register_author()
    manuscript = create_manuscript_in_draft(author)
    res = api.withdraw_manuscript(
        manuscript["id"], make_author_headers(author["id"]),
    )
    withdrawn = validate_success(res, expected_status=200)
    assert withdrawn["status"] == "WITHDRAWN"


def test_withdraw_from_submitted_cascades_pending_invitations(api):
    """PRD §3.2: "From SUBMITTED, every still-PENDING ReviewerInvitation
    at the current revision_round is set to WITHDRAWN."

    Note: PRD §3.2 says invitations are issued only after the manuscript
    enters UNDER_REVIEW (PRD §3.5). So in SUBMITTED there are typically
    no invitations to cascade — but the cascade rule on SUBMITTED is
    listed for completeness. We test the simple withdraw-from-SUBMITTED
    transition itself.
    """
    base = setup_submitted_manuscript()
    res = api.withdraw_manuscript(
        base["manuscript"]["id"],
        make_author_headers(base["author"]["id"]),
    )
    withdrawn = validate_success(res, expected_status=200)
    assert withdrawn["status"] == "WITHDRAWN"


def test_withdraw_from_under_review_cascades_pending_invitations(api):
    """PRD §3.2: "From UNDER_REVIEW, the same invitation cascade applies,
    and additionally every DRAFT or SUBMITTED Review at the current
    revision_round is set to SUPERSEDED."
    """
    base = setup_under_review_manuscript(topic_tag="ml")
    # Create one PENDING invitation and one ACCEPTED invitation
    # (creating a DRAFT review).
    reviewer_pending = register_reviewer(expertise_tags=["ml"])
    inv_pending_res = api.create_invitation(
        base["manuscript"]["id"],
        create_invitation_payload(reviewer_id=reviewer_pending["id"]),
        make_associate_editor_headers(base["associate_editor"]["id"]),
    )
    inv_pending = validate_success(inv_pending_res, expected_status=201)

    reviewer_accepted = register_reviewer(expertise_tags=["ml"])
    invite_and_accept_reviewer(
        base["manuscript"], base["associate_editor"], reviewer_accepted,
    )

    # Author withdraws.
    res = api.withdraw_manuscript(
        base["manuscript"]["id"],
        make_author_headers(base["author"]["id"]),
    )
    withdrawn = validate_success(res, expected_status=200)
    assert withdrawn["status"] == "WITHDRAWN"

    # Pending invitation should now be WITHDRAWN.
    list_res = api.list_invitations(
        base["manuscript"]["id"],
        make_associate_editor_headers(base["associate_editor"]["id"]),
    )
    invitations = list_res.json()["data"]
    pending = next(i for i in invitations if i["id"] == inv_pending["id"])
    assert pending["status"] == "WITHDRAWN", (
        "PRD §3.2: 'every still-PENDING ReviewerInvitation at the "
        "current revision_round is set to WITHDRAWN' — pending "
        f"invitation remained {pending['status']}"
    )


def test_withdraw_by_wrong_author_rejected(api, author_fallback_headers):
    """PRD §2.1 ownership rule: an Author-role caller whose X-User-ID
    does not equal the manuscript's corresponding_author_id cannot
    withdraw the manuscript.
    """
    base = setup_submitted_manuscript()
    res = api.withdraw_manuscript(
        base["manuscript"]["id"], author_fallback_headers,
    )
    assert res.status_code in (403, 404)
