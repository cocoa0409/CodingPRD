"""Benefit-payout and premium/inflation calculations.

Queue A (Difficulty): dual_variant_calc, combinatorial_formula.
Queue B (Corner): calculations section + derived-field reconciliation.
"""
from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    setup_claim_under_review,
    create_issued_policy,
    create_policyholder,
    add_premium_invoice,
    adjudicate_filing,
    approve_claim,
    read_benefit_pool,
    TEST_USERS,
)

UW = TEST_USERS["underwriter_headers"]
CE = TEST_USERS["claims_examiner_headers"]
REG = TEST_USERS["regulator_headers"]


# ===========================================================================
# dual_variant_calc / reimbursement_vs_indemnity_same_claim_lines
# ===========================================================================
def test_reimbursement_vs_indemnity_same_lines_pay_differently(api):
    """PRD 3.7: "The raw daily entitlement before caps depends on `product_mode`:
    under `INDEMNITY` it is the full `inflated_daily_max_cents` regardless of the
    billed charge; under `REIMBURSEMENT` it is the lesser of `billed_charge_cents`
    and `inflated_daily_max_cents`."
    PRD 3.7: "The claim's `month_paid_cents` is the sum of `benefit_paid_cents`
    across all of its lines."

    Lines 15000/25000/18000 with daily cap 20000, elim 0, ample monthly/pool:
    REIMBURSEMENT pays min(charge,20000) -> 15000+20000+18000 = 53000;
    INDEMNITY pays full 20000 each -> 60000.

    Design: Difficulty/dual_variant_calc/reimbursement_vs_indemnity_same_claim_lines
    """
    lines = [("2026-03-01", 15000), ("2026-03-02", 25000), ("2026-03-03", 18000)]
    reimb = setup_claim_under_review(
        lines=lines, policy_overrides={"product_mode": "REIMBURSEMENT"})
    indem = setup_claim_under_review(
        lines=lines, policy_overrides={"product_mode": "INDEMNITY"})

    reimb_claim = approve_claim(reimb["pol_id"], reimb["claim_id"])
    indem_claim = approve_claim(indem["pol_id"], indem["claim_id"])

    assert reimb_claim["month_paid_cents"] == 53000, reimb_claim
    assert indem_claim["month_paid_cents"] == 60000, indem_claim
    assert indem_claim["month_paid_cents"] - reimb_claim["month_paid_cents"] == 7000


def test_indemnity_pays_full_cap_above_charge(api):
    """PRD 3.7: "under `INDEMNITY` it is the full `inflated_daily_max_cents`
    regardless of the billed charge"; "The claim's `month_paid_cents` is the sum
    of `benefit_paid_cents` across all of its lines."

    A single INDEMNITY line charging only 15000 with a 20000 daily cap still pays
    the full 20000 (the insured keeps the difference).

    Design: Difficulty/dual_variant_calc/reimbursement_vs_indemnity_same_claim_lines
    """
    ctx = setup_claim_under_review(
        lines=[("2026-03-01", 15000)], policy_overrides={"product_mode": "INDEMNITY"})
    claim = approve_claim(ctx["pol_id"], ctx["claim_id"])
    assert claim["month_paid_cents"] == 20000, claim


# ===========================================================================
# dual_variant_calc / premium_amount_increase_vs_no_increase_variant
# ===========================================================================
def test_premium_amount_no_increase_vs_with_increase(api):
    """PRD 3.11: "When the regulator grants the full request — `granted_pct`
    equal to `requested_increase_pct` — the filing moves from `FILED` to
    `APPROVED` and `approved_increase_pct` is set to the requested figure."
    PRD 3.11: "The invoice's `amount_cents` is then the `base_premium_cents`
    multiplied by the quantity one hundred plus the applicable
    `approved_increase_pct`, divided by one hundred, with that single result
    rounded half-up to the nearest cent. When no increase applies, the amount
    equals the base premium unchanged."

    A +40% filing effective at period 1: invoice for period 0 stays 12000;
    invoice for period 1 created after approval is 12000*140/100 = 16800.

    Design: Difficulty/dual_variant_calc/premium_amount_increase_vs_no_increase_variant
    """
    ph = create_policyholder(full_name="Rae Rate")
    policy = create_issued_policy(ph["id"])
    inv0 = add_premium_invoice(policy["id"], 0, base_premium_cents=12000)

    filing = get_success_data(api_client.create_rate_filing(
        {"policy_id": policy["id"], "requested_increase_pct": 40, "effective_period_index": 1}, UW))
    adjudicate_filing(policy["id"], filing["id"], 40)

    inv1 = add_premium_invoice(policy["id"], 1, base_premium_cents=12000,
                               due_date="2026-02-28", grace_deadline="2026-05-04")

    assert inv0["amount_cents"] == 12000, inv0
    assert inv1["amount_cents"] == 16800, inv1


