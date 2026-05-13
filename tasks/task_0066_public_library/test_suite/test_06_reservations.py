"""Reservation creation, queueing, promotion, hold-expiry, cancellation tests (PRD §3.5)."""

import pytest

from test_helpers import (
    LIBRARIAN_HEADERS,
    NON_EXISTENT_UUID,
    advance_clock_days,
    assert_reservation,
    create_active_loan,
    create_book_title_with_copy,
    create_loan_payload,
    create_loan_with_pending_reservation,
    create_reservation_payload,
    create_verified_reader_with_card,
    make_reader_headers,
    setup_ready_for_pickup_reservation,
    validate_error,
    validate_success,
)


# =============================================================================
# Reservation creation & queueing (PRD §3.5)
# =============================================================================


def test_reservation_with_no_available_copy_starts_queued(api):
    """PRD §3.5: "The reservation enters QUEUED with held_copy_id null and
    hold_expires_at null."

    Claim: when no copy is AVAILABLE, the reservation enters QUEUED with
    held_copy_id null and hold_expires_at null.
    """
    ctx = create_loan_with_pending_reservation()
    assert_reservation(ctx["reservation"])
    assert ctx["reservation"]["status"] == "QUEUED"
    assert ctx["reservation"].get("held_copy_id") in (None,)
    assert ctx["reservation"].get("hold_expires_at") in (None,)


def test_reservation_with_available_copy_auto_promotes(api):
    """PRD §3.5: "When a copy of the title is available at the moment of
    submission and this new reservation lands at the head of the queue, the
    cascade fires immediately: the head reservation jumps from QUEUED to
    READY_FOR_PICKUP".

    Claim: when one AVAILABLE copy exists and the queue is empty, a new
    reservation is immediately READY_FOR_PICKUP with held_copy_id set.
    """
    title, copy = create_book_title_with_copy()
    reader, card = create_verified_reader_with_card()
    res = api.create_reservation(
        create_reservation_payload(title["id"], card["id"], channel="ONLINE"),
        make_reader_headers(reader["id"]),
    )
    reservation = validate_success(res, 201)
    assert_reservation(reservation)
    assert reservation["status"] == "READY_FOR_PICKUP"
    assert reservation["held_copy_id"] == copy["id"]
    assert reservation["hold_expires_at"] is not None


def test_reservation_queue_position_is_one_indexed_and_sequential(api):
    """PRD §3.5: "assigning the new reservation a 1-indexed position one past
    the last existing position."

    Claim: with one copy ON_LOAN and three reservations submitted in order,
    queue_position is 1, 2, 3.
    """
    title, copy = create_book_title_with_copy()
    # Make the copy unavailable so new reservations stay QUEUED.
    borrower, borrower_card = create_verified_reader_with_card()
    validate_success(
        api.create_loan(
            create_loan_payload(copy["id"], borrower_card["id"], channel="COUNTER"),
            make_reader_headers(borrower["id"]),
        ),
        201,
    )
    positions = []
    for _ in range(3):
        r, c = create_verified_reader_with_card()
        rv = validate_success(
            api.create_reservation(
                create_reservation_payload(title["id"], c["id"]),
                make_reader_headers(r["id"]),
            ),
            201,
        )
        positions.append(rv["queue_position"])
    assert positions == [1, 2, 3]


def test_duplicate_active_reservation_rejected(api):
    """PRD §3.5: "if the reader already has a Reservation for that title in
    QUEUED or READY_FOR_PICKUP, or a Loan for any copy of that title in
    BORROWED, RENEWED, or RECALL_PENDING, the request is rejected with
    ERR_DUPLICATE_RESERVATION."

    Claim: a reader cannot file two QUEUED reservations on the same title.
    """
    ctx = create_loan_with_pending_reservation()
    # reader_b already has a QUEUED reservation on this title.
    res = api.create_reservation(
        create_reservation_payload(ctx["title"]["id"], ctx["card_b"]["id"]),
        make_reader_headers(ctx["reader_b"]["id"]),
    )
    validate_error(res, "ERR_DUPLICATE_RESERVATION", expected_status=409)


def test_reservation_with_frozen_card_rejected(api):
    """PRD §3.5: "The acting card must be ACTIVE, otherwise the request is
    rejected with ERR_CARD_NOT_ACTIVE."

    Claim: filing a reservation with a FROZEN card returns
    ERR_CARD_NOT_ACTIVE.
    """
    title, copy = create_book_title_with_copy()
    reader, card = create_verified_reader_with_card()
    validate_success(api.freeze_card(card["id"], None, LIBRARIAN_HEADERS), 200)
    res = api.create_reservation(
        create_reservation_payload(title["id"], card["id"]),
        make_reader_headers(reader["id"]),
    )
    validate_error(res, "ERR_CARD_NOT_ACTIVE", expected_status=409)


