"""Invoicing and the exhibitor balance: the issue-then-void round trip that
returns `account_balance_cents` to exactly its pre-issue figure, the aggregate's
refusal to count DRAFT and fully settled invoices, partial settlement and its
residual, the payment ceiling, the sweep scope check, the suspended-exhibitor
gate on issuing, the segregation of duties that keeps an issuer from voiding his
own invoice, the FinanceController-only issue endpoint, and the immediacy of the
whole billing cascade."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_exhibitor,
    assert_invoice,
    assert_posture,
    assert_service_order,
    create_exhibitor,
    create_invoice_payload,
    get_booth,
    get_exhibitor,
    get_invoice,
    get_order,
    issue_invoice,
    pay_invoice,
    setup_draft_invoice,
    setup_issued_invoice,
    setup_order_ground,
    suspend_exhibitor,
    validate_error,
    validate_paginated,
    validate_success,
    void_invoice,
)

FINANCE = TEST_USERS["finance_controller_headers"]
FINANCE_ALT = TEST_USERS["finance_controller_alt_headers"]
LABOR = TEST_USERS["labor_supervisor_headers"]

# The two-line electrical order every scenario below bills: 4 x 32500 plus
# 3 x 21750 less a tenth, run through the volume and service-fee waterfall.
ORDER_TOTAL_CENTS = 193858
PARTIAL_PAYMENT_CENTS = 100000
RESIDUAL_BALANCE_CENTS = 93858
OVERSHOOTING_PAYMENT_CENTS = 200000
CREDIT_LIMIT_CENTS = 5000000


# --- money as a conserved quantity: issue then void is a perfect round trip

def test_issue_then_void_returns_account_balance_to_exactly_zero():
    """PRD §2.11: "None of them is maintained as an incremental delta, because a
    forward action and its compensating reversal must land the aggregate back on
    exactly the figure it held before — issuing and then voiding an invoice is a
    perfect round trip, and checking a crate in and then moving it out returns a
    warehouse's committed weight to its prior value."
    PRD §3.9: "It is the sum of `total_cents` over that exhibitor's invoices
    whose `status` is `ISSUED` or `PARTIALLY_SETTLED`, minus the sum of
    `settled_cents` over those same invoices, minus the sum of `settlement_cents`
    over that exhibitor's damage claims whose `status` is `SETTLED`."
    PRD §3.9: "Invoices in `DRAFT`, `SETTLED` and `VOID` are excluded outright,
    which is exactly what makes issuing and then voiding a perfect round trip
    back to the pre-issue figure."

    Design: Difficulty/compensating_invariant/invoice_issue_then_void_conserves_account_balance
    """
    ground = setup_draft_invoice(credit_limit_cents=CREDIT_LIMIT_CENTS)
    invoice_id = ground["invoice"]["id"]

    balance_start = get_exhibitor(ground["exhibitor"]["id"])["account_balance_cents"]
    assert balance_start == 0, \
        ("A DRAFT invoice is excluded from the aggregate, so the balance opens at "
         f"0, got {balance_start}")

    issued = issue_invoice(invoice_id)
    assert_invoice(issued)
    assert issued["status"] == "ISSUED", \
        f"Issuing moves the invoice DRAFT -> ISSUED, got {issued['status']}"
    assert issued["total_cents"] == ORDER_TOTAL_CENTS, \
        (f"The invoice sweeps one {ORDER_TOTAL_CENTS} cent order, got "
         f"{issued['total_cents']}")

    balance_issued = get_exhibitor(ground["exhibitor"]["id"])["account_balance_cents"]
    assert balance_issued == ORDER_TOTAL_CENTS, \
        (f"An ISSUED invoice puts its whole {ORDER_TOTAL_CENTS} cent total on the "
         f"balance, got {balance_issued}")

    voided = void_invoice(invoice_id, reason="Duplicate billing run",
                          headers=FINANCE_ALT)
    assert_invoice(voided)
    assert voided["status"] == "VOID", \
        f"Voiding an unsettled ISSUED invoice lands on VOID, got {voided['status']}"
    assert voided["settled_cents"] == 0, \
        f"A void is only available with settled_cents at 0, got {voided['settled_cents']}"

    exhibitor = get_exhibitor(ground["exhibitor"]["id"])
    assert_exhibitor(exhibitor)
    assert exhibitor["account_balance_cents"] == 0, \
        ("The compensating void must land the balance back on the exact pre-issue "
         f"0 with no drift, got {exhibitor['account_balance_cents']}")


def test_void_credits_the_swept_order_and_clears_its_invoice_link():
    """PRD §3.9: "On success the invoice moves to the terminal `VOID`,
    `voided_by_user_id` is recorded, every listed order's `billing_status`
    becomes `CREDITED` with its `invoice_id` cleared back to null, the
    exhibitor's balance is recomputed, and every booth of the exhibitor
    recomputes posture."
    PRD §3.9: "Voiding is available from `DRAFT` and from `ISSUED`, requires
    `settled_cents` to be exactly 0, and requires the acting `X-User-ID` to
    differ from the invoice's `issued_by_user_id`, a violation being refused with
    `ERR_SEGREGATION_OF_DUTIES`."
    PRD §2.10: "When no clause holds, `posture` is `OPEN` and `posture_reason` is
    null."

    Design: Difficulty/compensating_invariant/invoice_issue_then_void_conserves_account_balance
    """
    ground = setup_issued_invoice(credit_limit_cents=CREDIT_LIMIT_CENTS)
    invoice_id = ground["invoice"]["id"]
    order_id = ground["order"]["id"]

    billed = get_order(order_id)
    assert billed["billing_status"] == "INVOICED", \
        ("Setup failed: issuing must have moved the order to INVOICED, got "
         f"{billed['billing_status']}")
    assert billed["invoice_id"] == invoice_id, \
        f"Setup failed: the order must point at the issued invoice, got {billed['invoice_id']}"

    voided = void_invoice(invoice_id, reason="Duplicate billing run",
                          headers=FINANCE_ALT)
    assert voided["issued_by_user_id"] == "fin-1", \
        f"The issuer of record stays fin-1, got {voided['issued_by_user_id']}"
    assert voided["voided_by_user_id"] == "fin-2", \
        (f"The voiding operator fin-2 is recorded on the invoice, got "
         f"{voided['voided_by_user_id']}")

    order = get_order(order_id)
    assert_service_order(order)
    assert order["billing_status"] == "CREDITED", \
        (f"A voided invoice credits every order it swept, got {order['billing_status']}")
    assert order["invoice_id"] is None, \
        ("The void clears the order's invoice_id back to null, got "
         f"{order['invoice_id']}")

    assert get_exhibitor(ground["exhibitor"]["id"])["account_balance_cents"] == 0, \
        "The void recomputes the balance back to its pre-issue 0"
    assert_posture(get_booth(ground["booth"]["id"]), "OPEN", None)


# --- the issue edge is single-shot

def test_issuing_an_already_issued_invoice_is_rejected(api):
    """PRD §3.9: "Issuing moves the invoice `DRAFT → ISSUED`."
    PRD §2.9: "The target sits in a from-state the requested transition declares
    — otherwise `ERR_INVALID_STATE_TRANSITION` (409). Applies to every
    state-transition endpoint."
    PRD §3.9: "It is the sum of `total_cents` over that exhibitor's invoices
    whose `status` is `ISSUED` or `PARTIALLY_SETTLED`, minus the sum of
    `settled_cents` over those same invoices, minus the sum of `settlement_cents`
    over that exhibitor's damage claims whose `status` is `SETTLED`."

    Design: Corner/state_machines/issue_invoice_twice_is_rejected_on_second_attempt
    """
    ground = setup_issued_invoice(credit_limit_cents=CREDIT_LIMIT_CENTS)
    invoice_id = ground["invoice"]["id"]

    response = api.issue_invoice(invoice_id, FINANCE)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)

    invoice = get_invoice(invoice_id)
    assert_invoice(invoice)
    assert invoice["status"] == "ISSUED", \
        f"The refused second issue leaves the invoice ISSUED, got {invoice['status']}"

    balance = get_exhibitor(ground["exhibitor"]["id"])["account_balance_cents"]
    assert balance == ORDER_TOTAL_CENTS, \
        (f"The balance is a recomputation over invoice rows, so it stays at one "
         f"{ORDER_TOTAL_CENTS} rather than doubling, got {balance}")


# --- which invoices the balance aggregate admits

def test_account_balance_excludes_draft_and_fully_settled_invoices():
    """PRD §3.9: "It is the sum of `total_cents` over that exhibitor's invoices
    whose `status` is `ISSUED` or `PARTIALLY_SETTLED`, minus the sum of
    `settled_cents` over those same invoices, minus the sum of `settlement_cents`
    over that exhibitor's damage claims whose `status` is `SETTLED`."
    PRD §3.9: "Invoices in `DRAFT`, `SETTLED` and `VOID` are excluded outright,
    which is exactly what makes issuing and then voiding a perfect round trip
    back to the pre-issue figure."
    PRD §3.9: "A payment that leaves a remainder moves the invoice from `ISSUED`
    to `PARTIALLY_SETTLED` and may be repeated; a payment that brings
    `settled_cents` to exactly `total_cents` moves the invoice to the terminal
    `SETTLED` and moves every listed order's `billing_status` to `SETTLED`."

    Design: Corner/calculations/account_balance_excludes_draft_and_fully_settled_invoices
    """
    ground = setup_draft_invoice(credit_limit_cents=CREDIT_LIMIT_CENTS)
    invoice_id = ground["invoice"]["id"]
    exhibitor_id = ground["exhibitor"]["id"]

    assert ground["invoice"]["status"] == "DRAFT", \
        f"Setup failed: the invoice must open DRAFT, got {ground['invoice']['status']}"
    balance_draft = get_exhibitor(exhibitor_id)["account_balance_cents"]
    assert balance_draft == 0, \
        f"A DRAFT invoice is outside the aggregate, so the balance reads 0, got {balance_draft}"

    issue_invoice(invoice_id)
    balance_issued = get_exhibitor(exhibitor_id)["account_balance_cents"]
    assert balance_issued == ORDER_TOTAL_CENTS, \
        (f"Once ISSUED the invoice's whole total joins the balance, got "
         f"{balance_issued}")

    settled = pay_invoice(invoice_id, ORDER_TOTAL_CENTS)
    assert_invoice(settled)
    assert settled["status"] == "SETTLED", \
        (f"A payment reaching total_cents drives the invoice to the terminal "
         f"SETTLED, got {settled['status']}")
    assert settled["settled_cents"] == ORDER_TOTAL_CENTS, \
        f"settled_cents accumulates the full payment, got {settled['settled_cents']}"

    exhibitor = get_exhibitor(exhibitor_id)
    assert_exhibitor(exhibitor)
    assert exhibitor["account_balance_cents"] == 0, \
        ("A SETTLED invoice is excluded outright even though the row still "
         f"exists, so the balance returns to 0, got {exhibitor['account_balance_cents']}")

    order = get_order(ground["order"]["id"])
    assert order["billing_status"] == "SETTLED", \
        (f"Full settlement moves every listed order to SETTLED, got "
         f"{order['billing_status']}")


def test_partial_payment_leaves_residual_balance():
    """PRD §3.9: "A payment that leaves a remainder moves the invoice from
    `ISSUED` to `PARTIALLY_SETTLED` and may be repeated; a payment that brings
    `settled_cents` to exactly `total_cents` moves the invoice to the terminal
    `SETTLED` and moves every listed order's `billing_status` to `SETTLED`."
    PRD §3.9: "It is the sum of `total_cents` over that exhibitor's invoices
    whose `status` is `ISSUED` or `PARTIALLY_SETTLED`, minus the sum of
    `settled_cents` over those same invoices, minus the sum of `settlement_cents`
    over that exhibitor's damage claims whose `status` is `SETTLED`."
    PRD §3.9: "Every payment recomputes the exhibitor's `account_balance_cents`
    and re-evaluates the posture of every booth that exhibitor holds, which is
    how paying down a balance unfreezes a floor."

    Design: Corner/calculations/partial_payment_leaves_residual_balance
    """
    ground = setup_issued_invoice(credit_limit_cents=CREDIT_LIMIT_CENTS)
    invoice_id = ground["invoice"]["id"]

    paid = pay_invoice(invoice_id, PARTIAL_PAYMENT_CENTS)
    assert_invoice(paid)
    assert paid["status"] == "PARTIALLY_SETTLED", \
        (f"A payment short of the total moves the invoice to PARTIALLY_SETTLED, "
         f"got {paid['status']}")
    assert paid["settled_cents"] == PARTIAL_PAYMENT_CENTS, \
        f"settled_cents carries the {PARTIAL_PAYMENT_CENTS} paid, got {paid['settled_cents']}"

    balance = get_exhibitor(ground["exhibitor"]["id"])["account_balance_cents"]
    assert balance == RESIDUAL_BALANCE_CENTS, \
        (f"A PARTIALLY_SETTLED invoice contributes total minus settled, so the "
         f"balance is {RESIDUAL_BALANCE_CENTS}, got {balance}")

    order = get_order(ground["order"]["id"])
    assert_service_order(order)
    assert order["billing_status"] == "INVOICED", \
        ("Only full settlement moves the order to SETTLED, so it stays INVOICED, "
         f"got {order['billing_status']}")


# --- the payment ceiling

def test_payment_above_outstanding_balance_rejected(api):
    """PRD §3.9: "Payments are applied by supplying an `amount_cents`, which must
    be strictly positive and must not drive `settled_cents` beyond `total_cents`;
    a non-positive or overshooting amount is refused with
    `ERR_PAYMENT_EXCEEDS_BALANCE`."
    PRD §2.9: "The payment amount is positive and does not overshoot the invoice
    — otherwise `ERR_PAYMENT_EXCEEDS_BALANCE` (422). Applies to `POST
    /invoices/{id}/payments`."

    Design: Corner/validations/payment_above_outstanding_balance_rejected
    """
    ground = setup_issued_invoice(credit_limit_cents=CREDIT_LIMIT_CENTS)
    invoice_id = ground["invoice"]["id"]

    response = api.pay_invoice(invoice_id,
                               {"amount_cents": OVERSHOOTING_PAYMENT_CENTS}, FINANCE)
    validate_error(response, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE, 422)

    invoice = get_invoice(invoice_id)
    assert_invoice(invoice)
    assert invoice["settled_cents"] == 0, \
        (f"A refused overpayment settles nothing, got {invoice['settled_cents']}")
    assert invoice["status"] == "ISSUED", \
        f"The invoice stays ISSUED after the refusal, got {invoice['status']}"

    balance = get_exhibitor(ground["exhibitor"]["id"])["account_balance_cents"]
    assert balance == ORDER_TOTAL_CENTS, \
        (f"The rejected payment leaves the balance at {ORDER_TOTAL_CENTS}, got "
         f"{balance}")


# --- the sweep must stay inside one exhibitor and show

def test_invoice_sweeping_another_exhibitors_order_rejected(api):
    """PRD §3.9: "Every swept order must sit on a booth whose `exhibitor_id` and
    `show_id` match the invoice's own, or the request is refused with
    `ERR_INVOICE_SCOPE_MISMATCH`."
    PRD §2.9: "Every swept order belongs to the invoice's exhibitor and show —
    otherwise `ERR_INVOICE_SCOPE_MISMATCH` (422). Applies to `POST /invoices`."

    Design: Corner/validations/invoice_sweeping_another_exhibitors_order_rejected
    """
    ground = setup_order_ground(credit_limit_cents=CREDIT_LIMIT_CENTS)
    borealis = create_exhibitor(company_name="Borealis Robotics",
                                contact_email="ap@borealis.test",
                                credit_limit_cents=CREDIT_LIMIT_CENTS)

    response = api.create_invoice(
        create_invoice_payload(borealis["id"], ground["show"]["id"],
                               [ground["order"]["id"]]),
        FINANCE)
    validate_error(response, ApiErrorId.ERR_INVOICE_SCOPE_MISMATCH, 422)

    rows, meta = validate_paginated(
        api.list_invoices(FINANCE, params={"exhibitor_id": borealis["id"]}))
    assert meta["total_count"] == 0, \
        (f"The refused sweep must create no invoice row for Borealis, got "
         f"{meta['total_count']}")
    assert rows == [], f"Borealis holds no invoices, got {rows}"

    order = get_order(ground["order"]["id"])
    assert_service_order(order)
    assert order["billing_status"] == "UNBILLED", \
        (f"Acme's order is untouched by the refused sweep, got "
         f"{order['billing_status']}")


# --- issuing against a suspended account

def test_issue_invoice_against_suspended_exhibitor_rejected(api):
    """PRD §3.9: "Every listed service order must have a `billing_status` of
    `UNBILLED` or `REBILL_PENDING`, and the exhibitor's `status` must be `ACTIVE`
    — issuing against a `SUSPENDED` exhibitor is refused with
    `ERR_EXHIBITOR_SUSPENDED` and HTTP 402."
    PRD §2.9: "The exhibitor is not suspended — otherwise
    `ERR_EXHIBITOR_SUSPENDED` (402). Applies to `POST /invoices/{id}/issue`."

    Design: Corner/validations/issue_invoice_against_suspended_exhibitor_rejected
    """
    ground = setup_draft_invoice(credit_limit_cents=CREDIT_LIMIT_CENTS)
    invoice_id = ground["invoice"]["id"]
    exhibitor = suspend_exhibitor(ground["exhibitor"]["id"], reason="Credit review")
    assert exhibitor["status"] == "SUSPENDED", \
        f"Setup failed: the exhibitor must be SUSPENDED, got {exhibitor['status']}"

    response = api.issue_invoice(invoice_id, FINANCE)
    validate_error(response, ApiErrorId.ERR_EXHIBITOR_SUSPENDED, 402)

    invoice = get_invoice(invoice_id)
    assert_invoice(invoice)
    assert invoice["status"] == "DRAFT", \
        f"The refused issue leaves the invoice DRAFT, got {invoice['status']}"

    balance = get_exhibitor(ground["exhibitor"]["id"])["account_balance_cents"]
    assert balance == 0, \
        f"No money moves onto a suspended account's balance, got {balance}"

    order = get_order(ground["order"]["id"])
    assert order["billing_status"] == "UNBILLED", \
        (f"The order is never invoiced by the refused issue, got "
         f"{order['billing_status']}")


# --- who may issue and who may void

def test_invoice_void_by_the_issuing_operator_rejected(api):
    """PRD §2.1: "Three decisions may not be taken by the operator who originated
    the thing being decided: approving or rejecting a change order (the acting
    `X-User-ID` must differ from that change order's `created_by_user_id`),
    adjudicating a damage claim (must differ from `filed_by_user_id`), and
    voiding an invoice (must differ from `issued_by_user_id`). A violation of any
    of the three is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §3.9: "Voiding is available from `DRAFT` and from `ISSUED`, requires
    `settled_cents` to be exactly 0, and requires the acting `X-User-ID` to
    differ from the invoice's `issued_by_user_id`, a violation being refused with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/invoice_void_by_the_issuing_operator_rejected
    """
    ground = setup_issued_invoice(credit_limit_cents=CREDIT_LIMIT_CENTS)
    invoice_id = ground["invoice"]["id"]
    assert ground["invoice"]["issued_by_user_id"] == "fin-1", \
        ("Setup failed: fin-1 must be the issuer of record, got "
         f"{ground['invoice']['issued_by_user_id']}")

    response = api.void_invoice(invoice_id, {"reason": "Oops"}, FINANCE)
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

    invoice = get_invoice(invoice_id)
    assert_invoice(invoice)
    assert invoice["status"] == "ISSUED", \
        f"The refused void leaves the invoice ISSUED, got {invoice['status']}"
    assert invoice["voided_by_user_id"] is None, \
        (f"No voiding operator is recorded by a refused void, got "
         f"{invoice['voided_by_user_id']}")

    balance = get_exhibitor(ground["exhibitor"]["id"])["account_balance_cents"]
    assert balance == ORDER_TOTAL_CENTS, \
        (f"The balance does not unwind on a refused void and stays at "
         f"{ORDER_TOTAL_CENTS}, got {balance}")


def test_labor_supervisor_cannot_issue_invoice(api):
    """PRD §2.1: "Each endpoint declares the roles permitted to invoke it (see
    §4)."
    PRD §2.1: "When an authenticated operator's role is not on that endpoint's
    list, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §2.9: "The acting role appears on the endpoint's authorised list —
    otherwise `ERR_FORBIDDEN_ROLE` (403). Applies to every endpoint."

    Design: Corner/rbac/labor_supervisor_cannot_issue_invoice
    """
    ground = setup_draft_invoice(credit_limit_cents=CREDIT_LIMIT_CENTS)
    invoice_id = ground["invoice"]["id"]

    response = api.issue_invoice(invoice_id, LABOR)
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    invoice = get_invoice(invoice_id)
    assert_invoice(invoice)
    assert invoice["status"] == "DRAFT", \
        (f"Issuing is closed to the LaborSupervisor, so the invoice stays DRAFT, "
         f"got {invoice['status']}")
    assert invoice["issued_by_user_id"] is None, \
        (f"No issuer is recorded by the refused call, got "
         f"{invoice['issued_by_user_id']}")

    balance = get_exhibitor(ground["exhibitor"]["id"])["account_balance_cents"]
    assert balance == 0, \
        f"No money reaches the balance from a refused issue, got {balance}"


# --- the billing cascade lands before the response returns

def test_issue_cascade_is_visible_on_the_very_next_read(api):
    """PRD §2.11: "Cascades in this system are immediate and synchronous: by the
    time a write's response is returned, every dependent row it touches has
    already moved."
    PRD §3.9: "On success `subtotal_cents` and `total_cents` are recomputed,
    `issued_by_user_id` is set from the acting `X-User-ID`, every listed order's
    `billing_status` becomes `INVOICED` with its `invoice_id` set, the
    exhibitor's `account_balance_cents` is recomputed, and every booth that
    exhibitor holds recomputes posture — which is how a large invoice can freeze
    an exhibitor's entire floor presence in one write."

    Design: Corner/consistency_model/immediate_consistency_cascade_visible_without_any_settling_call
    """
    ground = setup_draft_invoice(credit_limit_cents=CREDIT_LIMIT_CENTS)
    invoice_id = ground["invoice"]["id"]

    issued = validate_success(api.issue_invoice(invoice_id, FINANCE))
    assert_invoice(issued)
    assert issued["status"] == "ISSUED", \
        f"The issue response already carries ISSUED, got {issued['status']}"
    assert issued["total_cents"] == ORDER_TOTAL_CENTS, \
        (f"The issue response already carries the recomputed {ORDER_TOTAL_CENTS} "
         f"total, got {issued['total_cents']}")

    balance = get_exhibitor(ground["exhibitor"]["id"])["account_balance_cents"]
    assert balance == ORDER_TOTAL_CENTS, \
        ("The very next read of the exhibitor already shows the recomputed "
         f"balance {ORDER_TOTAL_CENTS} with no settling call in between, got "
         f"{balance}")

    order = get_order(ground["order"]["id"])
    assert_service_order(order)
    assert order["billing_status"] == "INVOICED", \
        (f"The swept order has already moved to INVOICED, got "
         f"{order['billing_status']}")
    assert order["invoice_id"] == invoice_id, \
        f"The order already links back to the invoice, got {order['invoice_id']}"
    assert order["fulfillment_status"] == "PENDING", \
        (f"Billing leaves the fulfillment track alone, so the order stays PENDING, "
         f"got {order['fulfillment_status']}")
