"""Lot-issue endpoints (PRD §3.8)."""
from flask import Blueprint, request

import db
import errors
import lookups
import validators as V
from middleware import authenticate, authorize, get_json_body
from response import object_response, array_response
from serialize import public, public_list

bp = Blueprint("lot_issues", __name__)


@bp.route("/lot-issues", methods=["POST"])
def create_lot_issue():
    _, role = authenticate()
    authorize(role, ["MachineOperator", "PlantAdmin"])
    body = get_json_body()

    component_demand_id = V.as_string(V.require(body, "component_demand_id"), "component_demand_id")
    lot_id = V.as_string(V.require(body, "lot_id"), "lot_id")
    wop_id = V.as_string(V.require(body, "work_order_operation_id"), "work_order_operation_id")
    issued_qty = V.as_number(V.require(body, "issued_qty"), "issued_qty")

    with db.LOCK:
        # Existence (priority 3), left-to-right.
        demand = lookups.component_demand(component_demand_id)
        lot = lookups.lot(lot_id)
        lookups.work_order_operation(wop_id)

        if issued_qty <= 0:
            raise errors.invalid_request("issued_qty must be > 0.")

        # PRD §3.8 order: product mismatch FIRST, then insufficient qty.
        # ERR_LOT_PRODUCT_MISMATCH (422): lot.product_id == demand.component_product_id.
        if lot["product_id"] != demand["component_product_id"]:
            raise errors.ApiError(errors.ERR_LOT_PRODUCT_MISMATCH,
                                  "Lot product does not match demand component.", 422)

        # ERR_INSUFFICIENT_LOT_QTY (422): issued_qty <= lot.on_hand_qty.
        if issued_qty > lot["on_hand_qty"]:
            raise errors.ApiError(errors.ERR_INSUFFICIENT_LOT_QTY,
                                  "Issued quantity exceeds lot on-hand.", 422)

        rec = db.new_record()
        rec.update({
            "component_demand_id": component_demand_id,
            "lot_id": lot_id,
            "work_order_operation_id": wop_id,
            "issued_qty": issued_qty,
            "reversed": False,
        })
        db.lot_issues[rec["id"]] = rec

        # side effects: decrement lot on_hand, increment lot issued + demand issued.
        lot["on_hand_qty"] = lot["on_hand_qty"] - issued_qty
        lot["issued_qty"] = lot["issued_qty"] + issued_qty
        db.touch(lot)
        demand["issued_qty"] = demand["issued_qty"] + issued_qty
        db.touch(demand)

        return object_response(public(rec), 201)


@bp.route("/lot-issues/<rid>", methods=["GET"])
def get_lot_issue(rid):
    _, role = authenticate()
    authorize(role, ["ManufacturingEngineer", "ProductionPlanner", "MachineOperator",
                     "QualityInspector", "PlantAdmin"])
    return object_response(public(lookups.lot_issue(rid)))


@bp.route("/lot-issues", methods=["GET"])
def list_lot_issues():
    _, role = authenticate()
    authorize(role, ["ManufacturingEngineer", "ProductionPlanner", "MachineOperator",
                     "QualityInspector", "PlantAdmin"])
    limit, offset = V.parse_pagination(request.args)
    component_demand_id = request.args.get("component_demand_id")
    lot_id = request.args.get("lot_id")
    wop_id = request.args.get("work_order_operation_id")
    rows = list(db.lot_issues.values())
    if component_demand_id is not None:
        rows = [r for r in rows if r["component_demand_id"] == component_demand_id]
    if lot_id is not None:
        rows = [r for r in rows if r["lot_id"] == lot_id]
    if wop_id is not None:
        rows = [r for r in rows if r["work_order_operation_id"] == wop_id]
    page, total = V.paginate(rows, limit, offset)
    return array_response(public_list(page), limit, offset, total)
