"""GoodsReceipt endpoints (PRD §3.2).

A receipt occupies the half-open interval [received_date, received_date +
coverage_days). Posting recomputes the PO received total and is blocked on a
CLOSED PO or a window overlap with an already-POSTED receipt on the same PO.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from flask import Blueprint

import db
from errors import (
    APIError, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_PO_CLOSED, ERR_RECEIPT_WINDOW_OVERLAP,
)
from middleware import auth_required, ALL_ROLES
from response import ok_object
from routes._helpers import get_body, require_fields, serialize, is_int, is_str
from services.common import new_common_fields, touch
from services.ledger import recompute_po_received

bp = Blueprint("goods_receipts", __name__)


def _parse_date(value: str):
    """Parse an ISO 8601 date/datetime string into a datetime for interval math."""
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        # Plain date (YYYY-MM-DD).
        try:
            return datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            raise APIError(ERR_INVALID_REQUEST, 400, "received_date must be an ISO 8601 date")


@bp.post("/ap/goods-receipts")
def create_goods_receipt():
    auth_required({"APClerk", "APManager"})()
    body = get_body()
    require_fields(body, ["po_id", "received_amount_cents", "received_date"])

    po_id = body["po_id"]
    if po_id not in db.purchase_orders:
        raise APIError(ERR_NOT_FOUND, 404, "Purchase order not found")

    received = body["received_amount_cents"]
    if not is_int(received) or received < 1:
        raise APIError(ERR_INVALID_REQUEST, 400, "received_amount_cents must be an integer >= 1")

    received_date = body["received_date"]
    if not is_str(received_date):
        raise APIError(ERR_INVALID_REQUEST, 400, "received_date must be a string")
    _parse_date(received_date)  # validates format

    coverage_days = body.get("coverage_days", 1)
    if not is_int(coverage_days) or coverage_days < 1:
        raise APIError(ERR_INVALID_REQUEST, 400, "coverage_days must be an integer >= 1")

    gr = {
        **new_common_fields(),
        "po_id": po_id,
        "received_amount_cents": received,
        "received_date": received_date,
        "coverage_days": coverage_days,
        "status": "DRAFT",
    }
    db.goods_receipts[gr["id"]] = gr
    return ok_object(serialize(gr), http_status=201)


@bp.get("/ap/goods-receipts/<gid>")
def get_goods_receipt(gid):
    auth_required(ALL_ROLES)()
    gr = db.goods_receipts.get(gid)
    if gr is None:
        raise APIError(ERR_NOT_FOUND, 404, "Goods receipt not found")
    return ok_object(serialize(gr))


def _window(gr):
    start = _parse_date(gr["received_date"])
    end = start + timedelta(days=gr["coverage_days"])
    return start, end


@bp.post("/ap/goods-receipts/<gid>/post")
def post_goods_receipt(gid):
    auth_required({"APClerk", "APManager"})()
    gr = db.goods_receipts.get(gid)
    if gr is None:
        raise APIError(ERR_NOT_FOUND, 404, "Goods receipt not found")

    # State: only a DRAFT receipt may be posted.
    if gr["status"] != "DRAFT":
        raise APIError(ERR_INVALID_STATE, 409, "Goods receipt is not in DRAFT state")

    po = db.purchase_orders.get(gr["po_id"])
    if po is None:
        raise APIError(ERR_NOT_FOUND, 404, "Purchase order not found")

    # business: may not post against a CLOSED PO (409).
    if po["status"] == "CLOSED":
        raise APIError(ERR_PO_CLOSED, 409, "Cannot post a goods receipt against a CLOSED purchase order")

    # business_temporal: half-open window must not overlap any POSTED receipt on
    # the same PO; adjacency (end == next start) is allowed (409 on true overlap).
    new_start, new_end = _window(gr)
    for other in db.goods_receipts.values():
        if other["id"] == gr["id"] or other["po_id"] != po["id"] or other["status"] != "POSTED":
            continue
        o_start, o_end = _window(other)
        if new_start < o_end and o_start < new_end:  # strict overlap (half-open)
            raise APIError(ERR_RECEIPT_WINDOW_OVERLAP, 409,
                           "Goods receipt window overlaps a POSTED receipt on this PO")

    gr["status"] = "POSTED"
    touch(gr)
    recompute_po_received(po)
    return ok_object(serialize(gr))
