"""Interest accrual conventions, the repayment waterfall, coverage-band posture,
and the patronage year-end (PRD sections 2.4, 2.5, 3.6, 3.8, 3.9).
"""
from test_helpers import (
    ApiErrorId, TEST_USERS, api_client, assert_pool_invariant,
    create_association, create_distribution_payload, create_draw_payload,
    create_repayment_payload, disburse_draw, get_borrower, get_loan,
    get_success_data, get_summary, make_borrower_headers, set_clock,
    setup_active_loan, setup_declared_distribution, setup_loan_with_draw,
    setup_repaid_borrower, validate_error, validate_success,
)

OFFICER = TEST_USERS["loan_officer_headers"]
BOARD = TEST_USERS["board_headers"]
SYSTEM = TEST_USERS["system_headers"]

CAPPED_50M = {  # raw base 96,000,000 capped to the 50,000,000 commitment
    "collateral_type": "REAL_ESTATE",
    "appraised_value_cents": 60_000_000,
    "projected_revenue_cents": 80_000_000,
    "projected_expenses_cents": 50_000_000,
}


# ---------------------------------------------------------------------------
# Interest accrual: pinned rounding order (PRD 3.6)
# ---------------------------------------------------------------------------

def test_interest_accrual_daily_rounding_order(api):
    """PRD section 3.6: "For a segment in which principal stays constant at some
    value for a whole number of UTC days, the daily charge is that principal times
    the loan's `rate_bps` divided by 3,600,000 — basis points over ten thousand
    over a 360-day year, the actual/360 convention — rounded half-up to whole
    cents; the segment's accrual is that daily charge times the number of days."
    PRD section 3.6: "The rounding order is pinned: each segment's daily charge is
    rounded to whole cents first and then multiplied by days; accumulating raw
    fractions over a segment and rounding once at the end yields different cents
    and is non-conformant."

    Design: Difficulty/combinatorial_formula/interest_accrual_daily_rounding_order
    """
    ctx = setup_active_loan(**CAPPED_50M)
    set_clock("2026-04-01T00:00:00Z")
    disburse_draw(ctx, 10_000_001, purpose="FERTILIZER")
    set_clock("2026-05-01T00:00:00Z")  # 30 whole UTC days
    get_success_data(api.run_periodic_review(ctx["assoc"]["id"], SYSTEM))
    accrued = get_summary(ctx["loan"]["id"])["accrued_interest_cents"]
    assert accrued == 58_320, \
        "30 x round_half_up(10,000,001 x 700 / 3,600,000) = 30 x 1,944"
    assert accrued != 58_333, \
        "the sum-then-round alternative (58,333.33 -> 58,333) is non-conformant"


def test_interest_accrual_rounds_half_up_on_exact_half_cent(api):
    """PRD section 2.5: "where a rule says "rounded half-up to whole cents" the
    half-cent rounds toward the larger cent". PRD section 3.6: "For a segment in
    which principal stays constant at some value for a whole number of UTC days,
    the daily charge is that principal times the loan's `rate_bps` divided by
    3,600,000 — basis points over ten thousand over a 360-day year, the actual/360
    convention — rounded half-up to whole cents; the segment's accrual is that
    daily charge times the number of days."

    Design: Difficulty/combinatorial_formula/interest_accrual_daily_rounding_order
    """
    ctx = setup_active_loan(**CAPPED_50M)
    set_clock("2026-04-01T00:00:00Z")
    disburse_draw(ctx, 18_000, purpose="LABOR")  # daily charge exactly 3.5 cents
    set_clock("2026-04-11T00:00:00Z")  # 10 days
    get_success_data(api.run_periodic_review(ctx["assoc"]["id"], SYSTEM))
    accrued = get_summary(ctx["loan"]["id"])["accrued_interest_cents"]
    assert accrued == 40, "round_half_up(3.5) = 4 per day; 10 x 4 = 40 (floor gives 30)"


# ---------------------------------------------------------------------------
# Repayment waterfall (PRD 3.6)
# ---------------------------------------------------------------------------

