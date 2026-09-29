"""Early payment, settlement, accounting and remittance endpoints
(PRD 3.8, 3.9)."""

from flask import Blueprint

from db import (base_row, clock_date, date_midnight, db, plus_days, public,
                put_dt, sorted_rows, touch)
from errors import ApiError
from middleware import (BUYER_ADMIN, BUYER_TREASURY, FUNDER, PLATFORM_OPS,
                        SUPPLIER, authenticate, get_offer, get_payment,
                        scope_offer, scope_payment)
from response import ok, ok_list
from services import calc, flows
from services import guards as g
from services import recompute as rc
from validation import (body, filter_arg, opt_str, paginate, pagination,
                        req_enum, req_int, req_str)

bp = Blueprint("payments", __name__)

READ_ROLES = (BUYER_ADMIN, BUYER_TREASURY, SUPPLIER, FUNDER, PLATFORM_OPS)


def _payment_context(payment):
    invoice = db.invoices.get(payment["invoice_id"])
    program = rc.program_of_invoice(invoice) if invoice else None
    buyer = rc.buyer_of_program(program) if program else None
    supplier = db.suppliers.get(invoice["supplier_id"]) if invoice else None
    funder = db.funders.get(payment["funder_id"]) if payment.get("funder_id") else None
    offer = db.offers.get(payment["offer_id"])
    return invoice, program, buyer, supplier, funder, offer


def _settle_ledgers(payment, buyer, funder):
    if funder is not None:
        rc.recompute_funder_capital(funder)
    if buyer is not None:
        rc.recompute_buyer_credit(buyer)


@bp.post("/early-payments")
def reserve_payment():
    ctx = authenticate((BUYER_TREASURY,))
    b = body()
    offer_id = req_str(b, "offer_id", 1)
    expected_offer_version = req_int(b, "expected_offer_version", 0)
    offer = get_offer(offer_id)
    scope_offer(ctx, offer)

    invoice = db.invoices.get(offer["invoice_id"])
    program = rc.program_of_invoice(invoice) if invoice else None
    buyer = rc.buyer_of_program(program) if program else None
    supplier = db.suppliers.get(offer["supplier_id"])

    g.require_invoice_not_suppressed(invoice)
    g.require_program_open(program)
    if offer["status"] != "ACCEPTED":
        g.invalid_state("Only an ACCEPTED offer can be reserved for early payment.")
    if invoice["status"] != "AWARDED":
        g.invalid_state("The invoice is not AWARDED.")
    g.require_offer_version(offer, expected_offer_version)
    g.require_no_sanctions_hold(supplier)
    g.require_payment_ready(supplier)

    basis = offer["_requested_pay_date"]
    days = g.require_days_early(program, invoice, basis)

    face = invoice["face_amount_cents"]
    accepted_apr = offer["accepted_apr_bps"]
    discount = calc.discount_cents(face, accepted_apr, days)
    pre_fee_net = face - discount
    projected = flows.projected_value_date(basis)
    source, funder = flows.resolve_funding(
        program, buyer, invoice, accepted_apr, pre_fee_net, projected
    )
    fee = calc.funder_fee_cents(pre_fee_net, source, funder)
    net = calc.net_payment_cents(face, discount, fee)
    default_status = calc.default_accounting_status(source, days, accepted_apr, buyer)

    # re-reservation voids any prior live payment on the same offer, leaving its
    # settlement and accounting axes untouched
    released_funders = []
    for prior in rc.offer_payments(offer["id"]):
        if prior["funding_status"] in ("RESERVED", "DEPLOYED"):
            prior["funding_status"] = "VOID"
            touch(prior)
            if prior.get("funder_id"):
                released_funders.append(db.funders.get(prior["funder_id"]))

    row = base_row()
    row.update(
        {
            "offer_id": offer["id"],
            "invoice_id": invoice["id"],
            "funder_id": funder["id"] if funder is not None else None,
            "funding_source": source,
            "accepted_apr_bps": accepted_apr,
            "face_covered_cents": face,
            "days_early": days,
            "discount_amount_cents": discount,
            "funder_fee_cents": fee,
            "net_payment_cents": net,
            "funding_status": "RESERVED",
            "settlement_status": "UNSENT",
            "accounting_status": "UNCLASSIFIED",
            "default_accounting_status": default_status,
            "override_reason": None,
        }
    )
    put_dt(row, "requested_pay_date", basis, offer["requested_pay_date"])
    put_dt(row, "execution_date", None)
    put_dt(row, "value_date", None)
    db.payments[row["id"]] = row

    for released in released_funders:
        if released is not None and (funder is None or released["id"] != funder["id"]):
            rc.recompute_funder_capital(released)
    if funder is not None:
        rc.recompute_funder_capital(funder)
    if buyer is not None:
        rc.recompute_buyer_credit(buyer)
    rc.recompute_invoice_face(invoice)
    touch(offer)
    return ok(public(row), 201)


