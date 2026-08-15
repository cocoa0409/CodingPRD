"""Payment endpoints (authorize / capture / refund / void)."""
import hashlib
import json
import secrets
import string

from flask import Blueprint, request

from db import DB, new_id
from errors import ApiError
from middleware import auth
from response import ok, ok_list
from services import (
    compute_final_fee,
    get_order,
    get_payment,
    logical_now,
    payments_of_order,
    ref_lookup,
    ser_payment,
    sorted_created,
    stamp,
    touch,
)
from util import as_int, as_str, body, pagination_args, reject_unknown_fields, required

bp = Blueprint("payments", __name__)

READ_ROLES = ["RegistrarAdmin", "RegistrarOperator", "RegistrarReviewer", "Student"]
OP_ROLES = ["RegistrarOperator"]
_ALPHABET = string.ascii_letters + string.digits


def _payload_fingerprint(order_id, idem_key):
    return hashlib.sha256(
        json.dumps({"order_id": order_id}, sort_keys=True).encode("utf-8")
    ).hexdigest()


@bp.post("/registrar/payments")
def authorize_payment():
    user_id, role = auth(["Student"])
    data = body()
    reject_unknown_fields(data, {"order_id", "idempotency_key"})
    order_id = required(data, "order_id")
    idem_key = as_str(required(data, "idempotency_key"), "idempotency_key")
    order = ref_lookup("orders", order_id, "TranscriptOrder")

    # Idempotency: same key + same payload returns the original Payment;
    # same key with different payload -> ERR_IDEMPOTENCY_CONFLICT.
    # PRD 3.6 "already seen" is a global registry: the authorize payload is
    # only {order_id, idempotency_key}, so the different-payload case can only
    # arise when a key is reused across orders.
    for p in DB["payments"].values():
        if p["idempotency_key"] == idem_key:
            fp = _payload_fingerprint(order_id, idem_key)
            if p.get("_payload_fp") == fp:
                return ok(ser_payment(p), status=201)
            raise ApiError(
                "ERR_IDEMPOTENCY_CONFLICT",
                409,
                "idempotency_key already used with a different payload",
            )

    if order["fulfillment_status"] not in ("SUBMITTED", "HOLD_CHECK", "READY_TO_FULFILL"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Order fulfillment_status does not admit authorization",
        )
    for p in payments_of_order(order["id"]):
        if p["status"] in ("AUTHORIZED", "CAPTURED"):
            raise ApiError(
                "ERR_INVALID_STATE",
                409,
                "An AUTHORIZED or CAPTURED payment already exists for this order",
            )

    rec = {
        "id": new_id(),
        "order_id": order["id"],
        "amount_cents": order["quoted_fee_cents"],
        "captured_cents": 0,
        "refunded_cents": 0,
        "status": "AUTHORIZED",
        "idempotency_key": idem_key,
        "gateway_ref": "gw_" + "".join(secrets.choice(_ALPHABET) for _ in range(16)),
        "_payload_fp": _payload_fingerprint(order_id, idem_key),
    }
    stamp(rec)
    DB["payments"][rec["id"]] = rec
    order["payment_status"] = "AUTHORIZED"
    touch(order)
    return ok(ser_payment(rec), status=201)


@bp.get("/registrar/payments/<pid>")
def get_one_payment(pid):
    auth(READ_ROLES)
    return ok(ser_payment(get_payment(pid)))


@bp.get("/registrar/orders/<oid>/payments")
def list_order_payments(oid):
    auth(READ_ROLES)
    order = get_order(oid)
    limit, offset = pagination_args()
    items = payments_of_order(order["id"])
    st = request.args.get("status")
    if st is not None:
        items = [p for p in items if p["status"] == st]
    items = sorted_created(items)
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ser_payment(p) for p in page], total, limit, offset)


@bp.post("/registrar/payments/<pid>/capture")
def capture_payment(pid):
    auth(OP_ROLES)
    payment = get_payment(pid)
    if payment["status"] != "AUTHORIZED":
        raise ApiError("ERR_INVALID_STATE", 409, "Payment is not AUTHORIZED")
    order = get_order(payment["order_id"])
    if order["fulfillment_status"] == "CANCELLED":
        raise ApiError("ERR_INVALID_STATE", 409, "Order is CANCELLED")

    now = logical_now()
    # Recompute final fee at the capture-time clock.
    final_fee = compute_final_fee(order, now)
    order["final_fee_cents"] = final_fee

    # payment_capture_reconcile: never capture more than the final fee, never
    # less than 0, and never more than the authorized amount.
    target = max(0, final_fee - payment["refunded_cents"])
    if target > payment["amount_cents"]:
        # Shortfall recorded, not auto-charged; capture is capped at authorized.
        captured = payment["amount_cents"]
    else:
        captured = target
    payment["captured_cents"] = captured
    payment["amount_cents"] = final_fee
    payment["status"] = "CAPTURED"
    touch(payment)
    order["payment_status"] = "CAPTURED"
    touch(order)
    return ok(ser_payment(payment))


@bp.post("/registrar/payments/<pid>/refund")
def refund_payment(pid):
    auth(OP_ROLES)
    payment = get_payment(pid)
    data = body()
    reject_unknown_fields(data, {"refund_amount_cents"})
    amount = as_int(required(data, "refund_amount_cents"), "refund_amount_cents")
    if amount <= 0:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "refund_amount_cents must be positive"
        )
    if payment["status"] not in ("CAPTURED", "PARTIALLY_REFUNDED"):
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Payment is not in a refundable state"
        )
    cumulative = payment["refunded_cents"] + amount
    if cumulative > payment["captured_cents"]:
        raise ApiError(
            "ERR_REFUND_EXCEEDS_CAPTURED",
            422,
            "Cumulative refund would exceed captured_cents",
        )
    payment["refunded_cents"] = cumulative
    if cumulative == payment["captured_cents"]:
        payment["status"] = "REFUNDED"
    else:
        payment["status"] = "PARTIALLY_REFUNDED"
    touch(payment)
    order = get_order(payment["order_id"])
    order["payment_status"] = payment["status"]
    touch(order)
    return ok(ser_payment(payment))


@bp.post("/registrar/payments/<pid>/void")
def void_payment(pid):
    auth(OP_ROLES)
    payment = get_payment(pid)
    if payment["status"] != "AUTHORIZED":
        raise ApiError("ERR_INVALID_STATE", 409, "Payment is not AUTHORIZED")
    payment["status"] = "VOIDED"
    touch(payment)
    order = get_order(payment["order_id"])
    order["payment_status"] = "UNPAID"
    touch(order)
    return ok(ser_payment(payment))
