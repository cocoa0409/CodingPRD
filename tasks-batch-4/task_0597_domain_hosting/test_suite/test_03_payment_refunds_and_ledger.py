"""Payment waterfall, refunds, and the append-only money ledger."""
from test_helpers import (
    ApiErrorId,
    create_account,
    entries_of_type,
    first_issued_invoice,
    get_domain,
    get_invoice,
    ledger_entries,
    make_registrant_headers,
    pay_invoice,
    pay_invoice_payload,
    refund_payload,
    register_domain,
    validate_error,
    validate_paginated,
    validate_success,
    BILLING,
)


def _paid_privacy_invoice():
    """Account (card, no credit) + a .xyz privacy registration invoice paid in cash.

    Subtotal 1198, tax 98, total 1296. Returns (account, domain, invoice).
    """
    account = create_account()
    domain = register_domain(
        account, "budgetsite", "xyz", whois_privacy=True, auto_renew=False
    )
    invoice = first_issued_invoice(account["id"], make_registrant_headers(account["id"]))
    assert invoice["total_cents"] == 1296
    pay_invoice(invoice["id"], account, use_credit=False)
    return account, domain, invoice


# =========================================================================
# Cash conservation  (Difficulty/compensating_invariant)
# =========================================================================

def test_cash_payment_then_full_card_refund_restores_net_cash_to_zero(api):
    """PRD §2.7: "The cash conservation invariant follows directly: an invoice paid entirely
    in cash and then fully refunded to the card leaves `net_cash_cents` exactly where it
    stood before the payment, and leaves the invoice's `amount_paid_cents` minus
    `amount_refunded_cents` at zero."
    PRD §3.8: "A refund to `CARD` writes a `REFUND` ledger entry for the negative of the
    amount, restoring the account's `net_cash_cents`; a refund to `CREDIT` instead writes a
    `CREDIT_GRANT` entry for the positive amount, converting the money into store credit."

    Design: Difficulty/compensating_invariant/pay_then_full_card_refund_restores_net_cash_to_zero
    """
    account, _domain, invoice = _paid_privacy_invoice()
    headers = make_registrant_headers(account["id"])

    after_pay = validate_success(api.get_account(account["id"], headers))
    assert after_pay["net_cash_cents"] == 1296

    payments = entries_of_type(ledger_entries(account["id"]), "PAYMENT")
    assert len(payments) == 1 and payments[0]["amount_cents"] == 1296

    validate_success(
        api.refund_invoice(invoice["id"], refund_payload(1296, "CARD"), BILLING)
    )

    after_refund = validate_success(api.get_account(account["id"], headers))
    assert after_refund["net_cash_cents"] == 0, (
        "the two ledger rows (+1296, -1296) must cancel with zero drift"
    )
    assert after_refund["credit_balance_cents"] == 0, "a CARD refund creates no credit"

    entries = ledger_entries(account["id"])
    assert len(entries) == 2, f"expected exactly 2 ledger entries, got {len(entries)}"
    refunds = entries_of_type(entries, "REFUND")
    assert len(refunds) == 1 and refunds[0]["amount_cents"] == -1296


def test_full_refund_settles_the_invoice_without_undoing_the_registration(api):
    """PRD §3.8: "A refund smaller than the outstanding refundable balance leaves the invoice
    `PARTIALLY_REFUNDED` — and further partial refunds keep it there — while a refund that
    exactly settles the outstanding refundable balance moves it to `REFUNDED`, which is
    terminal."
    PRD §3.8: "Refunds move money only; they never undo the activations the payment
    performed. A domain paid for and then refunded stays registered."

    Design: Difficulty/compensating_invariant/pay_then_full_card_refund_restores_net_cash_to_zero
    """
    account, domain, invoice = _paid_privacy_invoice()

    validate_success(
        api.refund_invoice(invoice["id"], refund_payload(1296, "CARD"), BILLING)
    )

    settled = get_invoice(invoice["id"], account)
    assert settled["status"] == "REFUNDED"
    assert settled["amount_paid_cents"] == 1296
    assert settled["amount_refunded_cents"] == 1296

    assert get_domain(domain["id"], account)["lifecycle_status"] == "ACTIVE"


