"""Invoices, payments (PRD §3.11, §3.12)."""
from flask import Blueprint, request

import db
from errors import err
from response import ok, ok_list
from routes.helpers import gate, require_ownership
from services import validate as V
from services import calc
from services.common import new_record, touch, sort_by_created
from services.lookup import get_or_404
from services.serialize import invoice_out, payment_out
from services.billing import reevaluate_billing_on_settlement
from util import to_midnight, format_ts, format_date

bp = Blueprint("invoices", __name__)

PAY_METHODS = {"MANUAL", "AUTOPAY"}


@bp.route("/accounts/<aid>/invoices", methods=["POST"])
def generate_invoice(aid):
    gate({"Dispatcher"})
    a = get_or_404(db.service_accounts, aid)
    body = V.get_body(request)

    # priority 5: well-formedness
    expected_version = V.require_int(body, "expected_account_version")
    period_start = V.require_dt(body, "period_start")
    period_end = V.require_dt(body, "period_end")
    due_date = V.require_dt(body, "due_date")

    # priority 6: OCC on account.version
    if expected_version != a["version"]:
        raise err("ERR_STALE_VERSION", "expected_account_version does not match.")

    plan = db.service_plans[a["plan_id"]]
    ps = to_midnight(period_start)
    pe = to_midnight(period_end)

    gross = calc.invoice_gross(a, plan, ps, pe)

    # Create the invoice first so credits can point at it, then compute applied.
    inv = new_record({
        "account_id": a["id"],
        "period_start": format_date(ps),
        "period_end": format_date(pe),
        "gross_amount_cents": gross,
        "credit_applied_cents": 0,
        "amount_due_cents": gross,
        "due_date": format_date(to_midnight(due_date)),
        "status": "OPEN",
    })
    db.invoices[inv["id"]] = inv

    credit_applied = calc.apply_credits(a["id"], gross, inv["id"])
    inv["credit_applied_cents"] = credit_applied
    inv["amount_due_cents"] = max(0, gross - credit_applied)

    # generating the invoice increments the account's version
    touch(a)
    return ok(invoice_out(inv), 201)


@bp.route("/accounts/<aid>/invoices", methods=["GET"])
def list_account_invoices(aid):
    user_id, role = gate({"Dispatcher", "AccountHolder"})
    a = get_or_404(db.service_accounts, aid)
    require_ownership(role, user_id, a["id"])
    limit, offset = V.parse_pagination(request.args)
    items = [i for i in db.invoices.values() if i["account_id"] == a["id"]]
    items = sort_by_created(items)
    total = len(items)
    page = V.paginate(items, limit, offset)
    return ok_list([invoice_out(i) for i in page], limit, offset, total)


@bp.route("/invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    user_id, role = gate({"Dispatcher", "AccountHolder"})
    inv = get_or_404(db.invoices, iid)
    require_ownership(role, user_id, inv["account_id"])
    return ok(invoice_out(inv))


@bp.route("/invoices/<iid>/pay", methods=["POST"])
def pay_invoice(iid):
    user_id, role = gate({"AccountHolder", "Dispatcher"})
    inv = get_or_404(db.invoices, iid)
    require_ownership(role, user_id, inv["account_id"])
    body = V.get_body(request)
    amount = V.require_int(body, "amount_cents", minimum=1)
    method = V.require_enum(body, "method", PAY_METHODS)

    # priority 7: state legality (pay allowed from OPEN or PAST_DUE)
    if inv["status"] not in ("OPEN", "PAST_DUE"):
        raise err("ERR_INVALID_STATE", "Invoice is not OPEN or PAST_DUE.")
    # priority 15: exact settlement
    if amount != inv["amount_due_cents"]:
        raise err("ERR_PAYMENT_AMOUNT_MISMATCH", "Payment must equal amount_due_cents exactly.")

    payment = new_record({
        "invoice_id": inv["id"],
        "amount_cents": amount,
        "method": method,
        "status": "APPLIED",
    })
    db.payments[payment["id"]] = payment

    inv["status"] = "PAID"
    touch(inv)

    # re-evaluate billing dimension; PAST_DUE/IN_COLLECTIONS -> CURRENT when settled
    account = db.service_accounts.get(inv["account_id"])
    if account is not None and reevaluate_billing_on_settlement(account):
        touch(account)

    return ok(payment_out(payment), 201)


@bp.route("/invoices/<iid>/void", methods=["POST"])
def void_invoice(iid):
    gate({"Dispatcher"})
    inv = get_or_404(db.invoices, iid)
    # priority 7: void only from OPEN
    if inv["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Invoice is not OPEN.")

    # cascade: restore consumed credits back to ISSUED (conserve credit_balance)
    for c in db.missed_pickup_credits.values():
        if c.get("applied_invoice_id") == inv["id"] and c["status"] == "APPLIED":
            c["status"] = "ISSUED"
            c["applied_invoice_id"] = None
            touch(c)

    inv["status"] = "VOID"
    touch(inv)
    return ok(invoice_out(inv))


@bp.route("/invoices/<iid>/payments", methods=["GET"])
def list_payments(iid):
    user_id, role = gate({"Dispatcher", "AccountHolder"})
    inv = get_or_404(db.invoices, iid)
    require_ownership(role, user_id, inv["account_id"])
    limit, offset = V.parse_pagination(request.args)
    items = [p for p in db.payments.values() if p["invoice_id"] == inv["id"]]
    items = sort_by_created(items)
    total = len(items)
    page = V.paginate(items, limit, offset)
    return ok_list([payment_out(p) for p in page], limit, offset, total)
