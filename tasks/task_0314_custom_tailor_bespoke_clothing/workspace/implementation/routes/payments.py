"""Payments (deposit/balance capture), apply store credit (PRD §3.4)."""
from flask import Blueprint, request

import errors
import serializers as S
import validation as V
from db import db, new_id, touch
from errors import fail
from lookups import get_order, get_customer
from middleware import get_user_context, require_role, get_json_body
from response import success, list_response, now_iso
from services import calculations as calc
from services import orders as osvc

bp = Blueprint("payments", __name__)


@bp.post("/orders/<oid>/payments")
def capture_payment(oid):
    _, role = get_user_context()
    require_role(role, {"SalesAssociate", "ShopManager", "Customer"})
    o = get_order(oid)
    body = get_json_body()
    kind = V.req_enum(body, "kind", {"DEPOSIT", "BALANCE"})
    amount = V.req_int(body, "amount_cents")

    # fiscal gating (priority 14): DEPOSIT only while CONFIRMED, BALANCE only while
    # READY; amount must be strictly > 0.
    if amount <= 0:
        fail(errors.ERR_PAYMENT_NOT_ALLOWED_NOW, "Payment amount must be > 0")
    if kind == "DEPOSIT" and o["status"] != "CONFIRMED":
        fail(errors.ERR_PAYMENT_NOT_ALLOWED_NOW, "Deposit allowed only while CONFIRMED")
    if kind == "BALANCE" and o["status"] != "READY":
        fail(errors.ERR_PAYMENT_NOT_ALLOWED_NOW, "Balance allowed only while READY")

    # overpayment bound for BALANCE (priority 15): amount <= balance_due_cents
    if kind == "BALANCE" and amount > o["balance_due_cents"]:
        fail(errors.ERR_OVERPAYMENT_REJECTED, "Balance payment exceeds outstanding balance")

    rec = {
        "id": new_id(),
        "created_at": now_iso(),
        "order_id": oid,
        "kind": kind,
        "amount_cents": amount,
        "status": "CAPTURED",
    }
    db.payments[rec["id"]] = rec

    osvc.recompute_balance(o)
    touch(o)

    return success(S.payment(rec), status=201)


@bp.get("/orders/<oid>/payments")
def list_payments(oid):
    _, role = get_user_context()
    require_role(role, {"ShopManager", "SalesAssociate", "FittingSpecialist", "Customer"})
    get_order(oid)
    limit, offset = V.parse_pagination()
    kind = request.args.get("kind")
    status = request.args.get("status")

    def pred(p):
        if p["order_id"] != oid:
            return False
        if kind is not None and p["kind"] != kind:
            return False
        if status is not None and p["status"] != status:
            return False
        return True

    items = [p for p in db.payments.values() if pred(p)]
    items.sort(key=lambda p: p["created_at"])
    page = V.paginate(items, limit, offset)
    return list_response([S.payment(p) for p in page], len(items), limit, offset)


@bp.post("/orders/<oid>/apply-credit")
def apply_credit(oid):
    _, role = get_user_context()
    require_role(role, {"SalesAssociate", "ShopManager"})
    o = get_order(oid)
    body = get_json_body()
    amount = V.req_int(body, "amount_cents", minimum=1)

    customer = db.customers.get(o["customer_id"])
    available = customer["store_credit_cents"] if customer else 0

    # ceiling check (priority 16): cannot exceed available credit nor outstanding balance
    if amount > available or amount > o["balance_due_cents"]:
        fail(errors.ERR_INSUFFICIENT_STORE_CREDIT,
             "Applied credit exceeds available credit or outstanding balance")

    customer["store_credit_cents"] -= amount
    touch(customer)
    o["store_credit_applied_cents"] += amount
    osvc.recompute_balance(o)
    touch(o)

    return success(S.garment_order(o))