# =========================================================================
# Invoice-state check beats the payment-method check  (Difficulty/priority_pair)
# =========================================================================

def _credit_paid_registration():
    """Account with NO card and 2000 cents of credit; a 1298-cent registration invoice
    already paid entirely out of credit, leaving 702 cents of credit."""
    account = create_account(with_card=False, credit_cents=2000)
    domain = register_domain(account, "example", "com", auto_renew=False)
    invoice = first_issued_invoice(account["id"], make_registrant_headers(account["id"]))
    assert invoice["total_cents"] == 1298
    pay_invoice(invoice["id"], account, use_credit=True)
    return account, domain, invoice


def test_second_pay_on_a_paid_invoice_reports_the_invoice_state_error(api):
    """PRD §3.8: "Payment is available to the owning `Registrant` and to a `BillingAdmin`, on
    an `ISSUED` invoice only — anything else is `ERR_INVOICE_NOT_PAYABLE` — and against an
    `ACTIVE` account."
    PRD §2.8: "Only after all of that do the domain-specific state checks and business rules
    run, in the order the individual workflows of §3 describe."

    The account has no card and only 702 cents of credit left against a 1298-cent total, so
    the payment-method rule is also violated — but the invoice-status check is stated first
    in §3.8 and is the one that answers.

    Design: Difficulty/priority_pair_validation_conflict/invoice_state_check_beats_payment_method_check_on_pay
    """
    account, _domain, invoice = _credit_paid_registration()
    headers = make_registrant_headers(account["id"])

    resp = api.pay_invoice(invoice["id"], pay_invoice_payload(True), headers)

    assert resp.status_code == 409
    validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_PAYABLE.value, 409)


def test_rejected_second_pay_moves_no_money_and_leaves_the_invoice_paid(api):
    """PRD §3.8: "A successful payment writes a `CREDIT_APPLIED` ledger entry for the
    negative of the applied credit when that credit is greater than zero, writes a `PAYMENT`
    ledger entry for the positive cash remainder when that remainder is greater than zero,
    sets the invoice's `amount_paid_cents` to its `total_cents`, and moves the invoice
    `ISSUED → PAID`."
    PRD §3.1: "Attaching one means supplying a `card_token`, which the server records as
    `payment_method_token` and which flips the derived `payment_method_on_file` to true —
    that flag is true when and only when `payment_method_token` is non-null."

    Design: Difficulty/priority_pair_validation_conflict/invoice_state_check_beats_payment_method_check_on_pay
    """
    account, _domain, invoice = _credit_paid_registration()
    headers = make_registrant_headers(account["id"])

    api.pay_invoice(invoice["id"], pay_invoice_payload(True), headers)

    state = validate_success(api.get_account(account["id"], headers))
    assert state["credit_balance_cents"] == 702, "2000 granted, 1298 applied, nothing more"
    assert state["payment_method_on_file"] is False

    settled = get_invoice(invoice["id"], account)
    assert settled["status"] == "PAID"
    assert settled["amount_paid_cents"] == 1298


# =========================================================================
# Corner instances
# =========================================================================

