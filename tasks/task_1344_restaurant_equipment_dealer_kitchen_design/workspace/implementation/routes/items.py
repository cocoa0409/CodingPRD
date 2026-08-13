"""EquipmentItem endpoints (PRD 3.2): create on a layout, nested and
project-wide list/get."""

from __future__ import annotations

from flask import Blueprint, request

import db
from middleware import require_roles
from response import success_object
from routes.common import (
    check_project_ownership,
    paginate,
    resolve_item,
    resolve_layout,
    resolve_project,
    serialize,
)
from services.validate import json_body, opt_bool, req_enum, req_int, req_str

bp = Blueprint("items", __name__)

ITEM_KINDS = ("STOCK", "CUSTOM_FABRICATION")
ITEM_READ_ROLES = (
    "PlatformAdmin", "ProjectManager", "SalesRep", "KitchenDesigner",
    "Customer", "FabricationLead", "StartupTechnician",
)


@bp.route("/design-build-projects/<id>/layouts/<layoutId>/equipment-items", methods=["POST"])
@require_roles("KitchenDesigner", "SalesRep")
def create_item(id, layoutId, _user_id=None, _role=None):
    project = resolve_project(id)
    layout = resolve_layout(project, layoutId)
    body = json_body(required=True)
    item = db.stamp_new({
        "layout_id": layout["id"],
        "project_id": project["id"],
        "model_no": req_str(body, "model_no"),
        "item_kind": req_enum(body, "item_kind", ITEM_KINDS),
        "quantity": req_int(body, "quantity", min_value=1),
        "unit_price_cents": req_int(body, "unit_price_cents", min_value=0),
        "lead_time_days": req_int(body, "lead_time_days", min_value=0),
        "requires_hood": opt_bool(body, "requires_hood", default=False),
        "warranty_status": "UNREGISTERED",
        "status": "SCHEDULED",
    })
    db.items[item["id"]] = item
    return success_object(serialize(item), 201)


@bp.route("/design-build-projects/<id>/layouts/<layoutId>/equipment-items", methods=["GET"])
@require_roles(*ITEM_READ_ROLES)
def list_items_on_layout(id, layoutId, _user_id=None, _role=None):
    project = resolve_project(id)
    layout = resolve_layout(project, layoutId)
    check_project_ownership(_user_id, _role, project)
    status = request.args.get("status")
    item_kind = request.args.get("item_kind")
    records = [it for it in db.items.values() if it["layout_id"] == layout["id"]]
    if status is not None:
        records = [it for it in records if it["status"] == status]
    if item_kind is not None:
        records = [it for it in records if it["item_kind"] == item_kind]
    return paginate(records)


@bp.route("/design-build-projects/<id>/equipment-items", methods=["GET"])
@require_roles(*ITEM_READ_ROLES)
def list_items_on_project(id, _user_id=None, _role=None):
    project = resolve_project(id)
    check_project_ownership(_user_id, _role, project)
    layout_id = request.args.get("layout_id")
    status = request.args.get("status")
    records = [it for it in db.items.values() if it["project_id"] == project["id"]]
    if layout_id is not None:
        records = [it for it in records if it["layout_id"] == layout_id]
    if status is not None:
        records = [it for it in records if it["status"] == status]
    return paginate(records)


@bp.route("/design-build-projects/<id>/equipment-items/<itemId>", methods=["GET"])
@require_roles(*ITEM_READ_ROLES)
def get_item(id, itemId, _user_id=None, _role=None):
    project = resolve_project(id)
    item = resolve_item(project, itemId)
    check_project_ownership(_user_id, _role, project)
    return success_object(serialize(item), 200)
