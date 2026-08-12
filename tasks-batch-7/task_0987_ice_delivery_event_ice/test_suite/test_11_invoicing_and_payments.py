"""Invoice consolidation, payment waterfall, voids, and credit accounting
(PRD §3.8, §3.9)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    agent,
    full_book_payload,
    generate_invoice,
    get_customer,
    get_invoice,
    get_order,
    get_success_data,
    issue_invoice,
    make_active_book,
    make_customer,
    make_depot,
    make_payment,
    mini_book_payload,
    order_line,
    picked_up_order,
    run_ops,
    set_logical_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CLERK_1 = TEST_USERS["billing_clerk_1_headers"]
CLERK_2 = TEST_USERS["billing_clerk_2_headers"]


def _setup(customer_name, depot_name, limit=200000, book=None):
    depot = make_depot(10, depot_name)
    set_logical_clock()
    make_active_book(book or mini_book_payload())
    cust = make_customer(
        account_name=customer_name, kind="BAR_RESTAURANT", tier="STANDARD",
        credit_terms="NET_30", credit_limit_cents=limit,
    )
    return depot, cust


def _picked_up(cust, depot, qty=1, event_date="2026-05-10"):
    """One-pallet (default) will-call order driven to PICKED_UP (PRD §3.7)."""
    return picked_up_order(
        cust["id"], depot["id"], [order_line("BLOCK", "PALLET", qty)],
        channel="WILL_CALL", event_date=event_date,
        window_start="10:00", window_end="12:00",
    )


def _overdue_invoice(cust, depot, invoice, advance_to="2026-06-01T09:00:00Z"):
    set_logical_clock(advance_to)
    run_ops(depot["id"])
    return get_invoice(invoice["id"])


# ------------------------------------------------------------------ corner ----

def test_segregation_of_duties_void_by_issuer_rejected(api):
    """PRD §3.8: "The voiding clerk's `X-User-ID` must differ from the
    invoice's `issued_by_user_id` whenever that field is set; the clerk who
    issued an invoice cannot void it, and the attempt is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/state_machines/segregation_of_duties_void_by_issuer_rejected
    """
    depot, cust = _setup("S17", "Depot S17")
    _picked_up(cust, depot)
    invoice = issue_invoice(
        generate_invoice(cust["id"], "2026-05-01", "2026-06-01", CLERK_1)["id"],
        CLERK_1,
    )
    assert invoice["issued_by_user_id"] == "clerk_1"

    resp = api.void_invoice(invoice["id"], CLERK_1)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    voided = validate_success(api.void_invoice(invoice["id"], CLERK_2))
    assert voided["status"] == "VOID", "a different clerk may void"


def test_void_paid_invoice_rejected(api):
    """PRD §3.8: "That check is evaluated first; only then does the prohibition
    on voiding a `PAID` invoice apply (`ERR_INVOICE_NOT_VOIDABLE`), while a
    `VOID` invoice is already terminal (`ERR_ALREADY_TERMINAL`)."

    Design: Corner/state_machines/void_paid_invoice_rejected
    """
    depot, cust = _setup("S24", "Depot S24")
    _picked_up(cust, depot)
    invoice = issue_invoice(
        generate_invoice(cust["id"], "2026-05-01", "2026-06-01", CLERK_1)["id"],
        CLERK_1,
    )
    assert invoice["total_cents"] == 22500
    make_payment(cust["id"], 22500, method="ACH")
    assert get_invoice(invoice["id"])["status"] == "PAID"

    resp = api.void_invoice(invoice["id"], CLERK_2)
    validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_VOIDABLE)
    assert get_invoice(invoice["id"])["status"] == "PAID", "unchanged"


def test_consolidation_includes_no_show(api):
    """PRD §3.7: "`DELIVERED`, `PICKED_UP`, and `NO_SHOW` are thus the three
    billable terminal fulfillments; `CANCELLED` is the non-billable one."
    PRD §3.8: "Eligible orders are those of the customer whose `billing_status`
    is `UNBILLED`, whose fulfillment is `DELIVERED`, `PICKED_UP`, or `NO_SHOW`,
    and whose `fulfilled_at` date falls within the period — inclusive of the
    start, exclusive of the end."

    Design: Corner/calculations/consolidation_includes_no_show
    """
    from test_helpers import ready_order

    depot, cust = _setup("C27", "Depot C27")
    order = ready_order(
        cust["id"], depot["id"], [order_line("BLOCK", "PALLET", 1)],
        channel="WILL_CALL", event_date="2026-05-03",
        window_start="10:00", window_end="12:00",
    )
    set_logical_clock("2026-05-04T09:00:00Z")
    run_ops(depot["id"])
    assert get_order(order["id"], ADMIN)["fulfillment_status"] == "NO_SHOW"

    invoice = generate_invoice(cust["id"], "2026-05-01", "2026-06-01", CLERK_1)
    assert invoice["total_cents"] == 22500, "the NO_SHOW order is billed"
    assert get_order(order["id"], CLERK_1)["billing_status"] == "INVOICED"


def test_consolidation_empty_set_error(api):
    """PRD §3.8: "if the eligible set is empty, with `ERR_NO_BILLABLE_ORDERS`".
    PRD §3.8: "Eligible orders are those of the customer whose `billing_status`
    is `UNBILLED`, whose fulfillment is `DELIVERED`, `PICKED_UP`, or `NO_SHOW`,
    and whose `fulfilled_at` date falls within the period — inclusive of the
    start, exclusive of the end."

    Design: Corner/calculations/consolidation_empty_set_error
    """
    from test_helpers import confirmed_order

    depot, cust = _setup("C28", "Depot C28")
    # CONFIRMED is not in the billable status set.
    confirmed_order(
        cust["id"], depot["id"], [order_line("BLOCK", "PALLET", 1)],
        channel="WILL_CALL", event_date="2026-05-10",
        window_start="10:00", window_end="12:00",
    )
    resp = api.generate_invoice(
        {"customer_id": cust["id"], "period_start": "2026-05-01",
         "period_end": "2026-06-01"},
        CLERK_1,
    )
    validate_error(resp, ApiErrorId.ERR_NO_BILLABLE_ORDERS)


def test_invoice_period_conflict(api):
    """PRD §3.8: "if any non-`VOID` invoice already exists for the same
    customer and the same `period_start` and `period_end`, the request fails
    with `ERR_INVOICE_PERIOD_CONFLICT`".

    Design: Corner/validations/invoice_period_conflict
    """
    depot, cust = _setup("V36", "Depot V36")
    _picked_up(cust, depot)
    generate_invoice(cust["id"], "2026-05-01", "2026-06-01", CLERK_1)
    resp = api.generate_invoice(
        {"customer_id": cust["id"], "period_start": "2026-05-01",
         "period_end": "2026-06-01"},
        CLERK_1,
    )
    validate_error(resp, ApiErrorId.ERR_INVOICE_PERIOD_CONFLICT)


def test_waterfall_due_date_ordering(api):
    """PRD §3.8: "The eligible invoices are the customer's `ISSUED`,
    `PARTIALLY_PAID`, and `OVERDUE` ones, ordered by earliest `due_date` then
    earliest `created_at`."
    PRD §3.8: "the allocation is appended to the payment's `allocations` trace
    as an `invoice_id` / `applied_cents` pair in allocation order; and the
    invoice lands on `PAID` when its balance reaches zero, otherwise
    `PARTIALLY_PAID`".

    Design: Corner/calculations/waterfall_due_date_ordering
    """
    depot, cust = _setup("C29", "Depot C29", limit=500000)
    _picked_up(cust, depot, event_date="2026-05-10")
    inv1 = issue_invoice(
        generate_invoice(cust["id"], "2026-05-01", "2026-06-01", CLERK_1)["id"],
        CLERK_1,
    )
    assert inv1["due_date"] == "2026-05-31", "NET_30 from the 2026-05-01 issue date"

    set_logical_clock("2026-05-10T09:00:00Z")
    _picked_up(cust, depot, event_date="2026-05-20")
    inv2 = issue_invoice(
        generate_invoice(cust["id"], "2026-05-10", "2026-06-10", CLERK_1)["id"],
        CLERK_1,
    )
    assert inv2["due_date"] == "2026-06-09", "NET_30 from the 2026-05-10 issue date"

    payment = make_payment(cust["id"], 30000, method="ACH")
    assert payment["applied_cents"] == 30000
    assert payment["overpayment_cents"] == 0
    assert payment["allocations"] == [
        {"invoice_id": inv1["id"], "applied_cents": 22500},
        {"invoice_id": inv2["id"], "applied_cents": 7500},
    ], "earliest due_date first, in allocation order"

    inv1_after = get_invoice(inv1["id"])
    assert inv1_after["status"] == "PAID"
    assert inv1_after["amount_paid_cents"] == 22500
    inv2_after = get_invoice(inv2["id"])
    assert inv2_after["status"] == "PARTIALLY_PAID"
    assert inv2_after["amount_paid_cents"] == 7500
    assert inv2_after["balance_due_cents"] == 15000


# ----------------- difficulty: payment -> invoice -> standing cascade -----------

def _setup_overdue_45000(cust, depot):
    """2-pallet will-call order PICKED_UP -> invoice 45000 ISSUED (due
    2026-05-31) -> clock past due date -> aging sweep -> OVERDUE."""
    order = _picked_up(cust, depot, qty=2, event_date="2026-05-10")
    invoice = issue_invoice(
        generate_invoice(cust["id"], "2026-05-01", "2026-06-01", CLERK_1)["id"],
        CLERK_1,
    )
    assert invoice["total_cents"] == 45000
    set_logical_clock("2026-06-01T09:00:00Z")
    ops = run_ops(depot["id"])
    assert invoice["id"] in ops["overdue_invoice_ids"]
    assert get_customer(cust["id"])["standing"] == "HOLD"
    return order, invoice


def test_payment_pays_overdue_invoice_and_standing_recovers(api):
    """PRD §3.8: "Full payment cascades outward: every order attached to an
    invoice that reaches `PAID` sees its own `billing_status` move from
    `INVOICED` to `PAID`."
    PRD §3.8: "After the loop the customer's `standing` is recomputed — `GOOD`
    when no `OVERDUE` invoice remains — and `outstanding_exposure_cents` is
    recomputed."

    Design: Difficulty/transitive_cascade/payment_waterfall_pays_invoice_standing_recovers
    """
    depot, cust = _setup("TC2 Bar", "Depot TC2")
    order, invoice = _setup_overdue_45000(cust, depot)

    payment = make_payment(cust["id"], 45000, method="ACH")
    assert payment["applied_cents"] == 45000
    assert payment["overpayment_cents"] == 0

    invoice_after = get_invoice(invoice["id"])
    assert invoice_after["status"] == "PAID"
    assert invoice_after["amount_paid_cents"] == 45000
    assert invoice_after["balance_due_cents"] == 0

    customer_after = get_customer(cust["id"])
    assert customer_after["standing"] == "GOOD", "last OVERDUE cleared"
    assert customer_after["outstanding_exposure_cents"] == 0

    order_after = get_order(order["id"], CLERK_1)
    assert order_after["billing_status"] == "PAID", "attached-order fan-out"


def test_partial_payment_leaves_overdue_invoice_overdue(api):
    """PRD §3.8: "the invoice lands on `PAID` when its balance reaches zero,
    otherwise `PARTIALLY_PAID` — except that an `OVERDUE` invoice stays
    `OVERDUE` under a partial payment and only full payment lifts it to
    `PAID`."

    Design: Difficulty/transitive_cascade/payment_waterfall_pays_invoice_standing_recovers
    """
    depot, cust = _setup("TC2b Bar", "Depot TC2b")
    _order, invoice = _setup_overdue_45000(cust, depot)

    payment = make_payment(cust["id"], 20000, method="ACH")
    assert payment["applied_cents"] == 20000
    assert payment["overpayment_cents"] == 0

    invoice_after = get_invoice(invoice["id"])
    assert invoice_after["status"] == "OVERDUE", "partial payment does not lift OVERDUE"
    assert invoice_after["amount_paid_cents"] == 20000
    assert invoice_after["balance_due_cents"] == 25000
    assert get_customer(cust["id"])["standing"] == "HOLD"


# ----------------- difficulty: payment/void cent conservation ---------------------

def test_payment_void_cent_conservation(api):
    """PRD §3.8: "any `amount_paid_cents` already collected is moved into the
    customer's `credit_balance_cents` and reset to zero on the invoice".
    PRD §3.8: "the invoice lands on `PAID` when its balance reaches zero,
    otherwise `PARTIALLY_PAID`".

    Design: Difficulty/compensating_invariant/payment_void_cent_conservation
    """
    depot, cust = _setup("CI2 Bar", "Depot CI2")
    _picked_up(cust, depot, qty=2, event_date="2026-05-10")
    invoice = issue_invoice(
        generate_invoice(cust["id"], "2026-05-01", "2026-06-01", CLERK_1)["id"],
        CLERK_1,
    )
    assert invoice["total_cents"] == 45000

    payment = make_payment(cust["id"], 20000, method="ACH")
    assert payment["applied_cents"] == 20000
    mid = get_invoice(invoice["id"])
    assert mid["status"] == "PARTIALLY_PAID"
    assert mid["amount_paid_cents"] == 20000
    assert mid["balance_due_cents"] == 25000
    # Conservation before void: 20000 (non-VOID amount_paid) + 0 (wallet) ==
    # 20000 (payments received).

    voided = validate_success(api.void_invoice(invoice["id"], CLERK_2))
    assert voided["status"] == "VOID"
    after = get_invoice(invoice["id"])
    assert after["amount_paid_cents"] == 0, "reset to zero on the invoice"
    customer_after = get_customer(cust["id"])
    assert customer_after["credit_balance_cents"] == 20000, (
        "the compensating void conserved total cents: 0 + 20000 == 20000"
    )


def test_void_partial_invoice_conserves_cents_with_paid_survivor(api):
    """PRD §3.8: "any `amount_paid_cents` already collected is moved into the
    customer's `credit_balance_cents` and reset to zero on the invoice".
    PRD §3.8: "every attached order reverts from `INVOICED` to `UNBILLED` with
    its `invoice_id` cleared — becoming invoice-eligible again".

    Design: Difficulty/compensating_invariant/payment_void_cent_conservation
    """
    depot, cust = _setup("CI2b Bar", "Depot CI2b", limit=500000)
    order1 = _picked_up(cust, depot, event_date="2026-05-10")
    inv1 = issue_invoice(
        generate_invoice(cust["id"], "2026-05-01", "2026-06-01", CLERK_1)["id"],
        CLERK_1,
    )
    set_logical_clock("2026-05-10T09:00:00Z")
    order2 = _picked_up(cust, depot, event_date="2026-05-20")
    inv2 = issue_invoice(
        generate_invoice(cust["id"], "2026-05-10", "2026-06-10", CLERK_1)["id"],
        CLERK_1,
    )

    payment = make_payment(cust["id"], 30000, method="ACH")
    assert payment["applied_cents"] == 30000
    assert get_invoice(inv1["id"])["status"] == "PAID"
    assert get_invoice(inv2["id"])["status"] == "PARTIALLY_PAID"

    voided = validate_success(api.void_invoice(inv2["id"], CLERK_2))
    assert voided["status"] == "VOID"
    inv2_after = get_invoice(inv2["id"])
    assert inv2_after["amount_paid_cents"] == 0

    customer_after = get_customer(cust["id"])
    assert customer_after["credit_balance_cents"] == 7500
    inv1_after = get_invoice(inv1["id"])
    assert inv1_after["status"] == "PAID"
    assert inv1_after["amount_paid_cents"] == 22500, (
        "invariant: 22500 (PAID survivor) + 7500 (wallet) == 30000 received"
    )

    order2_after = get_order(order2["id"], CLERK_1)
    assert order2_after["billing_status"] == "UNBILLED"
    assert order2_after["invoice_id"] is None
    order1_after = get_order(order1["id"], CLERK_1)
    assert order1_after["billing_status"] == "PAID", "surviving invoice untouched"