def test_repayment_waterfall_interest_before_principal(api):
    """PRD section 3.6: "Otherwise `applied_interest_cents` is the lesser of the
    amount and the accrued interest, `applied_principal_cents` is the remainder of
    the amount, interest and principal fall by those portions, and the repayment
    records both portions with status `APPLIED`." PRD section 3.6: "When the two
    balances both reach exactly zero, the loan auto-transitions `ACTIVE` →
    `PAID_OFF`."

    Design: Corner/calculations/repayment_waterfall_interest_before_principal
    """
    ctx = setup_active_loan(**CAPPED_50M)
    set_clock("2026-04-01T00:00:00Z")
    disburse_draw(ctx, 10_000_000, purpose="SEED")
    set_clock("2026-04-11T00:00:00Z")  # 10 days at 1,944/day -> 19,440 accrued
    resp = api.create_repayment(
        create_repayment_payload(loan_account_id=ctx["loan"]["id"],
                                 amount_cents=10_019_440, source="HARVEST_PROCEEDS"),
        make_borrower_headers(ctx["bor"]["id"]))
    data = validate_success(resp, 201)
    assert data["applied_interest_cents"] == 19_440, "the interest bucket fills first"
    assert data["applied_principal_cents"] == 10_000_000
    assert data["status"] == "APPLIED"
    loan = get_loan(ctx["loan"]["id"])
    assert loan["status"] == "PAID_OFF", "exact payoff auto-closes the loan"
    assert loan["outstanding_principal_cents"] == 0
    assert loan["accrued_interest_cents"] == 0


def test_repayment_overpayment_rejected_then_exact_payoff(api):
    """PRD section 3.6: "The payment applies in full at creation: interest accrues
    to the clock date first; then if the amount exceeds accrued interest plus
    outstanding principal, the request is rejected outright with
    `ERR_PAYMENT_EXCEEDS_OUTSTANDING` — there is no partial application." PRD
    section 3.6: "When the two balances both reach exactly zero, the loan
    auto-transitions `ACTIVE` → `PAID_OFF`."

    Design: Corner/endpoints/repayment_overpayment_rejected_then_exact_payoff
    """
    ctx = setup_active_loan(**CAPPED_50M)  # clock 2026-03-01 throughout: zero accrual
    disburse_draw(ctx, 5_000_000, purpose="SEED")
    borrower = make_borrower_headers(ctx["bor"]["id"])
    loan_id = ctx["loan"]["id"]

    resp = api.create_repayment(
        create_repayment_payload(loan_account_id=loan_id, amount_cents=5_000_001,
                                 source="OTHER"), borrower)
    validate_error(resp, ApiErrorId.ERR_PAYMENT_EXCEEDS_OUTSTANDING)
    assert get_loan(loan_id)["outstanding_principal_cents"] == 5_000_000, \
        "the overpayment is rejected whole — balances unchanged"

    data = validate_success(api.create_repayment(
        create_repayment_payload(loan_account_id=loan_id, amount_cents=5_000_000,
                                 source="HARVEST_PROCEEDS"), borrower), 201)
    assert data["applied_interest_cents"] == 0
    assert get_loan(loan_id)["status"] == "PAID_OFF"


# ---------------------------------------------------------------------------
# Coverage-band posture (PRD 3.8) riding a stable ACTIVE lifecycle
# ---------------------------------------------------------------------------

def test_posture_cycles_watch_to_current_while_status_stays_active(api):
    """PRD section 3.8: "Coverage is the lesser of `approved_commitment_cents` and
    `borrowing_base_cents`, minus `outstanding_principal_cents` — the
    `coverage_cents` of the financial summary. When coverage times ten is at least
    the approved commitment — coverage of exactly one-tenth of the commitment
    counts — the loan recomputes to `CURRENT`. When coverage is zero or more but
    below one-tenth of the commitment, the loan recomputes to `WATCH`. When
    coverage is negative, the loan recomputes to `DELINQUENT`."

    Design: Difficulty/non_linear_state_machine/loan_account_parallel_status_and_posture
    """
    ctx = setup_active_loan(**CAPPED_50M)
    loan_id = ctx["loan"]["id"]
    disburse_draw(ctx, 46_000_000, purpose="FERTILIZER")
    loan = get_loan(loan_id)
    assert loan["status"] == "ACTIVE" and loan["payment_posture"] == "WATCH", \
        "coverage 4,000,000 is below the 5,000,000 tenth-band"

    get_success_data(api.create_repayment(
        create_repayment_payload(loan_account_id=loan_id, amount_cents=6_000_001,
                                 source="OTHER"),
        make_borrower_headers(ctx["bor"]["id"])))  # same day: zero accrued
    loan = get_loan(loan_id)
    assert loan["outstanding_principal_cents"] == 39_999_999
    assert loan["status"] == "ACTIVE" and loan["payment_posture"] == "CURRENT", \
        "coverage 10,000,001 x 10 >= 50,000,000 restores CURRENT"


