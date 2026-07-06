"""Financing plans, payments, payoff quotes, and invoicing.

Covers the dual scheduled-vs-early payoff quote, per-line tax rounding, the
state-before-fiscal validation ordering on payment, principal conservation across
payment/reversal, and invoice/void balance accounting.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId, TEST_USERS,
)
from test_helpers.fixtures import (
    create_customer, create_invoice, setup_financing_plan, post_payment,
)
from test_helpers.factories import create_invoice_payload, create_payment_payload

SALES = TEST_USERS["salesrep_headers"]
BILLING = TEST_USERS["billingadmin_headers"]


# ── Difficulty/dual_variant_calc/financing_scheduled_vs_early_payoff ─────────

def _plan_after_three_payments(api):
    customer, contract, plan = setup_financing_plan(
        original_principal_cents=1200000, apr_bps=1000, term_months=12)
    for _ in range(3):
        post_payment(plan["id"], amount_cents=110000)
    return plan


def test_payoff_quote_scheduled_and_early_diverge_after_three_payments(api):
    """PRD §3.7: "On the scheduled path, `scheduled_remaining_cents` is the plan's
    `monthly_payment_cents` multiplied by the remaining installments, carrying all future
    interest. On the early path, `early_payoff_cents` is the plan's current
    `remaining_principal_cents` plus a prepay fee of two percent of that remaining
    principal — the remaining principal multiplied by 200 basis points divided by 10000,
    rounded half up to whole cents."

    After 3 payments: scheduled = 110000*9 = 990000; early = 900000 + 18000 = 918000.

    Design: Difficulty/dual_variant_calc/financing_scheduled_vs_early_payoff
    """
    plan = _plan_after_three_payments(api)
    quote = validate_success(api.get_payoff_quote(plan["id"], BILLING), 200)
    assert quote["scheduled_remaining_cents"] == 990000, quote
    assert quote["early_payoff_cents"] == 918000, quote
    assert quote["scheduled_remaining_cents"] != quote["early_payoff_cents"], quote


def test_remaining_principal_after_three_payments(api):
    """PRD §3.7: "A successful payment is created in `POSTED` `status` with its
    `payment_date` captured from the logical clock, and the plan's
    `remaining_principal_cents` is reduced by the principal portion."

    Three 110000 payments (principal portion 100000 each) reduce remaining principal from
    1200000 to 900000.

    Design: Difficulty/dual_variant_calc/financing_scheduled_vs_early_payoff
    """
    plan = _plan_after_three_payments(api)
    fetched = validate_success(api.get_financing_plan(plan["id"], BILLING), 200)
    assert fetched["remaining_principal_cents"] == 900000, fetched


# ── Difficulty/compensating_invariant/financing_principal_conserved ──────────

def test_payment_reversal_marks_payment_reversed(api):
    """PRD §3.7: "A `BillingAdmin` reverses a payment, moving it from `POSTED` to
    `REVERSED` (permitted only while the payment is `POSTED`, otherwise
    `ERR_PAYMENT_NOT_POSTED`) and only while the parent plan is `ACTIVE` (otherwise
    `ERR_PLAN_NOT_ACTIVE`); as the compensating action, the plan's
    `remaining_principal_cents` is increased by the reversed payment's
    `principal_portion_cents`."

    Design: Difficulty/compensating_invariant/financing_principal_conserved
    """
    customer, contract, plan = setup_financing_plan(
        original_principal_cents=1200000, apr_bps=1000, term_months=12)
    payment = post_payment(plan["id"], amount_cents=110000)
    reversed_payment = validate_success(api.reverse_payment(payment["id"], BILLING), 200)
    assert reversed_payment["status"] == "REVERSED", reversed_payment


def test_payment_reversal_restores_remaining_principal(api):
    """PRD §3.7: "as the compensating action, the plan's `remaining_principal_cents` is
    increased by the reversed payment's `principal_portion_cents`."

    The payment (-100000 principal) and its reversal (+100000) restore remaining principal
    to the original 1200000.

    Design: Difficulty/compensating_invariant/financing_principal_conserved
    """
    customer, contract, plan = setup_financing_plan(
        original_principal_cents=1200000, apr_bps=1000, term_months=12)
    payment = post_payment(plan["id"], amount_cents=110000)
    validate_success(api.reverse_payment(payment["id"], BILLING), 200)
    fetched = validate_success(api.get_financing_plan(plan["id"], BILLING), 200)
    assert fetched["remaining_principal_cents"] == 1200000, fetched


# ── Difficulty/priority_pair_validation_conflict/payment_state_vs_overpayment_conflict

def _paid_off_plan(api):
    customer, contract, plan = setup_financing_plan(
        original_principal_cents=200000, apr_bps=0, term_months=2)
    post_payment(plan["id"], amount_cents=100000)
    post_payment(plan["id"], amount_cents=100000)
    return plan


def test_payment_on_paid_off_plan_reports_plan_not_active(api):
    """PRD §2.8: "Only once the body is well-formed does the system evaluate ownership
    (for the entity-backed roles), then the target resource's own state, then the
    cross-entity and business rules described throughout §3, and finally — for booking
    alone — the optimistic-concurrency version check."
    PRD §3.7: "Posting is allowed only while the plan is `ACTIVE` (otherwise
    `ERR_PLAN_NOT_ACTIVE`)."

    A payment against a PAID_OFF plan (remaining 0) violates both the state precondition
    and the overpayment rule; the earlier state check yields ERR_PLAN_NOT_ACTIVE.

    Design: Difficulty/priority_pair_validation_conflict/payment_state_vs_overpayment_conflict
    """
    plan = _paid_off_plan(api)
    resp = api.create_payment(plan["id"], create_payment_payload(amount_cents=100000),
                              BILLING)
    error = validate_error(resp, ApiErrorId.ERR_PLAN_NOT_ACTIVE.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_OVERPAYMENT.value, error


def test_paid_off_plan_reaches_terminal_state(api):
    """PRD §3.7: "When that reduction brings `remaining_principal_cents` to exactly zero,
    the plan automatically transitions from `ACTIVE` to `PAID_OFF` (terminal)."

    Two 100000 payments retire the 200000 principal and leave the plan PAID_OFF.

    Design: Difficulty/priority_pair_validation_conflict/payment_state_vs_overpayment_conflict
    """
    plan = _paid_off_plan(api)
    fetched = validate_success(api.get_financing_plan(plan["id"], BILLING), 200)
    assert fetched["status"] == "PAID_OFF", fetched


# ── Difficulty/combinatorial_formula/invoice_per_line_tax_rounding_mode_b ─────

def _three_taxable_lines_invoice(api):
    customer = create_customer(name="Dan Owner", service_address="4 Fir St",
                               roofline_feet=100)
    return validate_success(api.create_invoice(create_invoice_payload(
        customer["id"], source_type="MANUAL", tax_rate_bps=500, line_items=[
            {"description": "L1", "amount_cents": 1010, "taxable": True},
            {"description": "L2", "amount_cents": 1010, "taxable": True},
            {"description": "L3", "amount_cents": 1010, "taxable": True},
        ]), BILLING), 201)


def test_invoice_tax_rounded_per_line_then_summed(api):
    """PRD §3.8: "The `tax_cents` is computed per line and then summed: for each line whose
    `taxable` flag is true, the system rounds half up the line's `amount_cents` multiplied
    by the `tax_rate_bps` and divided by 10000, and the invoice tax is the sum of those
    per-line rounded amounts — rounding is applied independently to each taxable line
    before summation, never once over the aggregate."

    Three 1010 lines at 500 bps: round_half_up(50.5)=51 each -> 153 (not sum-then-round 152).

    Design: Difficulty/combinatorial_formula/invoice_per_line_tax_rounding_mode_b
    """
    inv = _three_taxable_lines_invoice(api)
    assert inv["tax_cents"] == 153, inv


def test_invoice_subtotal_and_total_with_per_line_tax(api):
    """PRD §3.8: "The `subtotal_cents` is the sum of `amount_cents` across all line items."
    PRD §3.8: "The `total_cents` is the subtotal plus the tax."

    subtotal 3030, tax 153 -> total 3183.

    Design: Difficulty/combinatorial_formula/invoice_per_line_tax_rounding_mode_b
    """
    inv = _three_taxable_lines_invoice(api)
    assert inv["subtotal_cents"] == 3030, inv
    assert inv["total_cents"] == 3183, inv


# ── Corner/calculations/payoff_quote_no_payments_correct_result ──────────────

def test_payoff_quote_with_no_payments(api):
    """PRD §3.7: "It first counts the plan's `POSTED` payments and derives
    `remaining_installments` as the plan's `term_months` minus that posted count. On the
    scheduled path, `scheduled_remaining_cents` is the plan's `monthly_payment_cents`
    multiplied by the remaining installments, carrying all future interest. On the early
    path, `early_payoff_cents` is the plan's current `remaining_principal_cents` plus a
    prepay fee of two percent of that remaining principal — the remaining principal
    multiplied by 200 basis points divided by 10000, rounded half up to whole cents."

    Zero payments: scheduled = 110000*12 = 1320000; early = 1200000 + 24000 = 1224000.

    Design: Corner/calculations/payoff_quote_no_payments_correct_result
    """
    customer, contract, plan = setup_financing_plan(
        original_principal_cents=1200000, apr_bps=1000, term_months=12)
    quote = validate_success(api.get_payoff_quote(plan["id"], BILLING), 200)
    assert quote["scheduled_remaining_cents"] == 1320000, quote
    assert quote["early_payoff_cents"] == 1224000, quote
    assert quote["remaining_principal_cents"] == 1200000, quote


# ── Corner/calculations/invoice_zero_tax_rate_default ────────────────────────

def test_invoice_omitted_tax_rate_defaults_to_zero(api):
    """PRD §3.8: "Optionally the admin supplies a `tax_rate_bps` in basis points
    (defaulting to 0)"
    PRD §3.8: "The `total_cents` is the subtotal plus the tax."

    Omitting tax_rate_bps yields tax 0 and total equal to the 7000 subtotal.

    Design: Corner/calculations/invoice_zero_tax_rate_default
    """
    customer = create_customer(name="Tax0 Owner", service_address="117 Main St",
                               roofline_feet=100)
    inv = validate_success(api.create_invoice(create_invoice_payload(
        customer["id"], source_type="MANUAL", line_items=[
            {"description": "Labor", "amount_cents": 4000, "taxable": True},
            {"description": "Trip", "amount_cents": 3000, "taxable": True},
        ]), BILLING), 201)
    assert inv["subtotal_cents"] == 7000, inv
    assert inv["tax_cents"] == 0, inv
    assert inv["total_cents"] == 7000, inv


# ── Corner/state_machines/void_non_issued_invoice_returns_invalid_state ──────

def test_void_already_voided_invoice_rejected(api):
    """PRD §3.8: "A `BillingAdmin` voids an invoice, moving it from `ISSUED` to `VOID`
    (permitted only while `ISSUED`, otherwise `ERR_INVOICE_NOT_ISSUED`)"

    Design: Corner/state_machines/void_non_issued_invoice_returns_invalid_state
    """
    customer = create_customer(name="Void Owner", service_address="108 Main St",
                               roofline_feet=100)
    inv = create_invoice(customer["id"], source_type="MANUAL", tax_rate_bps=0,
                         line_items=[{"description": "L1", "amount_cents": 5000,
                                      "taxable": False}])
    validate_success(api.void_invoice(inv["id"], BILLING), 200)
    resp = api.void_invoice(inv["id"], BILLING)
    validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_ISSUED.value, 409)


# ── Corner/state_machines/reverse_non_posted_payment_returns_invalid_state ───

def test_reverse_already_reversed_payment_rejected(api):
    """PRD §3.7: "A `BillingAdmin` reverses a payment, moving it from `POSTED` to
    `REVERSED` (permitted only while the payment is `POSTED`, otherwise
    `ERR_PAYMENT_NOT_POSTED`)"

    Reversing an already-REVERSED payment is refused and the plan principal is not
    restored twice (stays 1200000).

    Design: Corner/state_machines/reverse_non_posted_payment_returns_invalid_state
    """
    customer, contract, plan = setup_financing_plan(
        original_principal_cents=1200000, apr_bps=1000, term_months=12)
    payment = post_payment(plan["id"], amount_cents=110000)
    validate_success(api.reverse_payment(payment["id"], BILLING), 200)
    resp = api.reverse_payment(payment["id"], BILLING)
    validate_error(resp, ApiErrorId.ERR_PAYMENT_NOT_POSTED.value, 409)
    fetched = validate_success(api.get_financing_plan(plan["id"], BILLING), 200)
    assert fetched["remaining_principal_cents"] == 1200000, fetched


# ── Corner/errors/payment_on_nonexistent_plan_returns_not_found ──────────────

def test_payment_on_unknown_plan_returns_not_found(api):
    """PRD §2.7: "When a create operation references another resource — a `customer_id`,
    `contract_id`, `crew_id`, `route_day_id`, `job_id`, `storage_bin_id`, `estimate_id`,
    or `financing_plan_id` — the referenced resource must exist, and a missing target
    produces that resource type's not-found code with HTTP 404."
    PRD §2.7: "a missing financing plan `ERR_FINANCING_PLAN_NOT_FOUND`"

    Design: Corner/errors/payment_on_nonexistent_plan_returns_not_found
    """
    resp = api.create_payment("00000000-0000-4000-8000-000000000001",
                              create_payment_payload(amount_cents=10000), BILLING)
    validate_error(resp, ApiErrorId.ERR_FINANCING_PLAN_NOT_FOUND.value, 404)


# ── Corner/consistency_model/invoice_create_immediate_balance_visible ────────

def test_invoice_creation_immediately_reflected_in_balance(api):
    """PRD §3.8: "An invoice opens in `ISSUED` `status`, and its creation recomputes the
    billed customer's `outstanding_balance_cents`."
    PRD §2.11: "It is defined as the sum of `total_cents` across that customer's invoices
    whose `status` is `ISSUED`; invoices in `VOID` or `PAID` status are excluded from the
    sum."

    Immediately after POST /invoices, GET /customers reflects the 5000 balance.

    Design: Corner/consistency_model/invoice_create_immediate_balance_visible
    """
    customer = create_customer(name="Imm Owner", service_address="132 Main St",
                               roofline_feet=100)
    create_invoice(customer["id"], source_type="MANUAL", tax_rate_bps=0,
                   line_items=[{"description": "Install", "amount_cents": 5000,
                                "taxable": False}])
    fetched = validate_success(api.get_customer(customer["id"], BILLING), 200)
    assert fetched["outstanding_balance_cents"] == 5000, fetched
