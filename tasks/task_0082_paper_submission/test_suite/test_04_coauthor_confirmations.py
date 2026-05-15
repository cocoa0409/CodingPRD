"""Co-author confirmation lifecycle and bubble-up cascade (PRD §3.2)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_coauthor_confirmation,
    make_author_headers,
    register_author,
    setup_manuscript_awaiting_coauthor,
    validate_error,
    validate_success,
)


def test_coauthor_confirmations_created_one_per_coauthor(api):
    """PRD §3.2: "When co_author_ids is non-empty, the manuscript
    transitions from DRAFT to AWAITING_COAUTHOR, one CoAuthorConfirmation
    row is created per co-author with status=PENDING ..."
    """
    base = setup_manuscript_awaiting_coauthor(num_coauthors=3)
    assert len(base["confirmations"]) == 3
    for c in base["confirmations"]:
        assert_coauthor_confirmation(c)
        assert c["status"] == "PENDING"


def test_coauthor_confirm_requires_matching_user_id(api, author_fallback_headers):
    """PRD §3.2: "Each co-author then responds independently — confirming
    or declining their participation by acting on the confirmation row
    whose author_id matches X-User-ID."
    """
    base = setup_manuscript_awaiting_coauthor(num_coauthors=2)
    confirmation = base["confirmations"][0]
    # A different author (not the co-author of this confirmation) cannot
    # confirm. The fallback headers carry an unrelated X-User-ID.
    res = api.confirm_coauthor(
        base["manuscript"]["id"], confirmation["id"],
        author_fallback_headers,
    )
    assert res.status_code in (403, 404), (
        f"Expected 403/404 for wrong owner, got {res.status_code}: {res.text}"
    )


def test_coauthor_confirm_sets_responded_at(api):
    """PRD §3.2: "A confirmation sets responded_at to the server clock."
    """
    base = setup_manuscript_awaiting_coauthor(num_coauthors=2)
    confirmation = base["confirmations"][0]
    coauthor = next(
        c for c in base["coauthors"] if c["id"] == confirmation["author_id"]
    )
    res = api.confirm_coauthor(
        base["manuscript"]["id"], confirmation["id"],
        make_author_headers(coauthor["id"]),
    )
    data = validate_success(res, expected_status=200)
    assert data["status"] == "CONFIRMED"
    assert data["responded_at"] is not None


def test_all_coauthors_confirm_bubbles_manuscript_to_submitted(api):
    """PRD §3.2: "When the last PENDING sibling flips to CONFIRMED, the
    manuscript advances from AWAITING_COAUTHOR to SUBMITTED and a
    plagiarism check is requested."
    """
    base = setup_manuscript_awaiting_coauthor(num_coauthors=2)
    for confirmation in base["confirmations"]:
        coauthor = next(
            c for c in base["coauthors"]
            if c["id"] == confirmation["author_id"]
        )
        res = api.confirm_coauthor(
            base["manuscript"]["id"], confirmation["id"],
            make_author_headers(coauthor["id"]),
        )
        validate_success(res, expected_status=200)
    refetch = api.get_manuscript(
        base["manuscript"]["id"],
        make_author_headers(base["author"]["id"]),
    )
    manuscript = validate_success(refetch, expected_status=200)
    assert manuscript["status"] == "SUBMITTED"


def test_one_coauthor_declines_bubbles_manuscript_to_withdrawn(api):
    """PRD §3.2: "When any sibling declines, the manuscript transitions
    to WITHDRAWN: every still-PENDING sibling is set to DECLINED with
    responded_at=now, and an audit row with action
    COAUTHOR_DECLINED_AUTO_WITHDRAW is appended."
    """
    base = setup_manuscript_awaiting_coauthor(num_coauthors=2)
    confirmation = base["confirmations"][0]
    coauthor = next(
        c for c in base["coauthors"] if c["id"] == confirmation["author_id"]
    )
    res = api.decline_coauthor(
        base["manuscript"]["id"], confirmation["id"],
        make_author_headers(coauthor["id"]),
    )
    validate_success(res, expected_status=200)
    refetch = api.get_manuscript(
        base["manuscript"]["id"],
        make_author_headers(base["author"]["id"]),
    )
    manuscript = validate_success(refetch, expected_status=200)
    assert manuscript["status"] == "WITHDRAWN"


def test_coauthor_decline_cascades_remaining_pending_to_declined(api):
    """PRD §3.2: "When any sibling declines, the manuscript transitions
    to WITHDRAWN: every still-PENDING sibling is set to DECLINED with
    responded_at=now ..."
    """
    base = setup_manuscript_awaiting_coauthor(num_coauthors=3)
    # Decline by first confirmation.
    first = base["confirmations"][0]
    first_coauthor = next(
        c for c in base["coauthors"] if c["id"] == first["author_id"]
    )
    res = api.decline_coauthor(
        base["manuscript"]["id"], first["id"],
        make_author_headers(first_coauthor["id"]),
    )
    validate_success(res, expected_status=200)

    # List confirmations and verify all flipped to DECLINED.
    list_res = api.list_coauthor_confirmations(
        base["manuscript"]["id"],
        make_author_headers(base["author"]["id"]),
    )
    body = list_res.json()
    data = body["data"]
    for c in data:
        assert c["status"] == "DECLINED", (
            f"Confirmation {c['id']} still {c['status']} after cascade"
        )
        assert c["responded_at"] is not None
