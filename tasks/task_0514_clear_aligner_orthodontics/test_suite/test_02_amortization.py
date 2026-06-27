"""Amortization schedule tests (PRD §3.7 / §3.6 Amortization).

Activation generates the installment schedule with per-installment rounding and
a residual-absorbing final installment so principal portions total exactly the
financed principal.
"""
from test_helpers import (
    validate_success, validate_paginated,
    setup_plan_approved, create_financing,
    api_client, TEST_USERS,
)

BILLING = TEST_USERS["billing_headers"]


def _activate_and_list(api, ctx, term_months=12, apr_bps=1499, down_payment_cents=0):
    fin = create_financing(
        ctx["case"]["id"], term_months=term_months,
        down_payment_cents=down_payment_cents, apr_bps=apr_bps,
    )
    validate_success(
        api.activate_financing_plan(
            fin["id"], {"expected_financing_plan_version": fin["version"]}, BILLING,
        ),
        200,
    )
    # Request a full page: the schedule has term_months installments and the
    # default page limit is 10, so a 12-month plan would otherwise be truncated.
    data, _meta = validate_paginated(
        api.list_installments(fin["id"], BILLING, params={"limit": term_months})
    )
    data = sorted(data, key=lambda i: i["sequence_no"])
    return fin, data


def test_amortization_first_installment_amount_and_principal_split(api):
    """PRD §3.6 Amortization: "that base payment is rounded half-up to whole
    cents. Each of installments 1 through the second-to-last carries this base
    payment as its `amount_cents`."
    PRD §3.6 Amortization: "for each installment, the interest portion is the
    running balance multiplied by the monthly rate, rounded half-up to whole
    cents; the `principal_portion_cents` is the base payment minus that interest;
    and the running balance is reduced by that principal portion before the next
    installment."

    Principal 300000, term 12, apr 1499 bps: installment 1 amount 27076, with a
    principal portion of 23328.

    Design: Difficulty/dual_variant_calc/amortization_per_installment_rounding_distinct_from_refund
    """
    ctx = setup_plan_approved(proposed_step_count=10, list_price_cents=375000)
    assert ctx["case"]["total_contracted_cents"] == 300000
    _fin, insts = _activate_and_list(api, ctx)
    i1 = insts[0]
    assert i1["amount_cents"] == 27076, i1["amount_cents"]
    assert i1["principal_portion_cents"] == 23328, i1["principal_portion_cents"]


def test_amortization_principal_portions_sum_to_financed_principal(api):
    """PRD §3.6 Amortization: "The final installment is made to absorb the
    residual: its `amount_cents` is the financed principal plus the total
    interest minus the sum of the earlier installments' amounts, so that the
    schedule's principal portions sum exactly to the financed principal and no
    rounding drift accumulates."

    Principal 300000, term 12, apr 1499 bps: principal portions sum to exactly
    300000 (distinct from a naive sum-then-round).

    Design: Difficulty/dual_variant_calc/amortization_per_installment_rounding_distinct_from_refund
    """
    ctx = setup_plan_approved(proposed_step_count=10, list_price_cents=375000)
    assert ctx["case"]["total_contracted_cents"] == 300000
    _fin, insts = _activate_and_list(api, ctx)
    total_principal = sum(i["principal_portion_cents"] for i in insts)
    assert total_principal == 300000, total_principal


def test_amortization_final_installment_absorbs_residual(api):
    """PRD §3.6 Amortization: "The final installment is made to absorb the
    residual: its `amount_cents` is the financed principal plus the total
    interest minus the sum of the earlier installments' amounts".

    Principal 300000, term 12, apr 1499 bps: the residual lands on installment
    12 making its amount 27079 (vs the base 27076 on installments 1-11).

    Design: Difficulty/combinatorial_formula/amortization_mode_b_per_installment_rounding_order
    """
    ctx = setup_plan_approved(proposed_step_count=10, list_price_cents=375000)
    assert ctx["case"]["total_contracted_cents"] == 300000
    _fin, insts = _activate_and_list(api, ctx)
    i12 = insts[11]
    assert i12["sequence_no"] == 12
    assert i12["amount_cents"] == 27079, i12["amount_cents"]


def test_amortization_schedule_total_includes_interest(api):
    """PRD §3.6 Amortization: "Activation generates `term_months` `Installment`
    rows from the financed principal in a pinned order so that the scheduled
    amounts total exactly the financed principal plus all interest."

    Principal 300000, term 12, apr 1499 bps: the scheduled amounts total 324915
    (= 300000 principal + 24915 interest), more than principal because interest
    is added per installment.

    Design: Difficulty/combinatorial_formula/amortization_mode_b_per_installment_rounding_order
    """
    ctx = setup_plan_approved(proposed_step_count=10, list_price_cents=375000)
    assert ctx["case"]["total_contracted_cents"] == 300000
    _fin, insts = _activate_and_list(api, ctx)
    total = sum(i["amount_cents"] for i in insts)
    assert total == 324915, total
