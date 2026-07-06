from datetime import timedelta

from flask import Blueprint, request

import errors
from errors import err
from db import db, touch
from clock import iso_millis, parse_iso
from middleware import get_auth, require_role
from response import ok_object, ok_array
from validate import paginate
from routes.common import get_storage_account, get_invoice
import domain
from billing import issue_invoice, renewal_amount, next_period_index

bp = Blueprint("storage", __name__)


@bp.get("/storage-accounts/<i>")
def get_account(i):
    _uid, role = get_auth()
    require_role(role, {"BillingClerk", "Recipient"})
    return ok_object(get_storage_account(i))


@bp.get("/storage-accounts")
def list_accounts():
    _uid, role = get_auth()
    require_role(role, {"BillingClerk", "Recipient"})
    items = list(db.storage_accounts.values())
    recipient_f = request.args.get("recipient_id")
    reservation_f = request.args.get("reservation_id")
    status_f = request.args.get("status")
    if recipient_f is not None:
        items = [a for a in items if a["recipient_id"] == recipient_f]
    if reservation_f is not None:
        items = [a for a in items if a["reservation_id"] == reservation_f]
    if status_f is not None:
        items = [a for a in items if a["status"] == status_f]
    page, limit, offset, total = paginate(items)
    return ok_array(page, limit, offset, total)


def _elapsed_days(acct):
    start = parse_iso(acct["period_start"])
    delta = db.now() - start
    return delta.days  # floor to whole days for a positive delta


@bp.post("/storage-accounts/<i>/renew")
def renew(i):
    _uid, role = get_auth()
    require_role(role, {"BillingClerk"})
    acct = get_storage_account(i)
    if acct["status"] != "ACTIVE":
        raise err(errors.ERR_INVALID_STATE, "Account not ACTIVE")
    elapsed = _elapsed_days(acct)
    remaining = domain.BILLING_PERIOD_DAYS - elapsed
    idx = next_period_index(acct)
    inv = issue_invoice(acct, period_index=idx, billing_mode="RENEWAL", remaining_days=remaining)
    touch(db, acct)
    return ok_object(inv)


@bp.post("/storage-accounts/<i>/assess-lapse")
def assess_lapse(i):
    _uid, role = get_auth()
    require_role(role, {"BillingClerk"})
    acct = get_storage_account(i)
    if acct["status"] != "ACTIVE":
        raise err(errors.ERR_INVALID_STATE, "Account not ACTIVE")
    if acct["paid_through"] is None:
        raise err(errors.ERR_GRACE_NOT_ELAPSED, "Grace not elapsed")
    grace_end = parse_iso(acct["paid_through"]) + timedelta(days=domain.GRACE_DAYS)
    if db.now() < grace_end:
        raise err(errors.ERR_GRACE_NOT_ELAPSED, "Grace not elapsed")
    acct["status"] = "LAPSED"
    idx = next_period_index(acct)
    inv = issue_invoice(acct, period_index=idx, billing_mode="LAPSE")
    touch(db, acct)
    return ok_object(inv)


@bp.post("/storage-accounts/<i>/close")
def close(i):
    _uid, role = get_auth()
    require_role(role, {"BillingClerk"})
    acct = get_storage_account(i)
    if acct["status"] != "ACTIVE":
        raise err(errors.ERR_INVALID_STATE, "Account not ACTIVE")
    acct["status"] = "CLOSED"
    touch(db, acct)
    for inv in db.storage_invoices.values():
        if inv["storage_account_id"] == acct["id"] and inv["status"] == "ISSUED":
            inv["status"] = "VOID"
            touch(db, inv)
    return ok_object(acct)


@bp.get("/storage-invoices/<i>")
def get_one_invoice(i):
    _uid, role = get_auth()
    require_role(role, {"BillingClerk", "Recipient"})
    return ok_object(get_invoice(i))


@bp.get("/storage-invoices")
def list_invoices():
    _uid, role = get_auth()
    require_role(role, {"BillingClerk", "Recipient"})
    items = list(db.storage_invoices.values())
    account_f = request.args.get("storage_account_id")
    status_f = request.args.get("status")
    mode_f = request.args.get("billing_mode")
    if account_f is not None:
        items = [x for x in items if x["storage_account_id"] == account_f]
    if status_f is not None:
        items = [x for x in items if x["status"] == status_f]
    if mode_f is not None:
        items = [x for x in items if x["billing_mode"] == mode_f]
    page, limit, offset, total = paginate(items)
    return ok_array(page, limit, offset, total)


@bp.post("/storage-invoices/<i>/pay")
def pay(i):
    _uid, role = get_auth()
    require_role(role, {"BillingClerk"})
    inv = get_invoice(i)
    if inv["status"] != "ISSUED":
        raise err(errors.ERR_INVALID_STATE, "Invoice not ISSUED")
    acct = db.storage_accounts.get(inv["storage_account_id"])
    inv["status"] = "PAID"
    touch(db, inv)
    if acct is not None:
        # advance paid_through by one full billing period
        base = parse_iso(acct["paid_through"]) if acct["paid_through"] else parse_iso(acct["period_start"])
        acct["paid_through"] = iso_millis(base + timedelta(days=domain.BILLING_PERIOD_DAYS))
        # restore LAPSED -> ACTIVE when paying a LAPSE invoice on a LAPSED account
        if acct["status"] == "LAPSED" and inv["billing_mode"] == "LAPSE":
            acct["status"] = "ACTIVE"
        touch(db, acct)
    return ok_object(inv)
