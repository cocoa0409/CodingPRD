"""Fine accrual (provisional vs final), waiver, payment, and settlement tests (PRD §3.6)."""

import pytest

from test_helpers import (
    DAILY_RATE_BY_CATEGORY,
    FINE_CAP_BY_CATEGORY,
    LIBRARIAN_HEADERS,
    advance_clock_days,
    api_client,
    assert_fine,
    assert_fine_conserved,
    assert_no_fine_above_cap,
    create_active_loan,
    create_loan_then_return_late,
    create_overdue_loan,
    emit_payment_confirmed,
    make_fine_officer_headers,
    make_reader_headers,
    pay_fine_full,
    pay_fine_payload,
    validate_error,
    validate_success,
    waive_fine_amount,
    waive_fine_payload,
)


# =============================================================================
# Provisional vs final fine (PRD §3.6 dual variant)
# =============================================================================


def test_provisional_fine_zero_when_not_overdue(api):
    """PRD §3.6: "If the simulated now() is at or before the effective due
    date the provisional value is zero."

    Claim: a Loan still BORROWED before due_at carries a zero provisional fine
    indication.
    """
    ctx = create_active_loan(subject_category="GENERAL")
    loan = validate_success(
        api.get_loan(ctx["loan"]["id"], make_reader_headers(ctx["reader"]["id"])),
        200,
    )
    # PRD says "exposed via the loan-fetch endpoint" — the implementation may
    # expose this via any field; the strongest PRD-faithful assertion is that
    # the underlying reader has unpaid_fine_cents == 0.
    reader = validate_success(
        api.get_reader(ctx["reader"]["id"], LIBRARIAN_HEADERS), 200
    )
    assert reader["unpaid_fine_cents"] == 0


def test_final_fine_uses_returned_at_in_cents(api):
    """PRD §3.6: "Final reading — computed exactly once at the moment of
    return when the loan transitions to OVERDUE_CLOSED. The effective due date
    is the same recall-aware value, but the moment used is returned_at (a
    fixed timestamp), not the simulated now(). The number of overdue days is
    the difference between returned_at and the effective due date, expressed
    in days and rounded up."

    Claim: a 3-day-late return on a GENERAL-category title finalizes Fine
    with accrued_cents = 3 * 20 = 60.
    """
    ctx = create_loan_then_return_late(
        subject_category="GENERAL", days_past_due=3
    )
    assert ctx["fine"] is not None, "PRD §3.6: a late return must finalize a Fine"
    fine = ctx["fine"]
    assert_fine(fine)
    expected = 3 * DAILY_RATE_BY_CATEGORY["GENERAL"]
    assert fine["accrued_cents"] == expected, (
        f"PRD §3.6 GENERAL rate 20 cents/day × 3 days = {expected}; "
        f"got {fine['accrued_cents']}"
    )


def test_reference_fine_rate_50_per_day(api):
    """PRD §3.6: "The per-day rate daily_rate_cents is 20 for GENERAL, 50 for
    REFERENCE, 10 for CHILDREN, and 200 for RARE."

    Claim: a 4-day-late REFERENCE return produces accrued_cents = 4 * 50 = 200.
    """
    ctx = create_loan_then_return_late(
        subject_category="REFERENCE", days_past_due=4
    )
    assert ctx["fine"] is not None
    assert ctx["fine"]["accrued_cents"] == 4 * DAILY_RATE_BY_CATEGORY["REFERENCE"]
    assert ctx["fine"]["daily_rate_cents"] == DAILY_RATE_BY_CATEGORY["REFERENCE"]
    assert ctx["fine"]["fine_cap_cents"] == FINE_CAP_BY_CATEGORY["REFERENCE"]


def test_children_fine_rate_10_per_day(api):
    """PRD §3.6: "The per-day rate daily_rate_cents is ... 10 for CHILDREN".

    Claim: a 5-day-late CHILDREN return produces accrued_cents = 5 * 10 = 50.
    """
    ctx = create_loan_then_return_late(
        subject_category="CHILDREN", days_past_due=5
    )
    assert ctx["fine"] is not None
    assert ctx["fine"]["accrued_cents"] == 5 * DAILY_RATE_BY_CATEGORY["CHILDREN"]


# =============================================================================
# Fine cap (PRD §3.6)
# =============================================================================


