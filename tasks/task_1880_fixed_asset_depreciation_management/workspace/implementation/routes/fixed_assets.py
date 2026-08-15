"""FixedAsset endpoints."""
from flask import Blueprint, request
import db
import errors
from db import new_id, now_iso
from middleware import (require_roles, get_body, get_pagination,
                        require_string, optional_string, require_int,
                        optional_int, require_enum, optional_enum,
                        optional_bool, require_date)
from response import success_object, success_list
from services.serializers import fixed_asset_view, recompute_asset_derived
from services.inventory import refresh_asset_exceptions, recompute_line_status, recompute_run_counters

bp = Blueprint("fixed_assets", __name__)
ALL_ROLES = ("AssetAccountant", "Controller", "InventoryClerk", "TaxAnalyst")
BOOK_METHODS = {"STRAIGHT_LINE", "DOUBLE_DECLINING"}
TAX_METHODS = {"MACRS_5YR", "MACRS_7YR", "TAX_STRAIGHT_LINE"}

# Fields writable in DRAFT
DRAFT_EDITABLE = {"description", "acquisition_cost_cents", "salvage_value_cents",
                  "useful_life_months", "book_method", "tax_method", "bonus_elected",
                  "location", "cost_center"}
# Fields writable in IN_SERVICE (prospective)
INSERVICE_EDITABLE = {"useful_life_months", "salvage_value_cents", "location",
                      "cost_center", "description"}


def _check_unique_tag(asset_tag, exclude_id=None):
    for a in db.fixed_assets.values():
        if a["asset_tag"] == asset_tag and a["id"] != exclude_id:
            raise errors.duplicate_tag("asset_tag already exists")


