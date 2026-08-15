"""Disaster deferrals and their windows, the periodic-review checkpoint, margin
call escalation and cure, and the claim-payment cascade (PRD 2.4, 3.1, 3.5, 3.8).
"""
from test_helpers import (
    ApiErrorId, TEST_USERS, api_client, adjuster_report_payload,
    create_deferral, create_deferral_payload, declare_disaster, disburse_draw,
    get_borrower, get_loan, get_success_data, get_summary,
    make_borrower_headers, set_clock, setup_active_loan,
    setup_active_loan_with_deferral, setup_active_loan_with_reported_claim,
    setup_distressed_loan, setup_loan_with_draw, single_margin_notice,
    validate_error, validate_success,
)

OFFICER = TEST_USERS["loan_officer_headers"]
ADJUSTER = TEST_USERS["adjuster_headers"]
COMMITTEE = TEST_USERS["committee_headers"]
SYSTEM = TEST_USERS["system_headers"]


# ---------------------------------------------------------------------------
# Deferral window geometry (PRD 3.8)
# ---------------------------------------------------------------------------

def test_deferral_windows_require_thirty_day_buffer(api):
    """PRD section 3.8: "The `CreditCommittee` approves or denies: approval
    enforces, in order, that the new window does not overlap any other `APPROVED`
    or `IN_EFFECT` deferral of the same loan — `ERR_DEFERRAL_OVERLAP` — and only
    then that the gap between the new window and each such existing window is at
    least 30 days in both directions, neither starting less than thirty days after
    an existing window's end nor ending less than thirty days before an existing
    window's start — `ERR_DEFERRAL_GAP_TOO_SMALL`."

    Design: Difficulty/resource_temporal_overlap/deferral_windows_require_thirty_day_buffer
    """
    ctx = setup_active_loan_with_deferral()  # D1 [2026-06-01, 2026-08-01) APPROVED
    assert ctx["d1"]["status"] == "APPROVED"

    d2 = create_deferral(ctx, requested_start="2026-07-01T00:00:00Z",
                         requested_end="2026-09-01T00:00:00Z")  # overlaps D1
    resp = api.approve_deferral_request(d2["id"], COMMITTEE)
    validate_error(resp, ApiErrorId.ERR_DEFERRAL_OVERLAP)

    d3 = create_deferral(ctx, requested_start="2026-08-15T00:00:00Z",
                         requested_end="2026-10-01T00:00:00Z")  # 14-day gap
    resp = api.approve_deferral_request(d3["id"], COMMITTEE)
    validate_error(resp, ApiErrorId.ERR_DEFERRAL_GAP_TOO_SMALL)

    d4 = create_deferral(ctx, requested_start="2026-08-31T00:00:00Z",
                         requested_end="2026-10-15T00:00:00Z")  # exactly 30 days after
    data = validate_success(api.approve_deferral_request(d4["id"], COMMITTEE), 200)
    assert data["status"] == "APPROVED", "a start exactly 30 days after the prior end passes"

    d1 = get_success_data(api.get_deferral_request(ctx["d1"]["id"], OFFICER))
    assert d1["status"] == "APPROVED", "the first deferral stands throughout"


