"""Fulfillment orders and lines (PRD §3.9)."""

from flask import Blueprint, request

from db import DB
from errors import (
    ERR_INSUFFICIENT_FINISHED_GOODS, ERR_INVALID_STATE, ERR_NOT_FOUND,
    ERR_STALE_GOODS, err,
)
from middleware import (
    COMMON_SYS, base_fields, check_unknown_fields, get_json_body, paginate,
    pub, require_fields, require_role, sort_created, touch, v_enum, v_int,
    v_iso,
)
from response import success_list, success_object
from services import lazy_stale_finished_lot

bp = Blueprint("fulfillment", __name__)

CHANNELS = {"PRIVATE_LABEL", "SUBSCRIPTION", "WHOLESALE"}

ORDER_ALLOWED = {
    "customer_counterparty_id", "channel", "requested_ship_date",
    "order_status", "total_reserved_lbs",
} | COMMON_SYS

LINE_ALLOWED = {
    "finished_goods_lot_id", "allocated_lbs", "order_id", "line_status",
} | COMMON_SYS

ORDER_READ_ROLES = ("FulfillmentPlanner", "Trader")


def get_order_or_404(order_id):
    o = DB.fulfillment_orders.get(order_id)
    if o is None:
        raise err(ERR_NOT_FOUND, "Fulfillment order id does not exist")
    return o


def _order_lines(order_id):
    return sort_created(
        [l for l in DB.fulfillment_lines.values() if l["order_id"] == order_id])


@bp.post("/roastery/fulfillment-orders")
def create_fulfillment_order():
    require_role("FulfillmentPlanner")
    body = get_json_body()
    # Priority 5: body FK existence.
    cust = body.get("customer_counterparty_id")
    if isinstance(cust, str) and cust not in DB.counterparties:
        raise err(ERR_NOT_FOUND, "customer_counterparty_id does not exist")
    check_unknown_fields(body, ORDER_ALLOWED)
    require_fields(body, ["customer_counterparty_id", "channel", "requested_ship_date"])
    cid = body["customer_counterparty_id"]
    if not isinstance(cid, str) or cid not in DB.counterparties:
        raise err(ERR_NOT_FOUND, "customer_counterparty_id does not exist")
    channel = v_enum(body, "channel", CHANNELS)
    ship_date = v_iso(body, "requested_ship_date")
    o = base_fields()
    o.update({
        "customer_counterparty_id": cid,
        "channel": channel,
        "requested_ship_date": ship_date,
        "order_status": "DRAFT",
        "total_reserved_lbs": 0,
    })
    DB.fulfillment_orders[o["id"]] = o
    return success_object(pub(o), status=201)


@bp.get("/roastery/fulfillment-orders/<order_id>")
def get_fulfillment_order(order_id):
    require_role(*ORDER_READ_ROLES)
    return success_object(pub(get_order_or_404(order_id)))


@bp.get("/roastery/fulfillment-orders")
def list_fulfillment_orders():
    require_role(*ORDER_READ_ROLES)
    items = sort_created(DB.fulfillment_orders.values())
    cust = request.args.get("customer_counterparty_id")
    status = request.args.get("order_status")
    channel = request.args.get("channel")
    if cust is not None:
        items = [o for o in items if o["customer_counterparty_id"] == cust]
    if status is not None:
        items = [o for o in items if o["order_status"] == status]
    if channel is not None:
        items = [o for o in items if o["channel"] == channel]
    page, limit, offset, total = paginate(items)
    return success_list([pub(o) for o in page], limit, offset, total)


@bp.post("/roastery/fulfillment-orders/<order_id>/lines")
def add_fulfillment_line(order_id):
    require_role("FulfillmentPlanner")
    order = get_order_or_404(order_id)
    body = get_json_body()
    # Priority 5: body FK existence.
    lot_id = body.get("finished_goods_lot_id")
    if isinstance(lot_id, str) and lot_id not in DB.finished_goods_lots:
        raise err(ERR_NOT_FOUND, "finished_goods_lot_id does not exist")
    # Priority 6: lines are added to DRAFT orders only.
    if order["order_status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Lines may only be added to a DRAFT order")
    check_unknown_fields(body, LINE_ALLOWED)
    require_fields(body, ["finished_goods_lot_id", "allocated_lbs"])
    lid = body["finished_goods_lot_id"]
    if not isinstance(lid, str) or lid not in DB.finished_goods_lots:
        raise err(ERR_NOT_FOUND, "finished_goods_lot_id does not exist")
    allocated = v_int(body, "allocated_lbs", gt=0)
    line = base_fields()
    line.update({
        "order_id": order_id,
        "finished_goods_lot_id": lid,
        "allocated_lbs": allocated,
        # Reservation "activates" lines at DRAFT -> RESERVED; the line_status
        # vocabulary is ACTIVE | SHIPPED | RELEASED, so a freshly added line
        # is ACTIVE (it holds no inventory until the order is reserved).
        "line_status": "ACTIVE",
    })
    DB.fulfillment_lines[line["id"]] = line
    return success_object(pub(line), status=201)


@bp.get("/roastery/fulfillment-orders/<order_id>/lines")
def list_order_lines(order_id):
    require_role("FulfillmentPlanner")
    get_order_or_404(order_id)
    items = _order_lines(order_id)
    page, limit, offset, total = paginate(items)
    return success_list([pub(l) for l in page], limit, offset, total)


