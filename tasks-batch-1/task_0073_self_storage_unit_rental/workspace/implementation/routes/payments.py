from flask import Blueprint, request

import errors
from errors import err
from db import db
from models import make_common, touch, serialize
from middleware import get_identity, require_role
from helpers import (get_json_body, lookup, parse_pagination, paginate,
                     sort_by_created, require_tenant_owns_lease)
from response import success, list_response
from services import domain

bp = Blueprint("payments", __name__)


@bp.post("/payments")
def create_payment():
    user_id, role = get_identity()
    require_role(role, {"Tenant", "FacilityManager"})
    body = get_json_body()

    lease_id = body.get("lease_id")
    if not isinstance(lease_id, str) or not lease_id:
        raise err(errors.ERR_INVALID_REQUEST, "lease_id is required")
    lease = lookup(db.leases, lease_id, "lease")
    require_tenant_owns_lease(user_id, role, lease)

    amount = body.get("amount_cents")
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise err(errors.ERR_INVALID_REQUEST, "amount_cents must be an integer")
    if amount <= 0:
        raise err(errors.ERR_BALANCE_NOT_CLEARED, "amount_cents must be > 0")

    payment = make_common()
    payment.update({
        "lease_id": lease_id,
        "amount_cents": amount,
        "status": "APPLIED",
        "allocation": [],
        "overpay_credit_cents": 0,
    })

    # Oldest-due-first allocation: due_date ASC, then created_at ASC.
    open_invs = domain.lease_open_invoices(lease_id)
    open_invs.sort(key=lambda inv: (inv["due_date"], inv["created_at"], inv["_seq"]))

    remaining = amount
    allocation = []
    for inv in open_invs:
        if remaining <= 0:
            break
        unpaid = inv["total_amount_cents"] - inv["amount_paid_cents"]
        if unpaid <= 0:
            continue
        apply = min(remaining, unpaid)
        inv["amount_paid_cents"] += apply
        remaining -= apply
        if inv["amount_paid_cents"] >= inv["total_amount_cents"]:
            inv["status"] = "PAID"
        else:
            inv["status"] = "PARTIAL"
        touch(inv)
        allocation.append({"invoice_id": inv["id"], "applied_cents": apply})
        domain.append_ledger(lease, "PAYMENT", -apply, "PAYMENT", payment["id"])

    overpay = remaining
    if overpay > 0:
        domain.append_ledger(lease, "CREDIT", -overpay, "PAYMENT", payment["id"])

    payment["allocation"] = allocation
    payment["overpay_credit_cents"] = overpay
    db.payments[payment["id"]] = payment
    touch(lease)

    # Cure cascade when balance reaches zero.
    domain.apply_cure_cascade(lease)

    return success(serialize(payment), 201)


@bp.get("/payments/<payment_id>")
def get_payment(payment_id):
    user_id, role = get_identity()
    require_role(role, {"FacilityManager", "Tenant"})
    payment = lookup(db.payments, payment_id, "payment")
    lease = db.leases.get(payment["lease_id"])
    if lease is not None:
        require_tenant_owns_lease(user_id, role, lease)
    return success(serialize(payment), 200)


@bp.get("/payments")
def list_payments():
    user_id, role = get_identity()
    require_role(role, {"FacilityManager", "Tenant"})
    limit, offset = parse_pagination()
    items = list(db.payments.values())
    lease_id = request.args.get("lease_id")
    if lease_id is not None:
        items = [p for p in items if p["lease_id"] == lease_id]
    if role == "Tenant":
        owned = {l["id"] for l in db.leases.values() if l["tenant_id"] == user_id}
        items = [p for p in items if p["lease_id"] in owned]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_response([serialize(p) for p in page], total, limit, offset)


@bp.post("/payments/<payment_id>/reverse")
def reverse_payment(payment_id):
    _, role = get_identity()
    require_role(role, {"FacilityManager"})
    payment = lookup(db.payments, payment_id, "payment")

    if payment["status"] != "APPLIED":
        raise err(errors.ERR_INVALID_STATE, "Only an APPLIED payment can be reversed")

    lease = db.leases.get(payment["lease_id"])

    # Revert each touched invoice.
    for alloc in payment["allocation"]:
        inv = db.invoices.get(alloc["invoice_id"])
        if inv is None:
            continue
        inv["amount_paid_cents"] -= alloc["applied_cents"]
        if inv["amount_paid_cents"] < 0:
            inv["amount_paid_cents"] = 0
        if inv["status"] in ("PAID", "PARTIAL"):
            inv["status"] = "PARTIAL" if inv["amount_paid_cents"] > 0 else "OPEN"
        touch(inv)

    payment["status"] = "REVERSED"
    touch(payment)

    if lease is not None:
        domain.append_ledger(lease, "REVERSAL", payment["amount_cents"], "PAYMENT", payment["id"])
        touch(lease)

    return success(serialize(payment), 200)
