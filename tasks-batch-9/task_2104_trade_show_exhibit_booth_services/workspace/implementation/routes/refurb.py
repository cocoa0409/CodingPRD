"""Refurbishment work orders against stored property (PRD §3.4)."""
from flask import Blueprint

import db
import guards
import response
from errors import ApiError
from middleware import ANY_ROLE, own_warehouse, require_roles
from services import calc
from validation import json_body, require_row

bp = Blueprint("refurb", __name__)
store = db.store

SCOPES = ("GRAPHICS_REFRESH", "STRUCTURAL_REPAIR", "FULL_REBUILD")
TERMINAL = ("COMPLETED", "CANCELLED")


@bp.post("/refurb-work-orders")
def create_work_order():
    require_roles("WarehouseAgent", "ShowOperations")
    body = json_body()
    own_warehouse(body.peek_str("warehouse_id"))
    asset_id = body.string("asset_id")
    warehouse_id = body.string("warehouse_id")
    scope = body.enum("scope", SCOPES)
    estimate = body.integer("estimate_cents")

    require_row(store.assets, asset_id, "ERR_ASSET_NOT_FOUND", "Exhibit asset")
    require_row(store.warehouses, warehouse_id, "ERR_WAREHOUSE_NOT_FOUND", "Warehouse")

    work_order = {
        "id": db.new_id(),
        "asset_id": asset_id,
        "warehouse_id": warehouse_id,
        "scope": scope,
        "estimate_cents": estimate,
        "actual_cents": None,
        "variance_cents": None,
        "condition_grade_after": None,
        "status": "OPEN",
    }
    db.stamp_common(work_order)
    store.refurbs[work_order["id"]] = work_order
    return response.created(work_order)


@bp.get("/refurb-work-orders/<work_order_id>")
def get_work_order(work_order_id):
    require_roles(ANY_ROLE)
    work_order = require_row(store.refurbs, work_order_id, "ERR_REFURB_NOT_FOUND",
                             "Refurbishment work order")
    return response.ok(work_order)


@bp.get("/refurb-work-orders")
def list_work_orders():
    require_roles(ANY_ROLE)
    rows = list(store.refurbs.values())
    rows = response.filter_rows(rows, "asset_id", "warehouse_id", "status")
    return response.listing(rows)


@bp.post("/refurb-work-orders/<work_order_id>/progress")
def progress(work_order_id):
    require_roles("WarehouseAgent")
    body = json_body()
    work_order = store.refurbs.get(work_order_id)
    if work_order is not None:
        own_warehouse(work_order.get("warehouse_id"))

    to_status = body.enum("to_status", ("IN_PROGRESS", "COMPLETED", "CANCELLED"))
    actual_cents = body.integer("actual_cents", required=False, default=None)
    grade_after = body.enum("condition_grade_after", calc.CONDITION_GRADES,
                            required=False, default=None)
    if to_status == "COMPLETED" and actual_cents is None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "actual_cents is required when completing the work")

    work_order = require_row(store.refurbs, work_order_id, "ERR_REFURB_NOT_FOUND",
                             "Refurbishment work order")
    asset = store.assets.get(work_order["asset_id"])

    edges = {
        "IN_PROGRESS": ("OPEN",),
        "COMPLETED": ("IN_PROGRESS",),
        "CANCELLED": ("OPEN", "IN_PROGRESS"),
    }
    guards.transition(work_order["status"], TERMINAL, edges.get(to_status, ()))

    if to_status == "IN_PROGRESS":
        if asset is None or asset["status"] != "IN_STORAGE" or \
                asset.get("current_warehouse_id") != work_order["warehouse_id"]:
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "The shop must hold the asset in storage before work starts")
        asset["status"] = "IN_REFURB"
        db.touch(asset)
        work_order["status"] = "IN_PROGRESS"
        db.touch(work_order)
        return response.ok(work_order)

    if to_status == "COMPLETED":
        tolerance = calc.round_half_up(
            calc.dec(work_order["estimate_cents"]) * calc.REFURB_OVERRUN_TOLERANCE)
        if actual_cents > tolerance and \
                not _overrun_covered(work_order, actual_cents - tolerance):
            raise ApiError("ERR_REFURB_OVERRUN_UNAPPROVED",
                           "The cost overrun exceeds tolerance and is not covered")
        current_grade = asset["condition_grade"] if asset else "A"
        resolved_grade = grade_after or current_grade
        if calc.CONDITION_GRADES.index(resolved_grade) > \
                calc.CONDITION_GRADES.index(current_grade):
            raise ApiError("ERR_CONDITION_GRADE_REGRESSION",
                           "condition_grade_after may not be worse than the current grade")

        work_order["actual_cents"] = actual_cents
        work_order["variance_cents"] = actual_cents - int(work_order["estimate_cents"])
        work_order["condition_grade_after"] = resolved_grade
        work_order["status"] = "COMPLETED"
        db.touch(work_order)
        if asset is not None and asset["status"] == "IN_REFURB":
            asset["status"] = "IN_STORAGE"
            asset["refurb_cycles_count"] = int(asset["refurb_cycles_count"]) + 1
            asset["condition_grade"] = resolved_grade
            asset["stored_since"] = db.now_stamp()
            db.touch(asset)
        return response.ok(work_order)

    # CANCELLED
    work_order["status"] = "CANCELLED"
    db.touch(work_order)
    if asset is not None and asset["status"] == "IN_REFURB":
        asset["status"] = "IN_STORAGE"
        db.touch(asset)
    return response.ok(work_order)


def _overrun_covered(work_order, overrun_cents):
    """An APPLIED change order raised against this very asset may cover an overrun."""
    for change_order in store.change_orders.values():
        if change_order["status"] != "APPLIED":
            continue
        if change_order["target_type"] != "EXHIBIT_DESIGN":
            continue
        design = store.designs.get(change_order["target_id"])
        if design is None or design.get("asset_id") != work_order["asset_id"]:
            continue
        delta = change_order.get("price_delta_cents") or 0
        if int(delta) >= int(overrun_cents):
            return True
    return False
