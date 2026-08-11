"""Invoicing, early-pay discount, payment gates, and the day-close aging sweeps
(PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_accepted_lot,
    create_customer,
    create_invoiced_order,
    create_ordered_lot,
    create_pending_order,
    confirm_order,
    create_shipper,
    create_commodity,
    post_daily_price,
    receive_lot,
    file_inspection,
    certify_inspection,
    get_invoice,
    get_success_data,
    order_line,
    post_payment,
    run_day_close,
    set_clock,
    setup_accepted_lot,
    setup_invoiced_scenario,
    validate_error,
    validate_success,
)
from test_helpers import BILLING_HEADERS, RECEIVER_HEADERS, SALES_HEADERS


def _setup_two_line_invoice():
    """Order with lines (10 @ 12.50; 5 @ 8.00), 2 pallets, driven to INVOICED."""
    base = setup_accepted_lot(defect_pct=0)
    customer = create_customer(credit_limit_cents=1000000, terms_days=10)
    payload = {
        "customer_id": customer["id"], "delivery_date": "2026-05-02",
        "window_start": "08:00", "window_end": "10:00", "pallet_count": 2,
        "lines": [order_line(base["lot"]["id"], 10, 12.50),
                  order_line(base["lot"]["id"], 5, 8.00)],
    }
    order = get_success_data(api_client.create_sales_order(payload, SALES_HEADERS))
    confirm_order(order["id"])
    get_success_data(api_client.pick_order(order["id"], RECEIVER_HEADERS))
    get_success_data(api_client.deliver_order(order["id"], RECEIVER_HEADERS))
    invoice = get_success_data(
        api_client.create_invoice({"sales_order_id": order["id"]}, BILLING_HEADERS))
    base["customer"] = customer
    base["order"] = order
    base["invoice"] = invoice
    return base


def test_invoice_issuance_computes_totals_and_dates(api):
    """PRD §3.7: "computes `deposit_cents` as the order's `pallet_count` multiplied by
    2500 cents (a refundable $25.00 per pallet), and sets `total_cents` to the sum of
    `subtotal_cents` and `deposit_cents`"
    PRD §3.7: "The `due_date` is `invoice_date` plus the customer's `terms_days`, with
    the terms snapshotted at issuance — a later terms change on the customer does not
    move an already-issued due date. The `discount_eligible_until` date is
    `invoice_date` plus 5 days."

    Design: Difficulty/combinatorial_formula/invoice_settlement_nested_totals_and_discount
    """
    base = _setup_two_line_invoice()
    invoice = base["invoice"]
    assert invoice["subtotal_cents"] == 16500   # 10*12.50 -> 12500; 5*8.00 -> 4000
    assert invoice["deposit_cents"] == 5000     # 2 pallets * 2500
    assert invoice["total_cents"] == 21500
    assert invoice["due_date"] == "2026-05-11"  # invoice_date 2026-05-01 + terms 10
    assert invoice["discount_eligible_until"] == "2026-05-06"
    assert invoice["status"] == "OPEN"
    assert invoice["balance_cents"] == 21500


def test_first_payment_in_window_earns_discount_and_settles(api):
    """PRD §3.7: "The early-pay discount is earned on the first payment whose paid
    date is on or before `discount_eligible_until` (the boundary is inclusive), and
    only when no discount has yet been taken: in that case `discount_taken_cents`
    becomes `total_cents` multiplied by two percent, rounded half-up to integer
    cents."
    PRD §3.7: "the invoice moves to `PAID` exactly when `balance_cents` reaches 0"

    Design: Difficulty/combinatorial_formula/invoice_settlement_nested_totals_and_discount
    """
    base = _setup_two_line_invoice()
    set_clock("2026-05-02T09:00:00Z")  # inside the discount window
    # discount = round_half_up(21500 * 0.02) = 430; paying total - discount settles.
    post_payment(base["invoice"]["id"], 21070)
    invoice = get_invoice(base["invoice"]["id"])
    assert invoice["discount_taken_cents"] == 430
    assert invoice["paid_cents"] == 21070
    assert invoice["balance_cents"] == 0
    assert invoice["status"] == "PAID"


# --- PAST_DUE boundary (Difficulty/boundary_precision_check) ------------------

def test_day_close_on_due_date_keeps_invoice_open(api):
    """PRD §3.7: "First, every `OPEN` invoice whose `due_date` is strictly before the
    clock date and whose `balance_cents` is still positive becomes `PAST_DUE`; an
    invoice whose clock date equals its `due_date` exactly remains `OPEN` — the
    comparison is strict."

    Design: Difficulty/boundary_precision_check/invoice_past_due_strictly_after_due_date
    """
    base = setup_invoiced_scenario(terms_days=10, pallet_count=1, line_quantity=1,
                                   line_unit_price=50.00)
    assert base["invoice"]["due_date"] == "2026-05-11"
    set_clock("2026-05-11T09:00:00Z")  # ON the due date
    summary = run_day_close()
    assert summary["invoices_marked_past_due"] == 0
    assert get_invoice(base["invoice"]["id"])["status"] == "OPEN"


def test_day_close_after_due_date_marks_past_due(api):
    """PRD §3.7: "First, every `OPEN` invoice whose `due_date` is strictly before the
    clock date and whose `balance_cents` is still positive becomes `PAST_DUE`"

    Design: Difficulty/boundary_precision_check/invoice_past_due_strictly_after_due_date
    """
    base = setup_invoiced_scenario(terms_days=10, pallet_count=1, line_quantity=1,
                                   line_unit_price=50.00)
    set_clock("2026-05-12T09:00:00Z")  # one day past the due date
    summary = run_day_close()
    assert summary["invoices_marked_past_due"] == 1
    assert get_invoice(base["invoice"]["id"])["status"] == "PAST_DUE"


# --- Breadth ------------------------------------------------------------------

def test_invoice_dates_use_default_clock_when_unset(api):
    """PRD §2.4: "At server start the logical clock is exactly `2026-05-01T00:00:00Z`
    and never falls back to wall-clock time."
    PRD §3.7: "Issuance stamps `invoice_date` from the logical clock, copies the
    customer reference and the order's `subtotal_cents`"
    PRD §3.7: "The `due_date` is `invoice_date` plus the customer's `terms_days`, with
    the terms snapshotted at issuance — a later terms change on the customer does not
    move an already-issued due date. The `discount_eligible_until` date is
    `invoice_date` plus 5 days."

    Design: Corner/entities/invoice_dates_use_default_clock_when_unset
    """
    # Deliberately no clock call anywhere in this chain: the documented default
    # 2026-05-01T00:00:00Z holds.
    commodity = create_commodity(code="TOM", name="Tomato", temp_min_f=45,
                                 temp_max_f=55)
    shipper = create_shipper()
    post_daily_price(commodity["id"], market_date="2026-05-01", low_price=8.00,
                     high_price=12.00)
    lot = create_ordered_lot(shipper["id"], commodity["id"])
    receive_lot(lot["id"])
    inspection = file_inspection(lot["id"], defect_pct=0, result="PASS")
    certify_inspection(inspection["id"])
    customer = create_customer(credit_limit_cents=1000000, terms_days=10)
    order = create_pending_order(customer["id"], lot["id"], quantity=1,
                                 unit_price=50.00, pallet_count=1)
    confirm_order(order["id"])
    get_success_data(api_client.pick_order(order["id"], RECEIVER_HEADERS))
    get_success_data(api_client.deliver_order(order["id"], RECEIVER_HEADERS))

    invoice = get_success_data(
        api_client.create_invoice({"sales_order_id": order["id"]}, BILLING_HEADERS))
    assert invoice["invoice_date"] == "2026-05-01"
    assert invoice["due_date"] == "2026-05-11"
    assert invoice["discount_eligible_until"] == "2026-05-06"


def test_early_pay_discount_boundary_on_eligible_date(api):
    """PRD §3.7: "The early-pay discount is earned on the first payment whose paid
    date is on or before `discount_eligible_until` (the boundary is inclusive), and
    only when no discount has yet been taken: in that case `discount_taken_cents`
    becomes `total_cents` multiplied by two percent, rounded half-up to integer
    cents."

    Design: Corner/calculations/early_pay_discount_boundary_on_eligible_date
    """
    base = setup_accepted_lot(defect_pct=0)
    customer = create_customer(credit_limit_cents=100000000, terms_days=10)
    _, invoice1 = create_invoiced_order(customer["id"], base["lot"]["id"],
                                        quantity=1, unit_price=50.00, pallet_count=1,
                                        window_start="08:00", window_end="10:00")
    _, invoice2 = create_invoiced_order(customer["id"], base["lot"]["id"],
                                        quantity=1, unit_price=50.00, pallet_count=1,
                                        window_start="10:00", window_end="12:00")
    # Boundary: paying on exactly discount_eligible_until (2026-05-06) earns it.
    set_clock("2026-05-06T09:00:00Z")
    post_payment(invoice1["id"], 7350)  # 7500 - round(7500*0.02)=150
    first = get_invoice(invoice1["id"])
    assert first["discount_taken_cents"] == 150
    assert first["balance_cents"] == 0
    assert first["status"] == "PAID"

    # One day past the boundary: no discount accrues.
    set_clock("2026-05-07T09:00:00Z")
    post_payment(invoice2["id"], 100)
    second = get_invoice(invoice2["id"])
    assert second["discount_taken_cents"] == 0
    assert second["balance_cents"] == 7400
    assert second["status"] == "OPEN"


def test_payment_above_balance_returns_overpayment(api):
    """PRD §3.7: "The payment is rejected with `ERR_OVERPAYMENT` when `amount_cents`
    exceeds the `balance_cents` that would remain after any earned discount."

    Design: Corner/errors/payment_above_balance_returns_overpayment
    """
    base = setup_invoiced_scenario(terms_days=10, pallet_count=1, line_quantity=1,
                                   line_unit_price=50.00)
    set_clock("2026-05-02T09:00:00Z")  # inside the discount window
    # Even after the would-be 150 discount, balance would be 7350 < 10000.
    resp = api.create_payment({"invoice_id": base["invoice"]["id"],
                               "amount_cents": 10000}, BILLING_HEADERS)
    validate_error(resp, ApiErrorId.ERR_OVERPAYMENT)
    invoice = get_invoice(base["invoice"]["id"])
    assert invoice["paid_cents"] == 0
    assert invoice["status"] == "OPEN"


def test_second_invoice_for_order_returns_invoice_exists(api):
    """PRD §3.7: "Exactly one invoice may exist per order; attempting to invoice an
    already-`INVOICED` order is rejected with `ERR_INVOICE_EXISTS`."

    Design: Corner/errors/second_invoice_for_order_returns_invoice_exists
    """
    base = setup_invoiced_scenario(terms_days=10, pallet_count=1, line_quantity=1,
                                   line_unit_price=50.00)
    resp = api.create_invoice({"sales_order_id": base["order"]["id"]}, BILLING_HEADERS)
    validate_error(resp, ApiErrorId.ERR_INVOICE_EXISTS)
    invoices = get_success_data(
        api_client.list_order_invoices(base["order"]["id"], BILLING_HEADERS))
    assert len(invoices) == 1
    assert invoices[0]["id"] == base["invoice"]["id"]


def test_payment_on_paid_invoice_returns_invalid_state(api):
    """PRD §3.7: "Posting requires the invoice to be in `OPEN`, `PAST_DUE`, or
    `TRUST_CLAIMED` — a payment on a `PAID` invoice is `ERR_INVALID_STATE`."
    PRD §2.8: "and finally money gates (`ERR_CREDIT_LIMIT_EXCEEDED`,
    `ERR_OVERPAYMENT`), which always run last."

    Design: Corner/state_machines/payment_on_paid_invoice_returns_invalid_state
    """
    base = setup_invoiced_scenario(terms_days=10, pallet_count=1, line_quantity=1,
                                   line_unit_price=50.00)
    set_clock("2026-05-10T09:00:00Z")  # past the discount window: no discount
    post_payment(base["invoice"]["id"], 7500)
    assert get_invoice(base["invoice"]["id"])["status"] == "PAID"

    resp = api.create_payment({"invoice_id": base["invoice"]["id"],
                               "amount_cents": 100}, BILLING_HEADERS)
    # The state gate fires before the fiscal overpayment gate.
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