def test_deferral_gap_rule_applies_before_the_existing_window(api):
    """PRD section 3.8: "approval enforces, in order, that the new window does not
    overlap any other `APPROVED` or `IN_EFFECT` deferral of the same loan —
    `ERR_DEFERRAL_OVERLAP` — and only then that the gap between the new window and
    each such existing window is at least 30 days in both directions, neither
    starting less than thirty days after an existing window's end nor ending less
    than thirty days before an existing window's start —
    `ERR_DEFERRAL_GAP_TOO_SMALL`."

    Design: Difficulty/resource_temporal_overlap/deferral_windows_require_thirty_day_buffer
    """
    ctx = setup_active_loan_with_deferral(
        disaster_start="2026-03-01T00:00:00Z", request_clock="2026-03-15T00:00:00Z")
    # D1 [2026-06-01, 2026-08-01) APPROVED

    d2 = create_deferral(ctx, requested_start="2026-04-20T00:00:00Z",
                         requested_end="2026-05-20T00:00:00Z")  # ends 12 days before D1
    resp = api.approve_deferral_request(d2["id"], COMMITTEE)
    validate_error(resp, ApiErrorId.ERR_DEFERRAL_GAP_TOO_SMALL)

    d3 = create_deferral(ctx, requested_start="2026-04-01T00:00:00Z",
                         requested_end="2026-05-02T00:00:00Z")  # ends exactly 30 days before
    data = validate_success(api.approve_deferral_request(d3["id"], COMMITTEE), 200)
    assert data["status"] == "APPROVED", "the 30-day buffer holds in both directions"


def test_deferral_unknown_disaster_ref_rejected(api):
    """PRD section 3.8: "The `disaster_ref` must match an entry in the
    association's `active_disaster_declarations` that covers the borrower's
    `county` and whose `end_date` is at or after the clock; an absent, expired, or
    county-mismatched reference is rejected with `ERR_DISASTER_NOT_FOUND`."

    Design: Corner/validations/deferral_unknown_disaster_ref_rejected
    """
    ctx = setup_active_loan()  # no disaster ever declared
    resp = api.create_deferral_request(
        create_deferral_payload(loan_account_id=ctx["loan"]["id"],
                                disaster_ref="DR-NOPE",
                                requested_start="2026-08-10T00:00:00Z",
                                requested_end="2026-10-01T00:00:00Z"),
        make_borrower_headers(ctx["bor"]["id"]))
    validate_error(resp, ApiErrorId.ERR_DISASTER_NOT_FOUND)


def test_suspended_borrower_creation_blocked_rejected(api):
    """PRD section 3.1: "While suspended, borrower-initiated creation of draw
    requests, crop budgets, and deferral requests is rejected with
    `ERR_BORROWER_SUSPENDED`."

    Design: Corner/validations/suspended_borrower_creation_blocked_rejected
    """
    ctx = setup_distressed_loan()  # posture DELINQUENT -> borrower SUSPENDED
    assert get_borrower(ctx["bor"]["id"])["status"] == "SUSPENDED"
    declare_disaster(ctx["assoc"]["id"])  # DR-2026-07 covering BLACKHAWK

    resp = api.create_deferral_request(
        create_deferral_payload(loan_account_id=ctx["loan"]["id"]),
        make_borrower_headers(ctx["bor"]["id"]))
    validate_error(resp, ApiErrorId.ERR_BORROWER_SUSPENDED)


# ---------------------------------------------------------------------------
# The periodic review checkpoint (PRD 2.4)
# ---------------------------------------------------------------------------

def test_ops_run_activates_and_expires_deferrals(api):
    """PRD section 2.4: "The periodic review is the association's ops-run
    checkpoint, invoked by `System` or `LoanOfficer` against one association, and
    it performs all of the following in a single run: the association's
    `review_index` — a monotonic counter starting at 0 at creation — increments by
    1". PRD section 3.8: "an `APPROVED` deferral whose `requested_start` is at or
    before the clock while the clock still sits strictly before `requested_end`
    moves to `IN_EFFECT`; any `APPROVED` or `IN_EFFECT` deferral whose
    `requested_end` is at or before the clock moves to `EXPIRED`, whether or not it
    ever activated".

    Design: Corner/cross_cutting_complexity_layers/ops_run_activates_and_expires_deferrals
    """
    ctx = setup_active_loan_with_deferral()  # D1 [2026-06-01, 2026-08-01) APPROVED
    d1 = ctx["d1"]["id"]

    set_clock("2026-06-15T00:00:00Z")  # inside the window
    data = validate_success(api.run_periodic_review(ctx["assoc"]["id"], SYSTEM), 200)
    assert data["review_index"] == 1
    assert get_success_data(api.get_deferral_request(d1, OFFICER))["status"] == "IN_EFFECT"

    set_clock("2026-08-02T00:00:00Z")  # past the end
    data = validate_success(api.run_periodic_review(ctx["assoc"]["id"], SYSTEM), 200)
    assert data["review_index"] == 2, "one increment per run"
    assert get_success_data(api.get_deferral_request(d1, OFFICER))["status"] == "EXPIRED"


