"""Buildings, spaces, assets, PM plans, vendors, the KPI surface and the logical clock."""

from datetime import datetime, timezone

import billing
import calc
import domain
import ops
import serializers
import validate as v
from auth import require
from envelope import iso, list_response, object_response, pagination
from errors import fail
from flask import Blueprint
from store import base_fields, db, ordered, touch

bp = Blueprint("portfolio", __name__)

SPACE_TYPES = {"OFFICE", "LAB", "RETAIL", "COMMON", "PLANT"}
ASSET_CATEGORIES = {"HVAC", "ELEVATOR", "FIRE", "ELECTRICAL", "PLUMBING"}
CRITICALITIES = {"CRITICAL", "STANDARD", "LOW"}
ASSET_STATUSES = {"IN_SERVICE", "OUT_OF_SERVICE", "RETIRED"}
PLAN_STATUSES = {"ACTIVE", "SUSPENDED", "RETIRED"}
OCCUPANCY_STATUSES = {"VACANT", "OCCUPIED"}
TRADES = {"HVAC", "ELEVATOR", "FIRE", "ELECTRICAL", "PLUMBING", "JANITORIAL", "SECURITY"}

EPOCH = datetime(1970, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def get_building(building_id):
    row = db.buildings.get(building_id)
    if row is None:
        fail("ERR_BUILDING_NOT_FOUND", "Building %s does not exist." % building_id)
    return row


def get_asset(asset_id):
    row = db.assets.get(asset_id)
    if row is None:
        fail("ERR_ASSET_NOT_FOUND", "Asset %s does not exist." % asset_id)
    return row


# ---------------------------------------------------------------------------
# Buildings
# ---------------------------------------------------------------------------
@bp.post("/buildings")
@require("PlatformAdmin", "FacilityManager")
def create_building():
    data = v.body()
    name = v.string(data, "name")
    code = v.string(data, "code")
    gross_area = v.number(data, "gross_area_sqm", gt=0)
    region = v.string(data, "region", required=False)

    if any(b["code"] == code for b in db.buildings.values()):
        fail("ERR_DUPLICATE_BUILDING_CODE", "Building code '%s' already exists." % code)

    row = base_fields()
    row.update(
        {
            "name": name,
            "code": code,
            "gross_area_sqm": gross_area,
            "region": region,
            "operating_posture": "OPEN",
            "oos_critical_asset_count": 0,
            "open_p1_work_order_count": 0,
        }
    )
    db.buildings[row["id"]] = row
    return object_response(serializers.building(row), 201)


@bp.get("/buildings/<building_id>")
@require(
    "PlatformAdmin",
    "FacilityManager",
    "FinanceController",
    "SustainabilityAnalyst",
    "VendorTech",
    "TenantRep",
)
def read_building(building_id):
    return object_response(serializers.building(get_building(building_id)))


@bp.get("/buildings/<building_id>/kpi")
@require("PlatformAdmin", "FacilityManager", "FinanceController", "SustainabilityAnalyst")
def building_kpi(building_id):
    window_start = v.query_dt("window_start")
    window_end = v.query_dt("window_end")
    building = get_building(building_id)
    if window_start is None:
        window_start = EPOCH
    if window_end is None:
        window_end = db.clock
    return object_response(billing.kpi(building, window_start, window_end))


@bp.post("/buildings/<building_id>/ops-run")
@require("PlatformAdmin", "FacilityManager")
def building_ops_run(building_id):
    building = get_building(building_id)
    return object_response(ops.run(building))


# ---------------------------------------------------------------------------
# Spaces
# ---------------------------------------------------------------------------
@bp.post("/buildings/<building_id>/spaces")
@require("PlatformAdmin", "FacilityManager")
def create_space(building_id):
    data = v.body()
    space_code = v.string(data, "space_code")
    floor = v.integer(data, "floor")
    area = v.number(data, "area_sqm", gt=0)
    space_type = v.enum(data, "space_type", SPACE_TYPES)
    cost_center = v.string(data, "cost_center", required=False)

    building = get_building(building_id)

    clash = any(
        s["building_id"] == building["id"] and s["space_code"] == space_code
        for s in db.spaces.values()
    )
    if clash:
        fail(
            "ERR_DUPLICATE_SPACE_CODE",
            "Space code '%s' already exists in this building." % space_code,
        )

    row = base_fields()
    row.update(
        {
            "building_id": building["id"],
            "space_code": space_code,
            "floor": floor,
            "area_sqm": area,
            "space_type": space_type,
            "cost_center": cost_center,
            "allocated_share_pct": calc.round2(0),
            "free_share_pct": calc.round2(100),
            "occupancy_status": "VACANT",
        }
    )
    db.spaces[row["id"]] = row
    return object_response(serializers.space(row), 201)


@bp.get("/buildings/<building_id>/spaces")
@require("PlatformAdmin", "FacilityManager", "FinanceController", "TenantRep")
def list_spaces(building_id):
    occupancy = v.query_enum("occupancy_status", OCCUPANCY_STATUSES)
    limit, offset = pagination()
    building = get_building(building_id)

    rows = [s for s in db.spaces.values() if s["building_id"] == building["id"]]
    payload = [serializers.space(s) for s in ordered(rows)]
    if occupancy:
        payload = [s for s in payload if s["occupancy_status"] == occupancy]
    return list_response(payload, limit, offset)


@bp.get("/spaces/<space_id>")
@require("PlatformAdmin", "FacilityManager", "FinanceController", "TenantRep")
def read_space(space_id):
    row = db.spaces.get(space_id)
    if row is None:
        fail("ERR_SPACE_NOT_FOUND", "Space %s does not exist." % space_id)
    return object_response(serializers.space(row))


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------
@bp.post("/assets")
@require("PlatformAdmin", "FacilityManager")
def create_asset():
    data = v.body()
    building_id = v.string(data, "building_id")
    asset_tag = v.string(data, "asset_tag")
    category = v.enum(data, "category", ASSET_CATEGORIES)
    criticality = v.enum(data, "criticality", CRITICALITIES)
    runtime_hours = v.number(data, "runtime_hours", required=False, default=0)

    building = get_building(building_id)

    if any(a["asset_tag"] == asset_tag for a in db.assets.values()):
        fail("ERR_DUPLICATE_ASSET_TAG", "Asset tag '%s' already exists." % asset_tag)

    row = base_fields()
    row.update(
        {
            "building_id": building["id"],
            "asset_tag": asset_tag,
            "category": category,
            "criticality": criticality,
            "status": "IN_SERVICE",
            "runtime_hours": runtime_hours,
            "failure_count": 0,
            "condition_score": calc.condition_score(runtime_hours, 0),
            "last_pm_at": None,
        }
    )
    db.assets[row["id"]] = row
    return object_response(serializers.asset(row), 201)


@bp.get("/assets/<asset_id>")
@require("PlatformAdmin", "FacilityManager", "FinanceController", "VendorTech")
def read_asset(asset_id):
    return object_response(serializers.asset(get_asset(asset_id)))


@bp.get("/buildings/<building_id>/assets")
@require("PlatformAdmin", "FacilityManager", "FinanceController")
def list_assets(building_id):
    status = v.query_enum("status", ASSET_STATUSES)
    limit, offset = pagination()
    building = get_building(building_id)

    rows = [a for a in db.assets.values() if a["building_id"] == building["id"]]
    if status:
        rows = [a for a in rows if a["status"] == status]
    return list_response([serializers.asset(a) for a in ordered(rows)], limit, offset)


@bp.post("/assets/<asset_id>/report-failure")
@require("PlatformAdmin", "FacilityManager")
def report_failure(asset_id):
    asset = get_asset(asset_id)
    if asset["status"] != "IN_SERVICE":
        fail("ERR_ASSET_NOT_IN_SERVICE", "The asset is not IN_SERVICE.")

    asset["status"] = "OUT_OF_SERVICE"
    asset["failure_count"] += 1
    asset["condition_score"] = calc.condition_score(
        asset["runtime_hours"], asset["failure_count"]
    )
    touch(asset)

    building = db.buildings.get(asset["building_id"])
    if building is not None:
        domain.recompute_building(building)

    return object_response(serializers.asset(asset))


# ---------------------------------------------------------------------------
# PM plans
# ---------------------------------------------------------------------------
@bp.post("/pm-plans")
@require("PlatformAdmin", "FacilityManager")
def create_pm_plan():
    data = v.body()
    asset_id = v.string(data, "asset_id")
    interval_days = v.integer(data, "interval_days", ge=1)
    grace_days = v.integer(data, "grace_days", ge=0)
    next_due_at = v.datetime_field(data, "next_due_at")

    asset = get_asset(asset_id)

    row = base_fields()
    row.update(
        {
            "asset_id": asset["id"],
            "interval_days": interval_days,
            "grace_days": grace_days,
            "next_due_at": next_due_at,
            "status": "ACTIVE",
            "compliance_state": calc.compliance_state(next_due_at, grace_days, db.clock),
        }
    )
    db.pm_plans[row["id"]] = row
    return object_response(serializers.pm_plan(row), 201)


@bp.get("/assets/<asset_id>/pm-plans")
@require("PlatformAdmin", "FacilityManager")
def list_pm_plans(asset_id):
    status = v.query_enum("status", PLAN_STATUSES)
    limit, offset = pagination()
    asset = get_asset(asset_id)

    rows = [p for p in db.pm_plans.values() if p["asset_id"] == asset["id"]]
    if status:
        rows = [p for p in rows if p["status"] == status]
    return list_response([serializers.pm_plan(p) for p in ordered(rows)], limit, offset)


# ---------------------------------------------------------------------------
# Vendors
# ---------------------------------------------------------------------------
@bp.post("/vendors")
@require("PlatformAdmin", "FacilityManager")
def create_vendor():
    data = v.body()
    name = v.string(data, "name")
    trade = v.enum(data, "trade", TRADES)
    hourly_rate = v.number(data, "hourly_rate", gt=0)
    sla_response = v.integer(data, "sla_response_minutes", ge=1)
    sla_resolve = v.integer(data, "sla_resolve_minutes", ge=1)

    row = base_fields()
    row.update(
        {
            "name": name,
            "trade": trade,
            "hourly_rate": hourly_rate,
            "sla_response_minutes": sla_response,
            "sla_resolve_minutes": sla_resolve,
            "status": "ACTIVE",
            "strike_count": 0,
            "performance_score": calc.round2(100),
            "lifetime_performance_score": calc.round2(100),
            "completed_dispatch_count": 0,
        }
    )
    db.vendors[row["id"]] = row
    return object_response(serializers.vendor(row), 201)


@bp.get("/vendors/<vendor_id>")
@require("PlatformAdmin", "FacilityManager", "FinanceController", "VendorTech")
def read_vendor(vendor_id):
    row = db.vendors.get(vendor_id)
    if row is None:
        fail("ERR_VENDOR_NOT_FOUND", "Vendor %s does not exist." % vendor_id)
    return object_response(serializers.vendor(row))


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
@require("PlatformAdmin")
def set_clock():
    data = v.body()
    to_iso = v.datetime_field(data, "to_iso8601")
    db.clock = to_iso
    return object_response({"current_utc": iso(db.clock)})
