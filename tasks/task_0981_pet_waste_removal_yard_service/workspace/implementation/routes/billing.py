from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import services as svc
from clock import now
from errors import ApiError, err_invalid_request, err_invalid_state, err_unauthorized
from middleware import (
    auth,
    get_body,
    require,
    require_dt,
    lookup,
    lookup_fk,
    parse_pagination,
    paginate,
)
from response import ok_object, ok_list

bp = Blueprint("billing", __name__)


def _owned_invoice(iid, uid):
    inv = lookup(svc.invoices, iid, "Invoice")
    if inv["customer_id"] != uid:
        raise err_unauthorized("Customers may only act on their own invoices")
    return inv


def _check_credit_range(amount):
    if amount < 0 or amount > 100000:
        raise ApiError("ERR_CREDIT_OUT_OF_RANGE", 422,
                       "resolution_credit_cents must be between 0 and 100000")


@bp.post("/api/invoices")
def create_invoice():
    auth("BillingAdmin")
    data = get_body()
    customer_id = require(data, "customer_id", str)
    period_start = require_dt(data, "billing_period_start")
    period_end = require_dt(data, "billing_period_end")
    lookup_fk(svc.customers, customer_id, "Customer")
    rec = svc.create_invoice(customer_id, period_start, period_end)
    return ok_object(svc.ser_invoice(rec), status=201)


@bp.get("/api/invoices/<iid>")
def get_invoice(iid):
    uid, role = auth("BillingAdmin", "Customer")
    inv = lookup(svc.invoices, iid, "Invoice")
    if role == "Customer" and inv["customer_id"] != uid:
        raise err_unauthorized("Customers may only access their own invoices")
    return ok_object(svc.ser_invoice(inv))


@bp.get("/api/invoices")
def list_invoices():
    uid, role = auth("BillingAdmin", "Customer")
    limit, offset = parse_pagination()
    records = list(svc.invoices.values())
    if role == "Customer":
        requested = request.args.get("customer_id")
        if requested is not None and requested != uid:
            raise err_unauthorized("Customers may only list their own invoices")
        records = [i for i in records if i["customer_id"] == uid]
    else:
        customer_id = request.args.get("customer_id")
        if customer_id is not None:
            records = [i for i in records if i["customer_id"] == customer_id]
    status = request.args.get("invoice_status")
    if status is not None:
        records = [i for i in records if i["invoice_status"] == status]
    page, total = paginate(records, limit, offset)
    return ok_list([svc.ser_invoice(i) for i in page], total, limit, offset)


@bp.get("/api/invoices/<iid>/line-items")
def invoice_line_items(iid):
    uid, role = auth("BillingAdmin", "Customer")
    inv = lookup(svc.invoices, iid, "Invoice")
    if role == "Customer" and inv["customer_id"] != uid:
        raise err_unauthorized("Customers may only access their own invoices")
    limit, offset = parse_pagination()
    records = svc.invoice_lines(inv["id"])
    page, total = paginate(records, limit, offset)
    return ok_list([svc.ser_line_item(l) for l in page], total, limit, offset)


@bp.get("/api/invoice-line-items")
def list_line_items():
    uid, role = auth("BillingAdmin", "Customer", "OperationsManager")
    limit, offset = parse_pagination()
    records = list(svc.line_items.values())
    if role == "Customer":
        own_invoices = {i["id"] for i in svc.invoices.values() if i["customer_id"] == uid}
        records = [l for l in records if l["invoice_id"] in own_invoices]
    invoice_id = request.args.get("invoice_id")
    if invoice_id is not None:
        records = [l for l in records if l["invoice_id"] == invoice_id]
    visit_id = request.args.get("visit_id")
    if visit_id is not None:
        records = [l for l in records if l["visit_id"] == visit_id]
    addon_id = request.args.get("applied_addon_id")
    if addon_id is not None:
        records = [l for l in records if l["applied_addon_id"] == addon_id]
    line_type = request.args.get("line_type")
    if line_type is not None:
        records = [l for l in records if l["line_type"] == line_type]
    page, total = paginate(records, limit, offset)
    return ok_list([svc.ser_line_item(l) for l in page], total, limit, offset)


@bp.get("/api/invoice-line-items/<lid>")
def get_line_item(lid):
    uid, role = auth("BillingAdmin", "Customer", "OperationsManager")
    rec = lookup(svc.line_items, lid, "InvoiceLineItem")
    if role == "Customer":
        inv = svc.invoices.get(rec["invoice_id"])
        if inv is None or inv["customer_id"] != uid:
            raise err_unauthorized("Customers may only access their own invoice lines")
    return ok_object(svc.ser_line_item(rec))


