"""InventoryLot read endpoints (PRD 3.3)."""
from flask import Blueprint, request

from common import get_or_404, list_response
from db import db
from middleware import require_roles
from response import object_response
from services import serialize

bp = Blueprint("lots", __name__)

ALL_ROLES = ("FieldOps", "RouteDriver", "HostManager", "FinanceClerk")


@bp.route("/operations/lots", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_lots():
    rows = list(db.lots.values())
    slot_id = request.args.get("slot_id")
    machine_id = request.args.get("machine_id")
    restock_visit_id = request.args.get("restock_visit_id")
    if slot_id is not None:
        rows = [l for l in rows if l["slot_id"] == slot_id]
    if machine_id is not None:
        rows = [l for l in rows if l["machine_id"] == machine_id]
    if restock_visit_id is not None:
        rows = [l for l in rows if l["restock_visit_id"] == restock_visit_id]
    return list_response(rows, serialize.lot)


@bp.route("/operations/lots/<lot_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_lot(lot_id):
    obj = get_or_404("lots", lot_id)
    return object_response(serialize.lot(obj))
