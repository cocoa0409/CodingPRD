from flask import Blueprint

from auth import authenticate, require_role
from db import store
from envelope import success_object, success_list
from errors import raise_err, ERR_MATERIAL_LOT_NOT_FOUND, \
    ERR_DUPLICATE_CODE, ERR_INVALID_STATE, ERR_ALREADY_TERMINAL, \
    ERR_INVALID_REQUEST
from services import stamp_new, touch, ser_material_lot, sorted_rows
from util import new_id
from validate import get_body, check_fields, pagination_params, query_filter

bp = Blueprint("material_lots", __name__)

READ_ROLES = ["PlantAdmin", "ProcessEngineer", "QualityTechnician",
              "ProductionScheduler"]
LOT_STATUSES = {"QUARANTINED", "RELEASED", "IN_USE", "DEPLETED", "REJECTED"}
RESINS = {"PET", "HDPE", "PP"}
TERMINAL = ("REJECTED", "DEPLETED")


def get_lot_or_404(lot_id):
    lot = store.material_lots.get(lot_id)
    if lot is None:
        raise_err(ERR_MATERIAL_LOT_NOT_FOUND,
                  "MaterialLot id does not resolve")
    return lot


@bp.post("/material-lots")
def create_lot():
    _, role = authenticate()
    require_role(role, ["PlantAdmin"])
    body = check_fields(get_body(), {
        "material_type": ("enum", True, {"RESIN", "COLORANT"}),
        "resin_type": ("enum", False, RESINS),
        "color_code": ("str", False),
        "lot_code": ("str", True),
        "received_kg": ("number", True),
    })
    # conditional shape: resin lots name resin_type and carry no color_code;
    # colorant lots name color_code and carry no resin_type
    if body["material_type"] == "RESIN":
        if "resin_type" not in body:
            raise_err(ERR_INVALID_REQUEST,
                      "resin_type is required when material_type is RESIN")
        if "color_code" in body:
            raise_err(ERR_INVALID_REQUEST,
                      "color_code must be null for RESIN lots")
    else:
        if "color_code" not in body:
            raise_err(ERR_INVALID_REQUEST,
                      "color_code is required when material_type is COLORANT")
        if "resin_type" in body:
            raise_err(ERR_INVALID_REQUEST,
                      "resin_type must be null for COLORANT lots")
    for l in store.material_lots.values():
        if l["lot_code"] == body["lot_code"]:
            raise_err(ERR_DUPLICATE_CODE, "lot_code must be unique")
    lot = {
        "material_type": body["material_type"],
        "resin_type": body.get("resin_type"),
        "color_code": body.get("color_code"),
        "lot_code": body["lot_code"],
        "received_kg": body["received_kg"],
        "consumed_kg": body["received_kg"] * 0,
        "purge_wasted_kg": body["received_kg"] * 0,
        "status": "QUARANTINED",
    }
    stamp_new(lot, new_id())
    store.material_lots[lot["id"]] = lot
    return success_object(ser_material_lot(lot), 201)


@bp.get("/material-lots")
def list_lots():
    _, role = authenticate()
    require_role(role, READ_ROLES)
    material_type = query_filter("material_type", {"RESIN", "COLORANT"})
    resin_type = query_filter("resin_type", RESINS)
    status = query_filter("status", LOT_STATUSES)
    limit, offset = pagination_params()
    rows = list(store.material_lots.values())
    if material_type is not None:
        rows = [l for l in rows if l["material_type"] == material_type]
    if resin_type is not None:
        rows = [l for l in rows if l["resin_type"] == resin_type]
    if status is not None:
        rows = [l for l in rows if l["status"] == status]
    rows = sorted_rows(rows)
    page = rows[offset:offset + limit]
    return success_list([ser_material_lot(l) for l in page], limit, offset,
                        len(rows))


@bp.get("/material-lots/<lid>")
def get_lot(lid):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    return success_object(ser_material_lot(get_lot_or_404(lid)))


@bp.post("/material-lots/<lid>/release")
def release_lot(lid):
    _, role = authenticate()
    require_role(role, ["QualityTechnician"])
    check_fields(get_body(), {})
    lot = get_lot_or_404(lid)
    if lot["status"] in TERMINAL:
        raise_err(ERR_ALREADY_TERMINAL, "Lot is in a terminal state")
    if lot["status"] != "QUARANTINED":
        raise_err(ERR_INVALID_STATE, "Only a QUARANTINED lot can be released")
    lot["status"] = "RELEASED"
    touch(lot)
    return success_object(ser_material_lot(lot))


@bp.post("/material-lots/<lid>/hold")
def hold_lot(lid):
    _, role = authenticate()
    require_role(role, ["QualityTechnician"])
    check_fields(get_body(), {})
    lot = get_lot_or_404(lid)
    if lot["status"] in TERMINAL:
        raise_err(ERR_ALREADY_TERMINAL, "Lot is in a terminal state")
    if lot["status"] not in ("RELEASED", "IN_USE"):
        raise_err(ERR_INVALID_STATE,
                  "Only a RELEASED or IN_USE lot can be held")
    lot["status"] = "QUARANTINED"
    touch(lot)
    return success_object(ser_material_lot(lot))


@bp.post("/material-lots/<lid>/reject")
def reject_lot(lid):
    _, role = authenticate()
    require_role(role, ["QualityTechnician"])
    check_fields(get_body(), {})
    lot = get_lot_or_404(lid)
    if lot["status"] in TERMINAL:
        raise_err(ERR_ALREADY_TERMINAL, "Lot is in a terminal state")
    if lot["status"] != "QUARANTINED":
        raise_err(ERR_INVALID_STATE, "Only a QUARANTINED lot can be rejected")
    lot["status"] = "REJECTED"
    touch(lot)
    return success_object(ser_material_lot(lot))
