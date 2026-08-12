"""Credit ledger reads, redemptions, compost stock, billing, invoices, clock."""

from flask import Blueprint, request

import db
import response
from db import new_entity, store, touch
from errors import (ERR_ACCOUNT_DELINQUENT, ERR_INSUFFICIENT_CREDIT,
                    ERR_INVOICE_NOT_PAYABLE, ERR_REDEMPTION_NOT_FULFILLABLE,
                    ERR_SUBSCRIPTION_NOT_ACTIVE, ApiError, bad_request,
                    conflict, not_found, unprocessable)
from middleware import auth, own_or_403, require_roles
from services import (BAG_KG, BAG_PRICE_CENTS, account_standing, by_seq,
                      check_stock, compute_stock, post_entry, run_billing,
                      ser_entry, ser_invoice, ser_redemption)
from utils import (D, get_body, is_int, paginate, pagination_params,
                   parse_date, parse_instant, season_label)

bp = Blueprint("billing", __name__)


# ---------------------------------------------------------------------------
# Credit ledger reads
# ---------------------------------------------------------------------------
@bp.get("/credit-entries")
def list_entries():
    uid, role = auth()
    require_roles(role, "Subscriber", "OperationsManager")
    limit, offset = pagination_params()
    items = by_seq(store["credit_entries"].values())
    if role == "Subscriber":
        items = [e for e in items if e["subscriber_id"] == uid]
    for param, field in (("subscriber_id", "subscriber_id"),
                         ("pickup_id", "pickup_id"),
                         ("redemption_id", "redemption_id"),
                         ("invoice_id", "invoice_id"),
                         ("entry_type", "entry_type")):
        val = request.args.get(param)
        if val is not None:
            items = [e for e in items if e[field] == val]
    page, total = paginate(items, limit, offset)
    return response.ok_list([ser_entry(e) for e in page], limit, offset, total)


@bp.get("/credit-entries/<eid>")
def get_entry(eid):
    uid, role = auth()
    require_roles(role, "Subscriber", "OperationsManager")
    e = store["credit_entries"].get(eid)
    if e is None:
        not_found("Credit entry not found")
    if role == "Subscriber":
        own_or_403(e["subscriber_id"], uid)
    return response.ok(ser_entry(e))


# ---------------------------------------------------------------------------
# Credit redemptions
# ---------------------------------------------------------------------------
@bp.post("/credit-redemptions")
def create_redemption():
    uid, role = auth()
    require_roles(role, "Subscriber", "OperationsManager")
    body = get_body()
    subscriber_id = body.get("subscriber_id")
    if not isinstance(subscriber_id, str) or subscriber_id == "":
        bad_request("Missing or invalid field: subscriber_id")
    bags = body.get("bags")
    if not is_int(bags) or bags < 1:
        bad_request("bags must be an integer of at least 1")
    if role == "Subscriber":
        own_or_403(subscriber_id, uid)
    subscriber = store["subscribers"].get(subscriber_id)
    if subscriber is None:
        not_found("Subscriber not found")
    has_active = any(s["subscriber_id"] == subscriber_id
                     and s["service_status"] == "ACTIVE"
                     for s in store["subscriptions"].values())
    if not has_active:
        conflict(ERR_SUBSCRIPTION_NOT_ACTIVE,
                 "Subscriber holds no ACTIVE subscription")
    if account_standing(subscriber_id) != "GOOD_STANDING":
        raise ApiError(ERR_ACCOUNT_DELINQUENT, 402,
                       "Subscriber has an overdue issued invoice")
    total_cents = bags * BAG_PRICE_CENTS
    if subscriber["credit_balance_cents"] < total_cents:
        unprocessable(ERR_INSUFFICIENT_CREDIT,
                      "Credit balance does not cover the redemption")
    total_kg = D(bags * BAG_KG)
    check_stock(total_kg)
    r = new_entity(common=True)
    r.update({
        "subscriber_id": subscriber_id, "bags": bags, "total_kg": total_kg,
        "total_cents": total_cents, "status": "REQUESTED",
    })
    store["redemptions"][r["id"]] = r
    return response.ok(ser_redemption(r), code=201)


@bp.get("/credit-redemptions")
def list_redemptions():
    uid, role = auth()
    require_roles(role, "Subscriber", "OperationsManager")
    limit, offset = pagination_params()
    items = by_seq(store["redemptions"].values())
    if role == "Subscriber":
        items = [r for r in items if r["subscriber_id"] == uid]
    for param, field in (("subscriber_id", "subscriber_id"),
                         ("status", "status")):
        val = request.args.get(param)
        if val is not None:
            items = [r for r in items if r[field] == val]
    page, total = paginate(items, limit, offset)
    return response.ok_list([ser_redemption(r) for r in page], limit, offset,
                            total)


def _get_redemption_or_404(rid):
    r = store["redemptions"].get(rid)
    if r is None:
        not_found("Redemption not found")
    return r


