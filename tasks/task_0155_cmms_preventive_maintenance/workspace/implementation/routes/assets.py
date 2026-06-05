"""Asset routes (PRD §3.2, §4) — create, fetch, list (filters), retire (OCC)."""
from flask import Blueprint, request

import db
import errors
import serialize
from middleware import authenticate, authorize, get_json_body
from helpers import (require_str, opt_str, require_int, opt_enum, opt_dt,
                     parse_pagination, paginate)
from response import object_response, array_response

bp = Blueprint("assets", __name__)

CRITICALITY = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
METER_UNITS = {"HOURS", "CYCLES", "KM"}
NON_TERMINAL_WO = {"UNASSIGNED", "ASSIGNED", "IN_PROGRESS", "ON_HOLD"}


@bp.post("/assets")
def create_asset():
    _, role = authenticate()
    authorize(role, ["MaintenanceManager"])
    body = get_json_body()
    site_id = require_str(body, "site_id")
    parent_asset_id = opt_str(body, "parent_asset_id", default=None)
    name = require_str(body, "name")
    criticality = opt_enum(body, "criticality", CRITICALITY, default="MEDIUM")
    meter_unit = opt_enum(body, "meter_unit", METER_UNITS, default="HOURS")
    warranty_expires_at = opt_dt(body, "warranty_expires_at", default=None)
    warranty_cap = body.get("warranty_cost_cap_cents")
    if warranty_cap is not None and (isinstance(warranty_cap, bool) or not isinstance(warranty_cap, int)):
        raise errors.invalid_request("warranty_cost_cap_cents must be an integer or null.")
    if warranty_cap is not None and warranty_cap < 0:
        raise errors.invalid_request("warranty_cost_cap_cents must be >= 0.")
    acquisition = require_int_default(body, "acquisition_cost_cents", default=0, minimum=0)

    with db.LOCK:
        # FK existence (priority 4) -> ERR_REFERENCE_NOT_FOUND.
        if site_id not in db.sites:
            raise errors.reference_not_found("site_id does not reference an existing site.")
        if parent_asset_id is not None and parent_asset_id not in db.assets:
            raise errors.reference_not_found("parent_asset_id does not reference an existing asset.")
        rec = db.new_record()
        rec.update({
            "site_id": site_id,
            "parent_asset_id": parent_asset_id,
            "name": name,
            "criticality": criticality,
            "status": "OPERATIONAL",
            "meter_unit": meter_unit,
            "meter_reading": 0,
            "warranty_expires_at": db.iso(warranty_expires_at) if warranty_expires_at else None,
            "warranty_cost_cap_cents": warranty_cap,
            "acquisition_cost_cents": acquisition,
            "mtbf_hours": 0,
            "mttr_hours": 0,
        })
        db.assets[rec["id"]] = rec
        return object_response(serialize.asset(rec), 201)


def require_int_default(body, field, default, minimum=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request("Field %s must be an integer." % field)
    if minimum is not None and val < minimum:
        raise errors.invalid_request("Field %s must be >= %s." % (field, minimum))
    return val


@bp.get("/assets/<aid>")
def get_asset(aid):
    _, role = authenticate()
    authorize(role, ["MaintenanceManager", "Planner", "Technician", "WarrantyAdmin", "InventoryClerk"])
    with db.LOCK:
        rec = db.assets.get(aid)
        if rec is None:
            raise errors.not_found()
        return object_response(serialize.asset(rec), 200)


@bp.get("/assets")
def list_assets():
    _, role = authenticate()
    authorize(role, ["MaintenanceManager", "Planner", "Technician", "WarrantyAdmin", "InventoryClerk"])
    limit, offset = parse_pagination()
    site_id = request.args.get("site_id")
    parent_asset_id = request.args.get("parent_asset_id")
    with db.LOCK:
        items = sorted(db.assets.values(), key=lambda r: r["_seq"])
        if site_id is not None:
            items = [a for a in items if a["site_id"] == site_id]
        if parent_asset_id is not None:
            items = [a for a in items if a["parent_asset_id"] == parent_asset_id]
        total = len(items)
        page = paginate(items, limit, offset)
        return array_response([serialize.asset(r) for r in page], limit, offset, total)


@bp.post("/assets/<aid>/retire")
def retire_asset(aid):
    _, role = authenticate()
    authorize(role, ["MaintenanceManager"])
    body = get_json_body()
    with db.LOCK:
        asset = db.assets.get(aid)
        if asset is None:
            raise errors.not_found()
        # required field (priority 5)
        if "expected_asset_version" not in body or body["expected_asset_version"] is None:
            raise errors.invalid_request("Missing required field: expected_asset_version.")
        expected = body["expected_asset_version"]
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise errors.invalid_request("expected_asset_version must be an integer.")

        # State (priority 6): retire is defined only from OPERATIONAL/DOWN-as-busy.
        # RETIRED is terminal -> transition not defined -> ERR_INVALID_STATE.
        if asset["status"] == "RETIRED":
            raise errors.invalid_state("Asset is already RETIRED.")

        # OCC (priority 7).
        if expected != asset["version"]:
            raise errors.stale_version("expected_asset_version does not match the asset's current version.")

        # Asset-busy (priority 19): DOWN, or any non-terminal work order.
        if asset["status"] == "DOWN":
            raise errors.ApiError(errors.ERR_ASSET_BUSY, "Asset is DOWN and cannot be retired.", 409)
        for wo in db.work_orders.values():
            if wo["asset_id"] == aid and wo["execution_status"] in NON_TERMINAL_WO:
                raise errors.ApiError(errors.ERR_ASSET_BUSY,
                                      "Asset has active work orders and cannot be retired.", 409)

        asset["status"] = "RETIRED"
        db.touch(asset)
        # CASCADE: deactivate every PM schedule on this asset.
        for sched in db.pm_schedules.values():
            if sched["asset_id"] == aid and sched["active"]:
                sched["active"] = False
                db.touch(sched)
        return object_response(serialize.asset(asset), 200)
