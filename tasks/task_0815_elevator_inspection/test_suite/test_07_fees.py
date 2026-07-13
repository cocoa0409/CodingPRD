"""Fee invoices: the provisional-vs-final dual-variant amount and the
late-penalty due-period boundary."""
import test_helpers as th


# --------------------------------------------------------------------------
# Difficulty: dual_variant_calc / fee_amount_provisional_vs_final_late
# --------------------------------------------------------------------------
def test_fee_invoice_provisional_amount_is_base(api):
    """PRD §3.2: "A new invoice opens in PENDING status with a provisional
    amount_cents ... The provisional amount assumes on-time payment and equals the
    invoice's base fee ... for every other type the base is the renewal fee for the
    device's category — 30000 cents for a PASSENGER_ELEVATOR".

    Design: Difficulty/dual_variant_calc/fee_amount_provisional_vs_final_late
    """
    ctx = th.setup_owner_and_device(api, category="PASSENGER_ELEVATOR")
    resp = api.create_fee_invoice(
        th.create_fee_invoice_payload(ctx["device"]["id"], type="ANNUAL_RENEWAL", due_period=12), th.REG)
    invoice = th.validate_success(resp, expected_status=201)
    assert invoice["amount_cents"] == 30000, "provisional variant equals the category base fee"
    assert invoice["status"] == "PENDING"


def test_fee_invoice_final_amount_adds_late_penalty(api):
    """PRD §3.2: "the number of months overdue is the payment period minus the due
    period whenever the paid_period is strictly greater than the due_period ... A
    late penalty then accrues as the base fee multiplied by ten percent per whole
    month overdue, rounded half up, but the penalty is capped at the full base fee
    ... The finalized amount_cents is the base plus this penalty."

    Design: Difficulty/dual_variant_calc/fee_amount_provisional_vs_final_late
    """
    ctx = th.setup_owner_and_device(api, category="PASSENGER_ELEVATOR")
    invoice = th.create_fee_invoice(api, ctx["device"]["id"], itype="ANNUAL_RENEWAL", due_period=12)
    th.set_clock(api, 15)
    resp = api.pay_fee_invoice(invoice["id"], th.make_building_owner_headers(ctx["owner"]["id"]))
    paid = th.validate_success(resp)
    assert paid["amount_cents"] == 39000, "30000 base + min(30000*0.10*3, 30000)=9000 penalty"
    assert paid["status"] == "PAID"


# --------------------------------------------------------------------------
# Difficulty: boundary_precision_check / fee_penalty_due_period_boundary
# --------------------------------------------------------------------------
def test_fee_paid_exactly_at_due_period_has_no_penalty(api):
    """PRD §3.2: "the number of months overdue is the payment period minus the due
    period whenever the paid_period is strictly greater than the due_period, and
    zero otherwise."

    Design: Difficulty/boundary_precision_check/fee_penalty_due_period_boundary
    """
    ctx = th.setup_owner_and_device(api, category="PASSENGER_ELEVATOR")
    invoice = th.create_fee_invoice(api, ctx["device"]["id"], itype="ANNUAL_RENEWAL", due_period=12)
    th.set_clock(api, 12)
    resp = api.pay_fee_invoice(invoice["id"], th.make_building_owner_headers(ctx["owner"]["id"]))
    paid = th.validate_success(resp)
    assert paid["amount_cents"] == 30000, "paid_period 12 == due_period 12 accrues no penalty"
    assert paid["status"] == "PAID"


def test_fee_paid_before_due_period_has_no_penalty(api):
    """PRD §3.2: "the number of months overdue is the payment period minus the due
    period whenever the paid_period is strictly greater than the due_period, and
    zero otherwise."

    Design: Difficulty/boundary_precision_check/fee_penalty_due_period_boundary
    """
    ctx = th.setup_owner_and_device(api, category="PASSENGER_ELEVATOR")
    invoice = th.create_fee_invoice(api, ctx["device"]["id"], itype="ANNUAL_RENEWAL", due_period=12)
    th.set_clock(api, 11)
    resp = api.pay_fee_invoice(invoice["id"], th.make_building_owner_headers(ctx["owner"]["id"]))
    paid = th.validate_success(resp)
    assert paid["amount_cents"] == 30000, "paid_period 11 < due_period 12 accrues no penalty"
