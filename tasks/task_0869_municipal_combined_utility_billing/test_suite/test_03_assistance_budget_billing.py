"""Assistance enrollment and budget-billing enrollment, accrual, and levelization."""
from test_helpers import (
    validate_success, validate_error,
    TEST_USERS,
    open_account, enroll_budget_plan, setup_account_with_water_bill,
    setup_budget_plan_with_two_bills, assistance_payload,
)

BS = TEST_USERS["billing_specialist_headers"]
CW = TEST_USERS["assistance_caseworker_headers"]


def test_budget_billing_monthly_amount_computed_on_enroll(api):
    """PRD §3.4: "the plan's `monthly_budget_cents` is computed as the account's
    `prior_annual_charges_cents` divided by 12, rounded half up, and the plan opens in
    `status` `ACTIVE`."

    Design: Corner/calculations/budget_billing_monthly_amount_computed_on_enroll
    """
    account = open_account(api, account_holder_name="Bud Bea", prior_annual_charges_cents=48000)
    plan = enroll_budget_plan(api, account["id"])
    assert plan["monthly_budget_cents"] == 4000
    assert plan["status"] == "ACTIVE"


def test_levelization_true_up_positive_deferred_balance(api):
    """PRD §3.4: "Each time a bill is generated with `budget_billed` true, that bill's
    `total_due_cents` is set to the plan's `monthly_budget_cents` rather than to the actual
    metered cost — the actual charge is deferred — and the plan accrues:
    `cumulative_budgeted_cents` grows by `monthly_budget_cents` and `cumulative_actual_cents`
    grows by that bill's `actual_charges_cents`."
    PRD §3.4: "its `deferred_balance_cents` is set to `cumulative_actual_cents` minus
    `cumulative_budgeted_cents` — positive when the customer under-paid relative to true
    cost, negative when they over-paid — the plan advances `ACTIVE → TRUED_UP`".

    Design: Corner/calculations/levelization_true_up_deferred_balance_positive
    """
    ctx = setup_budget_plan_with_two_bills(api)
    assert ctx["bill1"]["total_due_cents"] == 4000
    assert ctx["bill1"]["actual_charges_cents"] == 4640
    plan = validate_success(api.true_up_plan(ctx["plan"]["id"], BS))
    assert plan["deferred_balance_cents"] == 1280
    assert plan["status"] == "TRUED_UP"


def test_budget_billed_bill_without_active_plan_rejected(api):
    """PRD §3.4: "A budget-billed bill requires an `ACTIVE` plan on the account; requesting
    one without such a plan is rejected with `ERR_NO_ACTIVE_PLAN`."

    Design: Corner/validations/budget_billed_bill_without_plan_returns_409
    """
    ctx = setup_account_with_water_bill(api, reading_value=9500, period_start="2026-01-01T00:00:00Z",
                                        period_end="2026-02-01T00:00:00Z")
    resp = api.create_bill(
        ctx["account"]["id"],
        {"period_start": "2026-02-01T00:00:00Z", "period_end": "2026-03-01T00:00:00Z", "budget_billed": True},
        BS,
    )
    validate_error(resp, "ERR_NO_ACTIVE_PLAN")


def test_assistance_enrollment_increments_account_version(api):
    """PRD §3.4: "Enrollment writes the account's `assistance_program` and
    `assistance_discount_pct` and increments the account's `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_assistance_enrollment
    """
    account = open_account(api, account_holder_name="Ver Val")
    assert account["version"] == 1
    updated = validate_success(api.enroll_assistance(account["id"], assistance_payload("SENIOR", 0.15), CW))
    assert updated["version"] == 2
    assert updated["assistance_program"] == "SENIOR"