def test_reservation_against_nonexistent_book_title(api):
    """PRD §2.6: "Foreign keys referenced in request bodies (copy_id, card_id,
    reservation_id, book_title_id) are validated the same way: an unresolvable
    id surfaces as ERR_NOT_FOUND."

    Claim: a reservation against a non-existent book_title_id returns 404.
    """
    reader, card = create_verified_reader_with_card()
    res = api.create_reservation(
        create_reservation_payload(NON_EXISTENT_UUID, card["id"]),
        make_reader_headers(reader["id"]),
    )
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


# =============================================================================
# Promotion on loan return (PRD §3.4 / §3.5 cascade)
# =============================================================================


def test_loan_return_promotes_queue_head(api):
    """PRD §3.5: "The same QUEUED → READY_FOR_PICKUP cascade also fires when
    a loan is returned and a queue head was waiting".

    Claim: returning the only loan promotes the queue head to READY_FOR_PICKUP
    and sets the Copy.status to RESERVED.
    """
    ctx = setup_ready_for_pickup_reservation()
    assert ctx["reservation"]["status"] == "READY_FOR_PICKUP"
    assert ctx["reservation"]["held_copy_id"] == ctx["copy"]["id"]

    listing = api.list_copies(ctx["title"]["id"], LIBRARIAN_HEADERS)
    target = next(c for c in listing.json()["data"] if c["id"] == ctx["copy"]["id"])
    assert target["status"] == "RESERVED", (
        "PRD §3.4: copy is promoted directly to RESERVED instead of AVAILABLE "
        "when a reservation queue head was waiting"
    )


# =============================================================================
# Pickup via reservation_id (PRD §3.3, §3.5)
# =============================================================================


def test_pickup_within_hold_succeeds_and_fulfills(api):
    """PRD §3.3: "When the request includes a reservation_id the reservation
    must currently be in READY_FOR_PICKUP with hold_expires_at strictly later
    than the simulated now()".
    PRD §3.3: "The reservation, if any, transitions to the terminal FULFILLED
    state."

    Claim: borrowing with reservation_id before hold_expires_at creates the
    loan AND moves the reservation to FULFILLED.
    """
    ctx = setup_ready_for_pickup_reservation()
    loan = validate_success(
        api.create_loan(
            create_loan_payload(
                ctx["copy"]["id"],
                ctx["card_b"]["id"],
                channel="COUNTER",
                reservation_id=ctx["reservation"]["id"],
            ),
            make_reader_headers(ctx["reader_b"]["id"]),
        ),
        201,
    )
    assert loan["status"] == "BORROWED"
    reservation = validate_success(
        api.get_reservation(
            ctx["reservation"]["id"], make_reader_headers(ctx["reader_b"]["id"])
        ),
        200,
    )
    assert reservation["status"] == "FULFILLED"


def test_pickup_after_hold_expires_returns_hold_expired(api):
    """PRD §3.3: "if the hold deadline has already been reached the operation
    is rejected with ERR_HOLD_EXPIRED."
    PRD §3.5: "the hold period of two days".

    Claim: advancing the clock past the 2-day hold period and then attempting
    pickup returns ERR_HOLD_EXPIRED.
    """
    ctx = setup_ready_for_pickup_reservation()
    # Advance well past the 2-day hold window (PRD §3.5).
    advance_clock_days(3)
    res = api.create_loan(
        create_loan_payload(
            ctx["copy"]["id"],
            ctx["card_b"]["id"],
            channel="COUNTER",
            reservation_id=ctx["reservation"]["id"],
        ),
        make_reader_headers(ctx["reader_b"]["id"]),
    )
    validate_error(res, "ERR_HOLD_EXPIRED", expected_status=409)


# =============================================================================
# Cancellation (PRD §3.5)
# =============================================================================


def test_cancel_queued_reservation_terminal(api):
    """PRD §3.5: "Cancellation of a QUEUED reservation moves it to the
    terminal CANCELLED state".

    Claim: DELETE on a QUEUED reservation sets status=CANCELLED.
    """
    ctx = create_loan_with_pending_reservation()
    res = api.cancel_reservation(
        ctx["reservation"]["id"], None, make_reader_headers(ctx["reader_b"]["id"])
    )
    cancelled = validate_success(res, 200)
    assert cancelled["status"] == "CANCELLED"


def test_cancel_ready_for_pickup_releases_copy(api):
    """PRD §3.5: "Cancellation of a READY_FOR_PICKUP reservation moves it to
    CANCELLED and releases the held copy back into circulation".

    Claim: cancelling a READY_FOR_PICKUP reservation moves status=CANCELLED
    and the Copy returns to AVAILABLE.
    """
    ctx = setup_ready_for_pickup_reservation()
    res = api.cancel_reservation(
        ctx["reservation"]["id"], None, make_reader_headers(ctx["reader_b"]["id"])
    )
    cancelled = validate_success(res, 200)
    assert cancelled["status"] == "CANCELLED"
    listing = api.list_copies(ctx["title"]["id"], LIBRARIAN_HEADERS)
    target = next(c for c in listing.json()["data"] if c["id"] == ctx["copy"]["id"])
    assert target["status"] == "AVAILABLE"
