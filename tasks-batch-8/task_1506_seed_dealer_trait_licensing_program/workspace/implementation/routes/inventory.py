"""InventoryLot endpoints."""

import db
from errors import ApiError, ERR_INVALID_STATE_TRANSITION, ERR_LOT_HAS_RESERVATIONS
from middleware import authenticate
from response import success_obj, success_list
from routes import make_blueprint
from util import body_json, check_shape, pagination_params, paginate, apply_filters, require_fk, exist_body_fks

bp = make_blueprint("inventory")

READ_ROLES = ["DealerAdmin", "SalesRep"]


@bp.post("/inventory-lots")
def create_lot():
    authenticate(["DealerAdmin"])
    body = body_json()
    fks = {"variety_id": ("varieties", "variety")}
    if body.get("treatment_option_id") is not None:
        fks["treatment_option_id"] = ("treatment_options", "treatment option")
    exist_body_fks(body, fks)
    check_shape(body, {
        "variety_id": {"type": "string", "required": True},
        "treatment_option_id": {"type": "string"},
        "warehouse_code": {"type": "string", "required": True},
        "received_units": {"type": "integer", "required": True, "min": 1},
        "expiry_date": {"type": "datetime", "required": True},
    })
    lot = db.new_entity("inventory_lots", {
        "variety_id": body["variety_id"],
        "treatment_option_id": body.get("treatment_option_id"),
        "warehouse_code": body["warehouse_code"],
        "received_units": body["received_units"],
        "expiry_date": body["expiry_date"],
        "on_hand_units": body["received_units"],
        "reserved_units": 0,
        "delivered_units": 0,
        "returned_units": 0,
        "written_off_units": 0,
        "status": "AVAILABLE",
    })
    return success_obj(db.public(lot), 201)


@bp.get("/inventory-lots/<lid>")
def get_lot(lid):
    authenticate(READ_ROLES)
    return success_obj(db.public(require_fk("inventory_lots", lid, "inventory lot")), 200)


@bp.get("/inventory-lots")
def list_lots():
    authenticate(READ_ROLES)
    limit, offset = pagination_params()
    items = apply_filters(db.all_of("inventory_lots"), ["variety_id", "treatment_option_id", "status"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([db.public(l) for l in page], limit, offset, total, has_more)


@bp.post("/inventory-lots/<lid>/quarantine")
def quarantine_lot(lid):
    authenticate(["DealerAdmin"])
    lot = require_fk("inventory_lots", lid, "inventory lot")
    if lot["status"] != "AVAILABLE":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "only an AVAILABLE lot can be quarantined")
    if lot["reserved_units"] != 0:
        raise ApiError(ERR_LOT_HAS_RESERVATIONS, 409, "lot has open reservations")
    lot["status"] = "QUARANTINED"
    db.touch(lot)
    return success_obj(db.public(lot), 200)


@bp.post("/inventory-lots/<lid>/release_quarantine")
def release_lot_quarantine(lid):
    authenticate(["DealerAdmin"])
    lot = require_fk("inventory_lots", lid, "inventory lot")
    if lot["status"] != "QUARANTINED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "only a QUARANTINED lot can be released")
    lot["status"] = "AVAILABLE"
    db.touch(lot)
    return success_obj(db.public(lot), 200)
