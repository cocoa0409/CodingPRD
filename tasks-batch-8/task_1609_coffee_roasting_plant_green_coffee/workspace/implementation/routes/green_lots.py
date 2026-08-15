"""GreenLot read endpoints + warehouse position singleton (PRD §2.6, §3.4)."""

from flask import Blueprint, request

from db import DB
from errors import ERR_NOT_FOUND, err
from middleware import paginate, pub, require_role, sort_created
from response import success_list, success_object

bp = Blueprint("green_lots", __name__)

GET_ROLES = ("Trader", "WarehouseClerk", "RoastOperator", "HeadRoaster",
             "RiskManager", "QAGrader")


@bp.get("/roastery/green-lots/<lot_id>")
def get_green_lot(lot_id):
    require_role(*GET_ROLES)
    lot = DB.green_lots.get(lot_id)
    if lot is None:
        raise err(ERR_NOT_FOUND, "Green lot id does not exist")
    return success_object(pub(lot))


@bp.get("/roastery/green-lots")
def list_green_lots():
    require_role(*GET_ROLES)
    items = sort_created(DB.green_lots.values())
    shipment_id = request.args.get("shipment_id")
    status = request.args.get("lot_status")
    if shipment_id is not None:
        items = [l for l in items if l["shipment_id"] == shipment_id]
    if status is not None:
        items = [l for l in items if l["lot_status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list([pub(l) for l in page], limit, offset, total)


@bp.get("/roastery/warehouse-position")
def get_warehouse_position():
    require_role("Trader", "RiskManager", "HeadRoaster", "WarehouseClerk")
    return success_object(pub(DB.position))
