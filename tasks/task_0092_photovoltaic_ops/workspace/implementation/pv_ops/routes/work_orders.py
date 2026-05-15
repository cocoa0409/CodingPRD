"""Work order endpoints: dispatch (under defect), start, complete, cancel."""
from __future__ import annotations

from flask import Blueprint, current_app, g

from pv_ops.auth import require_roles
from pv_ops.errors import (
    APIError,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_SPARE_PART_INSUFFICIENT,
    ERR_SUPPLIER_BLACKLISTED,
    ERR_VALIDATION,
)
from pv_ops.responses import created, success
from pv_ops.services import serializers
from pv_ops.services.cascades import recompute_station_operational_status
from pv_ops.utils import (
    fmt_dt,
    get_body,
    parse_dt,
    require_int,
    require_list,
    require_str,
)


bp = Blueprint("work_orders", __name__)


@bp.route("/pv-ops/defects/<defect_id>/work-orders", methods=["POST"])
@require_roles("O&MEngineer")
def dispatch_work_order(defect_id: str):
    body = get_body()
    assigned_supplier_id = require_str(body, "assigned_supplier_id")
    assigned_technician_id = require_str(body, "assigned_technician_id")
    scheduled_start = parse_dt(body.get("scheduled_start"), "scheduled_start")
    scheduled_end = parse_dt(body.get("scheduled_end"), "scheduled_end")
    if scheduled_end <= scheduled_start:
        raise APIError(ERR_VALIDATION, 422, "scheduled_end must be after scheduled_start")
    spare_part_lines = require_list(body, "spare_part_lines", min_len=0)
    if "before_metrics" not in body or not isinstance(body["before_metrics"], dict):
        raise APIError(ERR_VALIDATION, 422, "before_metrics object required")
    before_metrics = body["before_metrics"]

    # Validate spare_part_lines shape
    normalized_lines = []
    for line in spare_part_lines:
        if not isinstance(line, dict):
            raise APIError(ERR_VALIDATION, 422, "Each spare_part_line must be an object")
        pid = line.get("part_id")
        qty = line.get("quantity")
        if not isinstance(pid, str) or not isinstance(qty, int) or isinstance(qty, bool) or qty <= 0:
            raise APIError(ERR_VALIDATION, 422, "spare_part_lines entries need part_id and positive integer quantity")
        normalized_lines.append({"part_id": pid, "quantity": qty})

    store = current_app.extensions["store"]
    with store.lock:
        defect = store.defects.get(defect_id)
        if not defect:
            raise APIError(ERR_NOT_FOUND, 404, "Defect not found")
        supplier = store.suppliers.get(assigned_supplier_id)
        if not supplier:
            raise APIError(ERR_NOT_FOUND, 404, "Supplier not found")
        # State check on defect
        if defect.get("state") not in ("OPEN", "REOPENED"):
            raise APIError(ERR_INVALID_STATE, 409, "Defect must be OPEN or REOPENED")
        # Supplier blacklist
        if supplier.get("lifecycle_state") == "BLACKLISTED":
            raise APIError(ERR_SUPPLIER_BLACKLISTED, 422, "Supplier is BLACKLISTED")
        # Validate parts exist
        for line in normalized_lines:
            part = store.spare_parts.get(line["part_id"])
            if not part:
                raise APIError(ERR_NOT_FOUND, 404, "Spare part not found")
        # Atomic reservation: all-or-nothing
        for line in normalized_lines:
            part = store.spare_parts[line["part_id"]]
            available = int(part.get("stock_on_hand", 0)) - int(part.get("reserved_qty", 0))
            if available < line["quantity"]:
                raise APIError(
                    ERR_SPARE_PART_INSUFFICIENT,
                    422,
                    f"Insufficient stock for part {line['part_id']}",
                )
        # Commit
        for line in normalized_lines:
            part = store.spare_parts[line["part_id"]]
            part["reserved_qty"] = int(part.get("reserved_qty", 0)) + line["quantity"]
            store.bump(part)

        wo = {
            "defect_id": defect_id,
            "assigned_supplier_id": assigned_supplier_id,
            "assigned_technician_id": assigned_technician_id,
            "scheduled_start": fmt_dt(scheduled_start),
            "scheduled_end": fmt_dt(scheduled_end),
            "actual_start": None,
            "actual_end": None,
            "before_metrics": dict(before_metrics),
            "after_metrics": None,
            "spare_part_lines": normalized_lines,
            "state": "DISPATCHED",
        }
        store.insert_common(wo)
        store.work_orders[wo["id"]] = wo

        # Defect goes to DISPATCHED
        defect["state"] = "DISPATCHED"
        store.bump(defect)
        return created(serializers.work_order_view(wo))


