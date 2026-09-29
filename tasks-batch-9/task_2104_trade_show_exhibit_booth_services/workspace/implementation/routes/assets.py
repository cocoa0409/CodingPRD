"""Exhibit assets: registration and the storage / staging / retirement lifecycle."""
from flask import Blueprint

import db
import guards
import response
from errors import ApiError
from middleware import ANY_ROLE, own_exhibitor, own_warehouse, require_roles
from services import calc
from validation import json_body, require_row

bp = Blueprint("assets", __name__)
store = db.store

ASSET_STATUSES = ("IN_DESIGN", "FABRICATED", "IN_STORAGE", "STAGED", "ON_SHOW_FLOOR",
                  "IN_REFURB", "RETIRED", "WRITTEN_OFF")
TERMINAL = ("RETIRED", "WRITTEN_OFF")
EDGES = {
    "FABRICATED": ("IN_DESIGN",),
    "IN_STORAGE": ("FABRICATED", "ON_SHOW_FLOOR", "IN_REFURB"),
    "STAGED": ("IN_STORAGE",),
    "ON_SHOW_FLOOR": ("STAGED",),
    "RETIRED": ("IN_STORAGE", "FABRICATED"),
}


@bp.post("/exhibit-assets")
def create_asset():
    require_roles("Exhibitor", "ShowOperations")
    body = json_body()
    own_exhibitor(body.peek_str("exhibitor_id"))
    exhibitor_id = body.string("exhibitor_id")
    acquisition_mode = body.enum("acquisition_mode", ("RENTAL", "PURCHASE"))
    list_value = body.integer("list_value_cents")
    weight = body.integer("shipping_weight_lbs")
    grade = body.enum("condition_grade", calc.CONDITION_GRADES, required=False,
                      default="A")
    derived_from = body.string("derived_from_asset_id", required=False, default=None)

    require_row(store.exhibitors, exhibitor_id, "ERR_EXHIBITOR_NOT_FOUND", "Exhibitor")
    if derived_from is not None:
        require_row(store.assets, derived_from, "ERR_ASSET_NOT_FOUND", "Exhibit asset")

    asset = _new_asset(exhibitor_id, acquisition_mode, list_value, weight, grade,
                       derived_from)
    return response.created(asset)


def _new_asset(exhibitor_id, acquisition_mode, list_value, weight, grade, derived_from):
    asset = {
        "id": db.new_id(),
        "exhibitor_id": exhibitor_id,
        "current_warehouse_id": None,
        "derived_from_asset_id": derived_from,
        "acquisition_mode": acquisition_mode,
        "list_value_cents": list_value,
        "shipping_weight_lbs": weight,
        "condition_grade": grade,
        "refurb_cycles_count": 0,
        "stored_since": None,
        "status": "IN_DESIGN",
    }
    db.stamp_common(asset)
    store.assets[asset["id"]] = asset
    return asset


@bp.get("/exhibit-assets/<asset_id>")
def get_asset(asset_id):
    require_roles(ANY_ROLE)
    asset = store.assets.get(asset_id)
    own_exhibitor(asset["exhibitor_id"] if asset else None)
    asset = require_row(store.assets, asset_id, "ERR_ASSET_NOT_FOUND", "Exhibit asset")
    return response.ok(asset)


@bp.get("/exhibit-assets")
def list_assets():
    require_roles(ANY_ROLE)
    rows = list(store.assets.values())
    rows = response.filter_rows(rows, "exhibitor_id", "current_warehouse_id",
                                "derived_from_asset_id", "status")
    return response.listing(rows)


@bp.post("/exhibit-assets/<asset_id>/lifecycle")
def lifecycle(asset_id):
    require_roles("ShowOperations", "WarehouseAgent")
    body = json_body()
    own_warehouse(body.peek_str("warehouse_id"))
    to_status = body.enum("to_status", ASSET_STATUSES)
    warehouse_id = body.string("warehouse_id", required=False, default=None)
    if to_status == "IN_STORAGE" and warehouse_id is None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "warehouse_id is required when entering IN_STORAGE")

    asset = require_row(store.assets, asset_id, "ERR_ASSET_NOT_FOUND", "Exhibit asset")
    warehouse = None
    if warehouse_id is not None:
        warehouse = require_row(store.warehouses, warehouse_id, "ERR_WAREHOUSE_NOT_FOUND",
                                "Warehouse")

    guards.transition(asset["status"], TERMINAL, EDGES.get(to_status, ()))

    if to_status == "IN_STORAGE":
        if warehouse["status"] != "ACCEPTING":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "The warehouse is not ACCEPTING")
        asset["current_warehouse_id"] = warehouse_id
        asset["stored_since"] = db.now_stamp()
    elif to_status == "STAGED":
        for work_order in store.refurbs.values():
            if work_order["asset_id"] == asset_id and \
                    work_order["status"] in ("OPEN", "IN_PROGRESS"):
                raise ApiError("ERR_INVALID_STATE_TRANSITION",
                               "A refurbishment work order is still live on this asset")
        asset["stored_since"] = None
    elif to_status == "ON_SHOW_FLOOR":
        asset["current_warehouse_id"] = None
    elif to_status == "RETIRED":
        for claim in store.claims.values():
            if claim["asset_id"] == asset_id and \
                    claim["status"] in ("FILED", "UNDER_INVESTIGATION", "APPROVED"):
                raise ApiError("ERR_INVALID_STATE_TRANSITION",
                               "A damage claim is still live against this asset")
        asset["current_warehouse_id"] = None

    asset["status"] = to_status
    db.touch(asset)
    return response.ok(asset)