def test_posture_delinquent_excursion_returns_to_current(api):
    """PRD section 3.8: "When coverage is negative, the loan recomputes to
    `DELINQUENT`. Any recompute that lands outside `DELINQUENT` resets
    `consecutive_delinquent_reviews` to 0." PRD section 3.1: "While suspended,
    borrower-initiated creation of draw requests, crop budgets, and deferral
    requests is rejected with `ERR_BORROWER_SUSPENDED`." (repayments are not among
    the blocked borrower creations.)

    Design: Difficulty/non_linear_state_machine/loan_account_parallel_status_and_posture
    """
    ctx = setup_loan_with_draw(amount_cents=19_000_000)  # base 19,000,000, drawn full
    loan_id = ctx["loan"]["id"]
    assert get_loan(loan_id)["payment_posture"] == "WATCH", "coverage exactly 0 is WATCH"

    get_success_data(api.terminate_ucc_filing(ctx["fil"]["id"], OFFICER))
    loan = get_loan(loan_id)
    assert loan["status"] == "ACTIVE" and loan["payment_posture"] == "DELINQUENT", \
        "coverage 12,000,000 - 19,000,000 is negative"
    assert get_borrower(ctx["bor"]["id"])["status"] == "SUSPENDED"

    get_success_data(api.create_repayment(
        create_repayment_payload(loan_account_id=loan_id, amount_cents=12_000_000,
                                 source="OTHER"),
        make_borrower_headers(ctx["bor"]["id"])))  # same day: zero accrued
    loan = get_loan(loan_id)
    assert loan["status"] == "ACTIVE" and loan["payment_posture"] == "CURRENT", \
        "coverage 12,000,000 - 7,000,000 = 5,000,000 reaches exactly one-tenth"
    assert loan["consecutive_delinquent_reviews"] == 0, \
        "leaving DELINQUENT resets the counter"


def test_coverage_exactly_ten_percent_current_one_cent_less_watch(api):
    """PRD section 3.8: "When coverage times ten is at least the approved
    commitment — coverage of exactly one-tenth of the commitment counts — the loan
    recomputes to `CURRENT`. When coverage is zero or more but below one-tenth of
    the commitment, the loan recomputes to `WATCH`. When coverage is negative, the
    loan recomputes to `DELINQUENT`."

    Design: Difficulty/boundary_precision_check/coverage_exactly_ten_percent_current_one_cent_less_watch
    """
    ctx = setup_active_loan(**CAPPED_50M)
    loan_id = ctx["loan"]["id"]
    disburse_draw(ctx, 45_000_000, purpose="SEED")
    summary = get_summary(loan_id)
    assert summary["coverage_cents"] == 5_000_000
    assert summary["payment_posture"] == "CURRENT", \
        "5,000,000 x 10 >= 50,000,000: exactly one-tenth counts as CURRENT"

    disburse_draw(ctx, 1, purpose="FUEL")  # one cent more
    summary = get_summary(loan_id)
    assert summary["coverage_cents"] == 4_999_999
    assert summary["payment_posture"] == "WATCH", \
        "4,999,999 x 10 < 50,000,000: one cent below the tenth-band flips to WATCH"


def test_coverage_zero_is_watch_negative_is_delinquent(api):
    """PRD section 3.8: "When coverage is zero or more but below one-tenth of the
    commitment, the loan recomputes to `WATCH`. When coverage is negative, the loan
    recomputes to `DELINQUENT`."

    Design: Difficulty/boundary_precision_check/coverage_exactly_ten_percent_current_one_cent_less_watch
    """
    ctx = setup_loan_with_draw(amount_cents=19_000_000)  # base 19,000,000, drawn full
    loan_id = ctx["loan"]["id"]
    summary = get_summary(loan_id)
    assert summary["coverage_cents"] == 0
    assert summary["payment_posture"] == "WATCH", "zero coverage sits in the WATCH band"

    get_success_data(api.terminate_ucc_filing(ctx["fil"]["id"], OFFICER))
    summary = get_summary(loan_id)
    assert summary["coverage_cents"] == -7_000_000
    assert summary["payment_posture"] == "DELINQUENT", "negative coverage is DELINQUENT"


# ---------------------------------------------------------------------------
# Patronage year-end (PRD 3.9)
# ---------------------------------------------------------------------------

