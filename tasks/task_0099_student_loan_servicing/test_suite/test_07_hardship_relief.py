"""Hardship request lifecycle: submission validations, deferment vs
forbearance state transitions, PLUS in-school exclusion, 36-month
forbearance cap.

Anchors: PRD §3.5.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    TEST_DEFAULTS,
    TEST_USERS,
    advance_clock_by_days,
    api_client,
    approve_hardship_request,
    create_borrower_with_loan_in_repayment,
    create_hardship_request_payload,
    make_borrower_headers,
    reset_clock_to,
    submit_hardship_request,
    update_hardship_request_payload,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import _fmt_iso, _parse_iso  # type: ignore


# ---------------------------------------------------------------------------
# 1. Submission validation (PRD §3.5)
# ---------------------------------------------------------------------------
def test_submit_hardship_request_basic_success(api):
    """PRD §3.5: "The submission payload carries kind ... the
    requested window's requested_from and requested_to timestamps,
    and the applied_loan_ids array".

    Claim: a valid submission returns status=SUBMITTED.
    """
    borrower, loan, current = create_borrower_with_loan_in_repayment()
    requested_from = current
    requested_to = _fmt_iso(_parse_iso(current) + timedelta(days=90))
    req = submit_hardship_request(
        borrower["id"], "FORBEARANCE_GENERAL",
        requested_from=requested_from, requested_to=requested_to,
        applied_loan_ids=[loan["id"]],
    )
    assert req["status"] == "SUBMITTED"


def test_submit_with_end_not_after_start_rejected(api):
    """PRD §3.5: "Submission is rejected with ERR_BAD_DATE_WINDOW if
    requested_to is not strictly after requested_from".

    Claim: requested_to <= requested_from → ERR_BAD_DATE_WINDOW.
    """
    borrower, loan, current = create_borrower_with_loan_in_repayment()
    res = api.create_hardship_request(
        borrower["id"],
        create_hardship_request_payload(
            "FORBEARANCE_GENERAL",
            requested_from=current,
            requested_to=current,    # same instant
            applied_loan_ids=[loan["id"]],
        ),
        TEST_USERS["servicer_admin_headers"],
    )
    validate_error(res, "ERR_BAD_DATE_WINDOW")


def test_submit_with_past_requested_from_rejected(api):
    """PRD §3.5: "or if requested_from is in the past relative to
    now."

    Claim: requested_from < now → ERR_BAD_DATE_WINDOW.
    """
    borrower, loan, current = create_borrower_with_loan_in_repayment()
    past_from = _fmt_iso(_parse_iso(current) - timedelta(days=30))
    future_to = _fmt_iso(_parse_iso(current) + timedelta(days=30))
    res = api.create_hardship_request(
        borrower["id"],
        create_hardship_request_payload(
            "FORBEARANCE_GENERAL",
            requested_from=past_from, requested_to=future_to,
            applied_loan_ids=[loan["id"]],
        ),
        TEST_USERS["servicer_admin_headers"],
    )
    validate_error(res, "ERR_BAD_DATE_WINDOW")


# ---------------------------------------------------------------------------
# 2. Approval transitions (PRD §3.5)
# ---------------------------------------------------------------------------
def test_approve_deferment_moves_loan_to_deferment(api):
    """PRD §3.5: "From REPAYMENT, a DEFERMENT_* approval moves the
    loan to DEFERMENT".

    Claim: approving a DEFERMENT_UNEMPLOYMENT request transitions
    the loan REPAYMENT → DEFERMENT.
    """
    borrower, loan, current = create_borrower_with_loan_in_repayment()
    req_from = current
    req_to = _fmt_iso(_parse_iso(current) + timedelta(days=180))
    req = submit_hardship_request(
        borrower["id"], "DEFERMENT_UNEMPLOYMENT",
        requested_from=req_from, requested_to=req_to,
        applied_loan_ids=[loan["id"]],
    )
    approve_hardship_request(borrower["id"], req["id"])
    fetched = validate_success(
        api.get_loan(borrower["id"], loan["id"],
                     TEST_USERS["servicer_admin_headers"]),
        200,
    )
    assert fetched["status"] == "DEFERMENT", (
        "PRD §3.5: approved DEFERMENT_* must move REPAYMENT loan to DEFERMENT"
    )


def test_approve_forbearance_moves_loan_to_forbearance(api):
    """PRD §3.5: "a FORBEARANCE_* approval moves it to FORBEARANCE".

    Claim: approving FORBEARANCE_GENERAL transitions REPAYMENT →
    FORBEARANCE.
    """
    borrower, loan, current = create_borrower_with_loan_in_repayment()
    req_from = current
    req_to = _fmt_iso(_parse_iso(current) + timedelta(days=90))
    req = submit_hardship_request(
        borrower["id"], "FORBEARANCE_GENERAL",
        requested_from=req_from, requested_to=req_to,
        applied_loan_ids=[loan["id"]],
    )
    approve_hardship_request(borrower["id"], req["id"])
    fetched = validate_success(
        api.get_loan(borrower["id"], loan["id"],
                     TEST_USERS["servicer_admin_headers"]),
        200,
    )
    assert fetched["status"] == "FORBEARANCE"


def test_in_school_deferment_on_plus_loan_rejected(api):
    """PRD §3.5: "if kind is DEFERMENT_IN_SCHOOL and any applied loan
    is DIRECT_PLUS, the approval is rejected with
    ERR_PLUS_INELIGIBLE_FOR_IN_SCHOOL because in-school deferment
    is statutorily restricted to subsidized and unsubsidized direct
    loans".

    Claim: DEFERMENT_IN_SCHOOL approval on a PLUS loan →
    ERR_PLUS_INELIGIBLE_FOR_IN_SCHOOL.
    """
    borrower, loan, current = create_borrower_with_loan_in_repayment(
        loan_type="DIRECT_PLUS",
    )
    req_from = current
    req_to = _fmt_iso(_parse_iso(current) + timedelta(days=90))
    req = submit_hardship_request(
        borrower["id"], "DEFERMENT_IN_SCHOOL",
        requested_from=req_from, requested_to=req_to,
        applied_loan_ids=[loan["id"]],
    )
    res = api.update_hardship_request(
        borrower["id"], req["id"],
        update_hardship_request_payload(status="APPROVED"),
        TEST_USERS["servicer_certifier_headers"],
    )
    validate_error(res, "ERR_PLUS_INELIGIBLE_FOR_IN_SCHOOL")


# ---------------------------------------------------------------------------
# 3. Forbearance 36-month cap (PRD §3.5)
# ---------------------------------------------------------------------------
def test_forbearance_general_cap_exceeded(api):
    """PRD §3.5: "if kind is FORBEARANCE_GENERAL, the borrower's
    lifetime cumulative general-forbearance days plus the number of
    days in the requested window must be at most 1095 (that is,
    three years total across the borrower's lifetime), with
    violation reported as ERR_FORBEARANCE_CAP_EXCEEDED."

    Claim: first approve a 1000-day FORBEARANCE_GENERAL, then try a
    100-day one; 1000+100=1100 > 1095 → ERR_FORBEARANCE_CAP_EXCEEDED.
    """
    reset_clock_to(TEST_DEFAULTS["INITIAL_CLOCK"])
    borrower, loan, current = create_borrower_with_loan_in_repayment()
    # First request: 1000 days, approve.
    first_from = current
    first_to = _fmt_iso(_parse_iso(current) + timedelta(days=1000))
    first_req = submit_hardship_request(
        borrower["id"], "FORBEARANCE_GENERAL",
        requested_from=first_from, requested_to=first_to,
        applied_loan_ids=[loan["id"]],
    )
    approve_hardship_request(borrower["id"], first_req["id"])
    # Advance clock past first window so loan exits to REPAYMENT.
    new_now = advance_clock_by_days(1005, from_stamp=current)
    # Second request: 100 days, should fail because 1000+100 > 1095.
    second_from = new_now
    second_to = _fmt_iso(_parse_iso(new_now) + timedelta(days=100))
    second_req = submit_hardship_request(
        borrower["id"], "FORBEARANCE_GENERAL",
        requested_from=second_from, requested_to=second_to,
        applied_loan_ids=[loan["id"]],
    )
    res = api.update_hardship_request(
        borrower["id"], second_req["id"],
        update_hardship_request_payload(status="APPROVED"),
        TEST_USERS["servicer_certifier_headers"],
    )
    validate_error(res, "ERR_FORBEARANCE_CAP_EXCEEDED")


# ---------------------------------------------------------------------------
# 4. Cancellation (PRD §3.5)
# ---------------------------------------------------------------------------
def test_borrower_cancels_pending_request(api):
    """PRD §3.5: "the borrower themselves may cancel a request that
    is still in SUBMITTED to move it to CANCELLED."

    Claim: DELETE on SUBMITTED hardship request moves status to
    CANCELLED.
    """
    borrower, loan, current = create_borrower_with_loan_in_repayment()
    req_from = current
    req_to = _fmt_iso(_parse_iso(current) + timedelta(days=30))
    req = submit_hardship_request(
        borrower["id"], "FORBEARANCE_GENERAL",
        requested_from=req_from, requested_to=req_to,
        applied_loan_ids=[loan["id"]],
        use_borrower_role=True,
    )
    res = api.cancel_hardship_request(
        borrower["id"], req["id"],
        make_borrower_headers(borrower["id"]),
    )
    cancelled = validate_success(res, 200)
    assert cancelled["status"] == "CANCELLED"


def test_rejection_records_reason(api):
    """PRD §3.5: "rejection by the same role moves it to REJECTED
    with a rejection_reason".

    Claim: PATCH status=REJECTED with rejection_reason returns the
    request in REJECTED state with the reason persisted.
    """
    borrower, loan, current = create_borrower_with_loan_in_repayment()
    req_from = current
    req_to = _fmt_iso(_parse_iso(current) + timedelta(days=30))
    req = submit_hardship_request(
        borrower["id"], "FORBEARANCE_GENERAL",
        requested_from=req_from, requested_to=req_to,
        applied_loan_ids=[loan["id"]],
    )
    res = api.update_hardship_request(
        borrower["id"], req["id"],
        {"status": "REJECTED", "rejection_reason": "insufficient hardship"},
        TEST_USERS["servicer_certifier_headers"],
    )
    rejected = validate_success(res, 200)
    assert rejected["status"] == "REJECTED"
    assert rejected.get("rejection_reason") == "insufficient hardship"
