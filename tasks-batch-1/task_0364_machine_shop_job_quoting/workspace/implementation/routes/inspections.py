"""InspectionStation and Inspection routes (PRD §3.5)."""
from flask import Blueprint, request

from db import db, lock, base_fields, touch
from errors import err
from middleware import require_roles, require_auth
from helpers import (
    get_body, require_fields, validate_enum, as_int, as_str,
    paginate, serialize, serialize_list,
)
from response import success, list_response
import calculations as calc
import services as svc

bp = Blueprint("inspections", __name__)

INSPECTION_MODES = {"FAI", "IN_PROCESS", "FINAL"}
STATION_MODES = {"FAI", "IN_PROCESS", "FINAL", "ALL"}


def get_station_or_404(station_id):
    st = db.inspection_stations.get(station_id)
    if st is None:
        raise err("ERR_NOT_FOUND", "InspectionStation not found")
    return st


def get_inspection_or_404(inspection_id):
    insp = db.inspections.get(inspection_id)
    if insp is None:
        raise err("ERR_NOT_FOUND", "Inspection not found")
    return insp


# ---------------------------------------------------------------------------
# InspectionStation (configuration entity: id + created_at only)
# ---------------------------------------------------------------------------


@bp.route("/inspection-stations", methods=["POST"])
def create_inspection_station():
    require_roles("ShopAdmin", "Inspector")
    body = get_body()
    require_fields(body, "name", "supports_mode")
    name = as_str(body, "name")
    supports_mode = body["supports_mode"]
    validate_enum(supports_mode, STATION_MODES, "supports_mode")
    buffer_min = body.get("buffer_min")
    if buffer_min is None:
        buffer_min = 15
    else:
        buffer_min = as_int(body, "buffer_min")
    with lock():
        rec = base_fields(with_version=False)  # no updated_at / version
        rec.update({
            "name": name,
            "supports_mode": supports_mode,
            "buffer_min": buffer_min,
        })
        db.inspection_stations[rec["id"]] = rec
        return success(serialize(rec), status=201)


@bp.route("/inspection-stations/<station_id>", methods=["GET"])
def get_inspection_station(station_id):
    require_auth()
    with lock():
        return success(serialize(get_station_or_404(station_id)))


# ---------------------------------------------------------------------------
# Inspection
# ---------------------------------------------------------------------------


@bp.route("/inspections", methods=["POST"])
def create_inspection():
    require_roles("Inspector")
    body = get_body()
    require_fields(body, "work_order_id", "inspection_station_id", "mode",
                   "window_start_min", "window_end_min")
    work_order_id = as_str(body, "work_order_id")
    inspection_station_id = as_str(body, "inspection_station_id")
    mode = body["mode"]
    validate_enum(mode, INSPECTION_MODES, "mode")
    window_start_min = as_int(body, "window_start_min")
    window_end_min = as_int(body, "window_end_min")
    if window_end_min < window_start_min:
        raise err("ERR_INVALID_REQUEST", "window_end_min must be >= window_start_min")
    with lock():
        # existence: body FKs left to right (work_order_id then station)
        if work_order_id not in db.work_orders:
            raise err("ERR_NOT_FOUND", "WorkOrder not found")
        station = db.inspection_stations.get(inspection_station_id)
        if station is None:
            raise err("ERR_NOT_FOUND", "InspectionStation not found")

        # station mode capability (priority 10)
        supports = station["supports_mode"]
        if supports != "ALL" and mode != supports:
            raise err("ERR_STATION_MODE_UNSUPPORTED", "Station does not support this mode")

        # buffered closed-interval overlap on same station (priority 10)
        buffer_min = station["buffer_min"]
        new_start = window_start_min - buffer_min
        new_end = window_end_min + buffer_min
        for insp in db.inspections.values():
            if insp["inspection_station_id"] != inspection_station_id:
                continue
            if insp["status"] not in ("OPEN", "DISPOSITIONED"):
                continue
            # closed intervals overlap if start <= other_end and other_start <= end
            if new_start <= insp["window_end_min"] and insp["window_start_min"] <= new_end:
                raise err("ERR_STATION_CONFLICT", "Inspection window overlaps another on this station")

        rec = base_fields()
        rec.update({
            "work_order_id": work_order_id,
            "inspection_station_id": inspection_station_id,
            "mode": mode,
            "window_start_min": window_start_min,
            "window_end_min": window_end_min,
            "qty_inspected": 0,
            "qty_accepted": 0,
            "qty_rework": 0,
            "qty_scrap": 0,
            "status": "OPEN",
            "first_pass_yield_pct": 0,
        })
        db.inspections[rec["id"]] = rec
        return success(serialize(rec), status=201)