def _visible_payments(ctx):
    rows = []
    for payment in db.payments.values():
        invoice = db.invoices.get(payment["invoice_id"])
        if ctx.role == SUPPLIER:
            if invoice is None or invoice["supplier_id"] != ctx.uid:
                continue
        if ctx.role == FUNDER and payment.get("funder_id") != ctx.uid:
            continue
        if ctx.is_buyer:
            program = rc.program_of_invoice(invoice) if invoice else None
            if program is None or program["buyer_id"] != ctx.uid:
                continue
        rows.append(payment)
    return sorted_rows(rows)


@bp.get("/early-payments")
def list_payments():
    ctx = authenticate(READ_ROLES)
    limit, offset = pagination()
    rows = _visible_payments(ctx)
    for name in ("offer_id", "invoice_id", "funder_id", "funding_status", "settlement_status"):
        value = filter_arg(name)
        if value is not None:
            rows = [r for r in rows if r.get(name) == value]
    total = len(rows)
    return ok_list([public(r) for r in paginate(rows, limit, offset)], limit, offset, total)


@bp.get("/early-payments/<payment_id>")
def read_payment(payment_id):
    ctx = authenticate(READ_ROLES)
    payment = get_payment(payment_id)
    scope_payment(ctx, payment)
    return ok(public(payment))


def _advice_count_for_invoice(invoice_id):
    count = 0
    for advice in db.advices.values():
        payment = db.payments.get(advice["early_payment_id"])
        if payment is not None and payment["invoice_id"] == invoice_id:
            count += 1
    return count


@bp.post("/early-payments/<payment_id>/execute")
def execute_payment(payment_id):
    ctx = authenticate((BUYER_TREASURY,))
    payment = get_payment(payment_id)
    scope_payment(ctx, payment)
    invoice, program, buyer, supplier, funder, offer = _payment_context(payment)

    g.require_payment_not_terminal(payment)
    if payment["funding_status"] != "RESERVED":
        g.invalid_state("Only a RESERVED payment can be executed.")
    if payment["settlement_status"] != "UNSENT":
        g.invalid_state("The settlement axis has already moved.")
    if invoice["dispute_suppressed"]:
        g.invalid_state("The invoice is suppressed by an open dispute.")
    g.require_no_sanctions_hold(supplier)
    g.require_payment_ready(supplier)

    execution_dt = date_midnight(clock_date())
    days = g.require_days_early(program, invoice, execution_dt)

    face = invoice["face_amount_cents"]
    accepted_apr = payment["accepted_apr_bps"]
    discount = calc.discount_cents(face, accepted_apr, days)
    pre_fee_net = face - discount
    if payment["funding_source"] == "BUYER_SELF":
        g.require_buyer_credit_headroom(buyer, pre_fee_net, payment["id"])
    fee = calc.funder_fee_cents(pre_fee_net, payment["funding_source"], funder)
    net = calc.net_payment_cents(face, discount, fee)

    value_dt = plus_days(execution_dt, calc.VALUE_DATE_LAG_DAYS)
    put_dt(payment, "execution_date", execution_dt)
    put_dt(payment, "value_date", value_dt)
    payment["days_early"] = days
    payment["discount_amount_cents"] = discount
    payment["funder_fee_cents"] = fee
    payment["net_payment_cents"] = net
    payment["funding_status"] = "DEPLOYED"
    payment["settlement_status"] = "REMITTED"
    touch(payment)

    invoice["provisional_discount_cents"] = discount
    touch(invoice)
    _settle_ledgers(payment, buyer, funder)

    advice = base_row(common=False)
    advice.update(
        {
            "early_payment_id": payment["id"],
            "advice_number": calc.advice_number(
                invoice["invoice_number"], _advice_count_for_invoice(invoice["id"])
            ),
            "supplier_legal_name": supplier["legal_name"] if supplier else None,
            "supplier_account_last4": supplier["verified_account_last4"] if supplier else None,
            "gross_face_cents": face,
            "discount_cents": discount,
            "fee_cents": fee,
            "net_paid_cents": net,
            "delivery_status": "SENT"
            if supplier is not None and supplier["remittance_email"] is not None
            else "BOUNCED",
        }
    )
    put_dt(advice, "value_date", value_dt)
    db.advices[advice["id"]] = advice
    return ok(public(payment))


