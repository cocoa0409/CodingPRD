"""Manuscript drafting and submission (PRD §3.2)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_DEFAULTS,
    assert_manuscript,
    create_author_payload,
    create_manuscript_in_draft,
    create_manuscript_payload,
    make_author_headers,
    register_author,
    register_reviewer,
    setup_submitted_manuscript,
    submit_manuscript_to_submitted,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Manuscript creation (PRD §3.2)
# ---------------------------------------------------------------------------
def test_manuscript_created_in_draft_state(api):
    """PRD §3.2: "A Manuscript is created in DRAFT by the corresponding
    author."
    """
    author = register_author()
    payload = create_manuscript_payload(corresponding_author_id=author["id"])
    res = api.create_manuscript(payload, make_author_headers(author["id"]))
    manuscript = validate_success(res, expected_status=201)
    assert_manuscript(manuscript)
    assert manuscript["status"] == "DRAFT"
    assert manuscript["revision_round"] == 0
    assert manuscript["corresponding_author_id"] == author["id"]


@pytest.mark.parametrize("missing_field", [
    "title", "corresponding_author_id", "topic_tag", "review_mode",
    "manuscript_file_uri", "declaration_coi", "declaration_funding",
    "declaration_ethics",
])
def test_manuscript_create_missing_required_field(api, missing_field):
    """PRD §3.2: "The draft must carry title, corresponding_author_id,
    topic_tag, review_mode (SINGLE_BLIND, DOUBLE_BLIND, or OPEN),
    manuscript_file_uri, and all three declarations — declaration_coi,
    declaration_funding, and declaration_ethics."
    """
    author = register_author()
    payload = create_manuscript_payload(corresponding_author_id=author["id"])
    payload.pop(missing_field, None)
    res = api.create_manuscript(payload, make_author_headers(author["id"]))
    validate_error(res, ApiErrorId.ERR_VALIDATION.value)


def test_manuscript_create_invalid_review_mode_rejected(api):
    """PRD §3.2: "review_mode (SINGLE_BLIND, DOUBLE_BLIND, or OPEN)" —
    any other value is invalid input.
    """
    author = register_author()
    payload = create_manuscript_payload(
        corresponding_author_id=author["id"], review_mode="MAYBE",
    )
    res = api.create_manuscript(payload, make_author_headers(author["id"]))
    validate_error(res, ApiErrorId.ERR_VALIDATION.value)


@pytest.mark.parametrize("bad_topic_tag", [
    "Has Space", "UPPER", "kebab-case", "with.dot",
])
def test_manuscript_create_invalid_topic_tag_rejected(api, bad_topic_tag):
    """PRD §3.2: "The topic_tag must match the lower-snake-case shape
    [a-z0-9_]+."
    """
    author = register_author()
    payload = create_manuscript_payload(
        corresponding_author_id=author["id"], topic_tag=bad_topic_tag,
    )
    res = api.create_manuscript(payload, make_author_headers(author["id"]))
    validate_error(res, ApiErrorId.ERR_VALIDATION.value)


def test_manuscript_coauthors_must_not_include_corresponding(api):
    """PRD §3.2: "the system rejects co_author_ids that either contains
    the corresponding_author_id itself or has duplicate entries — both
    shapes return ERR_COAUTHOR_LIST_INVALID."
    """
    author = register_author()
    other = register_author()
    payload = create_manuscript_payload(
        corresponding_author_id=author["id"],
        co_author_ids=[author["id"], other["id"]],
    )
    res = api.create_manuscript(payload, make_author_headers(author["id"]))
    validate_error(res, ApiErrorId.ERR_COAUTHOR_LIST_INVALID.value)


def test_manuscript_coauthors_must_not_have_duplicates(api):
    """PRD §3.2: "the system rejects co_author_ids that either contains
    the corresponding_author_id itself or has duplicate entries — both
    shapes return ERR_COAUTHOR_LIST_INVALID."
    """
    author = register_author()
    co1 = register_author()
    payload = create_manuscript_payload(
        corresponding_author_id=author["id"],
        co_author_ids=[co1["id"], co1["id"]],
    )
    res = api.create_manuscript(payload, make_author_headers(author["id"]))
    validate_error(res, ApiErrorId.ERR_COAUTHOR_LIST_INVALID.value)


def test_manuscript_suggested_and_excluded_must_be_disjoint(api):
    """PRD §3.2: "The suggested_reviewer_ids and excluded_reviewer_ids
    arrays must be disjoint; any shared identifier returns
    ERR_REVIEWER_LISTS_OVERLAP."
    """
    author = register_author()
    reviewer = register_reviewer()
    payload = create_manuscript_payload(
        corresponding_author_id=author["id"],
        suggested_reviewer_ids=[reviewer["id"]],
        excluded_reviewer_ids=[reviewer["id"]],
    )
    res = api.create_manuscript(payload, make_author_headers(author["id"]))
    validate_error(res, ApiErrorId.ERR_REVIEWER_LISTS_OVERLAP.value)


# ---------------------------------------------------------------------------
# Submission (PRD §3.2)
# ---------------------------------------------------------------------------
def test_submit_without_orcid_verified_rejected(api):
    """PRD §3.2: "At submit time the corresponding author must have
    orcid_verified=true (otherwise ERR_ORCID_NOT_VERIFIED) ..."
    """
    author = register_author(verify_orcid=False)
    manuscript = create_manuscript_in_draft(author)
    res = api.submit_manuscript(
        manuscript["id"], make_author_headers(author["id"]),
    )
    validate_error(res, ApiErrorId.ERR_ORCID_NOT_VERIFIED.value)


@pytest.mark.parametrize("blank_field", [
    "declaration_coi", "declaration_funding", "declaration_ethics",
])
def test_submit_with_blank_declaration_rejected(api, blank_field):
    """PRD §3.2: "all three declaration fields must be non-empty, and
    manuscript_file_uri must be non-empty (otherwise
    ERR_DECLARATION_INCOMPLETE)."
    """
    author = register_author()
    overrides = {blank_field: ""}
    manuscript = create_manuscript_in_draft(author, **overrides)
    res = api.submit_manuscript(
        manuscript["id"], make_author_headers(author["id"]),
    )
    validate_error(res, ApiErrorId.ERR_DECLARATION_INCOMPLETE.value)


def test_submit_with_blank_manuscript_file_uri_rejected(api):
    """PRD §3.2: "... and manuscript_file_uri must be non-empty (otherwise
    ERR_DECLARATION_INCOMPLETE)."
    """
    author = register_author()
    manuscript = create_manuscript_in_draft(author, manuscript_file_uri="")
    res = api.submit_manuscript(
        manuscript["id"], make_author_headers(author["id"]),
    )
    validate_error(res, ApiErrorId.ERR_DECLARATION_INCOMPLETE.value)


def test_submit_with_empty_coauthors_goes_directly_to_submitted(api):
    """PRD §3.2: "When co_author_ids is empty, the manuscript transitions
    directly from DRAFT to SUBMITTED, a plagiarism check is requested
    from the external service ..."
    """
    author = register_author()
    manuscript = create_manuscript_in_draft(author, co_author_ids=[])
    res = api.submit_manuscript(
        manuscript["id"], make_author_headers(author["id"]),
    )
    submitted = validate_success(res, expected_status=200)
    assert submitted["status"] == "SUBMITTED"


def test_submit_with_coauthors_enters_awaiting_coauthor(api):
    """PRD §3.2: "When co_author_ids is non-empty, the manuscript
    transitions from DRAFT to AWAITING_COAUTHOR, one
    CoAuthorConfirmation row is created per co-author with status=PENDING."
    """
    author = register_author()
    co = register_author()
    manuscript = create_manuscript_in_draft(author, co_author_ids=[co["id"]])
    res = api.submit_manuscript(
        manuscript["id"], make_author_headers(author["id"]),
    )
    submitted = validate_success(res, expected_status=200)
    assert submitted["status"] == "AWAITING_COAUTHOR"


def test_submit_from_non_draft_state_rejected(api):
    """PRD §2.5: "state-machine permissibility of the requested
    transition (ERR_INVALID_STATE)." A second /submit on a manuscript
    already in SUBMITTED (or any non-DRAFT state) is not a permitted
    transition.
    """
    base = setup_submitted_manuscript()
    res = api.submit_manuscript(
        base["manuscript"]["id"],
        make_author_headers(base["author"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
