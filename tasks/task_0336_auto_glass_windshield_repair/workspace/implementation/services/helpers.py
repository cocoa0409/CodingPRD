"""Shared lookup, ownership, serialization, and aggregate helpers."""
from flask import g

import db
import errors
from errors import ApiError


# ---------------------------------------------------------------------------
# Existence lookups (ERR_NOT_FOUND, 404). Validated left-to-right by callers.
# ---------------------------------------------------------------------------
def get_or_404(store, resource_id):
    obj = store.get(resource_id)
    if obj is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Resource not found.")
    return obj


def get_customer(cid):
    return get_or_404(db.customers, cid)


def get_vehicle(vid):
    return get_or_404(db.vehicles, vid)


def get_work_order(wid):
    return get_or_404(db.work_orders, wid)


def get_glass_part(pid):
    return get_or_404(db.glass_parts, pid)


def get_part_order(pid):
    return get_or_404(db.part_orders, pid)


def get_technician(tid):
    return get_or_404(db.technicians, tid)


def get_service_bay(bid):
    return get_or_404(db.service_bays, bid)


def get_appointment(aid):
    return get_or_404(db.service_appointments, aid)


def get_recalibration(rid):
    return get_or_404(db.recalibration_jobs, rid)


def get_payment(pid):
    return get_or_404(db.payments, pid)


def get_warranty(wid):
    return get_or_404(db.warranties, wid)


# ---------------------------------------------------------------------------
# Ownership (ERR_FORBIDDEN, 403) for the entity-backed Customer role (PRD 2.1).
# Checked AFTER existence (the resource must be resolved to compare its owner).
# ---------------------------------------------------------------------------
def enforce_customer_owns(customer_id):
    """If the caller is a Customer, X-User-ID must equal customer_id."""
    if g.role == "Customer" and g.user_id != customer_id:
        raise ApiError(errors.ERR_FORBIDDEN, 403, "Not the resource owner.")


def enforce_work_order_owner(work_order):
    if g.role == "Customer":
        enforce_customer_owns(work_order["customer_id"])


# ---------------------------------------------------------------------------
# Work-order aggregate recompute (PRD 3.7 invariant).
# ---------------------------------------------------------------------------
def recompute_amount_paid(work_order):
    """Recompute the conserved ledger (PRD 3.7).

    amount_paid_cents = sum(amount_cents over every captured payment)
                        - sum(refunded_amount_cents over all payments).

    "Captured payment" is one that was successfully taken — its status is
    CAPTURED or (after a refund) REFUNDED. Its full amount_cents stays in the
    gross sum, and the refund subtracts only the refunded portion. A full
    refund nets to 0; a partial (restock) refund leaves the retained portion.
    """
    wid = work_order["id"]
    gross = 0
    refunded = 0
    for p in db.payments.values():
        if p["work_order_id"] != wid:
            continue
        if p["status"] in ("CAPTURED", "REFUNDED"):
            gross += p["amount_cents"]
        refunded += p["refunded_amount_cents"]
    work_order["amount_paid_cents"] = gross - refunded


def reserved_part_order_for(work_order_id):
    """Return the RESERVED part order for this work order, if any."""
    for po in db.part_orders.values():
        if po["work_order_id"] == work_order_id and po["status"] == "RESERVED":
            return po
    return None


# ---------------------------------------------------------------------------
# Serialization — public field projection for each entity type.
# ---------------------------------------------------------------------------
def view(obj):
    return db.public(obj)


def view_list(objs):
    return [db.public(o) for o in objs]
