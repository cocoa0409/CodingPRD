"""Release gating, invoice assembly, payment waterfall, and customer standing
(PRD §3.5)."""
from datetime import datetime

from test_helpers import (
    TEST_USERS,
    accept_quote,
    assert_invoice,
    assert_invoice_balance_invariant,
    create_customer,
    create_motor,
    create_payment_payload,
    create_shop,
    diagnose_work_order,
    get_customer,
    get_single_invoice,
    intake_work_order,
    issue_quote,
    record_coil_data,
    record_final_test,
    record_incoming_test,
    record_payment,
    release_work_order,
    send_quote,
    set_clock,
    setup_released_work_order,
    start_rewind,
    validate_error,
    validate_success,
)

MANAGER = TEST_USERS["service_manager_headers"]


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _release_simple_order(shop_id, customer_id, serial, rewind_hours, materials_cents=0):
    """Full pipeline to READY_FOR_PICKUP for one small-frame motor; returns
    (work_order, invoice)."""
    motor = create_motor(shop_id, customer_id, serial_number=serial, rated_kw=10, frame_mm=200)
    wo = intake_work_order(shop_id, customer_id, motor["id"], "STANDARD")
    record_incoming_test(shop_id, wo["id"])
    diagnose_work_order(
        shop_id, wo["id"], failure_diagnosis="x", rewind_hours=rewind_hours,
        materials_cents=materials_cents, replacement_cost_cents=999999,
    )
    quote = issue_quote(shop_id, wo["id"])
    send_quote(shop_id, wo["id"], quote["id"])
    accept_quote(shop_id, wo["id"], quote["id"], customer_id)
    start_rewind(shop_id, wo["id"])
    record_coil_data(shop_id, wo["id"])
    record_final_test(shop_id, wo["id"], 2.0)
    wo = release_work_order(shop_id, wo["id"])
    return wo, get_single_invoice(shop_id, wo["id"])


def _two_open_invoices(api):
    """Customer with I1 (34680c, issued 2026-08-01) and I2 (43860c, issued
    2026-08-02); clock ends at 2026-08-10 with both invoices OPEN."""
    shop = create_shop()
    customer = create_customer(shop["id"])
    _wo1, i1 = _release_simple_order(shop["id"], customer["id"], "M-WF1", rewind_hours=1)
    set_clock("2026-08-02T00:00:00Z")
    _wo2, i2 = _release_simple_order(shop["id"], customer["id"], "M-WF2", rewind_hours=2)
    set_clock("2026-08-10T00:00:00Z")
    return shop, customer, i1, i2


def _two_overdue_invoices(api):
    """Same ledger as _two_open_invoices but the clock ends at 2026-10-01:
    I1 is 31 days past due, I2 exactly 30."""
    shop = create_shop()
    customer = create_customer(shop["id"])
    _wo1, i1 = _release_simple_order(shop["id"], customer["id"], "M-S1", rewind_hours=1)
    set_clock("2026-08-02T00:00:00Z")
    _wo2, i2 = _release_simple_order(shop["id"], customer["id"], "M-S2", rewind_hours=2)
    set_clock("2026-10-01T00:00:00Z")
    return shop, customer, i1, i2


# ─── Invoice per-line rounding (Difficulty/combinatorial_formula) ───

def test_invoice_total_rounds_per_line_then_sums(api):
    """PRD §3.5: "Each line is computed and rounded to integer cents first;
    `invoice_total_cents` is the sum of the rounded lines, never a
    sum-then-round."
    PRD §3.5: "Every job carries an incoming-test fee of $75.00 (7500 cents).
    A core-loss test fee of $120.00 (12000 cents) is added when a core-loss
    test record exists for the order. A balancing fee of $95.00 (9500 cents)
    is added when the order has reached `BALANCING` at least once."

    Design: Difficulty/combinatorial_formula/invoice_total_rounds_per_line_then_sums
    """
    bundle = setup_released_work_order(
        rewind_hours=12, materials_cents=38000, replacement_cost_cents=9999999,
        core_loss_watts=3200,
        motor_overrides={"rated_kw": 75, "frame_mm": 355, "manufacture_year": 2020},
    )
    # Quote lines: labor 12*9500=114000, materials 38000, supplies
    # 100000*0.08 + 52000*0.06 = 11120, rush 0 -> 163120.
    # Invoice: 7500 + 12000 + 163120 + 9500 + 8500 = 200620.
    assert bundle["work_order"]["status"] == "READY_FOR_PICKUP"
    assert bundle["work_order"]["invoice_total_cents"] == 200620


