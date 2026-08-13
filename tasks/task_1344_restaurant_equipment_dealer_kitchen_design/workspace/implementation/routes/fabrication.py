"""FabricationOrder endpoints (PRD 3.4). Orders are spawned by quote
acceptance; the shop drawing ref is supplied through the approval flow."""

from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_FAB_NOT_APPROVED,
    ERR_FAB_NOT_IN_PRODUCTION,
    ERR_FAB_NOT_PENDING_DRAWING,
    ERR_PROJECT_NOT_READY_FOR_FABRICATION,
    ERR_SHOP_DRAWING_MISSING,
    HTTP_STATUS,
)
from middleware import require_roles
from response import success_object
from routes.common import paginate, resolve_fab, resolve_project, serialize
from services import workflow
from services.validate import json_body, opt_int, opt_str

bp = Blueprint("fabrication", __name__)

FAB_READ_ROLES = ("PlatformAdmin", "ProjectManager", "FabricationLead")


@bp.route("/design-build-projects/<id>/fabrication-orders", methods=["GET"])
@require_roles(*FAB_READ_ROLES)
def list_fab_orders(id, _user_id=None, _role=None):
    project = resolve_project(id)
    status = request.args.get("status")
    item_id = request.args.get("equipment_item_id")
    records = [f for f in db.fab_orders.values() if f["project_id"] == project["id"]]
    if status is not None:
        records = [f for f in records if f["status"] == status]
    if item_id is not None:
        records = [f for f in records if f["equipment_item_id"] == item_id]
    return paginate(records)


@bp.route("/design-build-projects/<id>/fabrication-orders/<fabId>", methods=["GET"])
@require_roles(*FAB_READ_ROLES)
def get_fab_order(id, fabId, _user_id=None, _role=None):
    project = resolve_project(id)
    fab = resolve_fab(project, fabId)
    return success_object(serialize(fab), 200)


@bp.route("/design-build-projects/<id>/fabrication-orders/<fabId>/approve-shop-drawing", methods=["POST"])
@require_roles("ProjectManager")
def approve_shop_drawing(id, fabId, _user_id=None, _role=None):
    project = resolve_project(id)
    fab = resolve_fab(project, fabId)
    if fab["status"] != "PENDING_SHOP_DRAWING":
        raise ApiError(
            ERR_FAB_NOT_PENDING_DRAWING, HTTP_STATUS[ERR_FAB_NOT_PENDING_DRAWING],
            "Approve-shop-drawing requires PENDING_SHOP_DRAWING",
        )
    # shop_drawing_ref is supplied through the approval flow (PRD 3.4).
    body = json_body(required=False)
    ref = opt_str(body, "shop_drawing_ref")
    if ref is not None:
        fab["shop_drawing_ref"] = ref
    quoted = opt_int(body, "quoted_fab_cost_cents", min_value=0)
    if quoted is not None:
        fab["quoted_fab_cost_cents"] = quoted
    if not fab.get("shop_drawing_ref"):
        raise ApiError(
            ERR_SHOP_DRAWING_MISSING, HTTP_STATUS[ERR_SHOP_DRAWING_MISSING],
            "shop_drawing_ref is empty at approve-shop-drawing",
        )
    fab["status"] = "SHOP_DRAWING_APPROVED"
    fab["_approved_dt"] = db.now_dt()
    db.touch(fab)
    return success_object(serialize(fab), 200)


@bp.route("/design-build-projects/<id>/fabrication-orders/<fabId>/start-production", methods=["POST"])
@require_roles("FabricationLead")
def start_production(id, fabId, _user_id=None, _role=None):
    project = resolve_project(id)
    fab = resolve_fab(project, fabId)
    if fab["status"] != "SHOP_DRAWING_APPROVED":
        raise ApiError(
            ERR_FAB_NOT_APPROVED, HTTP_STATUS[ERR_FAB_NOT_APPROVED],
            "Start-production requires SHOP_DRAWING_APPROVED",
        )
    if project["status"] not in ("CONTRACTED", "FABRICATION"):
        raise ApiError(
            ERR_PROJECT_NOT_READY_FOR_FABRICATION,
            HTTP_STATUS[ERR_PROJECT_NOT_READY_FOR_FABRICATION],
            "Start-production requires Project in CONTRACTED or FABRICATION",
        )
    fab["status"] = "IN_PRODUCTION"
    db.touch(fab)
    # First order entering production cascades the project upward.
    if project["status"] == "CONTRACTED":
        project["status"] = "FABRICATION"
        db.touch(project)
    return success_object(serialize(fab), 200)


@bp.route("/design-build-projects/<id>/fabrication-orders/<fabId>/complete", methods=["POST"])
@require_roles("FabricationLead")
def complete_fab(id, fabId, _user_id=None, _role=None):
    project = resolve_project(id)
    fab = resolve_fab(project, fabId)
    if fab["status"] != "IN_PRODUCTION":
        raise ApiError(
            ERR_FAB_NOT_IN_PRODUCTION, HTTP_STATUS[ERR_FAB_NOT_IN_PRODUCTION],
            "Complete requires IN_PRODUCTION",
        )
    item = db.items.get(fab["equipment_item_id"])
    fab["final_fab_cost_cents"] = workflow.reconcile_fab_cost(fab, item or {})
    fab["status"] = "FAB_COMPLETE"
    db.touch(fab)
    # Completing fabrication moves the linked item ORDERED -> RECEIVED.
    if item is not None and item["status"] == "ORDERED":
        item["status"] = "RECEIVED"
        db.touch(item)
    return success_object(serialize(fab), 200)
