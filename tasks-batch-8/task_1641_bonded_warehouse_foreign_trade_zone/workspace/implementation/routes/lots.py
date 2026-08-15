"""InventoryLot read-only endpoints (SCAFFOLD 1.5, PRD 3.3)."""
from flask import Blueprint, request

from db import db
from errors import ERR_LOT_NOT_FOUND
from middleware import authorized
from response import success_object, success_list
from serializers import lot_view
from validate import require_path, parse_pagination

bp = Blueprint("lots", __name__)

ALL_ROLES = ["ZoneOperator", "Importer", "CustomsOfficer", "GateOfficer"]


@bp.route("/zones/lots", methods=["GET"])
def list_lots():
    authorized(ALL_ROLES)
    limit, offset = parse_pagination()
    zone_id = request.args.get("zone_id")
    admission_id = request.args.get("admission_id")
    source_manipulation_id = request.args.get("source_manipulation_id")
    status = request.args.get("status")
    hts_code = request.args.get("hts_code")
    items = sorted(db["lots"].values(), key=lambda l: (l["created_at"], l["id"]))
    if zone_id is not None:
        items = [l for l in items if l["zone_id"] == zone_id]
    if admission_id is not None:
        items = [l for l in items if l["admission_id"] == admission_id]
    if source_manipulation_id is not None:
        items = [l for l in items if l["source_manipulation_id"] == source_manipulation_id]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    if hts_code is not None:
        items = [l for l in items if l["hts_code"] == hts_code]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([lot_view(l) for l in page], total, limit, offset)


@bp.route("/zones/lots/<lotId>", methods=["GET"])
def get_lot(lotId):
    authorized(ALL_ROLES)
    lot = require_path("lots", lotId, ERR_LOT_NOT_FOUND)
    return success_object(lot_view(lot))