def test_partial_approval_reprices_open_invoice(api):
    """PRD 3.11: "When the regulator grants a strictly partial amount —
    `granted_pct` greater than 0 and strictly less than `requested_increase_pct` —
    the filing moves from `FILED` to `PARTIALLY_APPROVED` and
    `approved_increase_pct` is set to the granted figure."
    PRD 3.11: "On a full or partial approval, every `OPEN` invoice for the policy
    whose `period_index` is at or after the filing's `effective_period_index` has
    its `amount_cents` recomputed."

    A +40% request partially granted at 25% effective at period 1 reprices an
    already-OPEN period-1 invoice to 12000*125/100 = 15000.

    Design: Difficulty/dual_variant_calc/premium_amount_increase_vs_no_increase_variant
    """
    ph = create_policyholder(full_name="Par Tial")
    policy = create_issued_policy(ph["id"])
    inv1 = add_premium_invoice(policy["id"], 1, base_premium_cents=12000,
                               due_date="2026-02-28", grace_deadline="2026-05-04")
    filing = get_success_data(api_client.create_rate_filing(
        {"policy_id": policy["id"], "requested_increase_pct": 40, "effective_period_index": 1}, UW))
    adjudicated = adjudicate_filing(policy["id"], filing["id"], 25)
    assert adjudicated["status"] == "PARTIALLY_APPROVED", adjudicated
    assert adjudicated["approved_increase_pct"] == 25, adjudicated

    refreshed = validate_success(api.get_premium_invoice(inv1["id"], UW))
    assert refreshed["amount_cents"] == 15000, refreshed


def test_rejected_filing_leaves_open_invoice_unchanged(api):
    """PRD 3.11: "When the regulator grants nothing — `granted_pct` equal to 0 —
    the filing moves from `FILED` to the terminal `REJECTED`,
    `approved_increase_pct` stays 0, and no invoices are repriced."

    A granted_pct=0 adjudication leaves an OPEN period-1 invoice at its base
    12000 and the filing REJECTED with approved_increase_pct 0.

    Design: Corner/state_machines/rate_filing_reject_branch_no_invoice_recompute
    """
    ph = create_policyholder(full_name="Rej Ect")
    policy = create_issued_policy(ph["id"])
    inv1 = add_premium_invoice(policy["id"], 1, base_premium_cents=12000,
                               due_date="2026-02-28", grace_deadline="2026-05-04")
    filing = get_success_data(api_client.create_rate_filing(
        {"policy_id": policy["id"], "requested_increase_pct": 40, "effective_period_index": 1}, UW))

    adjudicated = adjudicate_filing(policy["id"], filing["id"], 0)
    assert adjudicated["status"] == "REJECTED"
    assert adjudicated["approved_increase_pct"] == 0

    refreshed = validate_success(api.get_premium_invoice(inv1["id"], UW))
    assert refreshed["amount_cents"] == 12000, refreshed


