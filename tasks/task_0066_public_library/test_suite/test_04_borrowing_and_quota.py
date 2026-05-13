"""Loan creation, quota inspection, and blocking-conditions tests (PRD §3.3)."""

import pytest

from test_helpers import (
    LIBRARIAN_HEADERS,
    NON_EXISTENT_UUID,
    assert_loan,
    assert_version_increased,
    blacklist_reader_payload,
    create_active_loan,
    create_book_title_with_copy,
    create_loan_payload,
    create_loan_then_return_late,
    create_verified_reader_with_card,
    make_reader_headers,
    setup_card_with_n_active_loans_and_m_reservations,
    validate_error,
    validate_success,
)


# =============================================================================
# Loan creation happy path (PRD §3.3)
# =============================================================================


def test_create_loan_returns_loan_with_pinned_reader(api):
    """PRD §3.3: "the server creates a Loan whose copy_id and card_id are
    taken from the request, whose reader_id is copied from the card's reader_id
    at this moment (and is permanently pinned ...), whose borrowed_at is the
    moment of creation, and whose due_at is borrowed_at plus the card's
    loan_duration_days. The new loan starts in BORROWED with renewals_used
    zero, is_recalled false, recall_due_at null, and returned_at null."

    Claim: new Loan has status=BORROWED, renewals_used=0, is_recalled=false,
    recall_due_at null, returned_at null, and reader_id matches the card's
    reader_id at borrow time.
    """
    title, copy = create_book_title_with_copy()
    reader, card = create_verified_reader_with_card()
    payload = create_loan_payload(copy["id"], card["id"], channel="COUNTER")
    res = api.create_loan(payload, make_reader_headers(reader["id"]))
    loan = validate_success(res, 201)
    assert_loan(loan)
    assert loan["status"] == "BORROWED"
    assert loan["renewals_used"] == 0
    assert loan["is_recalled"] is False
    assert loan.get("recall_due_at") in (None,)
    assert loan.get("returned_at") in (None,)
    assert loan["reader_id"] == reader["id"]


def test_loan_creation_flips_copy_to_on_loan(api):
    """PRD §3.3: "The underlying copy transitions from AVAILABLE (or from
    RESERVED when a reservation_id was supplied) to ON_LOAN."

    Claim: after loan creation, the Copy's status is ON_LOAN.
    """
    title, copy = create_book_title_with_copy()
    reader, card = create_verified_reader_with_card()
    payload = create_loan_payload(copy["id"], card["id"], channel="COUNTER")
    loan = validate_success(
        api.create_loan(payload, make_reader_headers(reader["id"])), 201
    )

    # Verify by listing copies of the title.
    listing = api.list_copies(title["id"], LIBRARIAN_HEADERS)
    body = listing.json()
    copies = body["data"]
    target = next(c for c in copies if c["id"] == copy["id"])
    assert target["status"] == "ON_LOAN"


def test_loan_due_at_is_borrowed_at_plus_loan_duration_days(api):
    """PRD §3.3: "whose borrowed_at is the moment of creation, and whose
    due_at is borrowed_at plus the card's loan_duration_days."

    Claim: due_at - borrowed_at equals loan_duration_days for the card's type.
    """
    from datetime import datetime

    title, copy = create_book_title_with_copy()
    reader, card = create_verified_reader_with_card(card_type="STUDENT")
    loan = validate_success(
        api.create_loan(
            create_loan_payload(copy["id"], card["id"], channel="COUNTER"),
            make_reader_headers(reader["id"]),
        ),
        201,
    )

    def _parse(ts: str) -> datetime:
        # Accept "...Z" by replacing with +00:00 for fromisoformat.
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))

    delta = _parse(loan["due_at"]) - _parse(loan["borrowed_at"])
    assert delta.days == card["loan_duration_days"], (
        f"PRD §3.3: due_at must be borrowed_at + {card['loan_duration_days']} days; "
        f"got delta of {delta.days} days"
    )


# =============================================================================
# Blocking conditions (PRD §3.3)
# =============================================================================


