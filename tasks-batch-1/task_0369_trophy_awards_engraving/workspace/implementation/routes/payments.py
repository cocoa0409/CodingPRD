from flask import Blueprint
from db import db
from errors import err
from response import ok, ok_list
from middleware import authenticate, require_role
from services import serialize
from services.common import (
    get_json_body, new_id, paginate, page_slice, require_fields, is_int,
)
from db import now_iso
from services.orders import get_order_or_404, enforce_order_ownership

bp = Blueprint("payments", __name__)


@bp.route("/orders/<order_id>/payments", methods=["POST"])
def create_payment(order_id):
    caller = authenticate()
    require_role(caller, ("Customer",))
    o = get_order_or_404(order_id)
    enforce_order_ownership(caller, o)
    body = get_json_body()
    require_fields(body, ["amount_cents", "kind"])
    amount = body["amount_cents"]
    kind = body["kind"]
    if not is_int(amount) or amount < 1:
        raise err("ERR_INVALID_REQUEST", "amount_cents must be an integer >= 1")
    if kind not in ("DEPOSIT", "BALANCE", "FULL"):
        raise err("ERR_INVALID_REQUEST", "kind must be DEPOSIT, BALANCE, or FULL")

    # state + amount checks per kind
    if kind == "DEPOSIT":
        if o["production_status"] != "CONFIRMED" or o["payment_status"] != "UNPAID":
            raise err("ERR_INVALID_STATE", "Deposit only payable on a CONFIRMED, UNPAID order")
        if amount != o["deposit_due_cents"]:
            raise err("ERR_PAYMENT_AMOUNT_MISMATCH", "Deposit amount must equal deposit_due_cents")
        next_payment_status = "DEPOSIT_PAID"
    elif kind == "FULL":
        if o["production_status"] != "CONFIRMED" or o["payment_status"] != "UNPAID":
            raise err("ERR_INVALID_STATE", "Full payment only on a CONFIRMED, UNPAID order")
        if amount != o["invoice_total_cents"]:
            raise err("ERR_PAYMENT_AMOUNT_MISMATCH", "Full amount must equal invoice_total_cents")
        next_payment_status = "PAID_IN_FULL"
    else:  # BALANCE
        if o["payment_status"] != "DEPOSIT_PAID":
            raise err("ERR_INVALID_STATE", "Balance only payable on a DEPOSIT_PAID order")
        required = o["invoice_total_cents"] - o["amount_paid_cents"]
        if amount != required:
            raise err("ERR_PAYMENT_AMOUNT_MISMATCH", "Balance amount must equal remaining due")
        next_payment_status = "PAID_IN_FULL"

    pay = {
        "id": new_id(),
        "created_at": now_iso(),
        "order_id": order_id,
        "amount_cents": amount,
        "kind": kind,
        "pay_status": "CAPTURED",
    }
    db.payments[pay["id"]] = pay
    o["amount_paid_cents"] += amount
    o["payment_status"] = next_payment_status
    # payment dimension change does not itself bump order version (no spec for it);
    # only production transitions bump version.
    return ok(serialize.payment(pay), 201)


@bp.route("/orders/<order_id>/payments", methods=["GET"])
def list_payments(order_id):
    caller = authenticate()
    require_role(caller, ("Customer", "ShopStaff", "ShopManager"))
    o = get_order_or_404(order_id)
    enforce_order_ownership(caller, o)
    items = [p for p in db.payments.values() if p["order_id"] == order_id]
    limit, offset = paginate()
    page, total = page_slice(items, limit, offset)
    return ok_list([serialize.payment(p) for p in page], limit, offset, total)
