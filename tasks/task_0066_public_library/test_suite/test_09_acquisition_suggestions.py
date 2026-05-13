"""Acquisition-suggestion workflow tests (PRD §3.8)."""

import pytest

from test_helpers import (
    LIBRARIAN_HEADERS,
    acquire_new_book_title_payload,
    assert_acquisition_suggestion,
    create_suggestion_payload,
    create_verified_reader_with_card,
    decide_suggestion_payload,
    make_reader_headers,
    setup_under_review_suggestion,
    validate_error,
    validate_success,
)


def test_create_suggestion_initial_state(api):
    """PRD §3.8: "The suggestion enters SUBMITTED with review_notes null and
    decision_book_title_id null."

    Claim: a freshly submitted suggestion has status=SUBMITTED with null
    review_notes and null decision_book_title_id.
    """
    reader, card = create_verified_reader_with_card()
    res = api.create_suggestion(
        create_suggestion_payload(
            card["id"],
            suggested_isbn="9781234567897",
            suggested_title="Suggested Title",
            rationale="Important",
        ),
        make_reader_headers(reader["id"]),
    )
    suggestion = validate_success(res, 201)
    assert_acquisition_suggestion(suggestion)
    assert suggestion["status"] == "SUBMITTED"
    assert suggestion.get("review_notes") in (None,)
    assert suggestion.get("decision_book_title_id") in (None,)


def test_start_review_submitted_to_under_review(api):
    """PRD §3.8: "Starting review moves the suggestion from SUBMITTED to
    UNDER_REVIEW".

    Claim: start-review transitions SUBMITTED → UNDER_REVIEW.
    """
    ctx = setup_under_review_suggestion()
    assert ctx["suggestion"]["status"] == "UNDER_REVIEW"


def test_decide_acquire_creates_book_title_and_terminates(api):
    """PRD §3.8: "An ACQUIRE decision creates the new BookTitle from the
    supplied block ... and writes decision_book_title_id to the new title's
    id; the suggestion transitions to the terminal ACQUIRED state."

    Claim: deciding ACQUIRE creates a new BookTitle and sets
    decision_book_title_id; suggestion status becomes ACQUIRED.
    """
    ctx = setup_under_review_suggestion(suggested_isbn="9783161484100")
    new_title_block = acquire_new_book_title_payload("9783161484100")
    res = api.decide_suggestion(
        ctx["suggestion"]["id"],
        decide_suggestion_payload(
            "ACQUIRE",
            review_notes="approved",
            new_book_title=new_title_block,
        ),
        LIBRARIAN_HEADERS,
    )
    decided = validate_success(res, 200)
    assert decided["status"] == "ACQUIRED"
    assert decided["decision_book_title_id"] is not None
    # Verify the BookTitle row exists.
    title = validate_success(
        api.get_book_title(decided["decision_book_title_id"], LIBRARIAN_HEADERS),
        200,
    )
    assert title["isbn"] == "9783161484100"


def test_decide_decline_terminates(api):
    """PRD §3.8: "A DECLINE decision transitions the suggestion to the
    terminal DECLINED state."

    Claim: deciding DECLINE sets status=DECLINED.
    """
    ctx = setup_under_review_suggestion()
    res = api.decide_suggestion(
        ctx["suggestion"]["id"],
        decide_suggestion_payload("DECLINE"),
        LIBRARIAN_HEADERS,
    )
    decided = validate_success(res, 200)
    assert decided["status"] == "DECLINED"


def test_decide_defer_then_resume_under_review(api):
    """PRD §3.8: "A DEFER decision transitions the suggestion to DEFERRED,
    from which the librarian can re-initiate review later."

    Claim: deciding DEFER sets status=DEFERRED; a subsequent start-review
    returns it to UNDER_REVIEW.
    """
    ctx = setup_under_review_suggestion()
    deferred = validate_success(
        api.decide_suggestion(
            ctx["suggestion"]["id"],
            decide_suggestion_payload("DEFER"),
            LIBRARIAN_HEADERS,
        ),
        200,
    )
    assert deferred["status"] == "DEFERRED"

    resumed = validate_success(
        api.start_review_suggestion(ctx["suggestion"]["id"], None, LIBRARIAN_HEADERS),
        200,
    )
    assert resumed["status"] == "UNDER_REVIEW"


def test_acquire_with_duplicate_marc_rejected(api):
    """PRD §3.8: "An ACQUIRE decision creates the new BookTitle from the
    supplied block (subject to the same input validation as a direct
    cataloging — duplicate marc_control_number, wrong-length ISBN, or
    out-of-range publication_year all return ERR_INVALID_INPUT)".

    Claim: an ACQUIRE decision whose new_book_title carries a
    marc_control_number that already exists returns ERR_INVALID_INPUT (422).
    """
    from test_helpers import create_book_title

    existing = create_book_title()
    ctx = setup_under_review_suggestion(suggested_isbn="9780000000019")
    new_title_block = acquire_new_book_title_payload(
        "9780000000019",
        marc_control_number=existing["marc_control_number"],
    )
    res = api.decide_suggestion(
        ctx["suggestion"]["id"],
        decide_suggestion_payload("ACQUIRE", new_book_title=new_title_block),
        LIBRARIAN_HEADERS,
    )
    validate_error(res, "ERR_INVALID_INPUT", expected_status=422)