@bp.route("/fixed-assets", methods=["POST"])
def create_fixed_asset():
    require_roles("AssetAccountant")
    data = get_body()
    asset_tag = require_string(data, "asset_tag")
    description = require_string(data, "description")
    asset_class_id = require_string(data, "asset_class_id")
    acquisition_cost = require_int(data, "acquisition_cost_cents")
    cost_center = require_string(data, "cost_center")
    location = require_string(data, "location")
    parent_asset_id = optional_string(data, "parent_asset_id")

    # existence
    cls = db.asset_classes.get(asset_class_id)
    if cls is None:
        raise errors.not_found("asset_class_id not found")
    parent = None
    if parent_asset_id is not None:
        parent = db.fixed_assets.get(parent_asset_id)
        if parent is None:
            raise errors.not_found("parent_asset_id not found")

    # state checks on parent (priority 4)
    if parent is not None:
        if parent["status"] == "DISPOSED":
            raise errors.already_disposed("Parent asset is DISPOSED")
        if parent["status"] != "IN_SERVICE":
            raise errors.invalid_state("Parent asset must be IN_SERVICE")

    # uniqueness (priority 6)
    _check_unique_tag(asset_tag)

    # field values (priority 8)
    if acquisition_cost <= 0:
        raise errors.invalid_amount("acquisition_cost_cents must be > 0")
    salvage = optional_int(data, "salvage_value_cents")
    if salvage is None:
        salvage = 0
    if salvage < 0 or salvage >= acquisition_cost:
        raise errors.invalid_salvage_value()
    useful_life = optional_int(data, "useful_life_months")
    if useful_life is None:
        useful_life = cls["default_useful_life_months"]
    if useful_life <= 0:
        raise errors.invalid_request("useful_life_months must be > 0")
    book_method = optional_enum(data, "book_method", BOOK_METHODS) or cls["book_method"]
    tax_method = optional_enum(data, "tax_method", TAX_METHODS) or cls["tax_method"]
    bonus = optional_bool(data, "bonus_elected")
    if bonus is None:
        bonus = False
    if bonus and not cls["bonus_depreciation_allowed"]:
        raise errors.bonus_not_allowed()
    if parent is not None and acquisition_cost < cls["capitalization_threshold_cents"]:
        raise errors.below_capitalization_threshold()

    ts = now_iso()
    rec = {
        "id": new_id(),
        "asset_tag": asset_tag,
        "description": description,
        "asset_class_id": asset_class_id,
        "parent_asset_id": parent_asset_id,
        "source": "COMPONENT_ADDITION" if parent is not None else "PURCHASE",
        "acquisition_cost_cents": acquisition_cost,
        "salvage_value_cents": salvage,
        "useful_life_months": useful_life,
        "book_method": book_method,
        "tax_method": tax_method,
        "bonus_elected": bonus,
        "cost_center": cost_center,
        "location": location,
        "in_service_date": None,
        "status": "DRAFT",
        "accumulated_book_cents": 0,
        "accumulated_tax_cents": 0,
        "impairment_total_cents": 0,
        "net_book_value_cents": acquisition_cost,
        "open_inventory_exception": False,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.fixed_assets[rec["id"]] = rec
    return success_object(fixed_asset_view(rec), 201)


@bp.route("/fixed-assets", methods=["GET"])
def list_fixed_assets():
    require_roles(*ALL_ROLES)
    limit, offset = get_pagination()
    f_class = request.args.get("asset_class_id")
    f_parent = request.args.get("parent_asset_id")
    f_status = request.args.get("status")
    f_location = request.args.get("location")
    f_cc = request.args.get("cost_center")
    items = sorted(db.fixed_assets.values(), key=lambda r: (r["created_at"], r["id"]))
    out = []
    for rec in items:
        if f_class is not None and rec["asset_class_id"] != f_class:
            continue
        if f_parent is not None and rec.get("parent_asset_id") != f_parent:
            continue
        if f_status is not None and rec["status"] != f_status:
            continue
        if f_location is not None and rec["location"] != f_location:
            continue
        if f_cc is not None and rec["cost_center"] != f_cc:
            continue
        recompute_asset_derived(rec)
        out.append(rec)
    total = len(out)
    page = out[offset:offset + limit]
    return success_list([fixed_asset_view(r) for r in page], limit, offset, total)


@bp.route("/fixed-assets/<aid>", methods=["GET"])
def get_fixed_asset(aid):
    require_roles(*ALL_ROLES)
    rec = db.fixed_assets.get(aid)
    if rec is None:
        raise errors.not_found("Fixed asset not found")
    recompute_asset_derived(rec)
    return success_object(fixed_asset_view(rec))


@bp.route("/fixed-assets/<aid>", methods=["PATCH"])
def patch_fixed_asset(aid):
    require_roles("AssetAccountant")
    data = get_body()
    rec = db.fixed_assets.get(aid)
    if rec is None:
        raise errors.not_found("Fixed asset not found")
    # OCC — expected_asset_version is required
    if "expected_asset_version" not in data or data["expected_asset_version"] is None:
        raise errors.invalid_request("Missing required field: expected_asset_version")
    expected = data["expected_asset_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise errors.invalid_request("expected_asset_version must be an integer")
    if expected != rec["version"]:
        raise errors.stale_version()

    if rec["status"] == "DISPOSED":
        raise errors.already_disposed()

    # Determine which fields are being touched (besides expected_asset_version)
    touched = [k for k in data.keys() if k != "expected_asset_version"]
    if rec["status"] == "IN_SERVICE" or rec["status"] == "FULLY_DEPRECIATED":
        for f in touched:
            if f not in INSERVICE_EDITABLE:
                raise errors.field_immutable(f"Field {f} may not be edited on an in-service asset")
    elif rec["status"] == "DRAFT":
        for f in touched:
            if f not in DRAFT_EDITABLE:
                raise errors.invalid_request(f"Field {f} is not editable")

    # Validate and apply field by field
    if "description" in data:
        rec["description"] = require_string(data, "description")
    if "acquisition_cost_cents" in data:
        v = require_int(data, "acquisition_cost_cents")
        if v <= 0:
            raise errors.invalid_amount("acquisition_cost_cents must be > 0")
        rec["acquisition_cost_cents"] = v
    if "salvage_value_cents" in data:
        v = require_int(data, "salvage_value_cents")
        rec["salvage_value_cents"] = v
    if "useful_life_months" in data:
        v = require_int(data, "useful_life_months")
        if v <= 0:
            raise errors.invalid_request("useful_life_months must be > 0")
        rec["useful_life_months"] = v
    if "book_method" in data:
        rec["book_method"] = require_enum(data, "book_method", BOOK_METHODS)
    if "tax_method" in data:
        rec["tax_method"] = require_enum(data, "tax_method", TAX_METHODS)
    if "bonus_elected" in data:
        v = data["bonus_elected"]
        if not isinstance(v, bool):
            raise errors.invalid_request("bonus_elected must be a boolean")
        if v:
            cls = db.asset_classes.get(rec["asset_class_id"])
            if cls is None or not cls["bonus_depreciation_allowed"]:
                raise errors.bonus_not_allowed()
        rec["bonus_elected"] = v
    if "location" in data:
        rec["location"] = require_string(data, "location")
    if "cost_center" in data:
        rec["cost_center"] = require_string(data, "cost_center")

    # cross-field validation
    if rec["salvage_value_cents"] < 0 or rec["salvage_value_cents"] >= rec["acquisition_cost_cents"]:
        raise errors.invalid_salvage_value()

    rec["version"] += 1
    rec["updated_at"] = now_iso()
    recompute_asset_derived(rec)

    # location edit re-evaluates count line reconciliation for this asset
    if "location" in data:
        affected_runs = set()
        for line in db.inventory_count_lines.values():
            if line["asset_id"] == rec["id"]:
                recompute_line_status(line)
                line["updated_at"] = now_iso()
                line["version"] += 1
                affected_runs.add(line["run_id"])
        for rid in affected_runs:
            run = db.inventory_runs.get(rid)
            if run is not None:
                recompute_run_counters(run)
                run["updated_at"] = now_iso()
        refresh_asset_exceptions([rec["id"]])
    return success_object(fixed_asset_view(rec))


@bp.route("/fixed-assets/<aid>/place-in-service", methods=["POST"])
def place_in_service(aid):
    require_roles("AssetAccountant")
    data = get_body()
    rec = db.fixed_assets.get(aid)
    if rec is None:
        raise errors.not_found("Fixed asset not found")
    if rec["status"] != "DRAFT":
        raise errors.invalid_state("Asset is not DRAFT")
    in_service_date = require_date(data, "in_service_date")
    rec["in_service_date"] = in_service_date
    rec["status"] = "IN_SERVICE"
    rec["version"] += 1
    rec["updated_at"] = now_iso()
    recompute_asset_derived(rec)
    return success_object(fixed_asset_view(rec))