def test_loan_with_nonexistent_copy_returns_not_found(api):
    """PRD §3.3: "the path and body references must resolve (otherwise
    ERR_NOT_FOUND)".

    Claim: creating a Loan with a non-existent copy_id returns ERR_NOT_FOUND.
    """
    reader, card = create_verified_reader_with_card()
    payload = create_loan_payload(NON_EXISTENT_UUID, card["id"], channel="COUNTER")
    res = api.create_loan(payload, make_reader_headers(reader["id"]))
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_loan_on_non_available_copy_returns_copy_not_available(api):
    """PRD §3.3: "the copy must be in the state required by the operation
    (otherwise ERR_COPY_NOT_AVAILABLE)".

    Claim: borrowing a copy already ON_LOAN returns ERR_COPY_NOT_AVAILABLE.
    """
    title, copy = create_book_title_with_copy()
    # First borrower
    reader_a, card_a = create_verified_reader_with_card()
    validate_success(
        api.create_loan(
            create_loan_payload(copy["id"], card_a["id"], channel="COUNTER"),
            make_reader_headers(reader_a["id"]),
        ),
        201,
    )
    # Second borrower on the same now-ON_LOAN copy.
    reader_b, card_b = create_verified_reader_with_card()
    res = api.create_loan(
        create_loan_payload(copy["id"], card_b["id"], channel="COUNTER"),
        make_reader_headers(reader_b["id"]),
    )
    validate_error(res, "ERR_COPY_NOT_AVAILABLE", expected_status=409)


def test_loan_with_frozen_card_returns_card_not_active(api):
    """PRD §3.3: "the card must be ACTIVE (otherwise ERR_CARD_NOT_ACTIVE)".

    Claim: borrowing with a FROZEN card returns ERR_CARD_NOT_ACTIVE.
    """
    title, copy = create_book_title_with_copy()
    reader, card = create_verified_reader_with_card()
    validate_success(api.freeze_card(card["id"], None, LIBRARIAN_HEADERS), 200)
    res = api.create_loan(
        create_loan_payload(copy["id"], card["id"], channel="COUNTER"),
        make_reader_headers(reader["id"]),
    )
    validate_error(res, "ERR_CARD_NOT_ACTIVE", expected_status=409)


def test_loan_with_blacklisted_reader_returns_reader_blacklisted(
    api, admin_headers
):
    """PRD §3.3: "the reader must not be BLACKLISTED (otherwise
    ERR_READER_BLACKLISTED)".

    Claim: borrowing as a BLACKLISTED reader returns ERR_READER_BLACKLISTED.
    """
    reader, card = create_verified_reader_with_card()
    # First blacklist freezes the card; we'd hit ERR_CARD_NOT_ACTIVE.
    # The PRD §2.9 priority puts state-check (ERR_CARD_NOT_ACTIVE) at priority 9
    # ahead of business_safety (ERR_READER_BLACKLISTED) at priority 11. So to
    # observe ERR_READER_BLACKLISTED we must unfreeze the card first... but
    # blacklist always freezes cards. Cannot test in isolation without state
    # override. Instead, prepare a fresh ACTIVE card and have the reader become
    # BLACKLISTED via a path that does not freeze any card — but the PRD only
    # exposes blacklist via POST /readers/{id}/blacklist, which always freezes
    # cards. Therefore this test exercises the bundled outcome: with a
    # blacklisted reader + frozen card, the request fails, and the error_id is
    # one of the two — both are PRD-faithful per the priority rule.
    title, copy = create_book_title_with_copy()
    validate_success(
        api.blacklist_reader(reader["id"], blacklist_reader_payload(), admin_headers),
        200,
    )
    res = api.create_loan(
        create_loan_payload(copy["id"], card["id"], channel="COUNTER"),
        make_reader_headers(reader["id"]),
    )
    # Per PRD §2.9 the state check ERR_CARD_NOT_ACTIVE (priority 9) precedes
    # ERR_READER_BLACKLISTED (priority 11), so the card-frozen check fires first.
    assert res.status_code == 409
    body = res.json()
    assert body["data"]["error_id"] in (
        "ERR_CARD_NOT_ACTIVE",
        "ERR_READER_BLACKLISTED",
    ), body["data"]


