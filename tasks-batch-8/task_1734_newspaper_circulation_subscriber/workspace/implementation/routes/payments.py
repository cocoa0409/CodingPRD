"""Payment and BillingCharge endpoints (subscriber ledger surface)."""
from flask import Blueprint, request

import domain
from db import bump, by_created, create_rec, store
from errors import ApiError
from middleware import body, own_check, require_roles
from response import ok_obj, paginate
from serialize import ser_charge, ser_payment
from validate import req_enum, req_int, req_str

bp = Blueprint("payments", __name__)

PAYMENT_METHODS = ("CARD", "CHECK", "CASH", "ACH")


# --- Payment ----------------------------------------------------------------

@bp.post("/api/payments")
def create_payment():
    uid, role = require_roles("Subscriber", "ServiceRep", "CirculationDirector")
    b = body()
    if role == "Subscriber" and b.get("subscriber_id") is not None:
        own_check(uid, role, b.get("subscriber_id"))
    subscriber_id = req_str(b, "subscriber_id")
    amount = req_int(b, "amount_cents", min_v=1)
    method = req_enum(b, "method", PAYMENT_METHODS)
    subr = domain.fetch(store.subscribers, subscriber_id)
    rec = create_rec(store.payments, {
        "subscriber_id": subr["id"],
        "amount_cents": amount,
        "method": method,
        "status": "INITIATED",
        "allocations": [],
    })
    return ok_obj(ser_payment(rec), 201)


@bp.get("/api/payments")
def list_payments():
    require_roles("ServiceRep", "CirculationDirector")
    recs = by_created(store.payments.values())
    subscriber_id = request.args.get("subscriber_id")
    if subscriber_id is not None:
        recs = [p for p in recs if p["subscriber_id"] == subscriber_id]
    status = request.args.get("status")
    if status is not None:
        recs = [p for p in recs if p["status"] == status]
    return paginate(recs, ser_payment)


@bp.get("/api/payments/<pid>")
def get_payment(pid):
    uid, role = require_roles("Subscriber", "ServiceRep", "CirculationDirector")
    payment = domain.fetch(store.payments, pid)
    own_check(uid, role, payment["subscriber_id"])
    return ok_obj(ser_payment(payment))


@bp.post("/api/payments/<pid>/mark-cleared")
def mark_cleared(pid):
    require_roles("ServiceRep", "CirculationDirector")
    payment = domain.fetch(store.payments, pid)
    if payment["status"] != "INITIATED":
        raise ApiError("ERR_PAYMENT_NOT_INITIATED", 409,
                       "mark-cleared requires status INITIATED")
    payment["status"] = "CLEARED"
    allocs, remaining = domain.waterfall(payment["subscriber_id"],
                                         payment["amount_cents"], "payment")
    payment["allocations"] = [{"charge_id": ch["id"], "amount_cents": amt}
                              for ch, amt in allocs]
    bump(payment)
    subr = store.subscribers[payment["subscriber_id"]]
    # Payment remainder lands in unapplied_cash_cents; balances recompute.
    domain.settle_subscriber(subr, unapplied_delta=remaining)
    domain.reevaluate_billing(subr["id"])
    return ok_obj(ser_payment(payment))


@bp.post("/api/payments/<pid>/mark-failed")
def mark_failed(pid):
    require_roles("ServiceRep", "CirculationDirector")
    payment = domain.fetch(store.payments, pid)
    if payment["status"] != "INITIATED":
        raise ApiError("ERR_PAYMENT_NOT_INITIATED", 409,
                       "mark-failed requires status INITIATED")
    payment["status"] = "FAILED"  # no ledger effects
    bump(payment)
    return ok_obj(ser_payment(payment))


@bp.post("/api/payments/<pid>/reverse")
def reverse_payment(pid):
    require_roles("CirculationDirector")
    payment = domain.fetch(store.payments, pid)
    if payment["status"] != "CLEARED":
        raise ApiError("ERR_PAYMENT_NOT_CLEARED", 409,
                       "reverse requires status CLEARED")
    payment["status"] = "REVERSED"
    # Depth 1: undo each allocation in reverse allocation order.
    for alloc in reversed(payment["allocations"]):
        ch = store.charges.get(alloc["charge_id"])
        if ch is None:
            continue
        ch["paid_amount_cents"] -= alloc["amount_cents"]
        covered = ch["paid_amount_cents"] + ch["credit_applied_cents"]
        ch["status"] = domain.charge_status_for(covered, ch["amount_cents"])
        bump(ch)
    bump(payment)
    subr = store.subscribers[payment["subscriber_id"]]
    # Depth 2: balance recompute upward + unapplied-cash clawback.
    allocated_total = sum(a["amount_cents"] for a in payment["allocations"])
    remainder = payment["amount_cents"] - allocated_total
    domain.settle_subscriber(subr, unapplied_delta=-remainder)
    # Depth 3: worsened balance re-evaluates the billing axis.
    domain.reevaluate_billing(subr["id"])
    return ok_obj(ser_payment(payment))


# --- BillingCharge ----------------------------------------------------------

@bp.get("/api/billing-charges")
def list_charges():
    require_roles("ServiceRep", "CirculationDirector")
    recs = sorted(store.charges.values(),
                  key=lambda c: (c["period_start"], c["created_dt"], c["_ord"]))
    subscription_id = request.args.get("subscription_id")
    if subscription_id is not None:
        recs = [c for c in recs if c["subscription_id"] == subscription_id]
    subscriber_id = request.args.get("subscriber_id")
    if subscriber_id is not None:
        recs = [c for c in recs if c["subscriber_id"] == subscriber_id]
    status = request.args.get("status")
    if status is not None:
        recs = [c for c in recs if c["status"] == status]
    return paginate(recs, ser_charge)


@bp.get("/api/billing-charges/<cid>")
def get_charge(cid):
    uid, role = require_roles("Subscriber", "ServiceRep", "CirculationDirector")
    charge = domain.fetch(store.charges, cid)
    own_check(uid, role, charge["subscriber_id"])
    return ok_obj(ser_charge(charge))


@bp.post("/api/billing-charges/<cid>/write-off")
def write_off_charge(cid):
    require_roles("CirculationDirector")
    charge = domain.fetch(store.charges, cid)
    if charge["status"] not in ("OPEN", "PARTIALLY_PAID"):
        raise ApiError("ERR_CHARGE_NOT_OPEN", 409,
                       "write-off requires status OPEN or PARTIALLY_PAID")
    charge["status"] = "WRITTEN_OFF"  # excluded from balance_due_cents forever
    bump(charge)
    domain.settle_subscriber(store.subscribers[charge["subscriber_id"]])
    return ok_obj(ser_charge(charge))
