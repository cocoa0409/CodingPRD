"""BackupFuelingArrangement endpoints."""
from __future__ import annotations

from flask import Blueprint, request

from db import STORE, new_id, now_utc
from errors import (
    ApiError,
    ERR_STATION_NOT_FOUND,
    ERR_BACKUP_ARRANGEMENT_NOT_FOUND,
    ERR_BACKUP_NOT_ACTIVATABLE,
    ERR_BACKUP_NOT_IN_WINDOW,
    ERR_BACKUP_NOT_ACTIVE,
    ERR_BACKUP_NOT_RELEASABLE,
    ERR_BACKUP_CAPACITY_EXCEEDED,
    ERR_BACKUP_DRAW_EXCEEDED,
    ERR_INVALID_TIME_RANGE,
)
from middleware import get_caller, require_role
from response import success_object, success_list
from serializers import backup_arrangement_out
from services.core import touch, to_decimal
from validators import (
    body, require_fields, require_string, require_positive_int,
    require_positive_number, require_datetime, parse_pagination, paginate,
)

bp = Blueprint("backups", __name__)

_ALL_READ = ["NetworkOperator", "StationManager", "ComplianceOfficer",
             "FleetAccountManager", "FleetDriver"]


def get_backup_or_404(bid: str) -> dict:
    b = STORE.backup_arrangements.get(bid)
    if b is None:
        raise ApiError(ERR_BACKUP_ARRANGEMENT_NOT_FOUND, 404,
                       "Backup arrangement id does not exist")
    return b


@bp.post("/cng/backup-arrangements")
def create_backup():
    caller = get_caller()
    require_role(caller, ["StationManager"])
    data = body()
    require_fields(data, ["station_id", "partner_station_code",
                          "available_from", "available_until", "committed_gge"])
    station_id = require_string(data, "station_id")
    partner_station_code = require_string(data, "partner_station_code")
    available_from = require_datetime(data, "available_from")
    available_until = require_datetime(data, "available_until")
    committed_gge = require_positive_int(data, "committed_gge")

    # Existence
    station = STORE.stations.get(station_id)
    if station is None:
        raise ApiError(ERR_STATION_NOT_FOUND, 404, "Station id does not exist")

    # Aggregate capacity (stage 8)
    overlap_sum = 0
    for b in STORE.backup_arrangements.values():
        if b["station_id"] != station_id:
            continue
        if b["status"] not in ("RESERVED", "ACTIVATED"):
            continue
        # half-open overlap: a.from < b.until AND b.from < a.until
        if available_from < b["available_until"] and b["available_from"] < available_until:
            overlap_sum += b["committed_gge"]
    if overlap_sum + committed_gge > station["backup_capacity_gge"]:
        raise ApiError(ERR_BACKUP_CAPACITY_EXCEEDED, 409,
                       "Aggregate committed_gge would exceed station backup_capacity_gge")

    # Temporal (stage 9)
    if not available_from < available_until:
        raise ApiError(ERR_INVALID_TIME_RANGE, 422,
                       "available_from must be strictly earlier than available_until")

    now = now_utc()
    arrangement = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "station_id": station_id,
        "partner_station_code": partner_station_code,
        "available_from": available_from,
        "available_until": available_until,
        "committed_gge": committed_gge,
        "used_gge": to_decimal(0),
        "status": "RESERVED",
    }
    STORE.backup_arrangements[arrangement["id"]] = arrangement
    return success_object(backup_arrangement_out(arrangement), status=201)


@bp.get("/cng/backup-arrangements")
def list_backups():
    caller = get_caller()
    require_role(caller, _ALL_READ)
    limit, offset = parse_pagination()
    station_id = request.args.get("station_id")
    status = request.args.get("status")
    items = sorted(STORE.backup_arrangements.values(), key=lambda b: (b["created_at"], b["id"]))
    if station_id is not None:
        items = [b for b in items if b["station_id"] == station_id]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([backup_arrangement_out(b) for b in page], limit, offset, total)


@bp.get("/cng/backup-arrangements/<arrangementId>")
def get_backup(arrangementId: str):
    caller = get_caller()
    require_role(caller, _ALL_READ)
    return success_object(backup_arrangement_out(get_backup_or_404(arrangementId)))


@bp.post("/cng/backup-arrangements/<arrangementId>/activate")
def activate_backup(arrangementId: str):
    caller = get_caller()
    require_role(caller, ["StationManager"])
    b = get_backup_or_404(arrangementId)
    if b["status"] != "RESERVED":
        raise ApiError(ERR_BACKUP_NOT_ACTIVATABLE, 409,
                       "Backup activate requires RESERVED")
    now = now_utc()
    # Both ends inclusive for this check alone
    if not (b["available_from"] <= now <= b["available_until"]):
        raise ApiError(ERR_BACKUP_NOT_IN_WINDOW, 409,
                       "Backup activate requires available_from <= now <= available_until")
    b["status"] = "ACTIVATED"
    touch(b)
    return success_object(backup_arrangement_out(b))


@bp.post("/cng/backup-arrangements/<arrangementId>/record-draw")
def record_draw(arrangementId: str):
    caller = get_caller()
    require_role(caller, ["StationManager"])
    data = body()
    require_fields(data, ["gge_amount"])
    gge_amount = require_positive_number(data, "gge_amount")
    b = get_backup_or_404(arrangementId)
    if b["status"] != "ACTIVATED":
        raise ApiError(ERR_BACKUP_NOT_ACTIVE, 409,
                       "record-draw requires ACTIVATED arrangement")
    if b["used_gge"] + gge_amount > b["committed_gge"]:
        raise ApiError(ERR_BACKUP_DRAW_EXCEEDED, 409,
                       "used_gge + gge_amount would exceed committed_gge")
    b["used_gge"] += gge_amount
    touch(b)
    return success_object(backup_arrangement_out(b))


@bp.post("/cng/backup-arrangements/<arrangementId>/release")
def release_backup(arrangementId: str):
    caller = get_caller()
    require_role(caller, ["StationManager"])
    b = get_backup_or_404(arrangementId)
    if b["status"] != "ACTIVATED":
        raise ApiError(ERR_BACKUP_NOT_RELEASABLE, 409,
                       "Backup release requires ACTIVATED")
    b["status"] = "RELEASED"
    touch(b)
    return success_object(backup_arrangement_out(b))
