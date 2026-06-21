"""Genealogy-link read endpoints (PRD §3.8).

GenealogyLink rows are server-produced (consumed_qty is source:system) and have
no scaffold-declared creation endpoint; they are populated by the
complete-cascade when a build seals genealogy. These endpoints expose whatever
links exist for reverse-reachability over parent_lot_id / child_lot_id / work_order_id.
"""
from flask import Blueprint, request

import db
import lookups
import validators as V
from middleware import authenticate, authorize
from response import object_response, array_response
from serialize import public, public_list

bp = Blueprint("genealogy_links", __name__)


@bp.route("/genealogy-links/<rid>", methods=["GET"])
def get_genealogy_link(rid):
    _, role = authenticate()
    authorize(role, ["ManufacturingEngineer", "ProductionPlanner", "QualityInspector", "PlantAdmin"])
    return object_response(public(lookups.genealogy_link(rid)))


@bp.route("/genealogy-links", methods=["GET"])
def list_genealogy_links():
    _, role = authenticate()
    authorize(role, ["ManufacturingEngineer", "ProductionPlanner", "QualityInspector", "PlantAdmin"])
    limit, offset = V.parse_pagination(request.args)
    parent_lot_id = request.args.get("parent_lot_id")
    child_lot_id = request.args.get("child_lot_id")
    work_order_id = request.args.get("work_order_id")
    rows = list(db.genealogy_links.values())
    if parent_lot_id is not None:
        rows = [r for r in rows if r["parent_lot_id"] == parent_lot_id]
    if child_lot_id is not None:
        rows = [r for r in rows if r["child_lot_id"] == child_lot_id]
    if work_order_id is not None:
        rows = [r for r in rows if r["work_order_id"] == work_order_id]
    page, total = V.paginate(rows, limit, offset)
    return array_response(public_list(page), limit, offset, total)
