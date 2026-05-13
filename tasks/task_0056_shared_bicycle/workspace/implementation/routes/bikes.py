"""Bike endpoints (PRD §3.2, §3.5, §3.7, §3.11)."""
from __future__ import annotations

from flask import Blueprint, g, request

from constants import EBIKE_MIN_BATTERY_PCT
from db import (
    LOCK,
    bikes,
    geofences,
    loss_records,
    new_id,
    regions,
    work_orders,
    record_bike_in_region_history,
)
from errors import (
    ERR_BATTERY_TOO_LOW,
    ERR_BIKE_HAS_OPEN_WORKORDER,
    ERR_BIKE_IN_USE,
    ERR_BIKE_NOT_AVAILABLE,
    ERR_BIKE_NOT_IN_RECALL,
    ERR_BIKE_OFF_SHELF,
    ERR_INVALID_STATE,
    ERR_NO_LOSS_RECORD,
    ERR_NOT_FOUND,
    ERR_QUOTA_EXCEEDED,
    ERR_VALIDATION,
    raise_err,
)
from middleware import require_role
from response import success_list, success_object
from services.audit import write_audit
from services.regions import recompute_region_counts
from services.validators import (
    bump_version,
    check_version,
    ensure_enum,
    ensure_positive_int,
    get_json_body,
    parse_pagination,
)
from time_utils import now_iso


bp = Blueprint("bikes", __name__)

BIKE_MODELS = {"STANDARD", "E_BIKE"}
BIKE_STATUSES = {"AVAILABLE", "IN_USE", "FAULT", "RECALL"}
BIKE_SHELF_STATES = {"OFF_SHELF", "ON_SHELF", "SCRAPPED"}
LOCK_STATES = {"LOCKED", "UNLOCKED", "UNKNOWN"}
FAULT_CATEGORIES = {"FLAT_TIRE", "BRAKE", "LOCK_FAILURE", "BATTERY_SWAP", "CHARGING", "OTHER"}


def serialize_bike(b: dict) -> dict:
    return dict(b)


def _has_open_workorder(bike_id: str) -> bool:
    return any(
        wo for wo in work_orders.values()
        if wo.get("bike_id") == bike_id
        and wo.get("status") in ("OPEN", "ASSIGNED")
    )


