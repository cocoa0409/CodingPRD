"""Invoice tiered-discount tax breakdown, parallel delivery/payment axes, payment
ceilings, void guard, and payment-reversal AR conservation.

Translates queue-A (Difficulty) combinatorial_formula /
invoice_total_discount_tier_then_tax_eval_order, non_linear_state_machine /
invoice_parallel_delivery_and_payment_axes, compensating_invariant /
reverse_payment_preserves_invoice_ar_identity; plus queue-B (Corner) validations /
invoice_payment_exceeds_balance_rejected and validations /
void_invoice_with_payment_rejected.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    assert_invoice_ar_identity,
    setup_company_with_accounts, setup_sent_invoice, create_customer,
    create_sent_invoice, create_draft_invoice,
    create_invoice_payment_payload,
    make_accountant_headers, make_bookkeeper_headers,
)

ACCT = make_accountant_headers("u_acct")
BOOK = make_bookkeeper_headers("u_book")


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula /
#             invoice_total_discount_tier_then_tax_eval_order
# ---------------------------------------------------------------------------

def _sent_tier1_invoice():
    """One taxable line qty 1 unit_price 500000, CA jurisdiction at 1000 bps."""
    setup = setup_sent_invoice(unit_price_cents=500000, taxable=True,
                               tax_jurisdiction="CA", rate_bps=1000)
    return setup["invoice"]


def test_invoice_discount_tier_applied_on_taxable_subtotal(api):
    """PRD §3.6: "The `discount_cents` is the taxable subtotal multiplied by that
    discount percentage, rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/invoice_total_discount_tier_then_tax_eval_order
    """
    inv = _sent_tier1_invoice()
    assert inv["taxable_subtotal_cents"] == 500000, f"got {inv['taxable_subtotal_cents']}"
    assert inv["discount_cents"] == 25000, \
        f"500000 at 5% tier should discount 25000, got {inv['discount_cents']}"


def test_invoice_tax_on_discounted_base_then_total(api):
    """PRD §3.6: "The discounted taxable base is `taxable_subtotal_cents` minus
    `discount_cents`."
    PRD §3.6: "The `total_cents` is the discounted taxable base plus
    `nontaxable_subtotal_cents` plus `tax_cents`."

    Design: Difficulty/combinatorial_formula/invoice_total_discount_tier_then_tax_eval_order
    """
    inv = _sent_tier1_invoice()
    # tax on discounted base 475000 at 1000 bps = 47500; total = 475000 + 0 + 47500.
    assert inv["tax_cents"] == 47500, \
        f"tax must be on the discounted 475000 base (47500), got {inv['tax_cents']}"
    assert inv["total_cents"] == 522500, f"got {inv['total_cents']}"
    assert inv["delivery_status"] == "SENT", f"got {inv['delivery_status']}"


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine /
#             invoice_parallel_delivery_and_payment_axes
# ---------------------------------------------------------------------------

def _partially_paid_invoice(api):
    """SENT non-taxable invoice total 100000, then a 40000 CLEARED payment."""
    setup = setup_sent_invoice(unit_price_cents=100000, taxable=False, tax_jurisdiction="NONE")
    inv = setup["invoice"]
    co = setup["env"]["company"]["id"]
    bank = setup["env"]["bank"]["id"]
    pay = validate_success(api.create_invoice_payment(
        create_invoice_payment_payload(co, inv["id"], bank, 40000), BOOK), 201)
    return inv, pay


def test_partial_payment_sets_payment_status_partially_paid(api):
    """PRD §3.7: "`PARTIALLY_PAID` when the paid amount is greater than zero but
    less than `total_cents`, and `PAID` when the paid amount equals `total_cents`."

    Design: Difficulty/non_linear_state_machine/invoice_parallel_delivery_and_payment_axes
    """
    inv, _ = _partially_paid_invoice(api)
    refetched = validate_success(api.get_invoice(inv["id"], ACCT))
    assert refetched["payment_status"] == "PARTIALLY_PAID", \
        f"expected PARTIALLY_PAID, got {refetched['payment_status']}"


def test_partial_payment_leaves_delivery_status_sent(api):
    """PRD §3.6: "The two status axes are independent: `delivery_status` tracks the
    document's lifecycle (`DRAFT`, `SENT`, `VOID`) while `payment_status` tracks
    collection (`UNPAID`, `PARTIALLY_PAID`, `PAID`)."

    Design: Difficulty/non_linear_state_machine/invoice_parallel_delivery_and_payment_axes
    """
    inv, _ = _partially_paid_invoice(api)
    refetched = validate_success(api.get_invoice(inv["id"], ACCT))
    assert refetched["delivery_status"] == "SENT", \
        f"delivery_status must stay SENT after a partial payment, got {refetched['delivery_status']}"
    assert refetched["amount_paid_cents"] == 40000, f"got {refetched['amount_paid_cents']}"
    assert refetched["balance_due_cents"] == 60000, f"got {refetched['balance_due_cents']}"


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant /
#             reverse_payment_preserves_invoice_ar_identity
# ---------------------------------------------------------------------------

def _invoice_with_reversed_payment(api):
    setup = setup_sent_invoice(unit_price_cents=100000, taxable=False, tax_jurisdiction="NONE")
    inv = setup["invoice"]
    co = setup["env"]["company"]["id"]
    bank = setup["env"]["bank"]["id"]
    pay = validate_success(api.create_invoice_payment(
        create_invoice_payment_payload(co, inv["id"], bank, 60000), BOOK), 201)
    reversed_pay = validate_success(api.reverse_invoice_payment(pay["id"], ACCT))
    return inv, reversed_pay


def test_reverse_payment_returns_status_to_reversed(api):
    """PRD §3.7: "A cleared payment may be reversed by an `Accountant` or `Owner`,
    moving it from `CLEARED` to the terminal `REVERSED` state, provided the
    invoice's issue-date period is still `OPEN` (a closed period is rejected with
    `ERR_PERIOD_CLOSED`)."

    Design: Difficulty/compensating_invariant/reverse_payment_preserves_invoice_ar_identity
    """
    _, reversed_pay = _invoice_with_reversed_payment(api)
    assert reversed_pay["status"] == "REVERSED", f"got {reversed_pay['status']}"


def test_reverse_payment_restores_invoice_ar_identity(api):
    """PRD §3.7: "The compensation property holds: applying a payment and then
    reversing it leaves the
    `amount_paid_cents`-plus-`balance_due_cents`-equals-`total_cents` invariant
    intact."

    Design: Difficulty/compensating_invariant/reverse_payment_preserves_invoice_ar_identity
    """
    inv, _ = _invoice_with_reversed_payment(api)
    refetched = validate_success(api.get_invoice(inv["id"], ACCT))
    assert refetched["amount_paid_cents"] == 0, \
        f"paid should return to 0 after reversal, got {refetched['amount_paid_cents']}"
    assert refetched["balance_due_cents"] == 100000, \
        f"balance should return to total, got {refetched['balance_due_cents']}"
    assert refetched["payment_status"] == "UNPAID", f"got {refetched['payment_status']}"
    assert_invoice_ar_identity(refetched)


# ---------------------------------------------------------------------------
# Corner: validations / invoice_payment_exceeds_balance_rejected
# ---------------------------------------------------------------------------

def test_invoice_payment_exceeds_balance_rejected(api):
    """PRD §3.7: "The payment amount must be greater than zero and must not exceed
    the invoice's current `balance_due_cents`; an over-application is rejected with
    `ERR_PAYMENT_EXCEEDS_BALANCE`".

    Design: Corner/validations/invoice_payment_exceeds_balance_rejected
    """
    setup = setup_sent_invoice(unit_price_cents=100000, taxable=False, tax_jurisdiction="NONE")
    inv = setup["invoice"]
    co = setup["env"]["company"]["id"]
    bank = setup["env"]["bank"]["id"]
    resp = api.create_invoice_payment(
        create_invoice_payment_payload(co, inv["id"], bank, 120000), BOOK)
    validate_error(resp, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE.value)


# ---------------------------------------------------------------------------
# Corner: validations / void_invoice_with_payment_rejected
# ---------------------------------------------------------------------------

def test_void_invoice_with_cleared_payment_rejected(api):
    """PRD §3.6: "Voiding is permitted only when `payment_status` is `UNPAID`; an
    invoice carrying any cleared payment is rejected with
    `ERR_INVOICE_HAS_PAYMENTS`."

    Design: Corner/validations/void_invoice_with_payment_rejected
    """
    setup = setup_sent_invoice(unit_price_cents=100000, taxable=False, tax_jurisdiction="NONE")
    inv = setup["invoice"]
    co = setup["env"]["company"]["id"]
    bank = setup["env"]["bank"]["id"]
    validate_success(api.create_invoice_payment(
        create_invoice_payment_payload(co, inv["id"], bank, 40000), BOOK), 201)
    resp = api.void_invoice(inv["id"], ACCT)
    validate_error(resp, ApiErrorId.ERR_INVOICE_HAS_PAYMENTS.value)
    refetched = validate_success(api.get_invoice(inv["id"], ACCT))
    assert refetched["delivery_status"] == "SENT", f"must stay SENT, got {refetched['delivery_status']}"


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / send_invoice_with_empty_lines_rejected
# ---------------------------------------------------------------------------

def test_send_invoice_with_empty_lines_rejected(api):
    """PRD §3.6: "Sending requires that `lines` be non-empty (an empty invoice is
    rejected with `ERR_INVOICE_EMPTY`)".

    Design: Difficulty/boundary_precision_check/send_invoice_with_empty_lines_rejected
    """
    env = setup_company_with_accounts()
    co = env["company"]["id"]
    accts = env["accounts"]
    cust = create_customer(co, accts["ar"]["id"], tax_jurisdiction="NONE")
    inv = create_draft_invoice(co, cust["id"], accts["rev"]["id"], accts["taxliab"]["id"], [])
    resp = api.send_invoice(inv["id"], ACCT)
    validate_error(resp, ApiErrorId.ERR_INVOICE_EMPTY.value)
    refetched = validate_success(api.get_invoice(inv["id"], ACCT))
    assert refetched["delivery_status"] == "DRAFT", \
        f"empty invoice must stay DRAFT, got {refetched['delivery_status']}"


def test_send_invoice_with_one_line_succeeds(api):
    """PRD §3.6: "Sending requires that `lines` be non-empty (an empty invoice is
    rejected with `ERR_INVOICE_EMPTY`)".

    Design: Difficulty/boundary_precision_check/send_invoice_with_empty_lines_rejected
    """
    env = setup_company_with_accounts()
    co = env["company"]["id"]
    accts = env["accounts"]
    cust = create_customer(co, accts["ar"]["id"], tax_jurisdiction="NONE")
    inv = create_draft_invoice(
        co, cust["id"], accts["rev"]["id"], accts["taxliab"]["id"],
        [{"description": "svc", "quantity": 1, "unit_price_cents": 5000, "taxable": False}])
    sent = validate_success(api.send_invoice(inv["id"], ACCT))
    assert sent["delivery_status"] == "SENT", \
        f"a one-line invoice (boundary of non-empty) should send, got {sent['delivery_status']}"
