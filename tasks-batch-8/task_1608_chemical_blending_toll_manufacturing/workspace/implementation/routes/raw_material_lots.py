"""Raw material lot endpoints."""
from flask import Blueprint, request

import db
import errors
from middleware import require_role
from response import success_object, success_list
from services.common import (
    new_id,
    now_iso,
    pagination_params,
    paginate,
    sort_by_created_at,
    serialize_lot,
    to_decimal,
    parse_iso,
    as_float_3dp,
)
from services.calculations import zone_admits, GHS_CLASSES, ZONES

bp = Blueprint("raw_material_lots", __name__)


def _customer_or_404(cid):
    c = db.customers.get(cid)
    if c is None:
        raise errors.not_found("customer not found")
    return c


def _lot_or_404(customer_id, lot_id):
    l = db.raw_material_lots.get(lot_id)
    if l is None or l["customer_id"] != customer_id:
        raise errors.not_found("raw material lot not found")
    return l


@bp.route("/toll-operations/customers/<id>/raw-material-lots", methods=["POST"])
def create_lot(id):
    require_role({"BatchScheduler"})
    _customer_or_404(id)
    body = request.get_json(silent=True) or {}

    material_code = body.get("material_code")
    if not material_code or not isinstance(material_code, str):
        raise errors.invalid_request("material_code required")
    ghS_class = body.get("ghS_class")
    if ghS_class not in GHS_CLASSES:
        raise errors.invalid_request("ghS_class invalid")
    qty_received = to_decimal(body.get("quantity_kg_received"), "quantity_kg_received")
    if qty_received < 0:
        raise errors.invalid_request("quantity_kg_received must be >= 0")
    storage_zone = body.get("storage_zone")
    if storage_zone not in ZONES:
        raise errors.invalid_request("storage_zone invalid")
    received_at = body.get("received_at")
    if not received_at:
        raise errors.invalid_request("received_at required")
    parse_iso(received_at)

    # Segregation check
    if not zone_admits(ghS_class, storage_zone):
        raise errors.ApiError(
            errors.ERR_INCOMPATIBLE_SEGREGATION,
            409,
            "ghS_class not admitted by storage_zone",
        )

    now = now_iso()
    lid = new_id()
    qty_f = as_float_3dp(qty_received)
    lot = {
        "id": lid,
        "customer_id": id,
        "material_code": material_code,
        "ghS_class": ghS_class,
        "quantity_kg_received": qty_f,
        "quantity_kg_on_hand": qty_f,
        "quantity_kg_committed": 0.0,
        "quantity_kg_available": qty_f,
        "storage_zone": storage_zone,
        "received_at": received_at,
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    db.raw_material_lots[lid] = lot
    return success_object(serialize_lot(lot), status=201)


@bp.route("/toll-operations/customers/<id>/raw-material-lots", methods=["GET"])
def list_lots(id):
    require_role({"Any"})
    _customer_or_404(id)
    limit, offset = pagination_params()
    rows = [l for l in db.raw_material_lots.values() if l["customer_id"] == id]
    rows = sort_by_created_at(rows)
    slice_, total = paginate(rows, limit, offset)
    return success_list([serialize_lot(l) for l in slice_], limit, offset, total)


@bp.route("/toll-operations/customers/<id>/raw-material-lots/<lotId>", methods=["GET"])
def get_lot(id, lotId):
    require_role({"Any"})
    _customer_or_404(id)
    l = _lot_or_404(id, lotId)
    return success_object(serialize_lot(l))
