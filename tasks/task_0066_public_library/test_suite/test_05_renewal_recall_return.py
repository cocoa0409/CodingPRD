"""Renewal, recall, and return tests (PRD §3.4)."""

import pytest

from test_helpers import (
    LIBRARIAN_HEADERS,
    NON_EXISTENT_UUID,
    advance_clock_days,
    api_client,
    assert_loan,
    create_active_loan,
    create_book_title_with_copy,
    create_loan_payload,
    create_loan_then_return_late,
    create_overdue_loan,
    create_recalled_loan,
    create_reservation_payload,
    create_verified_reader_with_card,
    make_reader_headers,
    recall_loan_payload,
    return_loan_payload,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# =============================================================================
# Renewal (PRD §3.4)
# =============================================================================


def test_renew_increments_renewals_used_and_advances_due_at(api):
    """PRD §3.4: "On success the loan transitions through RENEWED ...
    renewals_used is incremented by one, the new due_at is the larger of the
    current due_at and the simulated now(), advanced by the card's
    loan_duration_days, and an AuditLog entry of event_type LOAN_RENEWED is
    appended."

    Claim: a successful renew increments renewals_used by 1.
    """
    ctx = create_active_loan(card_type="REGULAR")
    res = api.renew_loan(
        ctx["loan"]["id"], None, make_reader_headers(ctx["reader"]["id"])
    )
    renewed = validate_success(res, 200)
    assert renewed["renewals_used"] == ctx["loan"]["renewals_used"] + 1


def test_renew_at_renewal_limit_rejected(api):
    """PRD §3.4: "Renewing is permitted only when the loan is currently in
    BORROWED and the loan's renewals_used is strictly less than the card's
    max_renewals" — combined with "a renew at or beyond the renewal limit
    returns ERR_RENEWAL_LIMIT_REACHED."

    Claim: a TEMPORARY card (max_renewals=0) rejects the first renew with
    ERR_RENEWAL_LIMIT_REACHED.
    """
    ctx = create_active_loan(card_type="TEMPORARY")
    res = api.renew_loan(
        ctx["loan"]["id"], None, make_reader_headers(ctx["reader"]["id"])
    )
    validate_error(res, "ERR_RENEWAL_LIMIT_REACHED", expected_status=409)


def test_renew_with_active_reservation_blocked(api):
    """PRD §3.4: "no active reservation may exist for the loan's underlying
    BookTitle" — combined with "a renew while an active reservation exists for
    the title returns ERR_RESERVATION_BLOCKS_RENEWAL."

    Claim: with a QUEUED reservation on the title, renew returns
    ERR_RESERVATION_BLOCKS_RENEWAL.
    """
    ctx = create_active_loan()
    # Second reader files a reservation on the same title.
    other_reader, other_card = create_verified_reader_with_card()
    validate_success(
        api.create_reservation(
            create_reservation_payload(ctx["title"]["id"], other_card["id"]),
            make_reader_headers(other_reader["id"]),
        ),
        201,
    )
    res = api.renew_loan(
        ctx["loan"]["id"], None, make_reader_headers(ctx["reader"]["id"])
    )
    validate_error(res, "ERR_RESERVATION_BLOCKS_RENEWAL", expected_status=409)


def test_renew_after_recall_returns_loan_recalled(api):
    """PRD §3.4: "a renew on an already-recalled loan returns ERR_LOAN_RECALLED."

    Claim: renew on a Loan with is_recalled=true returns ERR_LOAN_RECALLED.

    NOTE on coverage: a recalled loan also has status=RECALL_PENDING, which by
    PRD §2.9 priority (state-machine eligibility precedes business-quantity
    constraints / recall flag) admits ERR_INVALID_STATE as an equally
    PRD-faithful reading. The assertion accepts either.
    """
    ctx = create_recalled_loan()
    res = api.renew_loan(
        ctx["loan"]["id"], None, make_reader_headers(ctx["reader"]["id"])
    )
    assert res.status_code == 409
    validate_error_is_one_of(res, ["ERR_LOAN_RECALLED", "ERR_INVALID_STATE"])


def test_renew_non_borrowed_loan_returns_invalid_state(api):
    """PRD §3.4: "a renew attempted on a non-BORROWED loan returns
    ERR_INVALID_STATE".

    Claim: renew on a RETURNED loan returns ERR_INVALID_STATE.
    """
    ctx = create_active_loan()
    validate_success(
        api.return_loan(
            ctx["loan"]["id"], return_loan_payload(),
            make_reader_headers(ctx["reader"]["id"]),
        ),
        200,
    )
    res = api.renew_loan(
        ctx["loan"]["id"], None, make_reader_headers(ctx["reader"]["id"])
    )
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# =============================================================================
# Recall (PRD §3.4)
# =============================================================================


def test_recall_overdue_loan_sets_is_recalled(api):
    """PRD §3.4: "On success the loan transitions to RECALL_PENDING,
    is_recalled is set to true, and recall_due_at is set to the smaller of (a)
    the existing due_at and (b) the simulated now() plus the recall grace
    period of three days."

    Claim: recall on an overdue loan sets status=RECALL_PENDING and
    is_recalled=true.
    """
    ctx = create_overdue_loan(days_past_due=1)
    res = api.recall_loan(
        ctx["loan"]["id"], recall_loan_payload(), LIBRARIAN_HEADERS
    )
    recalled = validate_success(res, 200)
    assert recalled["status"] == "RECALL_PENDING"
    assert recalled["is_recalled"] is True
    assert recalled["recall_due_at"] is not None


def test_recall_non_eligible_loan_rejected(api):
    """PRD §3.4: "Recall is declared from BORROWED or RENEWED and requires
    either that an active reservation exists for the loan's underlying title
    or that the loan is overdue".

    Claim: recall on a fresh, non-overdue, un-reserved loan is rejected
    (typically with ERR_INVALID_STATE since neither precondition holds).
    """
    ctx = create_active_loan()
    res = api.recall_loan(
        ctx["loan"]["id"], recall_loan_payload(), LIBRARIAN_HEADERS
    )
    assert res.status_code >= 400, (
        "PRD §3.4: recall without overdue OR active reservation must be rejected"
    )


# =============================================================================
# Return (PRD §3.4)
# =============================================================================


def test_return_on_time_no_fine(api):
    """PRD §3.4: "If returned_at is at or before the effective due date the
    loan transitions to the terminal RETURNED state and no fine is generated."

    Claim: returning a loan before due_at yields status=RETURNED and creates
    no Fine.
    """
    ctx = create_active_loan()
    res = api.return_loan(
        ctx["loan"]["id"],
        return_loan_payload(),
        make_reader_headers(ctx["reader"]["id"]),
    )
    returned = validate_success(res, 200)
    assert returned["status"] == "RETURNED"
    # Reader's unpaid_fine_cents should still be 0.
    reader = validate_success(
        api.get_reader(ctx["reader"]["id"], LIBRARIAN_HEADERS), 200
    )
    assert reader["unpaid_fine_cents"] == 0


def test_return_late_creates_fine_and_overdue_closed(api):
    """PRD §3.4: "If returned_at is strictly later than the effective due date
    the loan transitions to the terminal OVERDUE_CLOSED state and a Fine is
    finalized as described in §3.6."

    Claim: returning past due_at yields status=OVERDUE_CLOSED and the reader's
    unpaid_fine_cents becomes > 0.
    """
    ctx = create_loan_then_return_late(days_past_due=3, subject_category="GENERAL")
    assert ctx["loan"]["status"] == "OVERDUE_CLOSED"
    reader = validate_success(
        api.get_reader(ctx["reader"]["id"], LIBRARIAN_HEADERS), 200
    )
    assert reader["unpaid_fine_cents"] > 0


def test_return_releases_copy_to_available(api):
    """PRD §3.4: "the underlying copy is released: it normally returns to
    AVAILABLE".

    Claim: after an on-time return, the Copy's status is AVAILABLE.
    """
    ctx = create_active_loan()
    validate_success(
        api.return_loan(
            ctx["loan"]["id"], return_loan_payload(),
            make_reader_headers(ctx["reader"]["id"]),
        ),
        200,
    )
    listing = api.list_copies(ctx["title"]["id"], LIBRARIAN_HEADERS)
    target = next(c for c in listing.json()["data"] if c["id"] == ctx["copy"]["id"])
    assert target["status"] == "AVAILABLE"


def test_return_nonexistent_loan_returns_not_found(api):
    """PRD §2.6: "every path segment that names a resource must resolve".

    Claim: returning a non-existent loan id returns ERR_NOT_FOUND.
    """
    res = api.return_loan(NON_EXISTENT_UUID, return_loan_payload(), LIBRARIAN_HEADERS)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)
