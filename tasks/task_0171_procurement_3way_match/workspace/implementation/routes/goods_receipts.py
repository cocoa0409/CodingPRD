"""GoodsReceipt endpoints (PRD §3.5)."""
from flask import Blueprint, request, g

import errors
from errors import ApiError
from db import db
from middleware import require_roles
from response import object_response, list_response
from services.common import (
    init_common, touch, public, get_body, require_fields, require_positive_int,
    invalid, parse_pagination, paginate, resolve, parse_instant,
)

bp = Blueprint("goods_receipts", __name__)

GR_READ_ROLES = ("ProcurementAdmin", "Buyer", "Receiver", "Matcher", "PayablesClerk")


def _validate_received_lines(lines):
    if not isinstance(lines, list) or len(lines) == 0:
        invalid("received_lines must be a non-empty array")
    for l in lines:
        if not isinstance(l, dict):
            invalid("each received line must be an object")
        if "sku" not in l or not isinstance(l["sku"], str) or l["sku"] == "":
            invalid("each received line requires a sku")
        if "received_qty" not in l:
            invalid("each received line requires received_qty")
        require_positive_int(l["received_qty"], "received_qty")


def _po_requester_id(po):
    """The requester_id of the requisition behind a PO (None for blanket)."""
    req_id = po.get("requisition_id")
    if req_id is None:
        return None
    requisition = db.requisitions.get(req_id)
    if requisition is None:
        return None
    return requisition.get("requester_id")


@bp.route("/procurement/goods-receipts", methods=["POST"])
@require_roles("Receiver")
def create_goods_receipt():
    body = get_body()
    require_fields(body, ["purchase_order_id", "received_lines", "received_at"])
    po = resolve(db.purchase_orders, body["purchase_order_id"])

    release_order_id = body.get("release_order_id")
    release = None
    if release_order_id is not None:
        release = resolve(db.release_orders, release_order_id)

    _validate_received_lines(body["received_lines"])
    received_at = parse_instant(body["received_at"], "received_at")

    # BLANKET PO requires a release_order_id (ERR_INVALID_REQUEST).
    if po["po_type"] == "BLANKET" and release_order_id is None:
        invalid("BLANKET PO requires release_order_id")

    # SOD (priority 5): receiver must not be the requisition requester.
    requester_id = _po_requester_id(po)
    if requester_id is not None and g.user_id == requester_id:
        raise ApiError(errors.ERR_SEGREGATION_OF_DUTIES, 403,
                       "Receiver must not be the requisition requester")

    # State legality (priority 6): PO must be ISSUED.
    if po["status"] != "ISSUED":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "PO is not ISSUED")

    # Receipt over-tolerance: cumulative received per sku must not exceed
    # ordered quantity (QTY tolerance is implicit 0 — no over-delivery).
    if po["po_type"] == "STANDARD" and po["lines"] is not None:
        ordered_by_sku = {l["sku"]: l["quantity"] for l in po["lines"]}
        already_by_sku = {l["sku"]: l["received_total"] for l in po["lines"]}
        for rl in body["received_lines"]:
            sku = rl["sku"]
            ordered = ordered_by_sku.get(sku)
            if ordered is None:
                # sku not on the PO -> over-tolerance (nothing ordered).
                raise ApiError(errors.ERR_RECEIPT_OVER_TOLERANCE, 409,
                               "Received sku not on the purchase order")
            cumulative = already_by_sku.get(sku, 0) + rl["received_qty"]
            if cumulative > ordered:
                raise ApiError(errors.ERR_RECEIPT_OVER_TOLERANCE, 409,
                               "Cumulative received quantity exceeds ordered")

    rec = {
        "purchase_order_id": po["id"],
        "release_order_id": release_order_id,
        "received_lines": [
            {"sku": rl["sku"], "received_qty": rl["received_qty"]}
            for rl in body["received_lines"]
        ],
        "received_at": body["received_at"],
        "posted_by_id": g.user_id,
        "status": "POSTED",
    }
    init_common(rec)
    db.goods_receipts[rec["id"]] = rec

    # Increment PO line received_total per sku (conserved ledger).
    if po["po_type"] == "STANDARD" and po["lines"] is not None:
        by_sku = {l["sku"]: l for l in po["lines"]}
        for rl in rec["received_lines"]:
            line = by_sku.get(rl["sku"])
            if line is not None:
                line["received_total"] += rl["received_qty"]
        touch(po)

    # If the receipt fully covers a linked release order, flip it to RECEIVED.
    if release is not None and release["status"] == "OPEN":
        if _release_fully_covered(release, rec):
            release["status"] = "RECEIVED"
            rec["_received_release_id"] = release["id"]
            touch(release)

    return object_response(public(rec), status=201)


def _release_fully_covered(release, receipt):
    """A release is fully covered when each release line's quantity is met by
    the receipt's received_qty for that sku."""
    received_by_sku = {}
    for rl in receipt["received_lines"]:
        received_by_sku[rl["sku"]] = received_by_sku.get(rl["sku"], 0) + rl["received_qty"]
    for line in release["lines"]:
        if received_by_sku.get(line["sku"], 0) < line["quantity"]:
            return False
    return True


@bp.route("/procurement/goods-receipts/<gid>", methods=["GET"])
@require_roles(*GR_READ_ROLES)
def get_goods_receipt(gid):
    rec = resolve(db.goods_receipts, gid)
    return object_response(public(rec))


@bp.route("/procurement/goods-receipts", methods=["GET"])
@require_roles(*GR_READ_ROLES)
def list_goods_receipts():
    limit, offset = parse_pagination(request.args)
    purchase_order_id = request.args.get("purchase_order_id")
    release_order_id = request.args.get("release_order_id")
    status = request.args.get("status")
    items = []
    for rec in db.goods_receipts.values():
        if purchase_order_id is not None and rec["purchase_order_id"] != purchase_order_id:
            continue
        if release_order_id is not None and rec["release_order_id"] != release_order_id:
            continue
        if status is not None and rec["status"] != status:
            continue
        items.append(rec)
    page, total = paginate(items, limit, offset)
    return list_response(page, limit, offset, total)


@bp.route("/procurement/goods-receipts/<gid>/reverse", methods=["POST"])
@require_roles("Receiver")
def reverse_goods_receipt(gid):
    rec = resolve(db.goods_receipts, gid)
    if rec["status"] != "POSTED":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Receipt is not POSTED")

    # Refused if a MATCHED or EXCEPTION invoice references this receipt.
    for inv in db.invoices.values():
        if inv["goods_receipt_id"] == rec["id"] and inv["match_status"] in ("MATCHED", "EXCEPTION"):
            raise ApiError(errors.ERR_RECEIPT_HAS_INVOICE, 409,
                           "A matched/exception invoice references this receipt")

    # Decrement PO line received_total per sku (compensating restore).
    po = db.purchase_orders.get(rec["purchase_order_id"])
    if po is not None and po["po_type"] == "STANDARD" and po["lines"] is not None:
        by_sku = {l["sku"]: l for l in po["lines"]}
        for rl in rec["received_lines"]:
            line = by_sku.get(rl["sku"])
            if line is not None:
                line["received_total"] -= rl["received_qty"]
        touch(po)

    # Revert a release that was RECEIVED solely by this receipt.
    received_release_id = rec.get("_received_release_id")
    if received_release_id is not None:
        release = db.release_orders.get(received_release_id)
        if release is not None and release["status"] == "RECEIVED":
            release["status"] = "OPEN"
            touch(release)

    rec["status"] = "REVERSED"
    touch(rec)
    return object_response(public(rec))