@bp.post("/api/invoices/<iid>/finalize")
def finalize_invoice(iid):
    auth("BillingAdmin")
    data = get_body()
    expected_version = require(data, "expected_invoice_version", int)
    inv = lookup(svc.invoices, iid, "Invoice")
    if inv["invoice_status"] != "OPEN":
        raise err_invalid_state("finalize is only valid from OPEN")
    if expected_version != inv["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_invoice_version does not match the current version")
    if inv["billing_period_end"] > now():
        raise ApiError("ERR_PERIOD_NOT_CLOSED", 422,
                       "billing_period_end must be at or before the current time")
    customer = svc.customers.get(inv["customer_id"])

    # RECONCILED variant: SUBSCRIPTION_FEE_PRORATED lines for the period
    ps, pe = inv["billing_period_start"], inv["billing_period_end"]
    days_in_period = (pe - ps).days
    if customer is not None and days_in_period > 0:
        for sub in svc.subscriptions.values():
            if (
                sub["customer_id"] == customer["id"]
                and sub["status"] == "ACTIVE"
                and sub.get("started_on") is not None
            ):
                start_day = max(ps.date(), sub["started_on"].date())
                days_active = (pe.date() - start_day).days
                if days_active <= 0:
                    continue
                yard = svc.yards.get(sub["yard_id"])
                plan = svc.plans.get(sub["plan_id"])
                if yard is None or plan is None:
                    continue
                fee = svc.monthly_fee(plan, yard)
                per_day = svc.rhu(Decimal(fee) / Decimal(days_in_period))
                svc.post_line(
                    inv,
                    "SUBSCRIPTION_FEE_PRORATED",
                    f"Prorated subscription fee ({plan['plan_code']})",
                    days_active,
                    per_day,
                    bump_invoice=False,
                )

    lines = svc.invoice_lines(inv["id"])
    subtotal = sum(l["line_total_cents"] for l in lines)
    balance = customer["credit_balance_cents"] if customer is not None else 0
    credits_applied = min(balance, subtotal)
    inv["subtotal_cents"] = subtotal
    inv["credits_applied_cents"] = credits_applied
    inv["total_due_cents"] = subtotal - credits_applied
    if customer is not None and credits_applied != 0:
        customer["credit_balance_cents"] -= credits_applied
        svc.bump(customer)
    inv["invoice_status"] = "FINALIZED"
    inv["finalized_at"] = now()
    svc.bump(inv)
    return ok_object(svc.ser_invoice(inv))


@bp.post("/api/invoices/<iid>/record-payment")
def record_payment(iid):
    auth("BillingAdmin")
    data = get_body()
    amount = require(data, "amount_cents", int)
    inv = lookup(svc.invoices, iid, "Invoice")
    if inv["invoice_status"] != "FINALIZED":
        raise err_invalid_state("record-payment is only valid from FINALIZED")
    if amount != inv["total_due_cents"]:
        raise ApiError("ERR_PAYMENT_AMOUNT_MISMATCH", 422,
                       "amount_cents must exactly equal total_due_cents")
    inv["invoice_status"] = "PAID"
    svc.bump(inv)
    return ok_object(svc.ser_invoice(inv))


@bp.post("/api/invoices/<iid>/dispute")
def dispute_invoice(iid):
    uid, _ = auth("Customer")
    data = get_body()
    require(data, "reason", str)
    inv = _owned_invoice(iid, uid)
    if inv["invoice_status"] != "FINALIZED":
        raise err_invalid_state("dispute is only valid from FINALIZED")
    inv["invoice_status"] = "DISPUTED"
    svc.bump(inv)
    return ok_object(svc.ser_invoice(inv))


@bp.post("/api/invoices/<iid>/resolve-dispute")
def resolve_dispute(iid):
    auth("BillingAdmin")
    data = get_body()
    credit = require(data, "resolution_credit_cents", int)
    inv = lookup(svc.invoices, iid, "Invoice")
    if inv["invoice_status"] != "DISPUTED":
        raise err_invalid_state("resolve-dispute is only valid from DISPUTED")
    _check_credit_range(credit)
    if credit > 0:
        customer = svc.customers.get(inv["customer_id"])
        # post SATISFACTION_CREDIT to the NEXT OPEN invoice (or create one)
        target = svc.next_open_invoice_after(inv["customer_id"],
                                             inv["billing_period_start"])
        if target is None:
            ps = inv["billing_period_end"]
            pe = svc.month_period(ps + timedelta(days=1))[1]
            target = svc.create_invoice(inv["customer_id"], ps, pe)
        svc.post_line(target, "SATISFACTION_CREDIT", "Dispute resolution credit",
                      1, -credit)
        if customer is not None:
            customer["credit_balance_cents"] += credit
            svc.bump(customer)
    inv["invoice_status"] = "RESOLVED"
    svc.bump(inv)
    return ok_object(svc.ser_invoice(inv))
