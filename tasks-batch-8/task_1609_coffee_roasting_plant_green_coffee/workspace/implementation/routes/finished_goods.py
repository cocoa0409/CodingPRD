"""FinishedGoodsLot read endpoints with lazy freshness aging (PRD §3.9)."""

from flask import Blueprint, request

from db import DB
from errors import ERR_NOT_FOUND, err
from middleware import paginate, pub, require_role, sort_created
from response import success_list, success_object
from services import lazy_stale_finished_lot

bp = Blueprint("finished_goods", __name__)

READ_ROLES = ("FulfillmentPlanner", "RoastOperator", "HeadRoaster")


@bp.get("/roastery/finished-goods-lots/<lot_id>")
def get_finished_goods_lot(lot_id):
    require_role(*READ_ROLES)
    lot = DB.finished_goods_lots.get(lot_id)
    if lot is None:
        raise err(ERR_NOT_FOUND, "Finished goods lot id does not exist")
    lazy_stale_finished_lot(lot)
    return success_object(pub(lot))


@bp.get("/roastery/finished-goods-lots")
def list_finished_goods_lots():
    require_role(*READ_ROLES)
    items = sort_created(DB.finished_goods_lots.values())
    for lot in items:
        lazy_stale_finished_lot(lot)
    batch_id = request.args.get("roast_batch_id")
    product_id = request.args.get("product_id")
    status = request.args.get("lot_status")
    if batch_id is not None:
        items = [l for l in items if l["roast_batch_id"] == batch_id]
    if product_id is not None:
        items = [l for l in items if l["product_id"] == product_id]
    if status is not None:
        items = [l for l in items if l["lot_status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list([pub(l) for l in page], limit, offset, total)