@bp.get("/credit-redemptions/<rid>")
def get_redemption(rid):
    uid, role = auth()
    require_roles(role, "Subscriber", "OperationsManager")
    r = _get_redemption_or_404(rid)
    if role == "Subscriber":
        own_or_403(r["subscriber_id"], uid)
    return response.ok(ser_redemption(r))


@bp.post("/credit-redemptions/<rid>/fulfill")
def fulfill_redemption(rid):
    _, role = auth()
    require_roles(role, "OperationsManager")
    r = _get_redemption_or_404(rid)
    if r["status"] != "REQUESTED":
        conflict(ERR_REDEMPTION_NOT_FULFILLABLE, "Redemption is not REQUESTED")
    subscriber = store["subscribers"][r["subscriber_id"]]
    if subscriber["credit_balance_cents"] < r["total_cents"]:
        unprocessable(ERR_INSUFFICIENT_CREDIT,
                      "Credit balance no longer covers the redemption")
    post_entry(r["subscriber_id"], "REDEMPTION_DEBIT", -r["total_cents"],
               season_label(db.logical_now().date()), redemption_id=r["id"])
    r["status"] = "FULFILLED"
    touch(r)
    return response.ok(ser_redemption(r))


@bp.post("/credit-redemptions/<rid>/cancel")
def cancel_redemption(rid):
    uid, role = auth()
    require_roles(role, "Subscriber", "OperationsManager")
    r = _get_redemption_or_404(rid)
    if role == "Subscriber":
        own_or_403(r["subscriber_id"], uid)
    if r["status"] != "REQUESTED":
        conflict(ERR_REDEMPTION_NOT_FULFILLABLE, "Redemption is not REQUESTED")
    r["status"] = "CANCELLED"
    touch(r)
    return response.ok(ser_redemption(r))


# ---------------------------------------------------------------------------
# Compost stock
# ---------------------------------------------------------------------------
@bp.get("/compost-stock")
def compost_stock():
    _, role = auth()
    require_roles(role, "Subscriber", "Driver", "OperationsManager")
    return response.ok(compute_stock())


# ---------------------------------------------------------------------------
# Billing + invoices
# ---------------------------------------------------------------------------
@bp.post("/billing/run")
def billing_run():
    _, role = auth()
    require_roles(role, "OperationsManager")
    body = get_body()
    ws = parse_date(body.get("week_start_date"), "week_start_date")
    if ws.weekday() != 0:
        bad_request("week_start_date must be a Monday")
    return response.ok(run_billing(ws))


@bp.get("/invoices")
def list_invoices():
    uid, role = auth()
    require_roles(role, "Subscriber", "OperationsManager")
    limit, offset = pagination_params()
    items = by_seq(store["invoices"].values())
    if role == "Subscriber":
        items = [i for i in items if i["subscriber_id"] == uid]
    for param, field in (("subscriber_id", "subscriber_id"),
                         ("status", "status")):
        val = request.args.get(param)
        if val is not None:
            items = [i for i in items if i[field] == val]
    page, total = paginate(items, limit, offset)
    return response.ok_list([ser_invoice(i) for i in page], limit, offset,
                            total)


def _get_invoice_or_404(iid):
    inv = store["invoices"].get(iid)
    if inv is None:
        not_found("Invoice not found")
    return inv


@bp.get("/invoices/<iid>")
def get_invoice(iid):
    uid, role = auth()
    require_roles(role, "Subscriber", "OperationsManager")
    inv = _get_invoice_or_404(iid)
    if role == "Subscriber":
        own_or_403(inv["subscriber_id"], uid)
    return response.ok(ser_invoice(inv))


@bp.post("/invoices/<iid>/pay")
def pay_invoice(iid):
    uid, role = auth()
    require_roles(role, "Subscriber", "OperationsManager")
    inv = _get_invoice_or_404(iid)
    if role == "Subscriber":
        own_or_403(inv["subscriber_id"], uid)
    if inv["status"] != "ISSUED":
        conflict(ERR_INVOICE_NOT_PAYABLE, "Invoice is not ISSUED")
    inv["status"] = "PAID"
    touch(inv)
    return response.ok(ser_invoice(inv))


@bp.post("/invoices/<iid>/void")
def void_invoice(iid):
    _, role = auth()
    require_roles(role, "OperationsManager")
    inv = _get_invoice_or_404(iid)
    if inv["status"] != "ISSUED":
        conflict(ERR_INVOICE_NOT_PAYABLE, "Invoice is not ISSUED")
    if inv["credit_applied_cents"] > 0:
        post_entry(inv["subscriber_id"], "REVERSAL",
                   inv["credit_applied_cents"],
                   season_label(db.logical_now().date()), invoice_id=inv["id"])
    inv["status"] = "VOID"
    touch(inv)
    return response.ok(ser_invoice(inv))


# ---------------------------------------------------------------------------
# Logical clock (test-driving endpoint)
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    _, role = auth()
    require_roles(role, "OperationsManager")
    body = get_body()
    dt = parse_instant(body.get("to_iso8601"), "to_iso8601")
    db.set_logical(dt)
    return response.ok({"current_utc": db.fmt_ts(db.logical_now())})