@bp.route("/pv-ops/work-orders/<wo_id>/start", methods=["POST"])
@require_roles("FieldOperator")
def start_work_order(wo_id: str):
    store = current_app.extensions["store"]
    with store.lock:
        wo = store.work_orders.get(wo_id)
        if not wo:
            raise APIError(ERR_NOT_FOUND, 404, "Work order not found")
        if wo.get("state") != "DISPATCHED":
            raise APIError(ERR_INVALID_STATE, 409, "Work order not in DISPATCHED")
        defect = store.defects.get(wo["defect_id"])
        if not defect:
            raise APIError(ERR_NOT_FOUND, 404, "Defect not found")
        if defect.get("state") != "DISPATCHED":
            raise APIError(ERR_INVALID_STATE, 409, "Defect not in DISPATCHED")
        wo["state"] = "IN_PROGRESS"
        wo["actual_start"] = store.clock.now_iso()
        store.bump(wo)
        defect["state"] = "UNDER_REPAIR"
        store.bump(defect)
        return success(serializers.work_order_view(wo))


@bp.route("/pv-ops/work-orders/<wo_id>/complete", methods=["POST"])
@require_roles("FieldOperator")
def complete_work_order(wo_id: str):
    body = get_body()
    if "after_metrics" not in body or not isinstance(body["after_metrics"], dict) or len(body["after_metrics"]) == 0:
        raise APIError(ERR_VALIDATION, 422, "after_metrics non-empty object required")
    after_metrics = body["after_metrics"]
    store = current_app.extensions["store"]
    with store.lock:
        wo = store.work_orders.get(wo_id)
        if not wo:
            raise APIError(ERR_NOT_FOUND, 404, "Work order not found")
        if wo.get("state") != "IN_PROGRESS":
            raise APIError(ERR_INVALID_STATE, 409, "Work order not IN_PROGRESS")
        if not wo.get("before_metrics") or len(wo["before_metrics"]) == 0:
            raise APIError(ERR_VALIDATION, 422, "before_metrics must be non-empty")
        # Verify spare-part consumption is feasible: stock_on_hand >= line.quantity
        for line in wo.get("spare_part_lines", []):
            part = store.spare_parts.get(line["part_id"])
            if not part:
                raise APIError(ERR_NOT_FOUND, 404, "Spare part not found")
            if int(part.get("stock_on_hand", 0)) < line["quantity"]:
                raise APIError(
                    ERR_SPARE_PART_INSUFFICIENT,
                    422,
                    f"Insufficient stock to consume for part {line['part_id']}",
                )

        wo["state"] = "COMPLETED"
        wo["actual_end"] = store.clock.now_iso()
        wo["after_metrics"] = dict(after_metrics)
        store.bump(wo)

        # Consume parts
        for line in wo.get("spare_part_lines", []):
            part = store.spare_parts[line["part_id"]]
            part["stock_on_hand"] = int(part.get("stock_on_hand", 0)) - line["quantity"]
            part["reserved_qty"] = int(part.get("reserved_qty", 0)) - line["quantity"]
            if part["reserved_qty"] < 0:
                part["reserved_qty"] = 0
            store.bump(part)

        # Cascade: Defect -> RESOLVED
        defect = store.defects.get(wo["defect_id"])
        if defect:
            defect["state"] = "RESOLVED"
            defect["resolved_at"] = store.clock.now_iso()
            store.bump(defect)
            # Cascade hop 2: inverter lifecycle revert
            if defect.get("subject_type") == "INVERTER":
                inv = store.inverters.get(defect.get("subject_id"))
                if inv and inv.get("lifecycle_state") == "UNDER_REPAIR":
                    inv["lifecycle_state"] = "OPERATING"
                    store.bump(inv)
                    station = store.stations.get(inv.get("station_id"))
                    if station:
                        recompute_station_operational_status(store, station)
        return success(serializers.work_order_view(wo))


@bp.route("/pv-ops/work-orders/<wo_id>/cancel", methods=["POST"])
@require_roles("O&MEngineer")
def cancel_work_order(wo_id: str):
    store = current_app.extensions["store"]
    with store.lock:
        wo = store.work_orders.get(wo_id)
        if not wo:
            raise APIError(ERR_NOT_FOUND, 404, "Work order not found")
        if wo.get("state") != "DISPATCHED":
            raise APIError(ERR_INVALID_STATE, 409, "Only DISPATCHED work orders can be canceled")
        # Release reservations
        for line in wo.get("spare_part_lines", []):
            part = store.spare_parts.get(line["part_id"])
            if part:
                part["reserved_qty"] = int(part.get("reserved_qty", 0)) - line["quantity"]
                if part["reserved_qty"] < 0:
                    part["reserved_qty"] = 0
                store.bump(part)
        wo["state"] = "CANCELED"
        store.bump(wo)
        # Defect reverts to OPEN
        defect = store.defects.get(wo["defect_id"])
        if defect:
            defect["state"] = "OPEN"
            store.bump(defect)
        return success(serializers.work_order_view(wo))