@bp.get("/roastery/fulfillment-lines/<line_id>")
def get_fulfillment_line(line_id):
    require_role("FulfillmentPlanner")
    line = DB.fulfillment_lines.get(line_id)
    if line is None:
        raise err(ERR_NOT_FOUND, "Fulfillment line id does not exist")
    return success_object(pub(line))


@bp.get("/roastery/fulfillment-lines")
def list_fulfillment_lines():
    require_role("FulfillmentPlanner")
    items = sort_created(DB.fulfillment_lines.values())
    order_id = request.args.get("order_id")
    lot_id = request.args.get("finished_goods_lot_id")
    status = request.args.get("line_status")
    if order_id is not None:
        items = [l for l in items if l["order_id"] == order_id]
    if lot_id is not None:
        items = [l for l in items if l["finished_goods_lot_id"] == lot_id]
    if status is not None:
        items = [l for l in items if l["line_status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list([pub(l) for l in page], limit, offset, total)


@bp.post("/roastery/fulfillment-orders/<order_id>/reserve")
def reserve_order(order_id):
    require_role("FulfillmentPlanner")
    order = get_order_or_404(order_id)
    get_json_body()
    if order["order_status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Reserve requires order_status DRAFT")
    lines = _order_lines(order_id)
    if not lines:
        raise err(ERR_INVALID_STATE, "Reserve requires at least one fulfillment line")

    # Lazy freshness aging applies at allocation time (PRD §2.11).
    lots = {}
    for line in lines:
        lot = DB.finished_goods_lots.get(line["finished_goods_lot_id"])
        if lot is not None:
            lazy_stale_finished_lot(lot)
            lots[lot["id"]] = lot

    # Priority 17: every referenced lot must be FRESH at reservation time.
    for line in lines:
        lot = lots.get(line["finished_goods_lot_id"])
        if lot is None or lot["lot_status"] != "FRESH":
            raise err(ERR_STALE_GOODS,
                      "Every referenced finished goods lot must be FRESH at reservation time")

    # Priority 18: per-line sufficiency against available_lbs (cumulative
    # within the order when several lines draw from the same lot).
    remaining = {lot_id: lot["available_lbs"] for lot_id, lot in lots.items()}
    for line in lines:
        lot_id = line["finished_goods_lot_id"]
        if line["allocated_lbs"] > remaining[lot_id]:
            raise err(ERR_INSUFFICIENT_FINISHED_GOODS,
                      "allocated_lbs exceeds FinishedGoodsLot.available_lbs")
        remaining[lot_id] -= line["allocated_lbs"]

    for line in lines:
        line["line_status"] = "ACTIVE"
        touch(line)
    for lot_id, lot in lots.items():
        used = sum(l["allocated_lbs"] for l in lines if l["finished_goods_lot_id"] == lot_id)
        if used:
            lot["available_lbs"] -= used
            touch(lot)
    order["total_reserved_lbs"] = sum(l["allocated_lbs"] for l in lines)
    order["order_status"] = "RESERVED"
    touch(order)
    return success_object(pub(order))


@bp.post("/roastery/fulfillment-orders/<order_id>/pack")
def pack_order(order_id):
    require_role("FulfillmentPlanner")
    order = get_order_or_404(order_id)
    get_json_body()
    if order["order_status"] != "RESERVED":
        raise err(ERR_INVALID_STATE, "Pack requires order_status RESERVED")
    order["order_status"] = "PACKED"
    touch(order)
    return success_object(pub(order))


@bp.post("/roastery/fulfillment-orders/<order_id>/ship")
def ship_order(order_id):
    require_role("FulfillmentPlanner")
    order = get_order_or_404(order_id)
    get_json_body()
    if order["order_status"] != "PACKED":
        raise err(ERR_INVALID_STATE, "Ship requires order_status PACKED")
    lines = _order_lines(order_id)
    touched_lots = set()
    for line in lines:
        if line["line_status"] == "ACTIVE":
            line["line_status"] = "SHIPPED"
            touch(line)
            touched_lots.add(line["finished_goods_lot_id"])
    for lot_id in touched_lots:
        lot = DB.finished_goods_lots.get(lot_id)
        if lot is not None and lot["lot_status"] in ("FRESH", "STALE") \
                and lot["available_lbs"] == 0:
            lot["lot_status"] = "DEPLETED"
            touch(lot)
    order["order_status"] = "SHIPPED"
    touch(order)
    return success_object(pub(order))


@bp.post("/roastery/fulfillment-orders/<order_id>/cancel")
def cancel_order(order_id):
    require_role("FulfillmentPlanner")
    order = get_order_or_404(order_id)
    get_json_body()
    if order["order_status"] not in ("DRAFT", "RESERVED"):
        raise err(ERR_INVALID_STATE, "Cancel requires order_status DRAFT or RESERVED")
    if order["order_status"] == "RESERVED":
        touched_lots = set()
        for line in _order_lines(order_id):
            if line["line_status"] == "ACTIVE":
                line["line_status"] = "RELEASED"
                touch(line)
                lot = DB.finished_goods_lots.get(line["finished_goods_lot_id"])
                if lot is not None:
                    lot["available_lbs"] += line["allocated_lbs"]
                    touched_lots.add(lot["id"])
        for lot_id in touched_lots:
            touch(DB.finished_goods_lots[lot_id])
        order["total_reserved_lbs"] = 0
    order["order_status"] = "CANCELLED"
    touch(order)
    return success_object(pub(order))