def test_second_delinquent_review_escalates_default(api):
    """PRD section 3.8: "`DEFAULT` is never band-derived: it arrives only when a
    periodic review closes with the loan already `DELINQUENT` so that
    `consecutive_delinquent_reviews` reaches 2, or when a margin call escalates."

    Design: Corner/state_machines/second_delinquent_review_escalates_default
    """
    ctx = setup_loan_with_draw(amount_cents=19_000_000)  # drawn to the 19,000,000 base
    set_clock("2031-03-05T00:00:00Z")  # filing lapses at this review -> DELINQUENT

    get_success_data(api.run_periodic_review(ctx["assoc"]["id"], SYSTEM))
    loan = get_loan(ctx["loan"]["id"])
    assert loan["payment_posture"] == "DELINQUENT"
    assert loan["consecutive_delinquent_reviews"] == 1, \
        "the first delinquent close increments but does not escalate"

    get_success_data(api.run_periodic_review(ctx["assoc"]["id"], SYSTEM))
    loan = get_loan(ctx["loan"]["id"])
    assert loan["consecutive_delinquent_reviews"] == 2
    assert loan["payment_posture"] == "DEFAULT", \
        "the second consecutive delinquent close forces DEFAULT"


# ---------------------------------------------------------------------------
# Margin calls and the claim-payment cascade (PRD 3.5, 3.8)
# ---------------------------------------------------------------------------

def test_margin_escalate_forces_default_and_suspends(api):
    """PRD section 3.8: "A `CreditCommittee` member escalates an `ISSUED` notice
    to `ESCALATED`, and three things happen together: the loan's `payment_posture`
    is forced to `DEFAULT`, its `consecutive_delinquent_reviews` is set to 2, and
    the borrower's standing is re-evaluated — which under Section 3.1 suspends the
    borrower."

    Design: Corner/state_machines/margin_escalate_forces_default_and_suspends
    """
    ctx = setup_distressed_loan()  # notice ISSUED, posture DELINQUENT
    data = validate_success(
        api.escalate_margin_call_notice(ctx["notice"]["id"], COMMITTEE), 200)
    assert data["status"] == "ESCALATED"
    loan = get_loan(ctx["loan"]["id"])
    assert loan["payment_posture"] == "DEFAULT", "forced, not band-derived"
    assert loan["consecutive_delinquent_reviews"] == 2
    assert get_borrower(ctx["bor"]["id"])["status"] == "SUSPENDED"


