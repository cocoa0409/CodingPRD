"""MaintenanceWindow endpoints."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, request

from db import STORE, new_id, now_utc
from errors import (
    ApiError,
    ERR_STATION_NOT_FOUND,
    ERR_COMPRESSOR_NOT_FOUND,
    ERR_MAINTENANCE_WINDOW_NOT_FOUND,
    ERR_WINDOW_NOT_STARTABLE,
    ERR_WINDOW_NOT_IN_TIME_RANGE,
    ERR_WINDOW_NOT_COMPLETABLE,
    ERR_WINDOW_NOT_CANCELLABLE,
    ERR_COMPRESSOR_UNDER_MAINTENANCE,
    ERR_BACKUP_REQUIRED,
    ERR_OVERDUE_INSPECTION,
    ERR_INVALID_TIME_RANGE,
    ERR_WINDOW_OVERLAP,
)
from middleware import get_caller, require_role
from response import success_object, success_list
from serializers import maintenance_window_out
from services.core import (
    recompute_station_posture,
    station_has_overdue_inspection,
    touch,
    TURNAROUND_HOURS,
)
from validators import (
    body, require_fields, require_string, require_enum, require_datetime,
    parse_pagination, paginate,
)

bp = Blueprint("maintenance", __name__)

_ALL_READ = ["NetworkOperator", "StationManager", "ComplianceOfficer",
             "FleetAccountManager", "FleetDriver"]

_WINDOW_TYPES = {"PREVENTIVE", "CORRECTIVE", "EMERGENCY"}


def get_window_or_404(wid: str) -> dict:
    w = STORE.maintenance_windows.get(wid)
    if w is None:
        raise ApiError(ERR_MAINTENANCE_WINDOW_NOT_FOUND, 404,
                       "Maintenance window id does not exist")
    return w


def _resource_key(window: dict) -> str:
    """compressor-linked windows key on the compressor; whole-station windows
    key on the station itself. The two kinds never conflict."""
    if window["compressor_id"] is not None:
        return f"compressor:{window['compressor_id']}"
    return f"station:{window['station_id']}"


def _check_window_overlap(new: dict, skip_emergency_buffer: bool) -> None:
    key = _resource_key(new)
    for w in STORE.maintenance_windows.values():
        if w["id"] == new.get("id"):
            continue
        if w["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        if _resource_key(w) != key:
            continue
        # Overlap: half-open
        if new["starts_at"] < w["ends_at"] and w["starts_at"] < new["ends_at"]:
            raise ApiError(ERR_WINDOW_OVERLAP, 409,
                           "Maintenance window overlaps an existing window on the same resource")
        if skip_emergency_buffer:
            continue
        # Turnaround buffer (only when non-overlapping)
        buffer = timedelta(hours=TURNAROUND_HOURS)
        if new["starts_at"] >= w["ends_at"]:
            if new["starts_at"] - w["ends_at"] < buffer:
                raise ApiError(ERR_WINDOW_OVERLAP, 409,
                               "Insufficient turnaround buffer after existing window")
        elif w["starts_at"] >= new["ends_at"]:
            if w["starts_at"] - new["ends_at"] < buffer:
                raise ApiError(ERR_WINDOW_OVERLAP, 409,
                               "Insufficient turnaround buffer before existing window")


@bp.post("/cng/maintenance-windows")
def create_window():
    caller = get_caller()
    require_role(caller, ["StationManager"])
    data = body()
    require_fields(data, ["station_id", "starts_at", "ends_at", "window_type"])
    station_id = require_string(data, "station_id")
    compressor_id = data.get("compressor_id")
    if compressor_id is not None and not isinstance(compressor_id, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "compressor_id must be a string or null")
    starts_at = require_datetime(data, "starts_at")
    ends_at = require_datetime(data, "ends_at")
    window_type = require_enum(data, "window_type", _WINDOW_TYPES)

    # Existence (stage 4)
    if station_id not in STORE.stations:
        raise ApiError(ERR_STATION_NOT_FOUND, 404, "Station id does not exist")
    if compressor_id is not None:
        comp = STORE.compressors.get(compressor_id)
        if comp is None:
            raise ApiError(ERR_COMPRESSOR_NOT_FOUND, 404, "Compressor id does not exist")
        # Compressor must belong to this station
        if comp["station_id"] != station_id:
            raise ApiError(ERR_COMPRESSOR_NOT_FOUND, 404,
                           "Compressor does not belong to this station")

    # Safety (stage 7): non-EMERGENCY blocked while any inspection OVERDUE
    if window_type != "EMERGENCY" and station_has_overdue_inspection(station_id):
        raise ApiError(ERR_OVERDUE_INSPECTION, 409,
                       "Station has an OVERDUE safety inspection")

    # Uniqueness/overlap (stage 8)
    now = now_utc()
    new_window = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "station_id": station_id,
        "compressor_id": compressor_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "window_type": window_type,
        "status": "SCHEDULED",
    }
    _check_window_overlap(new_window, skip_emergency_buffer=(window_type == "EMERGENCY"))

    # Temporal (stage 9)
    if not starts_at < ends_at:
        raise ApiError(ERR_INVALID_TIME_RANGE, 422,
                       "starts_at must be strictly earlier than ends_at")

    STORE.maintenance_windows[new_window["id"]] = new_window
    return success_object(maintenance_window_out(new_window), status=201)


@bp.get("/cng/maintenance-windows")
def list_windows():
    caller = get_caller()
    require_role(caller, _ALL_READ)
    limit, offset = parse_pagination()
    station_id = request.args.get("station_id")
    compressor_id = request.args.get("compressor_id")
    status = request.args.get("status")
    items = sorted(STORE.maintenance_windows.values(), key=lambda w: (w["created_at"], w["id"]))
    if station_id is not None:
        items = [w for w in items if w["station_id"] == station_id]
    if compressor_id is not None:
        items = [w for w in items if w["compressor_id"] == compressor_id]
    if status is not None:
        items = [w for w in items if w["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([maintenance_window_out(w) for w in page], limit, offset, total)


@bp.get("/cng/maintenance-windows/<windowId>")
def get_window(windowId: str):
    caller = get_caller()
    require_role(caller, _ALL_READ)
    return success_object(maintenance_window_out(get_window_or_404(windowId)))


def _start_would_remove_last_capacity(window: dict) -> bool:
    """True when starting this window would remove the station's last online
    compression capacity: linked compressor is the only one in
    {ONLINE, DEGRADED}, or whole-station window while any capacity exists
    (any fueling capacity would be lost)."""
    station_id = window["station_id"]
    online = [
        c for c in STORE.compressors.values()
        if c["station_id"] == station_id and c["condition"] in ("ONLINE", "DEGRADED")
    ]
    if window["compressor_id"] is not None:
        return len(online) == 1 and online[0]["id"] == window["compressor_id"]
    # Whole-station window: any fueling capacity would be lost
    return len(online) > 0


def _has_covering_backup(window: dict) -> bool:
    for b in STORE.backup_arrangements.values():
        if b["station_id"] != window["station_id"]:
            continue
        if b["status"] != "ACTIVATED":
            continue
        if b["available_from"] <= window["starts_at"] and b["available_until"] >= window["ends_at"]:
            return True
    return False


@bp.post("/cng/maintenance-windows/<windowId>/start")
def start_window(windowId: str):
    caller = get_caller()
    require_role(caller, ["StationManager"])
    window = get_window_or_404(windowId)
    if window["status"] != "SCHEDULED":
        raise ApiError(ERR_WINDOW_NOT_STARTABLE, 409,
                       "Window start requires SCHEDULED")
    now = now_utc()
    if not (window["starts_at"] <= now < window["ends_at"]):
        raise ApiError(ERR_WINDOW_NOT_IN_TIME_RANGE, 409,
                       "Window start requires starts_at <= now < ends_at")
    comp = None
    if window["compressor_id"] is not None:
        comp = STORE.compressors.get(window["compressor_id"])
        if comp is not None and comp["condition"] == "UNDER_MAINTENANCE":
            raise ApiError(ERR_COMPRESSOR_UNDER_MAINTENANCE, 409,
                           "Compressor already UNDER_MAINTENANCE")
    # Continuity-of-service gate (safety stage)
    if window["window_type"] != "EMERGENCY" and _start_would_remove_last_capacity(window):
        if not _has_covering_backup(window):
            raise ApiError(ERR_BACKUP_REQUIRED, 409,
                           "Starting this window requires a covering ACTIVATED backup arrangement")

    window["status"] = "IN_PROGRESS"
    touch(window)
    if comp is not None:
        comp["condition"] = "UNDER_MAINTENANCE"
        touch(comp)
    recompute_station_posture(window["station_id"])
    return success_object(maintenance_window_out(window))


@bp.post("/cng/maintenance-windows/<windowId>/complete")
def complete_window(windowId: str):
    caller = get_caller()
    require_role(caller, ["StationManager"])
    window = get_window_or_404(windowId)
    if window["status"] != "IN_PROGRESS":
        raise ApiError(ERR_WINDOW_NOT_COMPLETABLE, 409,
                       "Window complete requires IN_PROGRESS")
    window["status"] = "COMPLETED"
    touch(window)
    if window["compressor_id"] is not None:
        comp = STORE.compressors.get(window["compressor_id"])
        if comp is not None:
            comp["condition"] = "ONLINE"
            touch(comp)
    recompute_station_posture(window["station_id"])
    return success_object(maintenance_window_out(window))


@bp.post("/cng/maintenance-windows/<windowId>/cancel")
def cancel_window(windowId: str):
    caller = get_caller()
    require_role(caller, ["StationManager"])
    window = get_window_or_404(windowId)
    if window["status"] != "SCHEDULED":
        raise ApiError(ERR_WINDOW_NOT_CANCELLABLE, 409,
                       "Window cancel requires SCHEDULED")
    window["status"] = "CANCELLED"
    touch(window)
    return success_object(maintenance_window_out(window))
