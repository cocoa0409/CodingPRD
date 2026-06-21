"""Financing and lease-to-own — the monthly schedule, the dual payoff conventions,
the cyclic plan lifecycle, the affordability gates, payoff, and OCC on the order.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_error_is_one_of,
    get_success_data, TEST_USERS,
    create_customer, create_sofa_product, create_draft_order, add_line, pay_in_full,
    apply_financing, post_payment, setup_pending_financing_plan,
    setup_active_financing_plan, setup_plan_after_payments,
)

SA = TEST_USERS["sales_associate_headers"]
SM = TEST_USERS["store_manager_headers"]


# ─── Difficulty: monthly payment — branch + ceil non-linear ───────────────
def test_installment_monthly_payment_and_total(api):
    """PRD 3.5: "For an `INSTALLMENT` plan, the system applies simple add-on interest: it
    takes the principal multiplied by 1,200 basis points (that is, by 1,200 divided by
    10,000), prorated by the term as `term_months` divided by 12, and rounds that interest
    half-up to whole cents; `total_of_payments_cents` is the principal plus that interest,
    and `monthly_payment_cents` is that total divided by `term_months`, rounded **up** to
    the next whole cent."

    Principal 116802, term 12 -> total 130818, monthly 10902.

    Design: Difficulty/combinatorial_formula/financing_monthly_payment_branch_and_ceil_nonlinear
    """
    customer, product, order, line, plan = setup_active_financing_plan(
        plan_type="INSTALLMENT", term_months=12)
    assert plan["financed_principal_cents"] == 116802
    assert plan["total_of_payments_cents"] == 130818
    assert plan["monthly_payment_cents"] == 10902


def test_lease_to_own_monthly_payment_branch(api):
    """PRD 3.5: "For a `LEASE_TO_OWN` plan, no interest is computed; instead
    `total_of_payments_cents` is the principal multiplied by 13 and divided by 10 — a flat
    1.30 times markup — rounded half-up to whole cents, and `monthly_payment_cents` is that
    total divided by `term_months`, again rounded **up** to the next whole cent."

    Second test for this instance: the lease branch takes the markup path, not interest.
    Principal 116802, term 12 -> total 151843, monthly 12654.

    Design: Difficulty/combinatorial_formula/financing_monthly_payment_branch_and_ceil_nonlinear
    """
    customer, product, order, line, plan = setup_active_financing_plan(
        plan_type="LEASE_TO_OWN", term_months=12)
    assert plan["financed_principal_cents"] == 116802
    assert plan["total_of_payments_cents"] == 151843
    assert plan["monthly_payment_cents"] == 12654


# ─── Difficulty: payoff balance dual variant ──────────────────────────────
def test_installment_payoff_rebates_unearned_interest(api):
    """PRD 3.6: "For an INSTALLMENT plan, early payoff rebates unearned interest by the
    sum-of-digits method ... the payoff balance is then total_of_payments_cents minus
    paid_to_date_cents, minus that unearned-interest rebate."

    After 3 payments of 10902 on the installment plan, payoff_balance == 90026.

    Design: Difficulty/dual_variant_calc/payoff_balance_installment_rebate_vs_lease_no_rebate
    """
    order, plan_id = setup_plan_after_payments(
        [10902, 10902, 10902], plan_type="INSTALLMENT", term_months=12)
    plan = get_success_data(api.get_financing_plan(plan_id, SA))
    assert plan["payoff_balance_cents"] == 90026


def test_lease_payoff_no_rebate(api):
    """PRD 3.6: "For a LEASE_TO_OWN plan, the markup is never rebated: the payoff balance
    is simply total_of_payments_cents minus paid_to_date_cents."

    Second test for this instance: same 3 payments on a lease plan -> payoff 113881,
    diverging from the installment rebate by 23855.

    Design: Difficulty/dual_variant_calc/payoff_balance_installment_rebate_vs_lease_no_rebate
    """
    order, plan_id = setup_plan_after_payments(
        [12654, 12654, 12654], plan_type="LEASE_TO_OWN", term_months=12)
    plan = get_success_data(api.get_financing_plan(plan_id, SA))
    assert plan["payoff_balance_cents"] == 113881


# ─── Difficulty: cyclic CURRENT -> PAST_DUE -> CURRENT ────────────────────
def test_financing_plan_cycles_current_pastdue_current(api):
    """PRD 3.6: "A payment posted against a `PAST_DUE` plan whose `amount_cents` is below
    the payoff balance restores the schedule only if it brings `paid_to_date_cents` up to
    at least `monthly_payment_cents` multiplied by the number of periods elapsed; if it
    does, the plan moves `PAST_DUE → CURRENT` ..."

    Approve, pay 1 month, advance clock 2 months, mark past due, then a catch-up payment
    returns the plan to CURRENT.

    Design: Difficulty/non_linear_state_machine/financing_plan_cyclic_current_pastdue_current
    """
    get_success_data(api.set_clock({"to_iso8601": "2026-01-01T00:00:00Z"}, SM))
    product = create_sofa_product()
    customer = create_customer(credit_score=760, monthly_income_cents=9000000,
                               existing_monthly_obligations_cents=0)
    order = create_draft_order(customer["id"])
    add_line(order["id"], product["id"])
    fresh = get_success_data(api.get_order(order["id"], SA))
    plan = apply_financing(order["id"], fresh["version"],
                           plan_type="INSTALLMENT", term_months=12)
    get_success_data(api.approve_financing_plan(plan["id"], SM))
    post_payment(plan["id"], 10902)
    get_success_data(api.set_clock({"to_iso8601": "2026-03-02T00:00:00Z"}, SM))
    get_success_data(api.mark_past_due_financing_plan(plan["id"], SM))
    post_payment(plan["id"], 10902)  # catch-up
    after = get_success_data(api.get_financing_plan(plan["id"], SA))
    assert after["status"] == "CURRENT", "catch-up payment restores schedule"
    assert after["payments_made_count"] == 2
    assert after["paid_to_date_cents"] == 21804


def test_mark_past_due_then_catch_up_payment_count(api):
    """PRD 3.6: "A `StoreManager` may flag a current plan as overdue, moving it `CURRENT
    → PAST_DUE`, but only when a period is genuinely owed ..."

    Second test for this instance: after marking past due (the node we cycle through),
    the plan is genuinely PAST_DUE before the catch-up returns it.

    Design: Difficulty/non_linear_state_machine/financing_plan_cyclic_current_pastdue_current
    """
    get_success_data(api.set_clock({"to_iso8601": "2026-01-01T00:00:00Z"}, SM))
    product = create_sofa_product()
    customer = create_customer(credit_score=760)
    order = create_draft_order(customer["id"])
    add_line(order["id"], product["id"])
    fresh = get_success_data(api.get_order(order["id"], SA))
    plan = apply_financing(order["id"], fresh["version"],
                           plan_type="INSTALLMENT", term_months=12)
    get_success_data(api.approve_financing_plan(plan["id"], SM))
    post_payment(plan["id"], 10902)
    get_success_data(api.set_clock({"to_iso8601": "2026-03-02T00:00:00Z"}, SM))
    pd = get_success_data(api.mark_past_due_financing_plan(plan["id"], SM))
    assert pd["status"] == "PAST_DUE"


# ─── Difficulty: DTI inclusive boundary ───────────────────────────────────
def test_dti_exactly_043_passes(api):
    """PRD 3.5: "the sum of `existing_monthly_obligations_cents` and
    `monthly_payment_cents`, multiplied by 100, must be at most 43 multiplied by
    `monthly_income_cents`."

    monthly 10902, obligations 20, income 25400: (20+10902)*100 = 1092200 == 43*25400 =
    1092200 -> inclusive boundary PASSES.

    Design: Difficulty/boundary_precision_check/dti_inclusive_boundary_equal_043_passes
    """
    product = create_sofa_product()
    customer = create_customer(credit_score=700, monthly_income_cents=25400,
                               existing_monthly_obligations_cents=20)
    order = create_draft_order(customer["id"])
    add_line(order["id"], product["id"])
    fresh = get_success_data(api.get_order(order["id"], SA))
    plan = apply_financing(order["id"], fresh["version"],
                           plan_type="INSTALLMENT", term_months=12)
    res = api.approve_financing_plan(plan["id"], SM)
    approved = validate_success(res, 200)
    assert approved["status"] == "CURRENT", "DTI exactly 0.43 is within the inclusive gate"


def test_dti_just_over_043_rejected(api):
    """PRD 3.5: "The **debt-to-income gate** requires that the customer's existing
    obligations plus this plan's payment stay within 43 percent of income ... A violation
    is rejected with `ERR_DTI_EXCEEDED`."

    Boundary X-1 on income: income 25399 makes 43*income = 1092157 < 1092200 -> FAILS.

    Design: Difficulty/boundary_precision_check/dti_inclusive_boundary_equal_043_passes
    """
    product = create_sofa_product()
    customer = create_customer(credit_score=700, monthly_income_cents=25399,
                               existing_monthly_obligations_cents=20)
    order = create_draft_order(customer["id"])
    add_line(order["id"], product["id"])
    fresh = get_success_data(api.get_order(order["id"], SA))
    plan = apply_financing(order["id"], fresh["version"],
                           plan_type="INSTALLMENT", term_months=12)
    res = api.approve_financing_plan(plan["id"], SM)
    validate_error(res, "ERR_DTI_EXCEEDED")


# ─── Corner: credit-too-low at approval ───────────────────────────────────
def test_credit_too_low_lease_to_own(api):
    """PRD 3.5: "The **credit gate** requires the customer's `credit_score` to be at least
    the floor for the plan type — 640 for an `INSTALLMENT` plan, 600 for a `LEASE_TO_OWN`
    plan — and a shortfall is rejected with `ERR_CREDIT_TOO_LOW`."

    Design: Corner/validations/financing_credit_too_low_on_approve
    """
    product = create_sofa_product()
    customer = create_customer(credit_score=550, monthly_income_cents=9000000,
                               existing_monthly_obligations_cents=0)
    order = create_draft_order(customer["id"])
    add_line(order["id"], product["id"])
    fresh = get_success_data(api.get_order(order["id"], SA))
    plan = apply_financing(order["id"], fresh["version"],
                           plan_type="LEASE_TO_OWN", term_months=12)
    res = api.approve_financing_plan(plan["id"], SM)
    validate_error(res, "ERR_CREDIT_TOO_LOW")


# ─── Corner: financing on a settled order ─────────────────────────────────
def test_financing_on_settled_order_rejected(api):
    """PRD 3.5: "an application against an already-settled order, or one that would
    duplicate an open plan, is rejected (the open-plan collision surfaces as
    `ERR_FINANCING_EXISTS`, an already-settled order as `ERR_ALREADY_SETTLED`)."

    The YAML pins only HTTP 409; PRD leaves two faithful error_ids for a PAID_IN_FULL
    order, so accept either.

    Design: Corner/validations/financing_application_on_settled_order_returns_financing_exists
    """
    product = create_sofa_product()
    customer = create_customer()
    order = create_draft_order(customer["id"])
    add_line(order["id"], product["id"])
    pay_in_full(order["id"])
    fresh = get_success_data(api.get_order(order["id"], SA))
    res = api.create_financing_plan({
        "order_id": order["id"], "plan_type": "INSTALLMENT", "term_months": 12,
        "expected_order_version": fresh["version"]}, SA)
    validate_error_is_one_of(res, ["ERR_ALREADY_SETTLED", "ERR_FINANCING_EXISTS"])


# ─── Corner: payoff in one shot ───────────────────────────────────────────
def test_payoff_in_one_shot_sets_order_paid_in_full(api):
    """PRD 3.6: "a payment whose `amount_cents` is at least the current
    `payoff_balance_cents` pays the plan off in one shot, moving it to `PAID_OFF`: ...
    `payoff_balance_cents` is set to 0, the order's `payment_status` is set to
    `PAID_IN_FULL`, the customer's `open_financing_count` is decremented by one ..."

    Design: Corner/state_machines/financing_payoff_in_one_shot_sets_order_paid_in_full
    """
    customer, product, order, line, plan = setup_active_financing_plan(
        plan_type="INSTALLMENT", term_months=12)
    validate_success(api.create_payment(plan["id"], {"amount_cents": 116802}, SA), 201)
    paid_plan = get_success_data(api.get_financing_plan(plan["id"], SA))
    assert paid_plan["status"] == "PAID_OFF"
    assert paid_plan["payoff_balance_cents"] == 0
    paid_order = get_success_data(api.get_order(order["id"], SA))
    assert paid_order["payment_status"] == "PAID_IN_FULL"
    paid_cust = get_success_data(api.get_customer(customer["id"], SA))
    assert paid_cust["open_financing_count"] == 0


# ─── Corner: too many open plans ──────────────────────────────────────────
def _approved_plan_for_new_order(api, customer_id, product_id):
    order = create_draft_order(customer_id)
    add_line(order["id"], product_id)
    fresh = get_success_data(api.get_order(order["id"], SA))
    plan = apply_financing(order["id"], fresh["version"],
                           plan_type="INSTALLMENT", term_months=12)
    get_success_data(api.approve_financing_plan(plan["id"], SM))
    return order


def test_third_open_plan_rejected(api):
    """PRD 3.5: "The **open-plan gate** requires the customer's `open_financing_count` to
    be strictly fewer than 2 open plans; reaching that ceiling is rejected with
    `ERR_TOO_MANY_OPEN_PLANS`."

    Design: Corner/errors/error_too_many_open_plans_on_third_approval
    """
    product = create_sofa_product()
    customer = create_customer(credit_score=800, monthly_income_cents=50000000,
                               existing_monthly_obligations_cents=0)
    _approved_plan_for_new_order(api, customer["id"], product["id"])
    _approved_plan_for_new_order(api, customer["id"], product["id"])
    # third plan pending, awaiting approval
    order3 = create_draft_order(customer["id"])
    add_line(order3["id"], product["id"])
    fresh = get_success_data(api.get_order(order3["id"], SA))
    plan3 = apply_financing(order3["id"], fresh["version"],
                            plan_type="INSTALLMENT", term_months=12)
    res = api.approve_financing_plan(plan3["id"], SM)
    validate_error(res, "ERR_TOO_MANY_OPEN_PLANS")


# ─── Corner: principal snapshot pinned at approval ────────────────────────
def test_financed_principal_snapshot_at_approval(api):
    """PRD 3.5: "First the plan snapshots `financed_principal_cents` as the order's
    current `order_total_cents`, version-pinned at this moment."

    Single-line sofa order_total 116802 -> financed_principal 116802 at approval.

    Design: Corner/cross_cutting_complexity_layers/financing_principal_snapshot_pinned_at_approval
    """
    customer, product, order, line, plan = setup_active_financing_plan(
        plan_type="INSTALLMENT", term_months=12)
    assert plan["financed_principal_cents"] == 116802


# ─── Difficulty: compensating invariant — open_financing_count conserved ──
def test_approve_increments_open_financing_count(api):
    """PRD 3.5: "On a successful approval ... the customer's `open_financing_count` is
    incremented by one ..."

    Design: Difficulty/compensating_invariant/financing_approve_then_decline_conserves_open_financing_count
    """
    customer, product, order, line, plan = setup_active_financing_plan(
        plan_type="INSTALLMENT", term_months=12, customer_overrides={"credit_score": 760})
    after_approve = get_success_data(api.get_customer(customer["id"], SA))
    assert after_approve["open_financing_count"] == 1, "approval increments the counter"


def test_cancel_order_declines_plan_and_restores_count(api):
    """PRD 3.11: "any `FinancingPlan` on the order in `PENDING_APPROVAL` or `CURRENT`
    status is set to `DECLINED` with the customer's `open_financing_count` recomputed
    accordingly."

    Approve -> count 1; cancelling the order cascades the CURRENT plan to DECLINED and
    recomputes the count back to 0 (zero drift).

    Design: Difficulty/compensating_invariant/financing_approve_then_decline_conserves_open_financing_count
    """
    customer, product, order, line, plan = setup_active_financing_plan(
        plan_type="INSTALLMENT", term_months=12, customer_overrides={"credit_score": 760})
    # Order is FINANCED + DRAFT; confirm it (no stop booked) so cancel is from CONFIRMED.
    get_success_data(api.confirm_order(order["id"], SA))
    after_approve = get_success_data(api.get_customer(customer["id"], SA))
    assert after_approve["open_financing_count"] == 1
    get_success_data(api.cancel_order(order["id"], SA))
    after_cancel = get_success_data(api.get_customer(customer["id"], SA))
    assert after_cancel["open_financing_count"] == 0, "cascade decline restores the count"
    plan_after = get_success_data(api.get_financing_plan(plan["id"], SA))
    assert plan_after["status"] == "DECLINED"


# ─── Corner: OCC stale order version on financing apply ───────────────────
def test_financing_apply_stale_order_version_rejected(api):
    """PRD 2.10: "applying for a financing plan requires `expected_order_version` carrying
    the client's last-observed `version` of the target `Order`; if that value does not
    equal the order's current `version` ... the application is rejected with
    `ERR_STALE_VERSION` (HTTP 412) ..."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_order_version_on_financing_apply_returns_412
    """
    product = create_sofa_product()
    customer = create_customer(credit_score=760)
    order = create_draft_order(customer["id"])
    add_line(order["id"], product["id"])
    stale = get_success_data(api.get_order(order["id"], SA))["version"]
    add_line(order["id"], product["id"])  # advances order.version past `stale`
    res = api.create_financing_plan({
        "order_id": order["id"], "plan_type": "INSTALLMENT", "term_months": 12,
        "expected_order_version": stale}, SA)
    validate_error(res, "ERR_STALE_VERSION")
