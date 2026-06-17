"""MaterialLot and LotAllocation routes (PRD §3.3, §3.8)."""
from flask import Blueprint, request

from db import db, lock, base_fields
from errors import err
from middleware import require_roles, require_auth
from helpers import (
    get_body, require_fields, validate_enum, as_int, as_str, parse_datetime,
    paginate, serialize, serialize_list,
)
from response import success, list_response

bp = Blueprint("material", __name__)

MATERIAL_SPECS = {"AL_6061", "SS_304", "TI_6AL4V", "BRASS_360"}


def get_lot_or_404(lot_id):
    lot = db.material_lots.get(lot_id)
    if lot is None:
        raise err("ERR_NOT_FOUND", "MaterialLot not found")
    return lot


# ---------------------------------------------------------------------------
# MaterialLot
# ---------------------------------------------------------------------------


@bp.route("/material-lots", methods=["POST"])
def create_material_lot():
    require_roles("MaterialController")
    body = get_body()
    require_fields(body, "material_spec", "heat_number", "qty_received",
                   "unit_cost_cents", "received_at")
    material_spec = body["material_spec"]
    validate_enum(material_spec, MATERIAL_SPECS, "material_spec")
    heat_number = as_str(body, "heat_number")
    qty_received = as_int(body, "qty_received", minimum=1)
    unit_cost_cents = as_int(body, "unit_cost_cents")
    received_at = body["received_at"]
    parse_datetime(received_at, "received_at")  # validate format
    with lock():
        rec = base_fields()
        rec.update({
            "material_spec": material_spec,
            "heat_number": heat_number,
            "qty_received": qty_received,
            "unit_cost_cents": unit_cost_cents,
            "received_at": received_at,
            "qty_remaining": qty_received,
            "status": "AVAILABLE",
        })
        db.material_lots[rec["id"]] = rec
        return success(serialize(rec), status=201)


@bp.route("/material-lots/<lot_id>", methods=["GET"])
def get_material_lot(lot_id):
    require_auth()
    with lock():
        return success(serialize(get_lot_or_404(lot_id)))


@bp.route("/material-lots", methods=["GET"])
def list_material_lots():
    require_auth()
    material_spec = request.args.get("material_spec")
    status = request.args.get("status")
    with lock():
        items = list(db.material_lots.values())
        if material_spec:
            items = [l for l in items if l["material_spec"] == material_spec]
        if status:
            items = [l for l in items if l["status"] == status]
        page, limit, offset, total = paginate(items)
        return list_response(serialize_list(page), limit, offset, total)


@bp.route("/material-lots/<lot_id>/lot-allocations", methods=["GET"])
def list_lot_allocations_for_lot(lot_id):
    require_auth()
    with lock():
        get_lot_or_404(lot_id)
        items = [a for a in db.lot_allocations.values() if a["material_lot_id"] == lot_id]
        page, limit, offset, total = paginate(items)
        return list_response(serialize_list(page), limit, offset, total)


# ---------------------------------------------------------------------------
# LotAllocation (read-only collection)
# ---------------------------------------------------------------------------


@bp.route("/lot-allocations/<allocation_id>", methods=["GET"])
def get_lot_allocation(allocation_id):
    require_auth()
    with lock():
        a = db.lot_allocations.get(allocation_id)
        if a is None:
            raise err("ERR_NOT_FOUND", "LotAllocation not found")
        return success(serialize(a))


@bp.route("/lot-allocations", methods=["GET"])
def list_lot_allocations():
    require_auth()
    work_order_id = request.args.get("work_order_id")
    material_lot_id = request.args.get("material_lot_id")
    status = request.args.get("status")
    with lock():
        items = list(db.lot_allocations.values())
        if work_order_id:
            items = [a for a in items if a["work_order_id"] == work_order_id]
        if material_lot_id:
            items = [a for a in items if a["material_lot_id"] == material_lot_id]
        if status:
            items = [a for a in items if a["status"] == status]
        page, limit, offset, total = paginate(items)
        return list_response(serialize_list(page), limit, offset, total)