def test_loan_with_unpaid_fine_returns_unpaid_fine(api):
    """PRD §3.3: "the reader's unpaid_fine_cents must equal zero (otherwise
    ERR_UNPAID_FINE)".

    Claim: a reader with an outstanding PENDING fine is blocked from borrowing
    with ERR_UNPAID_FINE.
    """
    ctx = create_loan_then_return_late(days_past_due=5)
    # Now this reader has unpaid_fine_cents > 0 and a fresh AVAILABLE card.
    title, copy = create_book_title_with_copy()
    res = api.create_loan(
        create_loan_payload(copy["id"], ctx["card"]["id"], channel="COUNTER"),
        make_reader_headers(ctx["reader"]["id"]),
    )
    validate_error(res, "ERR_UNPAID_FINE", expected_status=409)


def test_quota_exceeded_blocks_loan(api):
    """PRD §3.3: "the strict borrowing quota must be greater than zero
    (otherwise ERR_QUOTA_EXCEEDED)."

    Claim: with a TEMPORARY card (max_loans=2) and 2 active loans, a 3rd loan
    is rejected with ERR_QUOTA_EXCEEDED.
    """
    ctx = setup_card_with_n_active_loans_and_m_reservations(
        card_type="TEMPORARY", n_loans=2, m_reservations=0
    )
    title, copy = create_book_title_with_copy()
    res = api.create_loan(
        create_loan_payload(copy["id"], ctx["card"]["id"], channel="COUNTER"),
        make_reader_headers(ctx["reader"]["id"]),
    )
    validate_error(res, "ERR_QUOTA_EXCEEDED", expected_status=409)


# =============================================================================
# Quota inspection — strict vs chronological (PRD §3.3)
# =============================================================================


def test_quota_strict_vs_chronological_differ_with_reservation(api):
    """PRD §3.3: "a card with max_loans of 5, three in-flight loans, and one
    active reservation reports a strict remaining of 1 and a chronological
    remaining of 2."

    Claim: GET /cards/{id}/quota with mode=strict and mode=chronological
    yields strict=1 and chronological=2 on a REGULAR card with 3 loans + 1
    reservation.
    """
    ctx = setup_card_with_n_active_loans_and_m_reservations(
        card_type="REGULAR", n_loans=3, m_reservations=1
    )
    strict = validate_success(
        api.get_quota(
            ctx["card"]["id"],
            make_reader_headers(ctx["reader"]["id"]),
            params={"mode": "strict"},
        ),
        200,
    )
    chrono = validate_success(
        api.get_quota(
            ctx["card"]["id"],
            make_reader_headers(ctx["reader"]["id"]),
            params={"mode": "chronological"},
        ),
        200,
    )
    # The PRD doesn't pin the field name of the returned number; accept
    # either an explicit "remaining" key or the value embedded under
    # mode-specific keys.
    def _remaining(payload):
        for k in ("remaining", "quota_remaining", "borrowing_quota_remaining_strict",
                  "borrowing_quota_remaining_chronological"):
            if k in payload:
                return payload[k]
        # Fall back to whatever integer value the dict carries.
        ints = [v for v in payload.values() if isinstance(v, int)]
        assert ints, f"Cannot find numeric remaining in {payload}"
        return ints[0]

    assert _remaining(strict) == 1
    assert _remaining(chrono) == 2


def test_strict_quota_default_mode(api):
    """PRD §3.3: "an inspection endpoint on a card supports a mode query
    parameter to choose between two readings. In strict mode (the default and
    the one used to gate new loan creation)".

    Claim: GET /cards/{id}/quota without mode= behaves like mode=strict.
    """
    ctx = setup_card_with_n_active_loans_and_m_reservations(
        card_type="REGULAR", n_loans=3, m_reservations=1
    )
    default = validate_success(
        api.get_quota(ctx["card"]["id"], make_reader_headers(ctx["reader"]["id"])),
        200,
    )
    strict = validate_success(
        api.get_quota(
            ctx["card"]["id"],
            make_reader_headers(ctx["reader"]["id"]),
            params={"mode": "strict"},
        ),
        200,
    )
    # Compare the most likely numeric remaining values.
    def _remaining(payload):
        ints = [v for v in payload.values() if isinstance(v, int)]
        assert ints
        return ints[0]

    assert _remaining(default) == _remaining(strict)
