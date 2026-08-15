"""InventoryRun and InventoryCountLine endpoints."""
from flask import Blueprint
import db
import errors
from db import new_id, now_iso
from middleware import (require_roles, get_body, get_pagination,
                        require_string, optional_string, require_enum,
                        optional_enum, require_bool)
from response import success_object, success_list
from services.serializers import (inventory_run_view, inventory_count_line_view,
                                  recompute_asset_derived)
from services.inventory import (recompute_line_status, recompute_run_counters,
                                refresh_asset_exceptions)

bp = Blueprint("inventory_runs", __name__)
ALL_ROLES = ("AssetAccountant", "Controller", "InventoryClerk", "TaxAnalyst")
SCOPE_TYPES = {"ALL", "LOCATION", "COST_CENTER"}
CONDITIONS = {"GOOD", "DAMAGED"}


@bp.route("/inventory-runs", methods=["POST"])
def create_inventory_run():
    require_roles("InventoryClerk")
    data = get_body()
    name = require_string(data, "name")
    scope_type = require_enum(data, "scope_type", SCOPE_TYPES)
    scope_value = optional_string(data, "scope_value")
    if scope_type in ("LOCATION", "COST_CENTER") and not scope_value:
        raise errors.invalid_request("scope_value required for LOCATION/COST_CENTER scope")

    ts = now_iso()
    rec = {
        "id": new_id(),
        "name": name,
        "scope_type": scope_type,
        "scope_value": scope_value,
        "status": "COUNTING",
        "expected_count": 0,
        "matched_count": 0,
        "missing_count": 0,
        "mismatch_count": 0,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.inventory_runs[rec["id"]] = rec

    # Seed one line per in-scope asset
    assets = sorted(db.fixed_assets.values(), key=lambda a: (a["created_at"], a["id"]))
    seeded = 0
    for asset in assets:
        if asset["status"] not in ("IN_SERVICE", "FULLY_DEPRECIATED"):
            continue
        if scope_type == "LOCATION" and asset["location"] != scope_value:
            continue
        if scope_type == "COST_CENTER" and asset["cost_center"] != scope_value:
            continue
        line = {
            "id": new_id(),
            "run_id": rec["id"],
            "asset_id": asset["id"],
            "found": None,
            "counted_location": None,
            "condition": "GOOD",
            "reconciliation_status": "PENDING",
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "version": 1,
        }
        db.inventory_count_lines[line["id"]] = line
        seeded += 1
    rec["expected_count"] = seeded
    return success_object(inventory_run_view(rec), 201)


@bp.route("/inventory-runs/<rid>", methods=["GET"])
def get_inventory_run(rid):
    require_roles(*ALL_ROLES)
    rec = db.inventory_runs.get(rid)
    if rec is None:
        raise errors.not_found("Inventory run not found")
    return success_object(inventory_run_view(rec))


@bp.route("/inventory-runs/<rid>/count-lines", methods=["POST"])
def upsert_count_line(rid):
    require_roles("InventoryClerk")
    data = get_body()
    run = db.inventory_runs.get(rid)
    if run is None:
        raise errors.not_found("Inventory run not found")
    asset_id = require_string(data, "asset_id")
    # existence: asset must exist and be seeded
    asset = db.fixed_assets.get(asset_id)
    if asset is None:
        raise errors.not_found("asset_id not found")
    line = None
    for l in db.inventory_count_lines.values():
        if l["run_id"] == rid and l["asset_id"] == asset_id:
            line = l
            break
    if line is None:
        raise errors.asset_not_in_scope()
    # state
    if run["status"] != "COUNTING":
        raise errors.run_not_counting()

    found = require_bool(data, "found")
    counted_location = optional_string(data, "counted_location")
    condition = optional_enum(data, "condition", CONDITIONS)
    if condition is None:
        condition = "GOOD"
    if found and not counted_location:
        raise errors.invalid_request("counted_location required when found is true")

    line["found"] = found
    line["counted_location"] = counted_location
    line["condition"] = condition
    recompute_line_status(line)
    line["version"] += 1
    line["updated_at"] = now_iso()

    # DAMAGED on found asset auto-opens an ImpairmentReview unless one is OPEN
    if found and condition == "DAMAGED":
        existing_open = any(
            r for r in db.impairment_reviews.values()
            if r["asset_id"] == asset_id and r["status"] == "OPEN"
        )
        if not existing_open:
            ts = now_iso()
            review = {
                "id": new_id(),
                "asset_id": asset_id,
                "indicator": "DAMAGE",
                "source": "INVENTORY",
                "created_by_user_id": "system",
                "recoverable_value_cents": None,
                "write_down_cents": None,
                "status": "OPEN",
                "created_at": ts,
                "updated_at": ts,
                "version": 1,
            }
            db.impairment_reviews[review["id"]] = review

    recompute_run_counters(run)
    run["updated_at"] = now_iso()
    refresh_asset_exceptions([asset_id])
    return success_object(inventory_count_line_view(line))


@bp.route("/inventory-runs/<rid>/count-lines", methods=["GET"])
def list_run_count_lines(rid):
    require_roles(*ALL_ROLES)
    run = db.inventory_runs.get(rid)
    if run is None:
        raise errors.not_found("Inventory run not found")
    limit, offset = get_pagination()
    items = sorted(
        (l for l in db.inventory_count_lines.values() if l["run_id"] == rid),
        key=lambda r: (r["created_at"], r["id"]),
    )
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([inventory_count_line_view(r) for r in page], limit, offset, total)


@bp.route("/fixed-assets/<aid>/count-lines", methods=["GET"])
def list_asset_count_lines(aid):
    require_roles(*ALL_ROLES)
    asset = db.fixed_assets.get(aid)
    if asset is None:
        raise errors.not_found("Fixed asset not found")
    limit, offset = get_pagination()
    items = sorted(
        (l for l in db.inventory_count_lines.values() if l["asset_id"] == aid),
        key=lambda r: (r["created_at"], r["id"]),
    )
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([inventory_count_line_view(r) for r in page], limit, offset, total)


@bp.route("/inventory-runs/<rid>/begin-reconciliation", methods=["POST"])
def begin_reconciliation(rid):
    require_roles("InventoryClerk")
    rec = db.inventory_runs.get(rid)
    if rec is None:
        raise errors.not_found("Inventory run not found")
    if rec["status"] != "COUNTING":
        raise errors.invalid_state("Run is not COUNTING")
    for line in db.inventory_count_lines.values():
        if line["run_id"] == rid and line.get("found") is None:
            raise errors.uncounted_lines()
    rec["status"] = "RECONCILING"
    rec["version"] += 1
    rec["updated_at"] = now_iso()
    return success_object(inventory_run_view(rec))


@bp.route("/inventory-runs/<rid>/recount", methods=["POST"])
def recount(rid):
    require_roles("InventoryClerk")
    rec = db.inventory_runs.get(rid)
    if rec is None:
        raise errors.not_found("Inventory run not found")
    if rec["status"] != "RECONCILING":
        raise errors.invalid_state("Run is not RECONCILING")
    rec["status"] = "COUNTING"
    rec["version"] += 1
    rec["updated_at"] = now_iso()
    return success_object(inventory_run_view(rec))


@bp.route("/inventory-runs/<rid>/close", methods=["POST"])
def close_run(rid):
    require_roles("Controller")
    rec = db.inventory_runs.get(rid)
    if rec is None:
        raise errors.not_found("Inventory run not found")
    if rec["status"] != "RECONCILING":
        raise errors.invalid_state("Run is not RECONCILING")
    # every seeded line MATCHED or its asset DISPOSED
    affected_assets = []
    for line in db.inventory_count_lines.values():
        if line["run_id"] != rid:
            continue
        recompute_line_status(line)
        asset = db.fixed_assets.get(line["asset_id"])
        affected_assets.append(line["asset_id"])
        if line["reconciliation_status"] == "MATCHED":
            continue
        if asset is not None and asset["status"] == "DISPOSED":
            continue
        raise errors.unresolved_inventory_items()
    rec["status"] = "CLOSED"
    rec["version"] += 1
    rec["updated_at"] = now_iso()
    recompute_run_counters(rec)
    refresh_asset_exceptions(affected_assets)
    return success_object(inventory_run_view(rec))
