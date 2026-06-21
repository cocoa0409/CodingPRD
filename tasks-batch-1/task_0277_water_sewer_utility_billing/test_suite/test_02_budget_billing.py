"""Budget billing: flat-installment estimate vs chronological true-up, and the
optimistic-concurrency guard on enrollment.

Translates Difficulty queue: dual_variant_calc (estimate vs true-up),
combinatorial_formula (chronological evaluation-order). Corner queue:
cross_cutting_complexity_layers (OCC stale version, supersede with correct version).
"""
from test_helpers import (
    validate_success, validate_error,
    setup_budget_plan_two_posted_bills,
    fixtures, factories, TEST_USERS, ApiErrorId,
)

CLERK = TEST_USERS["billing_clerk_headers"]


# ===========================================================================
# Estimate variant vs chronological true-up (dual_variant_calc)
# ===========================================================================
def test_budget_estimate_installment_independent_of_actual(api):
    """PRD §3.7: "While a plan is `ACTIVE`, the **estimate** variant governs each
    cycle: the bill's `budget_billing_amount_cents` is set to the plan's
    `monthly_amount_cents`, and the bill's `total_cents` is that same flat
    installment — a forward estimate that is deliberately independent of the cycle's
    actual `amount_billed_cents`."

    Design: Difficulty/dual_variant_calc/budget_billing_estimate_vs_chronological_trueup
    """
    ctx = setup_budget_plan_two_posted_bills(monthly_amount_cents=10000)
    bill1 = validate_success(api.get_bill(ctx["bill1"]["id"], CLERK))
    bill2 = validate_success(api.get_bill(ctx["bill2"]["id"], CLERK))
    # actual amounts differ between cycles, but total_cents is the flat installment
    assert bill1["amount_billed_cents"] == 18980
    assert bill1["total_cents"] == 10000
    assert bill2["amount_billed_cents"] == 7240
    assert bill2["total_cents"] == 10000


def test_budget_trueup_chronological_delta(api):
    """PRD §3.7: "the system accumulates the actual `amount_billed_cents` across the
    account's `POSTED` and `PAID` bills since enrollment, taken in chronological
    order of their `created_at` ascending, to obtain the actual-to-date figure; it
    computes installments-to-date as the plan's `cycles_elapsed` multiplied by its
    `monthly_amount_cents`; and it sets `trued_up_delta_cents` to actual-to-date
    minus installments-to-date"

    Design: Difficulty/dual_variant_calc/budget_billing_estimate_vs_chronological_trueup
    """
    ctx = setup_budget_plan_two_posted_bills(monthly_amount_cents=10000)
    plan = validate_success(api.true_up_budget_plan(ctx["plan"]["id"], CLERK))
    # actual_to_date 18980 + 7240 = 26220 ; installments 2*10000 = 20000 ; delta 6220
    assert plan["trued_up_delta_cents"] == 6220


# ===========================================================================
# Chronological evaluation-order pinning (combinatorial_formula mode c)
# ===========================================================================
def test_budget_trueup_cycles_elapsed_and_final_state(api):
    """PRD §3.5: "If the account is on an `ACTIVE` budget-billing plan, posting also
    increments that plan's `cycles_elapsed` by one and recomputes its
    `trued_up_delta_cents` as a cascade."
    PRD §3.7: "This delta is posted to the account's ledger as an adjustment to
    `balance_due_cents`, and the plan moves to `TRUED_UP`."

    Design: Difficulty/combinatorial_formula/budget_trueup_chronological_circular_eval_mode_c
    """
    ctx = setup_budget_plan_two_posted_bills(monthly_amount_cents=10000)
    plan = validate_success(api.true_up_budget_plan(ctx["plan"]["id"], CLERK))
    assert plan["cycles_elapsed"] == 2
    assert plan["trued_up_delta_cents"] == 6220
    assert plan["status"] == "TRUED_UP"


def test_budget_trueup_delta_value_well_defined(api):
    """PRD §3.7: "it sets `trued_up_delta_cents` to actual-to-date minus
    installments-to-date — a positive delta meaning the account underpaid relative
    to true consumption."
    PRD §3.7: "The accumulation is strictly chronological; bill `id` is never used
    as a tie-break."

    Design: Difficulty/combinatorial_formula/budget_trueup_chronological_circular_eval_mode_c
    """
    ctx = setup_budget_plan_two_posted_bills(monthly_amount_cents=10000)
    plan = validate_success(api.true_up_budget_plan(ctx["plan"]["id"], CLERK))
    assert plan["trued_up_delta_cents"] == 6220


# ===========================================================================
# OCC: stale account version (cross_cutting_complexity_layers)
# ===========================================================================
def test_budget_plan_stale_account_version_returns_412(api):
    """PRD §2.7: "If another writer has advanced the account's `version` since the
    client read it, the two will not match and the enrollment is rejected with
    `ERR_STALE_ACCOUNT_VERSION` (HTTP 412)."
    PRD §3.7: "Enrollment increments the account's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/budget_plan_stale_account_version_returns_412
    """
    rs = fixtures.create_rate_schedule()
    account = fixtures.create_account(rs["id"])
    v0 = account["version"]
    validate_success(
        api.create_budget_plan(account["id"], factories.budget_plan_payload(10000, v0), CLERK), 201)
    # Second enrollment carrying the now-stale pre-enrollment version
    resp = api.create_budget_plan(account["id"], factories.budget_plan_payload(12000, v0), CLERK)
    validate_error(resp, ApiErrorId.ERR_STALE_ACCOUNT_VERSION.value)


def test_budget_plan_supersede_with_correct_version_succeeds(api):
    """PRD §3.7: "because a new plan supersedes any prior one — moves any previously
    `ACTIVE` plan to `CANCELLED`."
    PRD §2.7: "When they do match, the enrollment proceeds and increments the
    account's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/budget_plan_supersede_correct_version_succeeds
    """
    rs = fixtures.create_rate_schedule()
    account = fixtures.create_account(rs["id"])
    plan1 = validate_success(
        api.create_budget_plan(account["id"], factories.budget_plan_payload(10000, account["version"]), CLERK), 201)
    refreshed = validate_success(api.get_account(account["id"], CLERK))
    plan2 = validate_success(
        api.create_budget_plan(account["id"], factories.budget_plan_payload(12000, refreshed["version"]), CLERK), 201)
    assert plan2["status"] == "ACTIVE"
    plan1_after = validate_success(api.list_budget_plans(account["id"], CLERK))
    statuses = {p["id"]: p["status"] for p in plan1_after}
    assert statuses[plan1["id"]] == "CANCELLED"
    acct_after = validate_success(api.get_account(account["id"], CLERK))
    assert acct_after["budget_billing_enrolled"] is True
