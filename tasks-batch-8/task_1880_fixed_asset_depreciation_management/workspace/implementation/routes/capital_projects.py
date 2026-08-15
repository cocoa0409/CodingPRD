"""CapitalProject and CIPCostLine endpoints."""
from flask import Blueprint, request
import db
import errors
from db import new_id, now_iso
from middleware import (require_roles, get_body, get_pagination,
                        require_string, require_int, require_enum, require_date)
from response import success_object, success_list
from services.serializers import (capital_project_view, cip_cost_line_view,
                                  fixed_asset_view)

bp = Blueprint("capital_projects", __name__)
ALL_ROLES = ("AssetAccountant", "Controller", "InventoryClerk", "TaxAnalyst")
COST_TYPES = {"MATERIAL", "LABOR", "VENDOR_INVOICE", "OTHER"}


def _project_total(project_id):
    total = 0
    for line in db.cip_cost_lines.values():
        if line["project_id"] == project_id and line["status"] == "POSTED":
            total += line["amount_cents"]
    return total


def _bump_project(project):
    project["total_accumulated_cents"] = _project_total(project["id"])
    project["version"] += 1
    project["updated_at"] = now_iso()


@bp.route("/capital-projects", methods=["POST"])
def create_project():
    user_id, _ = require_roles("AssetAccountant")
    data = get_body()
    project_code = require_string(data, "project_code")
    name = require_string(data, "name")
    asset_class_id = require_string(data, "asset_class_id")
    # existence of FK
    if asset_class_id not in db.asset_classes:
        raise errors.not_found("asset_class_id not found")
    # uniqueness
    for rec in db.capital_projects.values():
        if rec["project_code"] == project_code:
            raise errors.duplicate_tag("project_code already exists")
    ts = now_iso()
    rec = {
        "id": new_id(),
        "project_code": project_code,
        "name": name,
        "asset_class_id": asset_class_id,
        "created_by_user_id": user_id,
        "total_accumulated_cents": 0,
        "status": "OPEN",
        "capitalized_asset_id": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.capital_projects[rec["id"]] = rec
    return success_object(capital_project_view(rec), 201)


@bp.route("/capital-projects", methods=["GET"])
def list_projects():
    require_roles(*ALL_ROLES)
    limit, offset = get_pagination()
    f_class = request.args.get("asset_class_id")
    f_cap_asset = request.args.get("capitalized_asset_id")
    f_status = request.args.get("status")
    items = sorted(db.capital_projects.values(), key=lambda r: (r["created_at"], r["id"]))
    out = []
    for rec in items:
        if f_class is not None and rec["asset_class_id"] != f_class:
            continue
        if f_cap_asset is not None and rec.get("capitalized_asset_id") != f_cap_asset:
            continue
        if f_status is not None and rec["status"] != f_status:
            continue
        out.append(rec)
    total = len(out)
    page = out[offset:offset + limit]
    return success_list([capital_project_view(r) for r in page], limit, offset, total)


@bp.route("/capital-projects/<pid>", methods=["GET"])
def get_project(pid):
    require_roles(*ALL_ROLES)
    rec = db.capital_projects.get(pid)
    if rec is None:
        raise errors.not_found("Capital project not found")
    return success_object(capital_project_view(rec))


@bp.route("/capital-projects/<pid>/capitalize", methods=["POST"])
def capitalize_project(pid):
    user_id, _ = require_roles("Controller")
    data = get_body()
    rec = db.capital_projects.get(pid)
    if rec is None:
        raise errors.not_found("Capital project not found")
    # SoD (priority 2) evaluated before state per §2.10 ordering:
    # state is priority 4, SoD priority 2 — so SoD first.
    if user_id == rec["created_by_user_id"]:
        raise errors.segregation_of_duties("Capitalizer must differ from project creator")
    if rec["status"] != "OPEN":
        raise errors.project_not_open()
    asset_tag = require_string(data, "asset_tag")
    description = require_string(data, "description")
    # uniqueness of asset_tag (priority 6) before threshold (priority 8)
    for a in db.fixed_assets.values():
        if a["asset_tag"] == asset_tag:
            raise errors.duplicate_tag("asset_tag already exists")
    cls = db.asset_classes.get(rec["asset_class_id"])
    threshold = cls["capitalization_threshold_cents"] if cls else 0
    if rec["total_accumulated_cents"] < threshold:
        raise errors.below_capitalization_threshold()
    # Create the FixedAsset
    ts = now_iso()
    asset = {
        "id": new_id(),
        "asset_tag": asset_tag,
        "description": description,
        "asset_class_id": rec["asset_class_id"],
        "parent_asset_id": None,
        "source": "CIP_CAPITALIZATION",
        "acquisition_cost_cents": rec["total_accumulated_cents"],
        "salvage_value_cents": 0,
        "useful_life_months": cls["default_useful_life_months"] if cls else 0,
        "book_method": cls["book_method"] if cls else "STRAIGHT_LINE",
        "tax_method": cls["tax_method"] if cls else "TAX_STRAIGHT_LINE",
        "bonus_elected": False,
        "cost_center": "",
        "location": "",
        "in_service_date": None,
        "status": "DRAFT",
        "accumulated_book_cents": 0,
        "accumulated_tax_cents": 0,
        "impairment_total_cents": 0,
        "net_book_value_cents": rec["total_accumulated_cents"],
        "open_inventory_exception": False,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.fixed_assets[asset["id"]] = asset
    rec["status"] = "CAPITALIZED"
    rec["capitalized_asset_id"] = asset["id"]
    rec["version"] += 1
    rec["updated_at"] = now_iso()
    return success_object(capital_project_view(rec))


@bp.route("/capital-projects/<pid>/cancel", methods=["POST"])
def cancel_project(pid):
    require_roles("Controller")
    rec = db.capital_projects.get(pid)
    if rec is None:
        raise errors.not_found("Capital project not found")
    if rec["status"] != "OPEN":
        raise errors.project_not_open()
    rec["status"] = "CANCELLED"
    rec["version"] += 1
    rec["updated_at"] = now_iso()
    return success_object(capital_project_view(rec))


@bp.route("/cip-cost-lines", methods=["POST"])
def create_cost_line():
    require_roles("AssetAccountant")
    data = get_body()
    project_id = require_string(data, "project_id")
    amount = require_int(data, "amount_cents")
    cost_type = require_enum(data, "cost_type", COST_TYPES)
    incurred_date = require_date(data, "incurred_date")
    project = db.capital_projects.get(project_id)
    if project is None:
        raise errors.not_found("project_id not found")
    if project["status"] != "OPEN":
        raise errors.project_not_open()
    if amount <= 0:
        raise errors.invalid_amount("amount_cents must be > 0")
    ts = now_iso()
    rec = {
        "id": new_id(),
        "project_id": project_id,
        "amount_cents": amount,
        "cost_type": cost_type,
        "incurred_date": incurred_date,
        "status": "POSTED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.cip_cost_lines[rec["id"]] = rec
    _bump_project(project)
    return success_object(cip_cost_line_view(rec), 201)


@bp.route("/capital-projects/<pid>/cost-lines", methods=["GET"])
def list_project_cost_lines(pid):
    require_roles(*ALL_ROLES)
    project = db.capital_projects.get(pid)
    if project is None:
        raise errors.not_found("Capital project not found")
    limit, offset = get_pagination()
    items = sorted(
        (l for l in db.cip_cost_lines.values() if l["project_id"] == pid),
        key=lambda r: (r["created_at"], r["id"]),
    )
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([cip_cost_line_view(r) for r in page], limit, offset, total)


@bp.route("/cip-cost-lines/<lid>/reverse", methods=["POST"])
def reverse_cost_line(lid):
    require_roles("AssetAccountant")
    rec = db.cip_cost_lines.get(lid)
    if rec is None:
        raise errors.not_found("Cost line not found")
    project = db.capital_projects.get(rec["project_id"])
    if project is None:
        raise errors.not_found("Project not found")
    if rec["status"] != "POSTED":
        raise errors.invalid_state("Line is not POSTED")
    if project["status"] != "OPEN":
        raise errors.project_not_open()
    rec["status"] = "REVERSED"
    rec["version"] += 1
    rec["updated_at"] = now_iso()
    _bump_project(project)
    return success_object(cip_cost_line_view(rec))