def test_credit_covering_the_whole_invoice_needs_no_card_on_file(api):
    """PRD §3.8: "If the cash remainder is greater than zero, the account must have a
    payment method on file — if it does not, the payment is refused with
    `ERR_PAYMENT_METHOD_REQUIRED` (402). A cash remainder of exactly zero, where store
    credit covered the whole invoice, requires no card at all; this boundary is deliberate."
    PRD §2.7: "`credit_balance_cents` is the sum of `amount_cents` over that account's
    `LedgerEntry` rows whose `entry_type` is `CREDIT_GRANT` or `CREDIT_APPLIED`."

    Design: Corner/calculations/credit_covering_the_whole_invoice_needs_no_card
    """
    account = create_account(with_card=False, credit_cents=1298)
    headers = make_registrant_headers(account["id"])
    domain = register_domain(account, "example", "com", auto_renew=False)
    invoice = first_issued_invoice(account["id"], headers)
    assert invoice["total_cents"] == 1298

    resp = api.pay_invoice(invoice["id"], pay_invoice_payload(True), headers)
    paid = validate_success(resp, 200)

    assert paid["status"] == "PAID"
    assert paid["amount_paid_cents"] == 1298

    state = validate_success(api.get_account(account["id"], headers))
    assert state["credit_balance_cents"] == 0
    assert state["net_cash_cents"] == 0

    entries = ledger_entries(account["id"])
    assert len(entries) == 2, "one CREDIT_GRANT and one CREDIT_APPLIED, nothing else"
    grants = entries_of_type(entries, "CREDIT_GRANT")
    applied = entries_of_type(entries, "CREDIT_APPLIED")
    assert len(grants) == 1 and grants[0]["amount_cents"] == 1298
    assert len(applied) == 1 and applied[0]["amount_cents"] == -1298
    assert entries_of_type(entries, "PAYMENT") == [], "no cash moved, so no PAYMENT entry"

    assert get_domain(domain["id"], account)["lifecycle_status"] == "ACTIVE"


def test_refund_above_the_outstanding_refundable_balance_is_rejected(api):
    """PRD §3.8: "The amount may not exceed what is still refundable, namely
    `amount_paid_cents` minus `amount_refunded_cents`; exceeding it is
    `ERR_REFUND_EXCEEDS_PAID`."
    PRD §3.8: "A refund to `CARD` writes a `REFUND` ledger entry for the negative of the
    amount, restoring the account's `net_cash_cents`; a refund to `CREDIT` instead writes a
    `CREDIT_GRANT` entry for the positive amount, converting the money into store credit."

    Design: Corner/validations/refund_larger_than_paid_amount_rejected
    """
    account = create_account()
    headers = make_registrant_headers(account["id"])
    register_domain(account, "example", "com", auto_renew=False)
    invoice = first_issued_invoice(account["id"], headers)
    assert invoice["total_cents"] == 1298
    pay_invoice(invoice["id"], account)

    too_much = api.refund_invoice(invoice["id"], refund_payload(1299, "CARD"), BILLING)
    validate_error(too_much, ApiErrorId.ERR_REFUND_EXCEEDS_PAID.value, 422)

    partial = validate_success(
        api.refund_invoice(
            invoice["id"], refund_payload(300, "CREDIT", reason="goodwill"), BILLING
        )
    )
    assert partial["status"] == "PARTIALLY_REFUNDED"
    assert partial["amount_refunded_cents"] == 300

    state = validate_success(api.get_account(account["id"], headers))
    assert state["credit_balance_cents"] == 300
    assert state["net_cash_cents"] == 1298, "a CREDIT refund does not return cash"


def test_refunding_an_unpaid_invoice_is_rejected(api):
    """PRD §3.8: "A `BillingAdmin` refunds a `PAID` or `PARTIALLY_REFUNDED` invoice — any
    other status is `ERR_INVOICE_NOT_REFUNDABLE` — supplying an `amount_cents`, a
    `destination` of `CARD` or `CREDIT`, and a `reason`."

    Design: Corner/validations/refunding_an_unpaid_invoice_rejected
    """
    account = create_account(with_card=False)
    headers = make_registrant_headers(account["id"])
    register_domain(account, "example", "com", auto_renew=False)
    invoice = first_issued_invoice(account["id"], headers)

    resp = api.refund_invoice(
        invoice["id"], refund_payload(100, "CARD", reason="oops"), BILLING
    )
    validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_REFUNDABLE.value, 409)

    after = get_invoice(invoice["id"], account)
    assert after["status"] == "ISSUED"
    assert after["amount_refunded_cents"] == 0

    _, meta = validate_paginated(api.list_ledger_entries(account["id"], headers))
    assert meta["total_count"] == 0, "a rejected refund writes no ledger entry"