@bp.post("/bikes")
def create_bike():
    require_role("Admin")
    body = get_json_body()
    if "model" not in body:
        raise_err(ERR_VALIDATION, "model is required")
    model = ensure_enum(body["model"], "model", BIKE_MODELS)
    lock_id = body.get("lock_id")
    if not isinstance(lock_id, str) or not lock_id:
        raise_err(ERR_VALIDATION, "lock_id is required")

    if model == "STANDARD":
        battery_pct = 100
    else:
        battery_pct = body.get("battery_pct", 100)
    if not isinstance(battery_pct, int) or isinstance(battery_pct, bool):
        raise_err(ERR_VALIDATION, "battery_pct must be an integer")
    if battery_pct < 0 or battery_pct > 100:
        raise_err(ERR_VALIDATION, "battery_pct must be between 0 and 100")

    with LOCK:
        # Ensure unique lock_id.
        for b in bikes.values():
            if b.get("lock_id") == lock_id:
                raise_err(ERR_VALIDATION, "lock_id must be unique")
        bid = new_id()
        ts = now_iso()
        bike = {
            "id": bid,
            "region_id": None,
            "model": model,
            "lock_id": lock_id,
            "shelf_state": "OFF_SHELF",
            "status": "AVAILABLE",
            "battery_pct": battery_pct if model == "E_BIKE" else 100,
            "last_lat": None,
            "last_lng": None,
            "last_motion_minute": 0,
            "lock_state": "LOCKED",
            "fault_categories": [],
            "current_ride_id": None,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        bikes[bid] = bike
    return success_object(serialize_bike(bike), status=201)


@bp.get("/bikes/<bike_id>")
def get_bike(bike_id):
    require_role("Admin", "Operator", "FieldStaff", "Rider")
    bike = bikes.get(bike_id)
    if bike is None:
        raise_err(ERR_NOT_FOUND, "Bike not found")
    return success_object(serialize_bike(bike))


@bp.patch("/bikes/<bike_id>")
def patch_bike(bike_id):
    require_role("Admin", "Operator", "FieldStaff")
    bike = bikes.get(bike_id)
    if bike is None:
        raise_err(ERR_NOT_FOUND, "Bike not found")
    body = get_json_body()

    with LOCK:
        check_version(body, bike)
        location_changed = False
        if "battery_pct" in body:
            val = body["battery_pct"]
            if not isinstance(val, int) or isinstance(val, bool):
                raise_err(ERR_VALIDATION, "battery_pct must be an integer")
            if val < 0 or val > 100:
                raise_err(ERR_VALIDATION, "battery_pct must be between 0 and 100")
            bike["battery_pct"] = val
        if "lock_state" in body:
            bike["lock_state"] = ensure_enum(body["lock_state"], "lock_state", LOCK_STATES)
        if "last_lat" in body:
            v = body["last_lat"]
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise_err(ERR_VALIDATION, "last_lat must be a number")
            if bike.get("last_lat") != float(v):
                bike["last_lat"] = float(v)
                location_changed = True
        if "last_lng" in body:
            v = body["last_lng"]
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise_err(ERR_VALIDATION, "last_lng must be a number")
            if bike.get("last_lng") != float(v):
                bike["last_lng"] = float(v)
                location_changed = True
        if location_changed and bike.get("region_id") and bike["region_id"] in regions:
            bike["last_motion_minute"] = regions[bike["region_id"]].get("clock_minutes", 0)
        bump_version(bike)
    return success_object(serialize_bike(bike))


@bp.post("/regions/<region_id>/bikes/<bike_id>/shelf")
def shelf_bike(region_id, bike_id):
    require_role("Operator", "Admin")
    region = regions.get(region_id)
    if region is None:
        raise_err(ERR_NOT_FOUND, "Region not found")
    bike = bikes.get(bike_id)
    if bike is None:
        raise_err(ERR_NOT_FOUND, "Bike not found")
    body = get_json_body()
    action = body.get("action")
    if action not in ("ON", "OFF"):
        raise_err(ERR_VALIDATION, "action must be 'ON' or 'OFF'")

    with LOCK:
        if action == "ON":
            if bike["shelf_state"] == "SCRAPPED":
                raise_err(ERR_INVALID_STATE, "Bike is SCRAPPED")
            if bike["shelf_state"] == "ON_SHELF":
                raise_err(ERR_INVALID_STATE, "Bike is already ON_SHELF")
            # Validations in scaffold order: quota → open WO → battery.
            if region["deployed_count"] + 1 > region["deployment_quota"]:
                raise_err(ERR_QUOTA_EXCEEDED, "deployment_quota would be exceeded")
            if _has_open_workorder(bike_id):
                raise_err(ERR_BIKE_HAS_OPEN_WORKORDER, "Bike has an open work order")
            if bike["model"] == "E_BIKE" and bike.get("battery_pct", 0) < EBIKE_MIN_BATTERY_PCT:
                raise_err(ERR_BATTERY_TOO_LOW, "E_BIKE battery_pct below minimum")
            before = {
                "shelf_state": bike["shelf_state"],
                "status": bike["status"],
                "region_id": bike.get("region_id"),
            }
            prior_posture = region["density_posture"]
            bike["shelf_state"] = "ON_SHELF"
            bike["status"] = "AVAILABLE"
            bike["region_id"] = region_id
            record_bike_in_region_history(region_id, bike_id)
            bump_version(bike)
            recompute_region_counts(region_id)
            write_audit(
                event_kind="OPS_ACTION",
                action="BIKE_ON_SHELF",
                subject_type="Bike",
                subject_id=bike_id,
                before=before,
                after={
                    "shelf_state": bike["shelf_state"],
                    "status": bike["status"],
                    "region_id": bike["region_id"],
                    "density_posture_before": prior_posture,
                    "density_posture_after": region["density_posture"],
                },
                region_id=region_id,
            )
        else:  # OFF
            if bike["shelf_state"] != "ON_SHELF":
                raise_err(ERR_INVALID_STATE, "Bike must be ON_SHELF to take OFF")
            if bike.get("region_id") != region_id:
                raise_err(ERR_INVALID_STATE, "Bike not in this region")
            if bike["status"] == "IN_USE":
                raise_err(ERR_BIKE_IN_USE, "Cannot OFF-shelf a bike that is IN_USE")
            before = {"shelf_state": bike["shelf_state"], "status": bike["status"]}
            bike["shelf_state"] = "OFF_SHELF"
            bike["status"] = "AVAILABLE"
            bump_version(bike)
            recompute_region_counts(region_id)
            write_audit(
                event_kind="OPS_ACTION",
                action="BIKE_OFF_SHELF",
                subject_type="Bike",
                subject_id=bike_id,
                before=before,
                after={"shelf_state": bike["shelf_state"], "status": bike["status"]},
                region_id=region_id,
            )
    return success_object(serialize_bike(bike))


@bp.post("/bikes/<bike_id>/recall")
def recall_bike(bike_id):
    require_role("Operator", "Admin")
    bike = bikes.get(bike_id)
    if bike is None:
        raise_err(ERR_NOT_FOUND, "Bike not found")
    with LOCK:
        # Active ride? Treat as IN_USE.
        if bike["status"] == "IN_USE":
            raise_err(ERR_BIKE_IN_USE, "Bike is currently in a ride")
        if bike["status"] != "AVAILABLE":
            raise_err(ERR_BIKE_NOT_AVAILABLE, "Bike status must be AVAILABLE to recall")
        bike["status"] = "RECALL"
        bump_version(bike)
        recompute_region_counts(bike.get("region_id"))
        write_audit(
            event_kind="OPS_ACTION",
            action="BIKE_RECALL",
            subject_type="Bike",
            subject_id=bike_id,
            before={"status": "AVAILABLE"},
            after={"status": "RECALL"},
            region_id=bike.get("region_id"),
        )
    return success_object(serialize_bike(bike))


@bp.post("/bikes/<bike_id>/release-recall")
def release_recall(bike_id):
    require_role("Operator", "Admin")
    bike = bikes.get(bike_id)
    if bike is None:
        raise_err(ERR_NOT_FOUND, "Bike not found")
    with LOCK:
        if bike["status"] != "RECALL":
            raise_err(ERR_BIKE_NOT_IN_RECALL, "Bike is not in RECALL")
        if _has_open_workorder(bike_id):
            raise_err(ERR_BIKE_HAS_OPEN_WORKORDER, "Bike has an open work order")
        bike["status"] = "AVAILABLE"
        bump_version(bike)
        recompute_region_counts(bike.get("region_id"))
    return success_object(serialize_bike(bike))


@bp.post("/bikes/<bike_id>/fault-report")
def report_fault(bike_id):
    require_role("Rider", "Operator")
    bike = bikes.get(bike_id)
    if bike is None:
        raise_err(ERR_NOT_FOUND, "Bike not found")
    body = get_json_body()
    if "category" not in body:
        raise_err(ERR_VALIDATION, "category is required")
    category = ensure_enum(body["category"], "category", FAULT_CATEGORIES)

    with LOCK:
        if bike["shelf_state"] != "ON_SHELF":
            raise_err(ERR_BIKE_OFF_SHELF, "Bike is not ON_SHELF")
        if bike["status"] != "AVAILABLE":
            raise_err(ERR_BIKE_NOT_AVAILABLE, "Bike status must be AVAILABLE")
        region_id = bike.get("region_id")
        region = regions.get(region_id) if region_id else None
        opened = region.get("clock_minutes", 0) if region else 0

        bike["status"] = "FAULT"
        if category not in bike["fault_categories"]:
            bike["fault_categories"].append(category)
        bump_version(bike)

        wo_id = new_id()
        ts = now_iso()
        wo = {
            "id": wo_id,
            "bike_id": bike_id,
            "region_id": region_id,
            "cause": "USER_REPORT",
            "category": category,
            "status": "OPEN",
            "assigned_operator_id": None,
            "sla_minutes": 1440,
            "opened_minute": opened,
            "resolved_minute": None,
            "resolution_note": None,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        work_orders[wo_id] = wo

        recompute_region_counts(region_id)
        write_audit(
            event_kind="OPS_ACTION",
            action="BIKE_FAULT_OPEN",
            subject_type="Bike",
            subject_id=bike_id,
            before={"status": "AVAILABLE"},
            after={"status": "FAULT", "fault_categories": list(bike["fault_categories"])},
            region_id=region_id,
        )

    from services.workorders_calc import serialize_workorder
    return success_object(serialize_workorder(wo), status=201)


@bp.post("/bikes/<bike_id>/scrap")
def scrap_bike(bike_id):
    require_role("Admin")
    bike = bikes.get(bike_id)
    if bike is None:
        raise_err(ERR_NOT_FOUND, "Bike not found")
    with LOCK:
        if bike["shelf_state"] == "SCRAPPED":
            raise_err(ERR_INVALID_STATE, "Bike is already SCRAPPED")
        if bike["status"] == "IN_USE":
            raise_err(ERR_BIKE_IN_USE, "Cannot scrap a bike that is IN_USE")
        # Find an unscrapped LossRecord referencing this bike.
        lr_match = None
        for lr in loss_records.values():
            if lr.get("bike_id") == bike_id and not lr.get("scrapped"):
                lr_match = lr
                break
        if lr_match is None:
            raise_err(ERR_NO_LOSS_RECORD, "No unscrapped LossRecord for this bike")
        region_id = bike.get("region_id")
        before = {"shelf_state": bike["shelf_state"], "status": bike["status"]}
        bike["shelf_state"] = "SCRAPPED"
        bump_version(bike)
        lr_match["scrapped"] = True
        recompute_region_counts(region_id)
        write_audit(
            event_kind="OPS_ACTION",
            action="BIKE_SCRAP",
            subject_type="Bike",
            subject_id=bike_id,
            before=before,
            after={"shelf_state": bike["shelf_state"]},
            region_id=region_id,
        )
    return success_object(serialize_bike(bike))


@bp.get("/regions/<region_id>/bikes")
def list_region_bikes(region_id):
    require_role("Admin", "Operator", "FieldStaff", "Rider")
    if region_id not in regions:
        raise_err(ERR_NOT_FOUND, "Region not found")
    status_filter = request.args.get("status")
    shelf_filter = request.args.get("shelf_state")
    if status_filter is not None and status_filter not in BIKE_STATUSES:
        raise_err(ERR_VALIDATION, "status filter invalid")
    if shelf_filter is not None and shelf_filter not in BIKE_SHELF_STATES:
        raise_err(ERR_VALIDATION, "shelf_state filter invalid")
    items = [b for b in bikes.values() if b.get("region_id") == region_id]
    if status_filter is not None:
        items = [b for b in items if b.get("status") == status_filter]
    if shelf_filter is not None:
        items = [b for b in items if b.get("shelf_state") == shelf_filter]
    items.sort(key=lambda b: b["created_at"])
    limit, offset = parse_pagination()
    total = len(items)
    window = items[offset:offset + limit]
    return success_list([serialize_bike(b) for b in window], limit=limit, offset=offset, total_count=total)
