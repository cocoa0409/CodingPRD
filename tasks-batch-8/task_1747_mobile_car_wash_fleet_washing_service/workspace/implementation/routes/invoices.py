"""Invoice endpoints."""

from flask import Blueprint, request

from db import store
from serialize import ser_invoice, customer_of_invoice
from services import build_invoice_record
from util import (
    caller, require_role, forbid, get_body, respond, paginate, req_str,
    req_enum, parse_period, touch, ApiError,
)
from errors import (
    ERR_NOT_FOUND, ERR_VALIDATION, ERR_INVALID_STATE, ERR_CONTRACT_NOT_ACTIVE,
    ERR_INVOICE_EXISTS,
)

bp = Blueprint("invoices", __name__)

BLOCKING_FINAL_STATES = ("DRAFT", "ISSUED", "DISPUTED", "PAID")


@bp.post("/fleet-wash/invoices/generate")
def generate_invoice():
    _uid, role = caller()
    require_role(role, {"PlatformAdmin", "Dispatcher"})
    body = get_body()
    contract_id = req_str(body, "fleet_contract_id")
    contract = store.contracts.get(contract_id)
    if contract is None:
        raise ApiError(ERR_NOT_FOUND, "FleetContract %s not found" % contract_id)
    period = parse_period(body.get("period_month"), "period_month")
    variant = req_enum(body, "variant", {"PROJECTION", "FINAL"})
    if contract["status"] != "ACTIVE":
        raise ApiError(ERR_CONTRACT_NOT_ACTIVE, "FleetContract is not ACTIVE")
    if variant == "FINAL":
        for inv in store.invoices.values():
            if inv["fleet_contract_id"] == contract_id \
                    and inv["period_month"] == period \
                    and inv["variant"] == "FINAL" \
                    and inv["status"] in BLOCKING_FINAL_STATES:
                raise ApiError(ERR_INVOICE_EXISTS,
                               "A FINAL invoice already exists for this contract and period")
        # Generating a FINAL voids existing PREVIEW rows for the same period.
        for inv in store.invoices.values():
            if inv["fleet_contract_id"] == contract_id \
                    and inv["period_month"] == period \
                    and inv["status"] == "PREVIEW":
                inv["status"] = "VOID"
                touch(inv)
    rec = build_invoice_record(contract, period, variant)
    return respond(ser_invoice(rec), 201)


@bp.get("/fleet-wash/invoices/<iid>")
def get_invoice(iid):
    uid, role = caller()
    rec = store.invoices.get(iid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, "Invoice %s not found" % iid)
    if role == "Customer" and customer_of_invoice(rec) != uid:
        forbid("Customers may only access their own invoices")
    return respond(ser_invoice(rec), 200)


@bp.get("/fleet-wash/invoices")
def list_invoices():
    uid, role = caller()
    contract_id = request.args.get("fleet_contract_id")
    period = request.args.get("period_month")
    status = request.args.get("status")
    recs = list(store.invoices.values())
    if role == "Customer":
        recs = [i for i in recs if customer_of_invoice(i) == uid]
    if contract_id is not None:
        recs = [i for i in recs if i["fleet_contract_id"] == contract_id]
    if period is not None:
        recs = [i for i in recs if i["period_month"] == period]
    if status is not None:
        recs = [i for i in recs if i["status"] == status]
    return paginate(recs, ser_invoice)


def _flip_orders(invoice, from_status, to_status):
    for oid in invoice["_line_order_ids"]:
        order = store.orders.get(oid)
        if order is not None and order["billing_status"] == from_status:
            order["billing_status"] = to_status
            touch(order)


@bp.post("/fleet-wash/invoices/<iid>/events")
def invoice_event(iid):
    uid, role = caller()
    require_role(role, {"Dispatcher", "Customer"})
    rec = store.invoices.get(iid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, "Invoice %s not found" % iid)
    body = get_body()
    event = req_str(body, "event_type")
    if event not in ("ISSUE", "MARK_PAID", "DISPUTE", "VOID"):
        raise ApiError(ERR_VALIDATION,
                       "event_type must be ISSUE, MARK_PAID, DISPUTE, or VOID")
    if event in ("ISSUE", "MARK_PAID", "VOID"):
        if role != "Dispatcher":
            forbid("%s requires a Dispatcher" % event)
    else:  # DISPUTE
        if role == "Customer":
            if customer_of_invoice(rec) != uid:
                forbid("Customers may only dispute their own contract's invoices")
        elif role != "Dispatcher":
            forbid("DISPUTE requires a Dispatcher or the contract's Customer")
    if event == "ISSUE":
        if rec["variant"] != "FINAL" or rec["status"] != "DRAFT":
            raise ApiError(ERR_INVALID_STATE,
                           "Only a DRAFT FINAL invoice may be issued")
        rec["status"] = "ISSUED"
        _flip_orders(rec, "UNBILLED", "INVOICED")
    elif event == "MARK_PAID":
        if rec["status"] != "ISSUED":
            raise ApiError(ERR_INVALID_STATE, "Invoice is not ISSUED")
        rec["status"] = "PAID"
        _flip_orders(rec, "INVOICED", "PAID")
    elif event == "DISPUTE":
        if rec["status"] != "ISSUED":
            raise ApiError(ERR_INVALID_STATE, "Invoice is not ISSUED")
        rec["status"] = "DISPUTED"
    else:  # VOID
        if rec["status"] != "DISPUTED":
            raise ApiError(ERR_INVALID_STATE, "Invoice is not DISPUTED")
        rec["status"] = "VOID"
        _flip_orders(rec, "INVOICED", "UNBILLED")
    touch(rec)
    return respond(ser_invoice(rec), 200)
