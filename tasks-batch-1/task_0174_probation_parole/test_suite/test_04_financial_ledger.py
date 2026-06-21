"""Financial obligations, the payment waterfall, payoff quote (forward-looking
vs chronological), discharge, and ledger conservation.

Difficulty queue: dual_variant_calc (payoff vs chronological),
compensating_invariant (payment then discharge conserves value).
Corner queue: calculations (waterfall ordering), validations (exceeds balance),
entities (payment immutability), consistency_model (immediate balances).
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    make_officer_headers, make_judge_headers,
    setup_active_supervisee, add_obligation, make_payment,
    setup_supervisee_with_obligation, set_clock,
)


# ─── Difficulty: dual_variant_calc / payoff_forward_looking_vs_chronological ──
def test_payoff_forward_looking_exceeds_chronological_fee_balance(api):
    """PRD §3.10: "for a FEE obligation that is recurring it additionally projects
    future accrual: it takes the whole-month count from the obligation's
    created_at to the as_of date, taking the floor and never less than zero,
    multiplies that month count by the obligation's monthly_accrual_cents, and
    adds the result to the outstanding amount."
    PRD §3.6: "For a FEE obligation whose recurring flag is true, the obligation
    accrues monthly_accrual_cents for each whole month that has elapsed since its
    created_at."

    Recurring FEE (principal 5000, monthly 5000, created 2026-01-01): posted
    fee_balance at clock 2026-03-01 is 15000 (2 months accrued + principal); the
    forward-looking payoff at as_of 2026-06-01 is 30000 (5 months accrued +
    principal). Same obligation, two divergent figures.

    Design: Difficulty/dual_variant_calc/payoff_forward_looking_vs_chronological_ledger
    """
    officer, sup = setup_active_supervisee(level_total=10)
    oh = make_officer_headers(officer["id"])

    set_clock("2026-01-01T00:00:00.000Z", officer["id"])
    add_obligation(
        sup["id"], officer["id"], "FEE", 5000,
        monthly_accrual_cents=5000, recurring=True,
    )
    set_clock("2026-03-01T00:00:00.000Z", officer["id"])

    sup_now = validate_success(api.get_supervisee(sup["id"], oh), 200)
    assert sup_now["fee_balance_cents"] == 15000

    quote = validate_success(
        api.get_payoff_quote(sup["id"], oh,
                             params={"as_of": "2026-06-01T00:00:00.000Z"}),
        200,
    )
    assert quote["projected_fee_cents"] == 30000
    assert quote["projected_total_cents"] == 30000


def test_payoff_forward_looking_larger_than_posted_for_recurring(api):
    """PRD §3.10: "Because this projection adds future accrual that the posted
    balances do not, the projected figure for a supervisee with recurring fees is
    larger than the posted fee_balance_cents for the same obligations"

    The same obligation gives projected_fee_cents (30000) strictly greater than
    posted fee_balance_cents (15000).

    Design: Difficulty/dual_variant_calc/payoff_forward_looking_vs_chronological_ledger
    """
    officer, sup = setup_active_supervisee(level_total=10)
    oh = make_officer_headers(officer["id"])
    set_clock("2026-01-01T00:00:00.000Z", officer["id"])
    add_obligation(
        sup["id"], officer["id"], "FEE", 5000,
        monthly_accrual_cents=5000, recurring=True,
    )
    set_clock("2026-03-01T00:00:00.000Z", officer["id"])
    sup_now = validate_success(api.get_supervisee(sup["id"], oh), 200)
    quote = validate_success(
        api.get_payoff_quote(sup["id"], oh,
                             params={"as_of": "2026-06-01T00:00:00.000Z"}),
        200,
    )
    assert quote["projected_fee_cents"] > sup_now["fee_balance_cents"]


# ─── Difficulty: compensating_invariant / payment_then_discharge_conserves ──
def test_payment_then_discharge_conserves_obligation_value(api):
    """PRD §3.6: "A SupervisingJudge may discharge an obligation, forgiving its
    remaining balance. ... it moves the obligation to the terminal DISCHARGED
    status, recomputes the supervisee's posted balances so the discharged
    obligation's outstanding amount no longer counts"

    A 4000 payment against a 10000 RESTITUTION leaves paid_cents 4000; discharging
    drives restitution_balance to 0 while paid_cents stays 4000 — value conserved.

    Design: Difficulty/compensating_invariant/payment_then_discharge_conserves_obligation_value
    """
    officer, sup, ob = setup_supervisee_with_obligation("RESTITUTION", 10000)
    oh = make_officer_headers(officer["id"])
    make_payment(sup["id"], officer["id"], 4000, allocation_policy="RESTITUTION_FIRST")

    discharged = validate_success(
        api.discharge_obligation(sup["id"], ob["id"], make_judge_headers()), 200
    )
    assert discharged["status"] == "DISCHARGED"
    assert discharged["paid_cents"] == 4000

    sup_after = validate_success(api.get_supervisee(sup["id"], oh), 200)
    assert sup_after["restitution_balance_cents"] == 0


def test_partial_payment_reduces_restitution_balance(api):
    """PRD §3.6: "The restitution_balance_cents is the sum, over every RESTITUTION
    obligation that is still OPEN or PARTIALLY_PAID, of that obligation's
    outstanding amount measured to the present moment (principal plus
    accrual-to-now minus paid)"

    A 4000 payment against a 10000 RESTITUTION leaves an outstanding (balance) of
    6000 — the value-accounting leg of the conservation invariant before discharge.

    Design: Difficulty/compensating_invariant/payment_then_discharge_conserves_obligation_value
    """
    officer, sup, ob = setup_supervisee_with_obligation("RESTITUTION", 10000)
    oh = make_officer_headers(officer["id"])
    make_payment(sup["id"], officer["id"], 4000)
    ob_after = validate_success(api.get_obligation(sup["id"], ob["id"], oh), 200)
    assert ob_after["paid_cents"] == 4000
    assert ob_after["status"] == "PARTIALLY_PAID"
    sup_after = validate_success(api.get_supervisee(sup["id"], oh), 200)
    assert sup_after["restitution_balance_cents"] == 6000


# ─── Corner: calculations / payment_waterfall_restitution_first_ordering ───
def test_payment_waterfall_restitution_first_fills_restitution_then_fee(api):
    """PRD §3.6: "Under RESTITUTION_FIRST, obligations are ordered first by type
    with restitution ahead of fees, then by ascending created_at, then by
    ascending parent_obligation_id as the final tie-break."
    PRD §3.6: "an OPEN obligation fully covered by a single payment becomes PAID ...
    an OPEN obligation that receives a partial payment becomes PARTIALLY_PAID"

    Paying 12000 against RESTITUTION 10000 + FEE 5000 fills restitution to 10000
    (PAID) then the fee to 2000 (PARTIALLY_PAID).

    Design: Corner/calculations/payment_waterfall_restitution_first_ordering
    """
    officer, sup = setup_active_supervisee(level_total=10)
    oh = make_officer_headers(officer["id"])
    ob_rest = add_obligation(sup["id"], officer["id"], "RESTITUTION", 10000)
    ob_fee = add_obligation(sup["id"], officer["id"], "FEE", 5000)

    make_payment(sup["id"], officer["id"], 12000, allocation_policy="RESTITUTION_FIRST")

    rest_after = validate_success(api.get_obligation(sup["id"], ob_rest["id"], oh), 200)
    fee_after = validate_success(api.get_obligation(sup["id"], ob_fee["id"], oh), 200)
    assert rest_after["paid_cents"] == 10000
    assert rest_after["status"] == "PAID"
    assert fee_after["paid_cents"] == 2000
    assert fee_after["status"] == "PARTIALLY_PAID"

    sup_after = validate_success(api.get_supervisee(sup["id"], oh), 200)
    assert sup_after["restitution_balance_cents"] == 0
    assert sup_after["fee_balance_cents"] == 3000


# ─── Corner: validations / payment_exceeds_balance_rejected ───
def test_payment_exceeds_balance_rejected_whole(api):
    """PRD §3.6: "If the tendered amount exceeds that total — meaning some money
    would remain after every obligation is filled — the entire payment is rejected
    with ERR_PAYMENT_EXCEEDS_BALANCE (HTTP 422); the system never posts a partial
    payment"

    A 6000 payment against a single OPEN 5000 obligation is rejected; paid stays 0.

    Design: Corner/validations/payment_exceeds_balance_rejected
    """
    officer, sup, ob = setup_supervisee_with_obligation("RESTITUTION", 5000)
    oh = make_officer_headers(officer["id"])
    res = api.create_payment(sup["id"], {"amount_cents": 6000}, oh)
    validate_error(res, "ERR_PAYMENT_EXCEEDS_BALANCE")
    ob_after = validate_success(api.get_obligation(sup["id"], ob["id"], oh), 200)
    assert ob_after["paid_cents"] == 0


# ─── Corner: entities / payment_is_immutable_no_version_field ───
def test_payment_has_no_version_field(api):
    """PRD §2.4: "A Payment carries only id and created_at; it has neither an
    updated_at field nor a version field, because once a payment is allocated it is
    never modified."

    Design: Corner/entities/payment_is_immutable_no_version_field
    """
    from test_helpers import assert_payment
    officer, sup, ob = setup_supervisee_with_obligation("RESTITUTION", 5000)
    oh = make_officer_headers(officer["id"])
    res = api.create_payment(sup["id"], {"amount_cents": 5000}, oh)
    pay = validate_success(res, 201)
    assert_payment(pay)
    assert "version" not in pay
    ob_after = validate_success(api.get_obligation(sup["id"], ob["id"], oh), 200)
    assert ob_after["status"] == "PAID"


# ─── Corner: consistency_model / immediate_consistency_balances_visible ───
def test_balance_visible_immediately_after_payment(api):
    """PRD §3.6: "Each such status change recomputes the supervisee's posted
    balances."
    PRD §3.6: "an OPEN obligation that receives a partial payment becomes
    PARTIALLY_PAID"

    Immediately after POST payment, GET supervisee reflects the new restitution
    balance (no lag).

    Design: Corner/consistency_model/immediate_consistency_balances_visible_in_same_response
    """
    officer, sup, ob = setup_supervisee_with_obligation("RESTITUTION", 10000)
    oh = make_officer_headers(officer["id"])
    make_payment(sup["id"], officer["id"], 4000)
    sup_now = validate_success(api.get_supervisee(sup["id"], oh), 200)
    assert sup_now["restitution_balance_cents"] == 6000
    ob_now = validate_success(api.get_obligation(sup["id"], ob["id"], oh), 200)
    assert ob_now["status"] == "PARTIALLY_PAID"