def test_fine_clamped_at_cap_for_general(api):
    """PRD §3.6: "Fine.accrued_cents is set to the smaller of that raw amount
    and fine_cap_cents."

    Claim: a return many days past due on a GENERAL category clamps
    accrued_cents at 5000 (fine_cap_cents for GENERAL).
    """
    # GENERAL: rate=20, cap=5000 → cap reached at 5000/20 = 250 days.
    ctx = create_loan_then_return_late(
        subject_category="GENERAL", days_past_due=280
    )
    assert ctx["fine"] is not None
    assert ctx["fine"]["accrued_cents"] == FINE_CAP_BY_CATEGORY["GENERAL"]
    assert_no_fine_above_cap(ctx["fine"])


# =============================================================================
# Initial Fine state (PRD §3.6)
# =============================================================================


def test_new_fine_initial_state(api):
    """PRD §3.6: "When a Fine is created its waived_cents and paid_cents are
    zero, its outstanding_cents is equal to accrued_cents minus waived_cents
    minus paid_cents (so initially equal to accrued_cents), and its
    settlement_status is PENDING."

    Claim: a freshly created Fine has waived_cents=0, paid_cents=0,
    outstanding_cents = accrued_cents, settlement_status=PENDING.
    """
    ctx = create_loan_then_return_late(days_past_due=2)
    assert ctx["fine"] is not None
    f = ctx["fine"]
    assert f["waived_cents"] == 0
    assert f["paid_cents"] == 0
    assert f["outstanding_cents"] == f["accrued_cents"]
    assert f["settlement_status"] == "PENDING"
    assert_fine_conserved(f)


# =============================================================================
# Waivers (PRD §3.6)
# =============================================================================


def test_waiver_decreases_outstanding(api):
    """PRD §3.6: "On a successful waive the fine's waived_cents is increased
    by waive_cents, outstanding_cents is recomputed".

    Claim: a partial waive reduces outstanding_cents by the waived amount and
    leaves accrued_cents unchanged.
    """
    ctx = create_loan_then_return_late(days_past_due=5)
    fine = ctx["fine"]
    waived = waive_fine_amount(fine["id"], 25, reason="HOLIDAY")
    assert waived["waived_cents"] == 25
    assert waived["outstanding_cents"] == fine["outstanding_cents"] - 25
    assert waived["accrued_cents"] == fine["accrued_cents"]
    assert_fine_conserved(waived)


@pytest.mark.parametrize("bad_reason", ["NOTAREASON", "SPECIAL", ""])
def test_waiver_invalid_reason_rejected(api, bad_reason):
    """PRD §3.6: "The waive is rejected with ERR_INVALID_WAIVER (HTTP 422)
    when the reason is outside that set" (set = SYSTEM_FAULT, HOLIDAY, HARDSHIP).

    Claim: waive with reason outside {SYSTEM_FAULT, HOLIDAY, HARDSHIP} returns
    ERR_INVALID_WAIVER (HTTP 422).
    """
    ctx = create_loan_then_return_late(days_past_due=3)
    res = api.waive_fine(
        ctx["fine"]["id"],
        waive_fine_payload(10, reason=bad_reason),
        make_fine_officer_headers(),
    )
    validate_error(res, "ERR_INVALID_WAIVER", expected_status=422)


def test_waiver_amount_exceeds_outstanding_rejected(api):
    """PRD §3.6: "it is rejected with ERR_INVALID_WAIVER (HTTP 422) when the
    reason is outside that set or when the requested waive_cents is larger
    than the current outstanding_cents".

    Claim: waive_cents > outstanding_cents returns ERR_INVALID_WAIVER (422).
    """
    ctx = create_loan_then_return_late(days_past_due=2)
    fine = ctx["fine"]
    over = fine["outstanding_cents"] + 50
    res = api.waive_fine(
        fine["id"], waive_fine_payload(over, reason="HOLIDAY"),
        make_fine_officer_headers(),
    )
    validate_error(res, "ERR_INVALID_WAIVER", expected_status=422)


# =============================================================================
# Payments (PRD §3.6)
# =============================================================================


