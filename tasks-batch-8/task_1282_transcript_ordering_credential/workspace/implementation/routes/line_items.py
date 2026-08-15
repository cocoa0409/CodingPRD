"""OrderLineItem endpoints (dispatch, mark-delivered, mark-bounced)."""
import secrets
import string

from flask import Blueprint, request

from db import DB
from errors import ApiError
from middleware import auth
from response import ok, ok_list
from services import (
    evaluate_order_bubble_up,
    get_line_item,
    get_order,
    lines_of_order,
    ser_line_item,
    sorted_created,
    touch,
)
from util import body, pagination_args, reject_unknown_fields

bp = Blueprint("line_items", __name__)

READ_ROLES = ["RegistrarAdmin", "RegistrarOperator", "RegistrarReviewer", "Student"]
OP_ROLES = ["RegistrarOperator"]
_ALPHABET = string.ascii_letters + string.digits


@bp.get("/registrar/line-items")
def list_line_items():
    auth(READ_ROLES)
    limit, offset = pagination_args()
    items = list(DB["order_line_items"].values())
    oid = request.args.get("order_id")
    if oid is not None:
        items = [l for l in items if l["order_id"] == oid]
    rid = request.args.get("recipient_id")
    if rid is not None:
        items = [l for l in items if l["recipient_id"] == rid]
    arid = request.args.get("archived_retrieval_id")
    if arid is not None:
        items = [l for l in items if l.get("archived_retrieval_id") == arid]
    st = request.args.get("line_status")
    if st is not None:
        items = [l for l in items if l["line_status"] == st]
    dk = request.args.get("delivery_kind")
    if dk is not None:
        items = [l for l in items if l["delivery_kind"] == dk]
    items = sorted_created(items)
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ser_line_item(l) for l in page], total, limit, offset)


@bp.get("/registrar/line-items/<lid>")
def get_one_line_item(lid):
    auth(READ_ROLES)
    return ok(ser_line_item(get_line_item(lid)))


@bp.post("/registrar/line-items/<lid>/dispatch")
def dispatch_line_item(lid):
    auth(OP_ROLES)
    line = get_line_item(lid)
    if line["line_status"] != "QUEUED":
        raise ApiError("ERR_INVALID_STATE", 409, "Line item is not QUEUED")
    order = get_order(line["order_id"])
    if order["payment_status"] not in ("CAPTURED", "WAIVED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Order payment_status must be CAPTURED or WAIVED to dispatch",
        )
    if line["delivery_kind"] == "ELECTRONIC_NETWORK":
        recipient = DB["recipients"].get(line["recipient_id"])
        if recipient is None:
            raise ApiError("ERR_NOT_FOUND", 404, "Recipient not found")
        if not recipient["active"]:
            raise ApiError(
                "ERR_RECIPIENT_INACTIVE", 422, "Recipient is no longer active"
            )
    line["tracking_ref"] = "TRK-" + "".join(
        secrets.choice(_ALPHABET) for _ in range(16)
    )
    line["line_status"] = "SENT"
    touch(line)

    # Bubble up: first SENT flips order to IN_TRANSIT.
    if order["fulfillment_status"] == "READY_TO_FULFILL":
        order["fulfillment_status"] = "IN_TRANSIT"
        touch(order)
    return ok(ser_line_item(line))


@bp.post("/registrar/line-items/<lid>/mark-delivered")
def mark_delivered(lid):
    auth(OP_ROLES)
    line = get_line_item(lid)
    if line["line_status"] != "SENT":
        raise ApiError("ERR_INVALID_STATE", 409, "Line item is not SENT")
    line["line_status"] = "DELIVERED"
    touch(line)
    order = get_order(line["order_id"])
    evaluate_order_bubble_up(order)
    return ok(ser_line_item(line))


@bp.post("/registrar/line-items/<lid>/mark-bounced")
def mark_bounced(lid):
    auth(OP_ROLES)
    line = get_line_item(lid)
    if line["line_status"] != "SENT":
        raise ApiError("ERR_INVALID_STATE", 409, "Line item is not SENT")
    line["line_status"] = "BOUNCED"
    touch(line)
    order = get_order(line["order_id"])
    evaluate_order_bubble_up(order)
    return ok(ser_line_item(line))