def test_claim_payment_cascade_cures_posture_margin_and_borrower(api):
    """PRD section 3.5: "Then the waterfall: `applied_interest_cents` is the
    lesser of the indemnity and the accrued interest; `applied_principal_cents` is
    the lesser of what remains and the outstanding principal; and any indemnity
    beyond total debt becomes `remitted_to_borrower_cents`." PRD section 3.8: "When
    the deficiency is zero or negative and an `ISSUED` notice exists, that notice
    cures itself to `CURED` and borrower standing is re-evaluated." PRD section
    3.1: "when none of the three conditions holds any longer, the borrower returns
    from `SUSPENDED` to `ACTIVE` on its own."

    Design: Difficulty/transitive_cascade/claim_payment_cascade_cures_posture_margin_and_borrower
    """
    ctx = setup_active_loan_with_reported_claim(claimed_loss_cents=8_000_000)
    loan_id = ctx["loan"]["id"]
    set_clock("2026-04-01T00:00:00Z")
    disburse_draw(ctx, 19_000_000, purpose="SEED")  # base 19,000,000 drawn in full
    set_clock("2026-04-02T00:00:00Z")
    get_success_data(api.terminate_ucc_filing(ctx["fil"]["id"], OFFICER))
    assert get_loan(loan_id)["payment_posture"] == "DELINQUENT"
    assert get_borrower(ctx["bor"]["id"])["status"] == "SUSPENDED"
    assert single_margin_notice(loan_id)["status"] == "ISSUED"

    get_success_data(api.adjuster_report_claim(
        ctx["clm"]["id"], adjuster_report_payload(adjuster_approved_cents=8_000_000),
        ADJUSTER))
    get_success_data(api.approve_claim(ctx["clm"]["id"], ADJUSTER))
    set_clock("2026-04-11T00:00:00Z")  # 10 days of accrual at 3,694/day
    data = validate_success(api.pay_claim(ctx["clm"]["id"], OFFICER), 200)
    assert data["status"] == "PAID"
    assert data["applied_interest_cents"] == 36_940, "10 days x 3,694 fills interest first"
    assert data["applied_principal_cents"] == 7_963_060
    assert data["remitted_to_borrower_cents"] == 0

    summary = get_summary(loan_id)
    assert summary["outstanding_principal_cents"] == 11_036_940
    assert summary["accrued_interest_cents"] == 0
    assert summary["payment_posture"] == "WATCH", \
        "coverage 12,000,000 - 11,036,940 = 963,060 lands in the WATCH band"
    assert single_margin_notice(loan_id)["status"] == "CURED", \
        "the restored coverage cures the outstanding notice"
    assert get_borrower(ctx["bor"]["id"])["status"] == "ACTIVE"


def test_claim_payment_remits_excess_and_closes_loan(api):
    """PRD section 3.5: "The `indemnity_to_lender_cents` is the lesser of
    `adjuster_approved_cents` and the coverage remaining at payment time." PRD
    section 3.5: "Then the waterfall: `applied_interest_cents` is the lesser of the
    indemnity and the accrued interest; `applied_principal_cents` is the lesser of
    what remains and the outstanding principal; and any indemnity beyond total debt
    becomes `remitted_to_borrower_cents`. Balances fall accordingly, the claim
    moves to `PAID` (terminal), and if principal and interest both reach exactly
    zero the loan auto-transitions `ACTIVE` → `PAID_OFF`."

    Design: Difficulty/transitive_cascade/claim_payment_cascade_cures_posture_margin_and_borrower
    """
    ctx = setup_active_loan_with_reported_claim(claimed_loss_cents=2_000_000)
    loan_id = ctx["loan"]["id"]
    set_clock("2026-04-01T00:00:00Z")
    disburse_draw(ctx, 1_000_000, purpose="SEED")

    get_success_data(api.adjuster_report_claim(
        ctx["clm"]["id"], adjuster_report_payload(adjuster_approved_cents=2_000_000),
        ADJUSTER))
    get_success_data(api.approve_claim(ctx["clm"]["id"], ADJUSTER))
    set_clock("2026-04-11T00:00:00Z")  # 10 days at 194/day -> 1,940 accrued
    data = validate_success(api.pay_claim(ctx["clm"]["id"], OFFICER), 200)
    assert data["status"] == "PAID"
    assert data["indemnity_to_lender_cents"] == 2_000_000
    assert data["applied_interest_cents"] == 1_940
    assert data["applied_principal_cents"] == 1_000_000
    assert data["remitted_to_borrower_cents"] == 998_060, \
        "the indemnity beyond total debt is remitted to the borrower"
    loan = get_loan(loan_id)
    assert loan["outstanding_principal_cents"] == 0
    assert loan["accrued_interest_cents"] == 0
    assert loan["status"] == "PAID_OFF"
