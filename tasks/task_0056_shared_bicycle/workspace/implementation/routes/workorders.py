"""WorkOrder endpoints (PRD §3.6, §3.9)."""
from __future__ import annotations

from flask import Blueprint, request

from db import LOCK, bikes, new_id, regions, work_orders
from errors import (
    ERR_NOT_FOUND,
    ERR_OPERATOR_REQUIRED,
    ERR_REFERENCE_NOT_FOUND,
    ERR_VALIDATION,
    ERR_WORKORDER_NOT_ASSIGNED,
    ERR_WORKORDER_NOT_OPEN,
    raise_err,
)
from middleware import require_role
from response import success_list, success_object
from services.audit import write_audit
from services.regions import recompute_region_counts
from services.validators import (
    bump_version,
    ensure_enum,
    ensure_positive_int,
    get_json_body,
    parse_pagination,
)
from services.workorders_calc import serialize_workorder
from time_utils import now_iso


bp = Blueprint("workorders", __name__)


WORKORDER_CAUSES = {"USER_REPORT", "LONG_STATIONARY", "LOCK_ABNORMAL", "LOW_BATTERY", "RECALL"}
WORKORDER_CATEGORIES = {"FLAT_TIRE", "BRAKE", "LOCK_FAILURE", "BATTERY_SWAP", "CHARGING", "OTHER"}
WORKORDER_STATUSES = {"OPEN", "ASSIGNED", "RESOLVED", "CANCELLED"}


def _open_or_assigned_for_bike(bike_id: str, exclude_id: str | None = None) -> bool:
    for wo in work_orders.values():
        if wo["bike_id"] != bike_id:
            continue
        if exclude_id and wo["id"] == exclude_id:
            continue
        if wo["status"] in ("OPEN", "ASSIGNED"):
            return True
    return False


