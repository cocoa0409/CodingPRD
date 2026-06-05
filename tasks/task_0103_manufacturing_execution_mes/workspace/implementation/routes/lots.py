"""Lot inventory endpoints (PRD §3.8)."""
from flask import Blueprint, request

import db
import errors
import lookups
import validators as V
from middleware import authenticate, authorize, get_json_body
from response import object_response, array_response
from serialize import public, public_list

bp = Blueprint("lots", __name__)


@bp.route("/lots", methods=["POST"])
def create_lot():
    _, role = authenticate()
    authorize(role, ["MachineOperator", "PlantAdmin"])
    body = get_json_body()

    product_id = V.as_string(V.require(body, "product_id"), "product_id")
    lot_code = V.as_string(V.require(body, "lot_code"), "lot_code")
    received_qty = V.as_number(V.require(body, "received_qty"), "received_qty")

    with db.LOCK:
        lookups.product(product_id)
        if received_qty <= 0:
            raise errors.invalid_request("received_qty must be > 0.")
        for l in db.lots.values():
            if l["lot_code"] == lot_code:
                raise errors.invalid_request("lot_code must be unique.")
        rec = db.new_record()
        rec.update({
            "product_id": product_id,
            "lot_code": lot_code,
            "received_qty": received_qty,
            "on_hand_qty": received_qty,
            "issued_qty": 0,
        })
        db.lots[rec["id"]] = rec
        return object_response(public(rec), 201)


@bp.route("/lots/<rid>", methods=["GET"])
def get_lot(rid):
    _, role = authenticate()
    authorize(role, ["ManufacturingEngineer", "ProductionPlanner", "MachineOperator",
                     "QualityInspector", "PlantAdmin"])
    return object_response(public(lookups.lot(rid)))


@bp.route("/lots", methods=["GET"])
def list_lots():
    _, role = authenticate()
    authorize(role, ["ManufacturingEngineer", "ProductionPlanner", "MachineOperator",
                     "QualityInspector", "PlantAdmin"])
    limit, offset = V.parse_pagination(request.args)
    product_id = request.args.get("product_id")
    rows = list(db.lots.values())
    if product_id is not None:
        rows = [r for r in rows if r["product_id"] == product_id]
    page, total = V.paginate(rows, limit, offset)
    return array_response(public_list(page), limit, offset, total)
