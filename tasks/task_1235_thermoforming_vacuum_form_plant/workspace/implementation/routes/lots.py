"""MaterialLot endpoints (PRD §3.1)."""

from decimal import Decimal
from flask import request

from db import STORE, new_record, bump
from errors import ApiError
from middleware import endpoint, ANY_ROLE
from response import ok_object, list_response
from serializers import ser_lot
from services import get_lot
from util import (
    GRADES,
    RESIN_TYPES,
    as_enum,
    as_positive_decimal,
    as_string,
    body_dict,
    req_present,
)

from routes import bp


@bp.route("/material-lots", methods=["POST"])
@endpoint({"MaterialsPlanner"})
def create_lot(user_id, role):
    body = body_dict(request.get_json(silent=True))
    lot_code = as_string(req_present(body, "lot_code"), "lot_code")
    resin_type = as_enum(req_present(body, "resin_type"), "resin_type", RESIN_TYPES)
    gauge_mm = as_positive_decimal(req_present(body, "gauge_mm"), "gauge_mm")
    grade_req = as_enum(
        req_present(body, "cleanliness_grade_required"), "cleanliness_grade_required", GRADES
    )
    quantity_kg = as_positive_decimal(req_present(body, "quantity_kg"), "quantity_kg")
    unit_cost = as_positive_decimal(req_present(body, "unit_cost_per_kg"), "unit_cost_per_kg")

    rec = new_record()
    rec.update({
        "lot_code": lot_code,
        "resin_type": resin_type,
        "gauge_mm": gauge_mm,
        "cleanliness_grade_required": grade_req,
        "quantity_kg": quantity_kg,
        "unit_cost_per_kg": unit_cost,
        "allocated_kg": Decimal("0"),
        "consumed_kg": Decimal("0"),
        "available_kg": quantity_kg,
        "status": "QUARANTINE",
    })
    STORE["material_lots"][rec["id"]] = rec
    return ok_object(ser_lot(rec), 201)


@bp.route("/material-lots", methods=["GET"])
@endpoint(ANY_ROLE)
def list_lots(user_id, role):
    items = list(STORE["material_lots"].values())
    status = request.args.get("status")
    if status is not None:
        items = [l for l in items if l["status"] == status]
    resin_type = request.args.get("resin_type")
    if resin_type is not None:
        items = [l for l in items if l["resin_type"] == resin_type]
    return list_response(items, ser_lot)


@bp.route("/material-lots/<lotId>", methods=["GET"])
@endpoint(ANY_ROLE)
def get_one_lot(user_id, role, lotId):
    return ok_object(ser_lot(get_lot(lotId)))


@bp.route("/material-lots/<lotId>/block", methods=["POST"])
@endpoint({"MaterialsPlanner"})
def block_lot(user_id, role, lotId):
    lot = get_lot(lotId)
    # p6 state: block requires CERTIFIED
    if lot["status"] != "CERTIFIED":
        raise ApiError("ERR_INVALID_LOT_STATE", "Lot block requires status CERTIFIED")
    lot["status"] = "BLOCKED"
    # Cascade: every allocation of this lot in RESERVED -> REVIEW
    for alloc in STORE["material_allocations"].values():
        if alloc["lot_id"] == lot["id"] and alloc["status"] == "RESERVED":
            alloc["status"] = "REVIEW"
            bump(alloc)
    bump(lot)
    return ok_object(ser_lot(lot))