# ===========================================================================
# combinatorial_formula / claim_payout_nested_min_over_charge_cap_monthly_pool
# ===========================================================================
def test_monthly_cap_clamps_indemnity_payout(api):
    """PRD 3.7: "That raw amount is then capped twice: it cannot exceed the
    remaining monthly headroom (`inflated_monthly_max_cents` minus the amount
    already paid this service month, floored at 0), and it cannot exceed the pool
    remaining. The line's `benefit_paid_cents` is the smallest of the raw
    entitlement, the monthly headroom, and the pool remaining"

    INDEMNITY daily cap 20000, monthly cap 45000, three days: 20000 + 20000 +
    5000 (monthly headroom clamps the third day) = 45000.

    Design: Difficulty/combinatorial_formula/claim_payout_nested_min_over_charge_cap_monthly_pool
    """
    ctx = setup_claim_under_review(
        lines=[("2026-03-01", 15000), ("2026-03-02", 25000), ("2026-03-03", 18000)],
        policy_overrides={"product_mode": "INDEMNITY", "monthly_benefit_max_cents": 45000})
    claim = approve_claim(ctx["pol_id"], ctx["claim_id"])
    assert claim["month_paid_cents"] == 45000, claim


def test_pool_clamps_indemnity_payout_to_remaining(api):
    """PRD 3.7: "That raw amount is then capped twice: it cannot exceed the
    remaining monthly headroom ... and it cannot exceed the pool remaining. The
    line's `benefit_paid_cents` is the smallest of the raw entitlement, the
    monthly headroom, and the pool remaining"

    INDEMNITY daily cap 20000 with a pool of only 30000: 20000 + 10000 (pool
    remaining clamps) + 0 = 30000.

    Design: Difficulty/combinatorial_formula/claim_payout_nested_min_over_charge_cap_monthly_pool
    """
    ctx = setup_claim_under_review(
        lines=[("2026-03-01", 15000), ("2026-03-02", 25000), ("2026-03-03", 18000)],
        policy_overrides={"product_mode": "INDEMNITY", "initial_pool_cents": 30000})
    claim = approve_claim(ctx["pol_id"], ctx["claim_id"])
    assert claim["month_paid_cents"] == 30000, claim


# ===========================================================================
# combinatorial_formula / inflation_growth_per_year_rounding_order_pinned
# ===========================================================================
def test_inflation_per_year_rounding_order_pinned(api):
    """PRD 3.2: "Starting from a base in cents, the system multiplies by one plus
    the rate and rounds the product half-up to the nearest cent, then repeats
    that multiply-and-round for each elapsed year in turn, always rounding before
    the next year's multiplication."
    PRD 3.2: "Summing across years first, or rounding only once at the very end,
    produces different cents and is incorrect."

    daily_max 20015 at COMPOUND_3PCT over two anniversaries:
    round(20015*1.03)=20615; round(20615*1.03)=21233 (round-once-at-end gives 21234).

    Design: Difficulty/combinatorial_formula/inflation_growth_per_year_rounding_order_pinned
    """
    ph = create_policyholder(full_name="Inf Test")
    policy = create_issued_policy(
        ph["id"], daily_benefit_max_cents=20015, monthly_benefit_max_cents=600450,
        initial_pool_cents=7305475, inflation_rider="COMPOUND_3PCT")
    get_success_data(api.apply_anniversary(policy["id"], UW))
    get_success_data(api.apply_anniversary(policy["id"], UW))

    refreshed = validate_success(api.get_policy(policy["id"], UW))
    assert refreshed["inflation_years_elapsed"] == 2, refreshed
    assert refreshed["inflated_daily_max_cents"] == 21233, refreshed


def test_inflation_5pct_one_year_half_up(api):
    """PRD 3.2: "a `COMPOUND_5PCT` rider grows at five percent per year (rate of
    0.05)."
    PRD 3.2: "the system multiplies by one plus the rate and rounds the product
    half-up to the nearest cent"
    PRD 2.8: "Wherever this document refers to rounding, it means round half-up to
    the nearest integer cent."

    daily_max 20010 at COMPOUND_5PCT over one anniversary:
    20010*1.05 = 21010.5 -> round half-up -> 21011.

    Design: Difficulty/combinatorial_formula/inflation_growth_per_year_rounding_order_pinned
    """
    ph = create_policyholder(full_name="Five Pct")
    policy = create_issued_policy(
        ph["id"], daily_benefit_max_cents=20010, monthly_benefit_max_cents=600300,
        initial_pool_cents=10005000, inflation_rider="COMPOUND_5PCT")
    get_success_data(api.apply_anniversary(policy["id"], UW))

    refreshed = validate_success(api.get_policy(policy["id"], UW))
    assert refreshed["inflation_years_elapsed"] == 1, refreshed
    assert refreshed["inflated_daily_max_cents"] == 21011, refreshed


