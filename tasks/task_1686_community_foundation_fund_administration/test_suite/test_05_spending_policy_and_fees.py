"""Spending policy runs, administrative fee schedules, and the endowed
spendable_balance interaction."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    create_active_fund,
    create_cleared_grantee,
    create_grant_in_review,
    make_officer_headers,
    post_snapshot,
    get_fund,
    setup_endowed_fund_with_12q_allowance,
    assert_spending_run,
    assert_fee_assessment,
    assert_money_eq,
    QUARTER_SNAPSHOT_SERIES,
    FISCAL_YEAR_END_SERIES,
    EXPECTED_12Q_BASE_VALUE,
    EXPECTED_12Q_ALLOWANCE,
    EXPECTED_3YR_BASE_VALUE,
    EXPECTED_3YR_ALLOWANCE,
    ApiErrorId,
    TEST_USERS,
)

FINANCE = TEST_USERS["finance_officer_headers"]


def test_average_12q_allowance(api):
    """PRD §3.5: "Under `AVERAGE_12Q`, the window is the twelve most recent
    `QUARTER_END` snapshots, and if fewer than twelve exist the run is rejected
    with `ERR_INSUFFICIENT_HISTORY` (HTTP 422); `base_value` is the sum of those
    twelve `market_value` figures divided by twelve, rounded half-up to two
    decimal places."
    PRD §3.5: "The run's `allowance_granted` is then `base_value` multiplied by
    the agreement's `spending_rate_pct` and divided by one hundred, rounded
    half-up to two decimal places."

    Design: Difficulty/dual_variant_calc/spending_allowance_average_12q_vs_fixed_3yr
    """
    env = setup_endowed_fund_with_12q_allowance()
    run = env["run"]
    assert_spending_run(run)
    assert run["formula_used"] == "AVERAGE_12Q"
    assert_money_eq(run["base_value"], EXPECTED_12Q_BASE_VALUE, "AVERAGE_12Q base")
    assert_money_eq(run["allowance_granted"], EXPECTED_12Q_ALLOWANCE, "AVERAGE_12Q allowance")
    fund = env["fund"]
    assert_money_eq(
        fund["current_spending_allowance"], EXPECTED_12Q_ALLOWANCE, "fund allowance"
    )
    assert_money_eq(fund["allowance_used"], 0.00, "allowance_used reset")


def test_fixed_3yr_allowance_differs(api):
    """PRD §3.5: "Under `FIXED_3YR`, the same construction draws the three most
    recent `FISCAL_YEAR_END` snapshots and requires all three, dividing their
    sum by three; the same fund, rate, and date generally yield a different
    allowance under the two formulas."
    PRD §3.5: "The rounding order is pinned: the average is rounded to cents
    first, and only then is the rate multiplication performed and rounded."

    Design: Difficulty/dual_variant_calc/spending_allowance_average_12q_vs_fixed_3yr
    """
    bundle = create_active_fund(
        fund_type="DESIGNATED",
        endowed=True,
        seed_amount=200000.00,
        agreement_overrides={"spending_rate_pct": 4.5, "spending_formula": "FIXED_3YR"},
    )
    fund_id = bundle["fund"]["id"]
    for effective_date, market_value in FISCAL_YEAR_END_SERIES:
        post_snapshot(fund_id, "FISCAL_YEAR_END", effective_date, market_value)
    run = validate_success(
        api.create_spending_run(fund_id, {"fiscal_year": 2026}, FINANCE), 201
    )
    assert_spending_run(run)
    assert run["formula_used"] == "FIXED_3YR"
    assert_money_eq(run["base_value"], EXPECTED_3YR_BASE_VALUE, "FIXED_3YR base")
    assert_money_eq(run["allowance_granted"], EXPECTED_3YR_ALLOWANCE, "FIXED_3YR allowance")
    # Same rate and overlapping history: the two formula variants diverge.
    assert float(run["allowance_granted"]) != EXPECTED_12Q_ALLOWANCE


def test_standard_schedule_fee_at_600000(api):
    """PRD §3.5: "Under the `STANDARD` schedule, the fee is marginal across
    three tiers: the portion of the balance up to 250,000.00 dollars is charged
    at 1.00 percent, the portion above 250,000.00 dollars and up to
    1,000,000.00 dollars — at most 750,000.00 dollars of it — is charged at 0.60
    percent, and any portion above 1,000,000.00 dollars is charged at 0.30
    percent; the three tier amounts are summed and the total rounded half-up to
    two decimal places."
    PRD §3.5: "The `quarterly_fee` is debited from the fund's `cash_balance`,
    and an assessment that would drive the cash balance below zero is rejected
    with `ERR_INSUFFICIENT_CASH`."

    Design: Difficulty/dual_variant_calc/admin_fee_standard_tiered_vs_flat
    """
    bundle = create_active_fund(
        fund_type="DESIGNATED",
        seed_amount=50000.00,
        agreement_overrides={"fee_tier_schedule": "STANDARD"},
    )
    fund_id = bundle["fund"]["id"]
    fee = validate_success(
        api.create_fee_assessment(
            fund_id,
            {"quarter_end_date": "2026-03-31T00:00:00Z", "quarter_end_balance": 600000.00},
            FINANCE,
        ),
        201,
    )
    assert_fee_assessment(fee)
    assert fee["schedule_used"] == "STANDARD"
    # 250000*1.00% + 350000*0.60% = 2500.00 + 2100.00 = 4600.00
    assert_money_eq(fee["annual_fee"], 4600.00, "STANDARD annual fee")
    assert_money_eq(fee["quarterly_fee"], 1150.00, "STANDARD quarterly fee")
    fund = get_fund(fund_id)
    assert_money_eq(fund["cash_balance"], 48850.00, "cash after STANDARD fee debit")


def test_flat_schedule_fee_at_600000(api):
    """PRD §3.5: "Under the `FLAT` schedule, `annual_fee` is the whole balance
    multiplied by 0.75 percent, rounded half-up to two decimal places."
    PRD §3.5: "Either way, `quarterly_fee` is the `annual_fee` divided by four
    and rounded half-up to two decimal places — the annual figure is rounded
    first and only then divided, and dividing before rounding is non-conformant."

    Design: Difficulty/dual_variant_calc/admin_fee_standard_tiered_vs_flat
    """
    bundle = create_active_fund(
        fund_type="DESIGNATED",
        seed_amount=50000.00,
        agreement_overrides={"fee_tier_schedule": "FLAT"},
    )
    fund_id = bundle["fund"]["id"]
    fee = validate_success(
        api.create_fee_assessment(
            fund_id,
            {"quarter_end_date": "2026-03-31T00:00:00Z", "quarter_end_balance": 600000.00},
            FINANCE,
        ),
        201,
    )
    assert fee["schedule_used"] == "FLAT"
    # 600000 * 0.75% = 4500.00
    assert_money_eq(fee["annual_fee"], 4500.00, "FLAT annual fee")
    assert_money_eq(fee["quarterly_fee"], 1125.00, "FLAT quarterly fee")
    fund = get_fund(fund_id)
    assert_money_eq(fund["cash_balance"], 48875.00, "cash after FLAT fee debit")


def test_spending_run_requires_full_twelve_quarters(api):
    """PRD §3.5: "Under `AVERAGE_12Q`, the window is the twelve most recent
    `QUARTER_END` snapshots, and if fewer than twelve exist the run is rejected
    with `ERR_INSUFFICIENT_HISTORY` (HTTP 422); `base_value` is the sum of those
    twelve `market_value` figures divided by twelve, rounded half-up to two
    decimal places."

    Design: Corner/calculations/spending_run_insufficient_history
    """
    bundle = create_active_fund(
        fund_type="DESIGNATED", endowed=True, seed_amount=200000.00
    )
    fund_id = bundle["fund"]["id"]
    # Only eleven quarter-end snapshots: one short of the required window.
    for effective_date, market_value in QUARTER_SNAPSHOT_SERIES[1:]:
        post_snapshot(fund_id, "QUARTER_END", effective_date, market_value)
    resp = api.create_spending_run(fund_id, {"fiscal_year": 2026}, FINANCE)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_HISTORY)
    # Adding the twelfth snapshot completes the window and the run succeeds.
    first_date, first_value = QUARTER_SNAPSHOT_SERIES[0]
    post_snapshot(fund_id, "QUARTER_END", first_date, first_value)
    run = validate_success(
        api.create_spending_run(fund_id, {"fiscal_year": 2026}, FINANCE), 201
    )
    assert_money_eq(run["allowance_granted"], EXPECTED_12Q_ALLOWANCE, "allowance after 12th snapshot")


def test_standard_fee_at_exact_tier_boundary(api):
    """PRD §3.5: "Under the `STANDARD` schedule, the fee is marginal across
    three tiers: the portion of the balance up to 250,000.00 dollars is charged
    at 1.00 percent, the portion above 250,000.00 dollars and up to
    1,000,000.00 dollars — at most 750,000.00 dollars of it — is charged at 0.60
    percent, and any portion above 1,000,000.00 dollars is charged at 0.30
    percent; the three tier amounts are summed and the total rounded half-up to
    two decimal places."
    PRD §3.5: "Either way, `quarterly_fee` is the `annual_fee` divided by four
    and rounded half-up to two decimal places — the annual figure is rounded
    first and only then divided, and dividing before rounding is non-conformant."

    Design: Corner/calculations/admin_fee_tier_boundary_exact_250000
    """
    bundle = create_active_fund(fund_type="DESIGNATED", seed_amount=50000.00)
    fund_id = bundle["fund"]["id"]
    fee = validate_success(
        api.create_fee_assessment(
            fund_id,
            {"quarter_end_date": "2026-03-31T00:00:00Z", "quarter_end_balance": 250000.00},
            FINANCE,
        ),
        201,
    )
    # Exactly at the tier-1 cap: 250000 * 1.00% = 2500.00
    assert_money_eq(fee["annual_fee"], 2500.00, "annual fee at tier boundary")
    assert_money_eq(fee["quarterly_fee"], 625.00, "quarterly fee at tier boundary")
    fund = get_fund(fund_id)
    assert_money_eq(fund["cash_balance"], 49375.00, "cash after fee debit")


def test_approve_at_exact_spendable_boundary_succeeds(api):
    """PRD §3.5: "For an endowed fund, the remaining allowance is the greater of
    zero and the difference between `current_spending_allowance` and
    `allowance_used`, and `spendable_balance` is the smaller of `cash_balance`
    and that remaining allowance, at 2 decimal places."
    PRD §3.6: "Fourth, the `amount` must not exceed the fund's
    `spendable_balance` at the decision instant — the allowance-aware figure of
    §3.5 — failing with `ERR_EXCEEDS_SPENDABLE` (HTTP 422)."

    Design: Difficulty/combinatorial_formula/endowed_spendable_min_cash_allowance_interaction
    """
    env = setup_endowed_fund_with_12q_allowance(seed_amount=200000.00)
    fund = env["fund"]
    # min(cash 200000.00, allowance 4666.87 - used 0.00) = 4666.87
    assert_money_eq(fund["spendable_balance"], EXPECTED_12Q_ALLOWANCE, "spendable before approve")
    grantee = create_cleared_grantee()
    grant = create_grant_in_review(
        fund_id=fund["id"],
        grantee_id=grantee["id"],
        amount=EXPECTED_12Q_ALLOWANCE,
        claimer_id="co-1",
    )
    resp = api.approve_grant(
        grant["id"], {}, make_officer_headers("ComplianceOfficer", "co-2")
    )
    data = validate_success(resp, 200)
    # Amount exactly equal to spendable_balance does not exceed it: approved.
    assert data["status"] == "APPROVED"


def test_approve_one_cent_above_spendable_rejected(api):
    """PRD §3.6: "Fourth, the `amount` must not exceed the fund's
    `spendable_balance` at the decision instant — the allowance-aware figure of
    §3.5 — failing with `ERR_EXCEEDS_SPENDABLE` (HTTP 422)."

    Design: Difficulty/combinatorial_formula/endowed_spendable_min_cash_allowance_interaction
    """
    env = setup_endowed_fund_with_12q_allowance(seed_amount=200000.00)
    fund = env["fund"]
    grantee = create_cleared_grantee()
    grant = create_grant_in_review(
        fund_id=fund["id"],
        grantee_id=grantee["id"],
        amount=4666.88,
        claimer_id="co-1",
    )
    resp = api.approve_grant(
        grant["id"], {}, make_officer_headers("ComplianceOfficer", "co-2")
    )
    validate_error(resp, ApiErrorId.ERR_EXCEEDS_SPENDABLE)
    after = validate_success(api.get_grant(grant["id"], make_officer_headers("ComplianceOfficer", "co-2")))
    assert after["status"] == "COMPLIANCE_REVIEW"