@bp.post("/early-payments/<payment_id>/settlement/confirm")
def confirm_settlement(payment_id):
    ctx = authenticate((BUYER_TREASURY, PLATFORM_OPS))
    payment = get_payment(payment_id)
    scope_payment(ctx, payment)
    invoice, program, buyer, supplier, funder, offer = _payment_context(payment)

    g.require_payment_not_terminal(payment)
    if payment["funding_status"] != "DEPLOYED":
        g.invalid_state("Only a DEPLOYED payment can be confirmed.")
    if payment["settlement_status"] != "REMITTED":
        g.invalid_state("Only a REMITTED settlement can be confirmed.")
    if payment["_value_date"] is None or clock_date() < payment["_value_date"].date():
        g.invalid_state("The value date has not yet arrived.")

    face = invoice["face_amount_cents"]
    accepted_apr = payment["accepted_apr_bps"]
    days = calc.days_early(invoice["_net_due_date"], payment["_value_date"])
    discount = calc.discount_cents(face, accepted_apr, days)
    pre_fee_net = face - discount
    fee = calc.funder_fee_cents(pre_fee_net, payment["funding_source"], funder)
    net = calc.net_payment_cents(face, discount, fee)

    payment["days_early"] = days
    payment["discount_amount_cents"] = discount
    payment["funder_fee_cents"] = fee
    payment["net_payment_cents"] = net
    payment["settlement_status"] = "CONFIRMED"
    payment["funding_status"] = "RELEASED"
    touch(payment)

    invoice["final_discount_cents"] = discount
    invoice["discount_true_up_cents"] = discount - invoice["provisional_discount_cents"]
    if invoice["status"] == "AWARDED":
        invoice["status"] = "EARLY_PAID"
    touch(invoice)
    _settle_ledgers(payment, buyer, funder)
    if program is not None:
        rc.recompute_program_adoption(program, force=True)
    return ok(public(payment))


@bp.post("/early-payments/<payment_id>/settlement/fail")
def fail_settlement(payment_id):
    ctx = authenticate((BUYER_TREASURY, PLATFORM_OPS))
    b = body()
    req_str(b, "failure_reason", 1, 500)
    payment = get_payment(payment_id)
    scope_payment(ctx, payment)
    invoice, program, buyer, supplier, funder, offer = _payment_context(payment)

    g.require_payment_not_terminal(payment)
    if payment["funding_status"] != "DEPLOYED":
        g.invalid_state("Only a DEPLOYED payment can fail settlement.")
    if payment["settlement_status"] != "REMITTED":
        g.invalid_state("Only a REMITTED settlement can fail.")

    payment["settlement_status"] = "FAILED"
    payment["funding_status"] = "VOID"
    touch(payment)

    invoice["provisional_discount_cents"] = 0
    rc.recompute_invoice_face(invoice, force=True)
    _settle_ledgers(payment, buyer, funder)
    return ok(public(payment))


@bp.post("/early-payments/<payment_id>/accounting-classification")
def classify_payment(payment_id):
    ctx = authenticate((BUYER_TREASURY,))
    b = body()
    classification = req_enum(b, "classification", ("TRADE_PAYABLE", "DEBT_RECLASSIFIED"))
    override_reason = opt_str(b, "override_reason", 0, 2000)
    payment = get_payment(payment_id)
    scope_payment(ctx, payment)

    if classification != payment["default_accounting_status"]:
        if override_reason is None or override_reason.strip() == "":
            raise ApiError("ERR_RECLASS_OVERRIDE_REASON_REQUIRED")

    payment["accounting_status"] = classification
    if override_reason is not None:
        payment["override_reason"] = override_reason
    touch(payment)
    return ok(public(payment))


@bp.get("/early-payments/<payment_id>/remittance-advices")
def list_advices(payment_id):
    ctx = authenticate((BUYER_TREASURY, SUPPLIER, PLATFORM_OPS))
    limit, offset = pagination()
    payment = get_payment(payment_id)
    scope_payment(ctx, payment)
    rows = sorted_rows(
        [a for a in db.advices.values() if a["early_payment_id"] == payment["id"]]
    )
    total = len(rows)
    return ok_list([public(r) for r in paginate(rows, limit, offset)], limit, offset, total)