def test_inflation_none_rider_leaves_base_unchanged(api):
    """PRD 3.2: "a `NONE` rider grows nothing (rate of 0)"; "An `Underwriter`
    advances inflation through an anniversary operation that adds exactly one to
    `inflation_years_elapsed`, recomputes the inflated maxima and pool"

    With NONE rider, after one anniversary inflated_daily_max_cents still equals
    the base 20000 while inflation_years_elapsed becomes 1.

    Design: Corner/calculations/inflation_growth_none_rider_no_change
    """
    ph = create_policyholder(full_name="No Infl")
    policy = create_issued_policy(ph["id"], daily_benefit_max_cents=20000, inflation_rider="NONE")
    get_success_data(api.apply_anniversary(policy["id"], UW))

    refreshed = validate_success(api.get_policy(policy["id"], UW))
    assert refreshed["inflation_years_elapsed"] == 1, refreshed
    assert refreshed["inflated_daily_max_cents"] == 20000, refreshed


# ===========================================================================
# Corner/calculations / elimination_period_self_pay_days_zero_benefit
# ===========================================================================
def test_elimination_period_self_pay_then_benefit(api):
    """PRD 3.7: "While elimination days remain owed, each qualifying day is
    consumed by the elimination period: its `elimination_applied` is set to true,
    its `benefit_paid_cents` is 0 (self-paid), and the owed count drops by one."
    PRD 3.9: "The policy's `elimination_days_satisfied` is the count of distinct
    service dates across all of the policy's approved claims whose lines are
    marked `is_qualifying_day`, capped at the policy's `elimination_period_days`."

    elimination_period_days=2: first two REIMBURSEMENT lines self-pay (0), third
    pays min(18000,20000)=18000; month_paid_cents=18000; elimination_days_satisfied=2.

    Design: Corner/calculations/elimination_period_self_pay_days_zero_benefit
    """
    ctx = setup_claim_under_review(
        lines=[("2026-03-01", 15000), ("2026-03-02", 25000), ("2026-03-03", 18000)],
        policy_overrides={"product_mode": "REIMBURSEMENT", "elimination_period_days": 2})
    claim = approve_claim(ctx["pol_id"], ctx["claim_id"])
    assert claim["month_paid_cents"] == 18000, claim

    policy = validate_success(api.get_policy(ctx["pol_id"], CE))
    assert policy["elimination_days_satisfied"] == 2, policy


# ===========================================================================
# Corner/cross_cutting / derived_field_remaining_pool_after_payment
# ===========================================================================
def test_remaining_pool_reconciles_after_payment(api):
    """PRD 3.7: "The benefit pool's `lifetime_paid_cents` is recomputed as the sum
    of all `CLAIM_PAYMENT` magnitudes, and its `remaining_pool_cents` is
    recomputed as `inflated_pool_cents` minus `lifetime_paid_cents`, floored at 0."

    One REIMBURSEMENT line charge 15000 (cap 20000) from a 10000000 pool:
    lifetime_paid_cents=15000, remaining_pool_cents=9985000.

    Design: Corner/cross_cutting_complexity_layers/derived_field_remaining_pool_after_payment
    """
    ctx = setup_claim_under_review(
        lines=[("2026-03-01", 15000)], policy_overrides={"product_mode": "REIMBURSEMENT"})
    claim = approve_claim(ctx["pol_id"], ctx["claim_id"])
    assert claim["month_paid_cents"] == 15000, claim

    pool = read_benefit_pool(ctx["pol_id"])
    assert pool["lifetime_paid_cents"] == 15000, pool
    assert pool["remaining_pool_cents"] == 9985000, pool
