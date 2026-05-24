"""Clock-driven delinquency, default boundary, default cascade to plan EXPIRED,
the borrower-status bubble-up rule, delinquency-record outcomes, daily interest
accrual, subsidy_active behavior, and the pinned capitalization order.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    assert_loan, assert_delinquency_record,
    create_servicing_event_payload, create_payment_payload,
    TEST_USERS,
    advance_clock, create_borrower, create_loan, fire_servicing_event,
    get_loan_version, get_loan,
    create_loan_in_grace, create_loan_in_repayment,
    attach_standard_10yr_plan,
    setup_loan_in_repayment_with_standard_plan,
    setup_loan_in_default,
    setup_loan_in_delinquent_via_clock,
)


# ─── Difficulty Rule 6a: 270-day default boundary ────


def test_default_declared_at_269_days_rejected(api, servicer_headers):
    """PRD §3.5: "A servicer may also drive the default transition explicitly
    through a `DEFAULT_DECLARED` `ServicingEvent` with `reason_code` of
    `MISSED_PAYMENTS_270D`. The same boundary applies: the loan's current
    open `DelinquencyRecord` must have `cumulative_days` of at least 270;
    an attempt at 269 or below is rejected with
    `ERR_DEFAULT_THRESHOLD_NOT_MET`."

    Loan REPAYMENT 2026-06-01; system delinquency opens on missed
    2026-07-01 due date; clock at 2027-03-27 → cumulative_days = 269 →
    DEFAULT_DECLARED rejected.

    Design: Difficulty/boundary_precision_check/default_threshold_270_days_exact_boundary
    """
    # Build a loan that delinquencies at 2026-07-01 + grace_window
    # and try DEFAULT_DECLARED at 2027-03-27 (269 days after 2026-07-01).
    advance_clock("2026-06-01T00:00:00Z")
    _, loan = create_loan_in_repayment(
        disbursement_date="2025-06-01",
        grace_begin_on="2025-06-01",
        repayment_begin_on="2026-06-01",
        original_principal_cents=2_000_000, interest_rate_bps=533,
    )
    attach_standard_10yr_plan(loan["id"])
    # Drive the loan into DELINQUENT (the first missed due_date 2026-07-01)
    advance_clock("2026-07-17T00:00:00Z")
    # Advance to 2027-03-27 (269 days past 2026-07-01)
    advance_clock("2027-03-27T00:00:00Z")

    res = api.create_servicing_event(
        loan["id"],
        create_servicing_event_payload(
            "DEFAULT_DECLARED", "2027-03-27", "MISSED_PAYMENTS_270D",
        ),
        servicer_headers,
    )
    validate_error(res, "ERR_DEFAULT_THRESHOLD_NOT_MET", expected_status=409)


# NOTE: test_default_declared_at_270_days_succeeds was DELETED per
# STEP 1b unique-derivability collapse. PRD §3.5 simultaneously requires
# (a) clock-advance to auto-transition a loan to DEFAULT when
# cumulative_days >= 270, AND (b) a manual DEFAULT_DECLARED ServicingEvent
# to require the loan to be in DELINQUENT with cumulative_days >= 270.
# Any PRD-faithful implementation that runs the clock-advance cascade
# (which the PRD requires) leaves no addressable state in which a manual
# DEFAULT_DECLARED can fire at exactly 270 days: by the time
# cumulative_days reaches 270, the auto-cascade has already moved the
# loan to DEFAULT. The test setup advances the clock past 270 days,
# making the manual DEFAULT_DECLARED necessarily rejected as a state
# violation. The companion 269-day rejection test (above) remains; it
# exercises the boundary in the only window the PRD admits.

# ─── Difficulty Rule 4b: clock-advance cascade ───────


def test_clock_advance_past_270_days_cascades_repayment_plan_to_expired(
    api, servicer_headers,
):
    """PRD §3.5: "If `cumulative_days` reaches 270 — 270 days triggers
    default; 269 days does not — the loan transitions to `DEFAULT`: the
    open `DelinquencyRecord` closes with `outcome` of `DEFAULTED`, a
    capitalization of all `accrued_interest_cents` is performed per §2.7,
    any `ACTIVE` `RepaymentPlan` transitions to `EXPIRED`, the borrower's
    `borrower_status` recomputes to `IN_DEFAULT`, and the loan's `version`
    increments."

    A single POST /_clock/advance to 2027-04-28 (after both the first
    missed due date and the 270-day default threshold) drives the loan
    through REPAYMENT → DELINQUENT → DEFAULT and cascades the
    ACTIVE plan to EXPIRED.

    Design: Difficulty/transitive_cascade/missed_payment_delinquency_then_default_two_hop
    """
    advance_clock("2026-06-01T00:00:00Z")
    _, loan = create_loan_in_repayment(
        disbursement_date="2025-06-01",
        grace_begin_on="2025-06-01",
        repayment_begin_on="2026-06-01",
        original_principal_cents=2_000_000, interest_rate_bps=533,
    )
    plan = attach_standard_10yr_plan(loan["id"])
    assert plan["status"] == "ACTIVE"

    advance_clock("2027-04-28T00:00:00Z")
    loan_after = get_loan(loan["id"])
    assert loan_after["status"] == "DEFAULT"

    plan_after = validate_success(api.get_repayment_plan(plan["id"], servicer_headers), 200)
    assert plan_after["status"] == "EXPIRED"


def test_clock_advance_past_270_days_drives_loan_to_default_status(
    api, servicer_headers,
):
    """PRD §3.5: "If a due date has been crossed unsatisfied, the loan
    transitions to `DELINQUENT`: a new `DelinquencyRecord` opens with
    `opened_on` set to the missed due date, the loan's `days_delinquent`
    becomes the count of days from that missed due date to the current
    clock date, and the loan's `version` increments."
    PRD §3.5: "If `cumulative_days` reaches 270 — 270 days triggers
    default; 269 days does not — the loan transitions to `DEFAULT`: the
    open `DelinquencyRecord` closes with `outcome` of `DEFAULTED`, a
    capitalization of all `accrued_interest_cents` is performed per §2.7,
    any `ACTIVE` `RepaymentPlan` transitions to `EXPIRED`, the borrower's
    `borrower_status` recomputes to `IN_DEFAULT`, and the loan's `version`
    increments."

    Each link in the cascade is caused by the previous link's state
    change, not directly by the clock advance: the loan must first
    transition to DELINQUENT (Hop 1) before the cumulative_days counter
    can begin to advance toward 270 (Hop 2). Confirming the final
    Loan.status == DEFAULT proves both hops fired in order.

    Design: Difficulty/transitive_cascade/missed_payment_delinquency_then_default_two_hop
    """
    advance_clock("2026-06-01T00:00:00Z")
    _, loan = create_loan_in_repayment(
        disbursement_date="2025-06-01",
        grace_begin_on="2025-06-01",
        repayment_begin_on="2026-06-01",
        original_principal_cents=2_000_000, interest_rate_bps=533,
    )
    attach_standard_10yr_plan(loan["id"])
    advance_clock("2027-04-28T00:00:00Z")
    loan_after = get_loan(loan["id"])
    assert loan_after["status"] == "DEFAULT"


def test_clock_advance_delinquent_loan_bubbles_up_borrower_status_at_risk(
    api, servicer_headers,
):
    """PRD §2.8: "First, child-`Loan` activity rolls up onto the parent
    `Borrower`. The borrower's `borrower_status` is a compound rollup over
    their non-terminal loans: `CURRENT` whenever every non-terminal loan
    is in `IN_SCHOOL`, `GRACE`, `REPAYMENT`, `DEFERMENT`, or `FORBEARANCE`
    and no loan is `DELINQUENT`; `AT_RISK` whenever any loan is
    `DELINQUENT`; `IN_DEFAULT` whenever any loan is `DEFAULT`; and
    `CLEARED` whenever every loan is in `PAID_OFF` or `DISCHARGED`."

    Design: Corner/state_machines/borrower_status_bubble_up_to_at_risk_on_delinquent
    """
    borrower, loan = setup_loan_in_delinquent_via_clock(
        clock_initial="2026-06-01T00:00:00Z",
        disbursement_date="2025-06-01",
        grace_begin_on="2025-06-01",
        repayment_begin_on="2026-06-01",
        advance_to="2026-07-17T00:00:00Z",
        original_principal_cents=2_000_000,
        interest_rate_bps=533,
    )
    assert loan["status"] == "DELINQUENT"
    borrower_after = validate_success(api.get_borrower(borrower["id"], servicer_headers), 200)
    assert borrower_after["borrower_status"] == "AT_RISK"


# ─── DelinquencyRecord outcomes ────────────────────


def test_cure_payment_closes_delinquency_record_with_cured_outcome(api, servicer_headers):
    """PRD §3.4: "Separately, when the loan was in `DELINQUENT` and the
    incoming payment is large enough to cover every missed scheduled
    monthly payment since the open `DelinquencyRecord`'s `opened_on` (i.e.,
    the full arrears), the loan cascades back to `REPAYMENT`, the open
    `DelinquencyRecord` closes with `outcome` of `CURED`, `days_delinquent`
    resets to zero, and the loan's `version` increments."

    Design: Corner/state_machines/cure_payment_closes_delinquency_record_with_cured_outcome
    """
    advance_clock("2026-06-01T00:00:00Z")
    _, loan = create_loan_in_repayment(
        disbursement_date="2025-06-01",
        grace_begin_on="2025-06-01",
        repayment_begin_on="2026-06-01",
        original_principal_cents=2_000_000, interest_rate_bps=533,
    )
    attach_standard_10yr_plan(loan["id"])
    advance_clock("2026-07-17T00:00:00Z")
    loan_delinquent = get_loan(loan["id"])
    assert loan_delinquent["status"] == "DELINQUENT"

    # Cure payment (50000 cents > one scheduled 21537 cents) brings loan
    # back to REPAYMENT and closes the open delinquency record with
    # outcome=CURED.
    validate_success(api.create_payment(
        create_payment_payload(loan["id"], 50_000, "2026-07-17", "ACH"),
        servicer_headers,
    ), 201)
    loan_repay = get_loan(loan["id"])
    assert loan_repay["status"] == "REPAYMENT"

    body = api.list_delinquency_records(loan["id"], servicer_headers).json()
    data = body["data"]
    assert len(data) >= 1
    record = data[0]
    assert record["outcome"] == "CURED"


def test_forbearance_during_delinquency_closes_record_as_forborne(api, servicer_headers):
    """PRD §3.2: "Forbearance follows a parallel structure: `FORBEARANCE_BEGIN`
    is accepted from either `REPAYMENT` or `DELINQUENT` with reason among
    `ECONOMIC_HARDSHIP`, `NATURAL_DISASTER`, `ADMIN_FORBEARANCE`, or
    `MEDICAL`. The loan moves to `FORBEARANCE`, `subsidy_active` is forced
    to false (forbearance never subsidizes interest, regardless of
    `loan_type`), `days_delinquent` is reset to zero, and if the loan had
    been in `DELINQUENT` the open `DelinquencyRecord` closes with
    `outcome` of `FORBORNE`."

    Design: Corner/state_machines/forbearance_during_delinquency_closes_record_as_forborne
    """
    advance_clock("2026-06-01T00:00:00Z")
    _, loan = create_loan_in_repayment(
        disbursement_date="2025-06-01",
        grace_begin_on="2025-06-01",
        repayment_begin_on="2026-06-01",
        original_principal_cents=2_000_000, interest_rate_bps=533,
    )
    attach_standard_10yr_plan(loan["id"])
    advance_clock("2026-07-17T00:00:00Z")
    loan_del = get_loan(loan["id"])
    assert loan_del["status"] == "DELINQUENT"

    fire_servicing_event(loan["id"], "FORBEARANCE_BEGIN", "2026-07-17", "ECONOMIC_HARDSHIP")
    loan_after = get_loan(loan["id"])
    assert loan_after["status"] == "FORBEARANCE"

    body = api.list_delinquency_records(loan["id"], servicer_headers).json()
    data = body["data"]
    assert len(data) >= 1
    record = data[0]
    assert record["outcome"] == "FORBORNE"


# ─── Interest accrual + subsidy ────────────────────


def test_subsidized_loan_no_interest_accrual_in_school(api, servicer_headers):
    """PRD §2.7: "Loans whose `subsidy_active` is true — Direct Subsidized
    loans during `IN_SCHOOL`, `GRACE`, or `DEFERMENT` — do not accrue
    interest on the borrower's side because the federal government pays
    it; their `accrued_interest_cents` does not increment on those days."
    PRD §3.1: "The `subsidy_active` flag is computed: it is true precisely
    when `loan_type` is `DIRECT_SUBSIDIZED` and `status` is one of
    `IN_SCHOOL`, `GRACE`, or `DEFERMENT`, and false otherwise."

    Design: Corner/calculations/subsidized_loan_no_interest_accrual_in_school_or_grace
    """
    advance_clock("2026-06-01T00:00:00Z")
    borrower = create_borrower(email="subsidized@example.com")
    loan = create_loan(
        borrower["id"],
        loan_type="DIRECT_SUBSIDIZED",
        original_principal_cents=100_000,
        interest_rate_bps=533,
        disbursement_date="2026-06-01",
    )
    advance_clock("2026-08-01T00:00:00Z")
    loan_after = get_loan(loan["id"])
    assert loan_after["subsidy_active"] is True
    assert loan_after["accrued_interest_cents"] == 0


def test_unsubsidized_loan_daily_accrual_known_inputs(api, servicer_headers):
    """PRD §2.7: "Interest accrues daily, computed on a 365-day basis (not
    360, as is the convention for federal Direct loans). On each elapsed
    day, every loan whose `subsidy_active` flag is false accrues additional
    interest equal to its `outstanding_principal_cents` multiplied by its
    `interest_rate_bps`, divided by ten thousand to convert basis points
    to a decimal rate and then divided by 365 to obtain the daily rate,
    with the result rounded half-up to a whole cent and added to
    `accrued_interest_cents`."

    Unsubsidized $1000 @ 5.33% for 30 days IN_SCHOOL: per-day accrual is
    round_half_up(100000 * 533 / 10000 / 365) = round_half_up(14.6027) = 15;
    cumulative over 30 days = 450 cents.

    Design: Corner/calculations/unsubsidized_loan_accrual_per_diem_correct
    """
    advance_clock("2026-06-01T00:00:00Z")
    borrower = create_borrower(email="unsub-accrual@example.com")
    loan = create_loan(
        borrower["id"],
        loan_type="DIRECT_UNSUBSIDIZED",
        original_principal_cents=100_000,
        interest_rate_bps=533,
        disbursement_date="2026-06-01",
    )
    advance_clock("2026-07-01T00:00:00Z")
    loan_after = get_loan(loan["id"])
    assert loan_after["subsidy_active"] is False
    assert loan_after["accrued_interest_cents"] == 450


# ─── Difficulty Rule 2b: capitalization pinned order ──


def test_forbearance_end_capitalization_writes_principal_and_zeros_accrued(
    api, servicer_headers,
):
    """PRD §2.7: "When a capitalization fires, the system follows a pinned
    three-step order: first, the capitalizable amount is added to
    `outstanding_principal_cents` and to the cumulative
    `capitalized_interest_cents` on the loan; next, `accrued_interest_cents`
    is set to zero; finally, the loan's `version` is incremented by one.
    The capitalizable amount itself depends on the transition: a
    grace-to-repayment, forbearance-to-repayment, or delinquent-to-default
    transition capitalizes the full `accrued_interest_cents`..."

    $20,000 UNSUBSIDIZED @ 5.33%, 30 days in FORBEARANCE (subsidy_active
    is false throughout — forbearance never subsidizes per §2.7), then
    FORBEARANCE_END: per-day accrual 292 cents × 30 = 8760 cents
    capitalize. After capitalization: outstanding_principal_cents =
    2000000 + 8760 = 2008760; accrued_interest_cents = 0;
    capitalized_interest_cents = 8760.

    Design: Difficulty/combinatorial_formula/capitalization_pinned_order_circular_dependency
    """
    # Build loan, drive to FORBEARANCE on 2026-06-01.
    advance_clock("2026-06-01T00:00:00Z")
    borrower = create_borrower(email="capitalize-order@example.com")
    loan = create_loan(
        borrower["id"],
        loan_type="DIRECT_UNSUBSIDIZED",
        original_principal_cents=2_000_000,
        interest_rate_bps=533,
        disbursement_date="2026-06-01",
    )
    fire_servicing_event(loan["id"], "GRACE_BEGIN", "2026-06-01", "OTHER")
    fire_servicing_event(loan["id"], "REPAYMENT_BEGIN", "2026-06-01", "GRACE_EXPIRY")
    attach_standard_10yr_plan(loan["id"])
    fire_servicing_event(loan["id"], "FORBEARANCE_BEGIN", "2026-06-01", "ECONOMIC_HARDSHIP")

    # Advance clock 30 days (no payment, accrual fires daily for an
    # unsubsidized loan in forbearance per §2.7).
    advance_clock("2026-07-01T00:00:00Z")

    # FORBEARANCE_END capitalizes the accrued amount.
    fire_servicing_event(loan["id"], "FORBEARANCE_END", "2026-07-01", "OTHER")
    loan_after = get_loan(loan["id"])

    assert loan_after["status"] == "REPAYMENT"
    assert loan_after["outstanding_principal_cents"] == 2_008_760
    assert loan_after["accrued_interest_cents"] == 0
    assert loan_after["capitalized_interest_cents"] == 8_760


def test_forbearance_end_capitalization_preserves_pinned_step_order_via_principal_update(
    api, servicer_headers,
):
    """PRD §2.7: "When a capitalization fires, the system follows a pinned
    three-step order: first, the capitalizable amount is added to
    `outstanding_principal_cents` and to the cumulative
    `capitalized_interest_cents` on the loan; next, `accrued_interest_cents`
    is set to zero; finally, the loan's `version` is incremented by one."

    The pinned order means accrued_interest is read into principal BEFORE
    it is zeroed. If the order were reversed the principal increment would
    be zero. A non-zero outstanding_principal_cents above the original
    proves the order was correct.

    Design: Difficulty/combinatorial_formula/capitalization_pinned_order_circular_dependency
    """
    advance_clock("2026-06-01T00:00:00Z")
    borrower = create_borrower(email="cap-order-2@example.com")
    loan = create_loan(
        borrower["id"],
        loan_type="DIRECT_UNSUBSIDIZED",
        original_principal_cents=2_000_000,
        interest_rate_bps=533,
        disbursement_date="2026-06-01",
    )
    fire_servicing_event(loan["id"], "GRACE_BEGIN", "2026-06-01", "OTHER")
    fire_servicing_event(loan["id"], "REPAYMENT_BEGIN", "2026-06-01", "GRACE_EXPIRY")
    attach_standard_10yr_plan(loan["id"])
    fire_servicing_event(loan["id"], "FORBEARANCE_BEGIN", "2026-06-01", "ECONOMIC_HARDSHIP")
    advance_clock("2026-07-01T00:00:00Z")
    fire_servicing_event(loan["id"], "FORBEARANCE_END", "2026-07-01", "OTHER")
    loan_after = get_loan(loan["id"])

    assert loan_after["outstanding_principal_cents"] > 2_000_000, (
        "outstanding_principal_cents must have grown by the capitalized "
        "amount; if accrued_interest were zeroed first, the principal "
        "increment would be 0 and this assertion would fail."
    )
    assert loan_after["accrued_interest_cents"] == 0