@bp.post("/workorders")
def create_workorder():
    require_role("Operator", "Admin")
    body = get_json_body()
    if "bike_id" not in body:
        raise_err(ERR_VALIDATION, "bike_id is required")
    bike_id = body["bike_id"]
    if "cause" not in body:
        raise_err(ERR_VALIDATION, "cause is required")
    cause = ensure_enum(body["cause"], "cause", WORKORDER_CAUSES)
    if "category" not in body:
        raise_err(ERR_VALIDATION, "category is required")
    category = ensure_enum(body["category"], "category", WORKORDER_CATEGORIES)
    if "sla_minutes" not in body:
        raise_err(ERR_VALIDATION, "sla_minutes is required")
    sla = ensure_positive_int(body["sla_minutes"], "sla_minutes")

    with LOCK:
        bike = bikes.get(bike_id)
        if bike is None:
            raise_err(ERR_REFERENCE_NOT_FOUND, "bike_id not found")
        region_id = bike.get("region_id")
        region = regions.get(region_id) if region_id else None
        opened = region.get("clock_minutes", 0) if region else 0

        wo_id = new_id()
        ts = now_iso()
        wo = {
            "id": wo_id,
            "bike_id": bike_id,
            "region_id": region_id,
            "cause": cause,
            "category": category,
            "status": "OPEN",
            "assigned_operator_id": None,
            "sla_minutes": sla,
            "opened_minute": opened,
            "resolved_minute": None,
            "resolution_note": None,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        work_orders[wo_id] = wo

        # Flip bike to FAULT if it isn't already.
        if bike["status"] != "FAULT":
            prev = bike["status"]
            bike["status"] = "FAULT"
            if category not in bike["fault_categories"]:
                bike["fault_categories"].append(category)
            bump_version(bike)
            recompute_region_counts(region_id)
            write_audit(
                event_kind="OPS_ACTION",
                action="BIKE_FAULT_OPEN",
                subject_type="Bike",
                subject_id=bike_id,
                before={"status": prev},
                after={"status": "FAULT"},
                region_id=region_id,
            )
        else:
            if category not in bike["fault_categories"]:
                bike["fault_categories"].append(category)
                bump_version(bike)
    return success_object(serialize_workorder(wo), status=201)


@bp.post("/workorders/<workorder_id>/assign")
def assign_workorder(workorder_id):
    require_role("Operator", "Admin")
    wo = work_orders.get(workorder_id)
    if wo is None:
        raise_err(ERR_NOT_FOUND, "WorkOrder not found")
    body = get_json_body()
    if "assigned_operator_id" not in body or not isinstance(body["assigned_operator_id"], str) or not body["assigned_operator_id"]:
        raise_err(ERR_OPERATOR_REQUIRED, "assigned_operator_id is required")
    operator_id = body["assigned_operator_id"]

    with LOCK:
        wo = work_orders[workorder_id]
        if wo["status"] != "OPEN":
            raise_err(ERR_WORKORDER_NOT_OPEN, "WorkOrder is not OPEN")
        wo["status"] = "ASSIGNED"
        wo["assigned_operator_id"] = operator_id
        bump_version(wo)
        write_audit(
            event_kind="OPS_ACTION",
            action="WORKORDER_ASSIGN",
            subject_type="WorkOrder",
            subject_id=workorder_id,
            before={"status": "OPEN"},
            after={"status": "ASSIGNED", "assigned_operator_id": operator_id},
            region_id=wo.get("region_id"),
        )
    return success_object(serialize_workorder(wo))


@bp.post("/workorders/<workorder_id>/resolve")
def resolve_workorder(workorder_id):
    require_role("Operator")
    wo = work_orders.get(workorder_id)
    if wo is None:
        raise_err(ERR_NOT_FOUND, "WorkOrder not found")
    body = get_json_body()
    note = body.get("resolution_note")
    if not isinstance(note, str) or not note:
        raise_err(ERR_VALIDATION, "resolution_note is required")

    with LOCK:
        wo = work_orders[workorder_id]
        if wo["status"] != "ASSIGNED":
            raise_err(ERR_WORKORDER_NOT_ASSIGNED, "WorkOrder is not ASSIGNED")
        region = regions.get(wo.get("region_id"))
        clock = int(region.get("clock_minutes", 0)) if region else 0
        wo["status"] = "RESOLVED"
        wo["resolved_minute"] = clock
        wo["resolution_note"] = note
        bump_version(wo)

        # Clear category from bike; flip status if no remaining work.
        bike = bikes.get(wo["bike_id"])
        if bike:
            cat = wo.get("category")
            if cat and cat in bike["fault_categories"]:
                bike["fault_categories"].remove(cat)
            still_open = _open_or_assigned_for_bike(bike["id"], exclude_id=workorder_id)
            if not still_open and not bike["fault_categories"] and bike["status"] == "FAULT":
                bike["status"] = "AVAILABLE"
                bump_version(bike)
                recompute_region_counts(bike.get("region_id"))
            else:
                bump_version(bike)
        write_audit(
            event_kind="OPS_ACTION",
            action="WORKORDER_RESOLVE",
            subject_type="WorkOrder",
            subject_id=workorder_id,
            before={"status": "ASSIGNED"},
            after={"status": "RESOLVED"},
            region_id=wo.get("region_id"),
        )
    return success_object(serialize_workorder(wo))


@bp.post("/workorders/<workorder_id>/cancel")
def cancel_workorder(workorder_id):
    require_role("Operator", "Admin")
    wo = work_orders.get(workorder_id)
    if wo is None:
        raise_err(ERR_NOT_FOUND, "WorkOrder not found")
    with LOCK:
        wo = work_orders[workorder_id]
        if wo["status"] != "OPEN":
            raise_err(ERR_WORKORDER_NOT_OPEN, "WorkOrder is not OPEN")
        wo["status"] = "CANCELLED"
        bump_version(wo)
        bike = bikes.get(wo["bike_id"])
        if bike:
            cat = wo.get("category")
            if cat and cat in bike["fault_categories"]:
                bike["fault_categories"].remove(cat)
            still_open = _open_or_assigned_for_bike(bike["id"], exclude_id=workorder_id)
            if not still_open and not bike["fault_categories"] and bike["status"] == "FAULT":
                bike["status"] = "AVAILABLE"
                bump_version(bike)
                recompute_region_counts(bike.get("region_id"))
    return success_object(serialize_workorder(wo))


@bp.get("/workorders/<workorder_id>")
def get_workorder(workorder_id):
    require_role("Operator", "Admin")
    wo = work_orders.get(workorder_id)
    if wo is None:
        raise_err(ERR_NOT_FOUND, "WorkOrder not found")
    return success_object(serialize_workorder(wo))


@bp.get("/workorders")
def list_workorders():
    require_role("Operator", "Admin")
    status_filter = request.args.get("status")
    region_filter = request.args.get("region_id")
    sla_filter = request.args.get("sla_breached")

    if status_filter is not None and status_filter not in WORKORDER_STATUSES:
        raise_err(ERR_VALIDATION, "status filter invalid")

    items = list(work_orders.values())
    if status_filter is not None:
        items = [w for w in items if w.get("status") == status_filter]
    if region_filter is not None:
        items = [w for w in items if w.get("region_id") == region_filter]

    items.sort(key=lambda w: w["created_at"])
    serialized = [serialize_workorder(w) for w in items]

    if sla_filter is not None:
        if sla_filter.lower() in ("true", "1"):
            want = True
        elif sla_filter.lower() in ("false", "0"):
            want = False
        else:
            raise_err(ERR_VALIDATION, "sla_breached filter must be boolean")
        serialized = [w for w in serialized if w["sla_breached"] == want]

    limit, offset = parse_pagination()
    total = len(serialized)
    window = serialized[offset:offset + limit]
    return success_list(window, limit=limit, offset=offset, total_count=total)