def test_patronage_fiscal_window_half_open_membership(api):
    """PRD section 3.9: "Each eligible borrower's weight is the sum of
    `applied_interest_cents` over its loans' repayments with status `APPLIED` —
    `REVERSED` repayments are excluded, and insurance-indemnity applications are
    not repayments and never count — whose `created_at` falls inside the half-open
    fiscal-year window, on or after January 1 of the `fiscal_year` at 00:00:00 UTC
    and strictly before January 1 of the following year." PRD section 3.9: "The cap
    then binds first: a borrower's dividend never exceeds 25% (2500 basis points)
    of the interest it paid, so each line's share is the lesser of its raw share
    and the cap." PRD section 3.9: "Cents that remain because caps cannot absorb
    them are never redistributed; they stay in `undistributed_cents`."

    Design: Corner/calculations/patronage_fiscal_window_half_open_membership
    """
    set_clock("2026-03-01T00:00:00Z")
    assoc = create_association("Prairie FCS", "CH-1851")
    ctx = setup_repaid_borrower(
        assoc, "Alpha Farms", "41-1000001",
        draw_cents=10_000_000, repay_cents=2_000_000, repay_clock="2028-01-01T00:00:00Z",
        maturity_date="2030-12-31T00:00:00Z", coverage_end="2031-01-01T00:00:00Z",
        policy_number="POL-A", filing_number="UCC-A", commitment_cents=20_000_000)
    assert ctx["repay"]["applied_interest_cents"] == 1_304_424, \
        "671 days at 1,944/day; created at the FY2028 window's inclusive start"

    set_clock("2029-01-01T00:00:00Z")  # the window's exclusive end
    second = get_success_data(api.create_repayment(
        create_repayment_payload(loan_account_id=ctx["loan"]["id"],
                                 amount_cents=1_000_000, source="HARVEST_PROCEEDS"),
        make_borrower_headers(ctx["bor"]["id"])))
    assert second["applied_interest_cents"] == 662_094, \
        "366 days on 9,304,424 at 1,809/day; created one instant past the window"

    dst = setup_declared_distribution(assoc["id"], fiscal_year=2028,
                                      pool_cents=1_000_000)
    data = validate_success(api.allocate_patronage_distribution(dst["id"], BOARD), 200)
    assert data["status"] == "ALLOCATED"
    assert len(data["allocation_lines"]) == 1
    line = data["allocation_lines"][0]
    assert line["borrower_id"] == ctx["bor"]["id"]
    assert line["interest_paid_cents"] == 1_304_424, \
        "only the 2028-01-01 repayment counts; the 2029-01-01 repayment is outside"
    assert line["final_share_cents"] == 326_106, \
        "raw share 1,000,000 capped at floor(1,304,424 x 25%)"
    assert data["allocated_cents"] == 326_106
    assert data["undistributed_cents"] == 673_894
    assert_pool_invariant(data)


def test_patronage_wrong_fiscal_year_rejected(api):
    """PRD section 3.9: "The `fiscal_year` must equal the association's
    `current_fiscal_year` minus one — the distribution is always for the year just
    closed — and any other year is rejected with `ERR_INVALID_FISCAL_YEAR`". PRD
    section 2.4: "the association's `current_fiscal_year` — the UTC calendar year
    of the logical clock — all read this clock."

    Design: Corner/validations/patronage_wrong_fiscal_year_rejected
    """
    set_clock("2029-01-15T00:00:00Z")  # current_fiscal_year 2029 -> only 2028 declarable
    assoc = create_association("Prairie FCS", "CH-1851")
    resp = api.create_patronage_distribution(
        create_distribution_payload(association_id=assoc["id"], fiscal_year=2026,
                                    pool_cents=100_000), BOARD)
    validate_error(resp, ApiErrorId.ERR_INVALID_FISCAL_YEAR)


def test_patronage_duplicate_declaration_rejected(api):
    """PRD section 3.9: "one distribution exists per association and fiscal year,
    and a duplicate declaration is rejected with `ERR_DISTRIBUTION_EXISTS`."

    Design: Corner/validations/patronage_duplicate_declaration_rejected
    """
    dst = setup_declared_distribution(
        create_association("Prairie FCS", "CH-1851")["id"], fiscal_year=2028,
        pool_cents=100_000)
    resp = api.create_patronage_distribution(
        create_distribution_payload(association_id=dst["association_id"],
                                    fiscal_year=2028, pool_cents=200_000), BOARD)
    validate_error(resp, ApiErrorId.ERR_DISTRIBUTION_EXISTS)
    first = validate_success(api.get_patronage_distribution(dst["id"], BOARD), 200)
    assert first["status"] == "DECLARED" and first["pool_cents"] == 100_000, \
        "the first declaration stands untouched"


def test_patronage_allocate_empty_base_rejected(api):
    """PRD section 3.9: "The eligible population is the association's borrowers
    with `patronage_eligible` true and status other than `TERMINATED`; and the
    whole allocation is rejected with `ERR_NO_ELIGIBLE_PATRONAGE_BASE` when the
    total eligible interest weight is zero."

    Design: Corner/validations/patronage_allocate_empty_base_rejected
    """
    dst = setup_declared_distribution(
        create_association("Prairie FCS", "CH-1851")["id"], fiscal_year=2028,
        pool_cents=100_000)
    resp = api.allocate_patronage_distribution(dst["id"], BOARD)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_PATRONAGE_BASE)
    assert validate_success(api.get_patronage_distribution(dst["id"], BOARD), 200)["status"] == "DECLARED"
