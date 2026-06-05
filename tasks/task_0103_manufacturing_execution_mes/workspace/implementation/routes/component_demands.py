"""Component-demand read endpoints (PRD §3.4)."""
from flask import Blueprint, request

import db
import lookups
import validators as V
from middleware import authenticate, authorize
from response import object_response, array_response
from serialize import public, public_list

bp = Blueprint("component_demands", __name__)


@bp.route("/component-demands/<rid>", methods=["GET"])
def get_component_demand(rid):
    _, role = authenticate()
    authorize(role, ["ManufacturingEngineer", "ProductionPlanner", "PlantAdmin"])
    return object_response(public(lookups.component_demand(rid)))


@bp.route("/component-demands", methods=["GET"])
def list_component_demands():
    _, role = authenticate()
    authorize(role, ["ManufacturingEngineer", "ProductionPlanner", "PlantAdmin"])
    limit, offset = V.parse_pagination(request.args)
    work_order_id = request.args.get("work_order_id")
    component_product_id = request.args.get("component_product_id")
    rows = list(db.component_demands.values())
    if work_order_id is not None:
        rows = [r for r in rows if r["work_order_id"] == work_order_id]
    if component_product_id is not None:
        rows = [r for r in rows if r["component_product_id"] == component_product_id]
    page, total = V.paginate(rows, limit, offset)
    return array_response(public_list(page), limit, offset, total)