def test_invoice_record_matches_per_line_total(api):
    """PRD §3.5: "The invoice itself snapshots the order's economics at
    issuance: `total_cents` equals the work order's `invoice_total_cents` at
    that moment, `amount_paid_cents` starts at zero, `balance_due_cents` is
    the total minus the amount paid".

    Design: Difficulty/combinatorial_formula/invoice_total_rounds_per_line_then_sums
    """
    bundle = setup_released_work_order(
        rewind_hours=12, materials_cents=38000, replacement_cost_cents=9999999,
        core_loss_watts=3200,
        motor_overrides={"rated_kw": 75, "frame_mm": 355, "manufacture_year": 2020},
    )
    invoice = bundle["invoice"]
    assert_invoice(invoice)
    assert invoice["total_cents"] == 200620
    assert invoice["balance_due_cents"] == 200620
    assert invoice["status"] == "OPEN"
    assert_invoice_balance_invariant(invoice)


# ─── Waterfall conservation (Difficulty/compensating_invariant) ───

def test_payment_waterfall_conserves_total_cents(api):
    """PRD §3.5: "The allocation is a waterfall across the customer's `OPEN`
    and `OVERDUE` invoices, oldest first by `issued_at` ascending with ties
    broken by `created_at` ascending — never by identifier."
    PRD §3.5: "The response enumerates the allocation as an `applied` list of
    `invoice_id` and `applied_cents` pairs, plus any `credit_added_cents`."

    Design: Difficulty/compensating_invariant/payment_waterfall_conserves_total_cents
    """
    shop, customer, i1, i2 = _two_open_invoices(api)
    result = record_payment(shop["id"], customer["id"], 70000)

    applied_total = sum(entry["applied_cents"] for entry in result["applied"])
    assert applied_total + result["credit_added_cents"] == 70000
    assert result["applied"][0]["invoice_id"] == i1["id"]
    assert result["applied"][0]["applied_cents"] == 34680
    assert result["applied"][1]["invoice_id"] == i2["id"]
    assert result["applied"][1]["applied_cents"] == 35320  # min(35320, 43860)
    assert result["credit_added_cents"] == 0


def test_payment_flips_fully_paid_invoice_and_leaves_partial(api):
    """PRD §3.5: "Each invoice in turn absorbs the smaller of the remaining
    payment and its own `balance_due_cents`, growing `amount_paid_cents` and
    shrinking `balance_due_cents` by the applied amount, and an invoice whose
    balance reaches zero flips automatically to `PAID`."

    Design: Difficulty/compensating_invariant/payment_waterfall_conserves_total_cents
    """
    shop, customer, i1, i2 = _two_open_invoices(api)
    record_payment(shop["id"], customer["id"], 70000)

    inv1 = validate_success(api.get_invoice(shop["id"], i1["id"], MANAGER), 200)
    assert inv1["status"] == "PAID"
    assert_invoice_balance_invariant(inv1)

    inv2 = validate_success(api.get_invoice(shop["id"], i2["id"], MANAGER), 200)
    assert inv2["status"] == "OPEN"
    assert inv2["balance_due_cents"] == 8540
    assert_invoice_balance_invariant(inv2)


# ─── Standing derived two ways (Difficulty/dual_variant_calc) ───

def test_standing_hold_then_watch_after_waterfall_payment(api):
    """PRD §3.5: "It is `HOLD` when any of their invoices is more than thirty
    days past its `due_at` — exactly thirty days past due is not enough.
    Short of that, it is `WATCH` when any invoice is past due".
    PRD §3.5: "Standing is recomputed after every payment."

    Design: Difficulty/dual_variant_calc/standing_recomputed_two_ways_on_payment_vs_overdue
    """
    shop, customer, i1, i2 = _two_overdue_invoices(api)
    before = get_customer(shop["id"], customer["id"])
    assert before["standing"] == "HOLD"  # I1 31 days past due

    record_payment(shop["id"], customer["id"], 44680)
    after = get_customer(shop["id"], customer["id"])
    assert after["standing"] == "WATCH"  # I2 exactly 30 days past due


def test_payment_allocation_oldest_first_with_partial_second(api):
    """PRD §3.5: "The allocation is a waterfall across the customer's `OPEN`
    and `OVERDUE` invoices, oldest first by `issued_at` ascending with ties
    broken by `created_at` ascending — never by identifier."
    PRD §3.5: "an `OPEN` invoice past its `due_at` with a positive balance
    becomes `OVERDUE`".

    Design: Difficulty/dual_variant_calc/standing_recomputed_two_ways_on_payment_vs_overdue
    """
    shop, customer, i1, i2 = _two_overdue_invoices(api)
    result = record_payment(shop["id"], customer["id"], 44680)

    assert result["applied"][0]["invoice_id"] == i1["id"]
    assert result["applied"][0]["applied_cents"] == 34680
    assert result["applied"][1]["invoice_id"] == i2["id"]
    assert result["applied"][1]["applied_cents"] == 10000
    assert result["credit_added_cents"] == 0

    inv1 = validate_success(api.get_invoice(shop["id"], i1["id"], MANAGER), 200)
    assert inv1["status"] == "PAID"
    inv2 = validate_success(api.get_invoice(shop["id"], i2["id"], MANAGER), 200)
    assert inv2["status"] == "OVERDUE"
    assert inv2["balance_due_cents"] == 33860