@bp.route("/inspections/<inspection_id>", methods=["GET"])
def get_inspection(inspection_id):
    require_auth()
    with lock():
        return success(serialize(get_inspection_or_404(inspection_id)))


@bp.route("/inspections", methods=["GET"])
def list_inspections():
    require_auth()
    work_order_id = request.args.get("work_order_id")
    inspection_station_id = request.args.get("inspection_station_id")
    status = request.args.get("status")
    with lock():
        items = list(db.inspections.values())
        if work_order_id:
            items = [i for i in items if i["work_order_id"] == work_order_id]
        if inspection_station_id:
            items = [i for i in items if i["inspection_station_id"] == inspection_station_id]
        if status:
            items = [i for i in items if i["status"] == status]
        page, limit, offset, total = paginate(items)
        return list_response(serialize_list(page), limit, offset, total)


@bp.route("/inspections/<inspection_id>/disposition", methods=["POST"])
def disposition_inspection(inspection_id):
    require_roles("Inspector")
    body = get_body()
    require_fields(body, "qty_inspected", "qty_accepted", "qty_rework", "qty_scrap")
    qty_inspected = as_int(body, "qty_inspected", minimum=0)
    qty_accepted = as_int(body, "qty_accepted", minimum=0)
    qty_rework = as_int(body, "qty_rework", minimum=0)
    qty_scrap = as_int(body, "qty_scrap", minimum=0)
    with lock():
        insp = get_inspection_or_404(inspection_id)
        # state legality (priority 5)
        if insp["status"] != "OPEN":
            raise err("ERR_INVALID_STATE", "Inspection must be OPEN to disposition")
        wo = db.work_orders.get(insp["work_order_id"])
        # cross-entity precondition (priority 7): WO must be IN_PROCESS
        if wo is None or wo["status"] != "IN_PROCESS":
            raise err("ERR_WO_NOT_IN_PROCESS", "WorkOrder is not IN_PROCESS")
        # QC mode safety gate (priority 8)
        pl = db.part_lines.get(wo["part_line_id"])
        if pl is not None and pl["tolerance_class"] == "CRITICAL":
            if insp["mode"] not in ("FAI", "FINAL"):
                raise err("ERR_INSPECTION_MODE_REQUIRED",
                          "CRITICAL part must be dispositioned via FAI or FINAL")
        # disposition arithmetic (priority 11)
        if qty_inspected != qty_accepted + qty_rework + qty_scrap:
            raise err("ERR_DISPOSITION_QTY_MISMATCH",
                      "qty_inspected must equal accepted + rework + scrap")
        if qty_inspected > wo["qty_in_process"]:
            raise err("ERR_DISPOSITION_EXCEEDS_WIP", "qty_inspected exceeds qty_in_process")

        # commit
        insp["qty_inspected"] = qty_inspected
        insp["qty_accepted"] = qty_accepted
        insp["qty_rework"] = qty_rework
        insp["qty_scrap"] = qty_scrap
        insp["first_pass_yield_pct"] = calc.first_pass_yield(qty_accepted, qty_inspected)
        insp["status"] = "DISPOSITIONED"
        touch(insp)

        # cascade onto WorkOrder counters
        wo["qty_in_process"] -= qty_inspected
        wo["qty_accepted"] += qty_accepted
        wo["qty_rework_pending"] += qty_rework
        wo["qty_scrapped"] += qty_scrap
        touch(wo)
        # bubble-up: IN_PROCESS -> COMPLETED
        svc.maybe_bubble_wo_in_process_to_completed(wo)

        return success(serialize(insp))
