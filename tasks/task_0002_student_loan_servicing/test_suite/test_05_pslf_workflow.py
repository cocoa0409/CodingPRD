"""PSLF: employment certification field shape, qualifying-payment-count
recount under the relaxed-lookback variant, and the PSLF qualifying-count
compensating invariant under payment reverse.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    create_employment_certification_payload,
    create_payment_payload,
    TEST_USERS, ONGOING_CERTIFICATION_END,
    advance_clock, create_borrower,
    setup_payments_then_cert_for_relaxed_lookback,
    setup_borrower_with_n_qualifying_payments,
    make_pslf_adjudicator_headers,
)


# ─── Certification validation (corner) ───────────────


def test_certification_period_end_before_start_returns_invalid(api, servicer_headers):
    """PRD §3.6: "Field-level violations on submission — `employer_ein` not
    exactly nine digits, `weekly_hours` outside the inclusive range
    [0, 80], or `period_end_on` earlier than `period_start_on` — are
    rejected at create time with `ERR_CERTIFICATION_FIELDS_INVALID`."

    Design: Corner/validations/certification_period_end_before_start_returns_invalid
    """
    advance_clock("2026-06-01T00:00:00Z")
    borrower = create_borrower(email="cert-period-inv@example.com")
    res = api.create_employment_certification(
        {
            "borrower_id": borrower["id"],
            "employer_ein": "123456789",
            "employer_type": "GOVERNMENT_FEDERAL",
            "period_start_on": "2026-06-01",
            "period_end_on": "2026-01-01",
            "weekly_hours": 40,
        },
        servicer_headers,
    )
    validate_error(res, "ERR_CERTIFICATION_FIELDS_INVALID", expected_status=422)


def test_certification_ein_not_9_digits_returns_invalid(api, servicer_headers):
    """PRD §3.6: "Field-level violations on submission — `employer_ein` not
    exactly nine digits, `weekly_hours` outside the inclusive range
    [0, 80], or `period_end_on` earlier than `period_start_on` — are
    rejected at create time with `ERR_CERTIFICATION_FIELDS_INVALID`."

    Design: Corner/validations/certification_ein_not_9_digits_returns_invalid
    """
    advance_clock("2026-06-01T00:00:00Z")
    borrower = create_borrower(email="ein-inv@example.com")
    res = api.create_employment_certification(
        {
            "borrower_id": borrower["id"],
            "employer_ein": "12345",
            "employer_type": "GOVERNMENT_FEDERAL",
            "period_start_on": "2026-01-01",
            "period_end_on": "2099-12-31",
            "weekly_hours": 40,
        },
        servicer_headers,
    )
    validate_error(res, "ERR_CERTIFICATION_FIELDS_INVALID", expected_status=422)


# ─── Difficulty Rule 1b: relaxed-lookback recount ───


def test_pslf_recount_under_relaxed_lookback_picks_up_prior_payments(
    api, servicer_headers,
):
    """PRD §3.6: "The recount is the engine that absorbs all three
    triggering events uniformly: a fresh `APPROVED` certification
    re-evaluates payments by their `posted_on` against the newly approved
    window, so payments that previously did not qualify (because no
    certification covered their date) may now begin to count; a fresh
    `POSTED` payment is evaluated for the first time; and a fresh
    `REVERSED` payment is excluded going forward, possibly dropping the
    count below threshold and (per §3.4) reverting an
    `ELIGIBLE_FOR_FORGIVENESS` tracker back to `TRACKING`."
    PRD §3.6: "On approval, the derived `pslf_qualifying_employer` flag
    becomes true precisely when `status` is `APPROVED`, `employer_type` is
    one of `GOVERNMENT_FEDERAL`, `GOVERNMENT_STATE_LOCAL_TRIBAL`,
    `NONPROFIT_501C3`, or `OTHER_NONPROFIT_QUALIFYING`, and `weekly_hours`
    is at least 30..."

    Two POSTED payments on the scheduled 2026-11-15 and 2026-12-15
    due-dates exist BEFORE any certification approval. A single
    GOVERNMENT_FEDERAL / 40 hr/wk certification whose period
    (2026-10-01 → 2099-12-31) covers both payments is then approved; the
    triggered recount evaluates each payment against the now-approved
    window and counts both → qualifying_payment_count = 2.

    Design: Difficulty/dual_variant_calc/pslf_qualifying_payment_strict_vs_relaxed_lookback
    """
    borrower, _loan, tracker, payments, cert = (
        setup_payments_then_cert_for_relaxed_lookback()
    )
    # Pre-cert: zero qualifying payments expected (no APPROVED cert yet).
    tracker_pre = validate_success(api.get_pslf_tracker(
        tracker["id"], TEST_USERS["pslf_adjudicator_headers"],
    ), 200)
    assert tracker_pre["qualifying_payment_count"] == 0

    # Approve cert → triggers recount; relaxed-lookback picks up the two
    # prior payments now covered by the approved window.
    validate_success(api.approve_employment_certification(
        cert["id"], TEST_USERS["servicer_headers"],
    ), 200)
    tracker_post = validate_success(api.get_pslf_tracker(
        tracker["id"], TEST_USERS["pslf_adjudicator_headers"],
    ), 200)
    assert tracker_post["qualifying_payment_count"] == 2
    assert tracker_post["last_recount_on"] == "2027-01-15"


def test_pslf_payments_pslf_qualifying_flag_true_after_cert_approval(
    api, servicer_headers,
):
    """PRD §3.6: "The `pslf_qualifying` flag on the payment row reflects
    whether the payment currently satisfies these conditions."
    PRD §3.6: "A given payment counts toward the tally when, and only
    when, all of the following hold at recount time: the payment's `status`
    is `POSTED` (reversed payments do not count); the payment's `posted_on`
    falls within the `period_start_on`/`period_end_on` window of an
    `APPROVED` `EmploymentCertification` for the same borrower whose
    `pslf_qualifying_employer` is true; the parent `Loan` had an `ACTIVE`
    `RepaymentPlan` with `plan_type` in `STANDARD_10YR`, `IBR`, `PAYE`, or
    `SAVE` on the payment's `posted_on`; the payment's `amount_cents` is
    at least the `monthly_payment_cents` that was in force on the parent
    loan's active plan on `posted_on`; and `posted_on` falls within the
    monthly billing cycle's on-time window, defined as the cycle's
    scheduled due date through fifteen days after the due date..."

    After the certification approval triggers the recount, each prior
    payment's `pslf_qualifying` flag flips to true on the payment row.

    Design: Difficulty/dual_variant_calc/pslf_qualifying_payment_strict_vs_relaxed_lookback
    """
    borrower, _loan, tracker, payments, cert = (
        setup_payments_then_cert_for_relaxed_lookback()
    )
    validate_success(api.approve_employment_certification(
        cert["id"], TEST_USERS["servicer_headers"],
    ), 200)
    for pay in payments:
        pay_after = validate_success(api.get_payment(
            pay["id"], TEST_USERS["servicer_headers"],
        ), 200)
        assert pay_after["pslf_qualifying"] is True, (
            f"Payment {pay['id']} should be PSLF-qualifying after the "
            f"covering APPROVED certification triggers a recount"
        )


# ─── Difficulty Rule 9b: PSLF count compensating invariant ──


def test_pslf_count_invariant_post_then_reverse(api, servicer_headers):
    """PRD §3.4: "A `LoanServicer` may reverse a previously posted payment
    for up to thirty days after its `posted_on`."
    PRD §3.4: "On success the payment moves to `REVERSED`,
    `outstanding_principal_cents` is increased by the prior
    `applied_to_principal_cents`, `accrued_interest_cents` is increased by
    the prior `applied_to_interest_cents`, the loan's `version` increments,
    and the borrower's `PSLFTracker` is recounted — if removing this
    payment drops `qualifying_payment_count` below `required_payment_count`
    and the tracker had been in `ELIGIBLE_FOR_FORGIVENESS`, the tracker
    reverts to `TRACKING`."
    PRD §3.6: "a fresh `REVERSED` payment is excluded going forward,
    possibly dropping the count below threshold and (per §3.4) reverting
    an `ELIGIBLE_FOR_FORGIVENESS` tracker back to `TRACKING`."

    Tracker starts at count=5 after recount. A sixth payment is posted then
    immediately reversed; after a subsequent recount the count must return
    to 5 (the reversed payment no longer contributes).

    Design: Difficulty/compensating_invariant/pslf_qualifying_count_invariant_under_payment_reverse_then_recount
    """
    borrower, loan, tracker, payments = (
        setup_borrower_with_n_qualifying_payments(n_payments=5)
    )
    assert tracker["qualifying_payment_count"] == 5

    # Post one more qualifying payment, then immediately reverse it.
    advance_clock("2026-12-01T00:00:00Z")
    extra = validate_success(api.create_payment(
        create_payment_payload(loan["id"], 21_537, "2026-12-01", "ACH"),
        TEST_USERS["servicer_headers"],
    ), 201)
    validate_success(api.reverse_payment(
        extra["id"], TEST_USERS["servicer_headers"],
    ), 200)
    # Force a recount and assert the count is back at 5.
    h_adj = TEST_USERS["pslf_adjudicator_headers"]
    validate_success(api.recount_pslf_tracker(tracker["id"], h_adj), 200)
    tracker_after = validate_success(api.get_pslf_tracker(tracker["id"], h_adj), 200)
    assert tracker_after["qualifying_payment_count"] == 5
    pay_after = validate_success(api.get_payment(
        extra["id"], TEST_USERS["servicer_headers"],
    ), 200)
    assert pay_after["status"] == "REVERSED"


def test_pslf_count_unchanged_when_post_and_reverse_net_to_zero(api, servicer_headers):
    """PRD §3.6: "Recounts are triggered automatically whenever a `Payment`
    posts, whenever a `Payment` is reversed, and whenever an
    `EmploymentCertification` is approved; a recount can also be invoked
    explicitly via the tracker recount capability (which is idempotent —
    calling it without intervening events leaves the tracker unchanged)."
    PRD §3.4: "On success the payment moves to `REVERSED`,
    `outstanding_principal_cents` is increased by the prior
    `applied_to_principal_cents`, `accrued_interest_cents` is increased by
    the prior `applied_to_interest_cents`, the loan's `version` increments,
    and the borrower's `PSLFTracker` is recounted — if removing this
    payment drops `qualifying_payment_count` below `required_payment_count`
    and the tracker had been in `ELIGIBLE_FOR_FORGIVENESS`, the tracker
    reverts to `TRACKING`."

    The conserved quantity (count) is preserved across a post→reverse
    cycle on an isolated payment: the recount fires twice (once on the
    post, once on the reverse), and the net change to
    qualifying_payment_count is zero.

    Design: Difficulty/compensating_invariant/pslf_qualifying_count_invariant_under_payment_reverse_then_recount
    """
    borrower, loan, tracker, payments = (
        setup_borrower_with_n_qualifying_payments(n_payments=5)
    )
    count_before = tracker["qualifying_payment_count"]
    assert count_before == 5

    advance_clock("2026-12-01T00:00:00Z")
    extra = validate_success(api.create_payment(
        create_payment_payload(loan["id"], 21_537, "2026-12-01", "ACH"),
        TEST_USERS["servicer_headers"],
    ), 201)
    validate_success(api.reverse_payment(
        extra["id"], TEST_USERS["servicer_headers"],
    ), 200)
    h_adj = TEST_USERS["pslf_adjudicator_headers"]
    tracker_after = validate_success(api.get_pslf_tracker(tracker["id"], h_adj), 200)
    assert tracker_after["qualifying_payment_count"] == count_before