# ─── Thirty-day standing boundary (Difficulty/boundary_precision_check) ───

def test_thirty_days_overdue_is_watch_not_hold(api):
    """PRD §3.5: "It is `HOLD` when any of their invoices is more than thirty
    days past its `due_at` — exactly thirty days past due is not enough."

    Design: Difficulty/boundary_precision_check/standing_hold_boundary_thirty_days_is_watch_not_hold
    """
    shop = create_shop()
    customer = create_customer(shop["id"])
    _wo, _invoice = _release_simple_order(shop["id"], customer["id"], "M-B30", rewind_hours=1)
    # Invoice issued 2026-08-01, due 2026-08-31.
    set_clock("2026-09-30T00:00:00Z")  # exactly 30 days past due
    standing = get_customer(shop["id"], customer["id"])
    assert standing["standing"] == "WATCH"


def test_thirty_one_days_overdue_is_hold(api):
    """PRD §3.5: "It is `HOLD` when any of their invoices is more than thirty
    days past its `due_at` — exactly thirty days past due is not enough."

    Design: Difficulty/boundary_precision_check/standing_hold_boundary_thirty_days_is_watch_not_hold
    """
    shop = create_shop()
    customer = create_customer(shop["id"])
    _wo, _invoice = _release_simple_order(shop["id"], customer["id"], "M-B31", rewind_hours=1)
    set_clock("2026-09-30T00:00:00Z")
    assert get_customer(shop["id"], customer["id"])["standing"] == "WATCH"

    set_clock("2026-10-01T00:00:00Z")  # 31 days past due
    assert get_customer(shop["id"], customer["id"])["standing"] == "HOLD"


# ─── Computed invoice read (Corner/endpoints) ───

def test_computed_read_invoice_after_release(api):
    """PRD §3.5: "The invoice itself snapshots the order's economics at
    issuance: `total_cents` equals the work order's `invoice_total_cents` at
    that moment, `amount_paid_cents` starts at zero, `balance_due_cents` is
    the total minus the amount paid, `issued_at` is stamped at release,
    `due_at` falls thirty days after issuance on net-30 terms".

    Design: Corner/endpoints/computed_read_invoice_after_release
    """
    bundle = setup_released_work_order(
        priority="RUSH",
        rewind_hours=10, materials_cents=20000, replacement_cost_cents=999999,
        motor_overrides={"rated_kw": 30, "frame_mm": 200, "manufacture_year": 2020},
    )
    # Quote lines: 85000 + 20000 + 8300 + round(113300*0.35)=39655 -> 152955.
    # Invoice: 7500 + 152955 + 9500 + 8500 = 178455 (no core-loss line).
    invoices = validate_success(
        api.list_invoices(bundle["shop"]["id"], bundle["work_order"]["id"], MANAGER), 200
    )
    assert len(invoices) == 1
    invoice = invoices[0]
    assert_invoice(invoice)
    assert invoice["total_cents"] == 178455
    assert invoice["status"] == "OPEN"
    assert invoice["balance_due_cents"] == 178455
    delta = _parse(invoice["due_at"]) - _parse(invoice["issued_at"])
    assert delta.days == 30


# ─── Void with payments (Corner/validations) ───

def test_invoice_void_with_payments_rejected(api):
    """PRD §3.5: "A `ServiceManager` may void an invoice only while its
    `amount_paid_cents` is still zero — any applied payment blocks the void
    with `ERR_INVOICE_HAS_PAYMENTS` (HTTP 409)".

    Design: Corner/validations/invoice_void_with_payments_rejected
    """
    bundle = setup_released_work_order(
        motor_overrides={"rated_kw": 30, "frame_mm": 200, "manufacture_year": 2020}
    )
    shop_id, cust_id = bundle["shop"]["id"], bundle["customer"]["id"]
    invoice = bundle["invoice"]

    record_payment(shop_id, cust_id, 1000)
    res = api.void_invoice(shop_id, invoice["id"], MANAGER)
    validate_error(res, "ERR_INVOICE_HAS_PAYMENTS", expected_status=409)