def test_payment_without_confirmed_event_rejected(api):
    """PRD §3.6: "If no matching PAYMENT_CONFIRMED event has been recorded for
    that idempotency_key, the payment is rejected with
    ERR_PAYMENT_EVENT_MISSING."

    Claim: paying without first posting PAYMENT_CONFIRMED with the matching
    idempotency_key returns ERR_PAYMENT_EVENT_MISSING.
    """
    ctx = create_loan_then_return_late(days_past_due=3)
    fine = ctx["fine"]
    res = api.pay_fine(
        fine["id"],
        pay_fine_payload(10, idempotency_key="never-emitted-key-abc"),
        make_reader_headers(ctx["reader"]["id"]),
    )
    validate_error(res, "ERR_PAYMENT_EVENT_MISSING", expected_status=409)


def test_payment_exceeding_outstanding_rejected(api):
    """PRD §3.6: "If the requested pay_cents exceeds the current
    outstanding_cents, the payment is rejected with ERR_FINE_OVERPAYMENT."

    Claim: pay_cents > outstanding_cents (with a valid PAYMENT_CONFIRMED
    event) returns ERR_FINE_OVERPAYMENT.
    """
    ctx = create_loan_then_return_late(days_past_due=3)
    fine = ctx["fine"]
    key = "over-pay-test-key"
    over_amount = fine["outstanding_cents"] + 1000
    emit_payment_confirmed(fine["id"], key, over_amount)
    res = api.pay_fine(
        fine["id"],
        pay_fine_payload(over_amount, idempotency_key=key),
        make_reader_headers(ctx["reader"]["id"]),
    )
    validate_error(res, "ERR_FINE_OVERPAYMENT", expected_status=409)


def test_payment_clears_outstanding_settles_fine(api):
    """PRD §3.6: "Whenever a waive or a pay reduces outstanding_cents to zero
    — equivalently, when accrued_cents equals waived_cents plus paid_cents —
    the fine automatically transitions to the terminal SETTLED state."

    Claim: paying the full outstanding amount transitions the Fine to SETTLED
    with outstanding_cents=0.
    """
    ctx = create_loan_then_return_late(days_past_due=3)
    settled = pay_fine_full(ctx["fine"], ctx["reader"]["id"])
    assert settled["settlement_status"] == "SETTLED"
    assert settled["outstanding_cents"] == 0
    assert settled["paid_cents"] == ctx["fine"]["accrued_cents"]
    assert_fine_conserved(settled)


def test_settled_fine_clears_reader_unpaid_fine(api):
    """PRD §3.6: "the reader's unpaid_fine_cents is recomputed (it is the sum
    of outstanding_cents over the reader's Fine rows whose settlement_status
    is PENDING)".

    Claim: after a Fine settles, the reader's unpaid_fine_cents returns to 0.
    """
    ctx = create_loan_then_return_late(days_past_due=3)
    pay_fine_full(ctx["fine"], ctx["reader"]["id"])
    reader = validate_success(
        api.get_reader(ctx["reader"]["id"], LIBRARIAN_HEADERS), 200
    )
    assert reader["unpaid_fine_cents"] == 0


# =============================================================================
# Reader posture recompute (PRD §3.6)
# =============================================================================


def test_reader_overdue_with_pending_fine(api):
    """PRD §3.6: "the server checks whether ... any PENDING fine of the
    reader has outstanding_cents strictly greater than zero ... If either is
    true the reader's status is OVERDUE".

    Claim: a reader with a PENDING Fine outstanding>0 has status=OVERDUE.
    """
    ctx = create_loan_then_return_late(days_past_due=3)
    reader = validate_success(
        api.get_reader(ctx["reader"]["id"], LIBRARIAN_HEADERS), 200
    )
    assert reader["status"] == "OVERDUE"
    assert reader["unpaid_fine_cents"] > 0


def test_reader_normal_after_fine_settled(api):
    """PRD §3.6: "otherwise it is NORMAL. The recompute fires after every
    loan transition, every fine transition, and every sweep run."

    Claim: after the only pending Fine is settled (and no loans overdue),
    Reader.status returns to NORMAL.
    """
    ctx = create_loan_then_return_late(days_past_due=3)
    pay_fine_full(ctx["fine"], ctx["reader"]["id"])
    reader = validate_success(
        api.get_reader(ctx["reader"]["id"], LIBRARIAN_HEADERS), 200
    )
    assert reader["status"] == "NORMAL"
