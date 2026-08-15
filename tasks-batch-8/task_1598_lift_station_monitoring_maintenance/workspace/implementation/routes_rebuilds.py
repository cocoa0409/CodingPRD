"""PumpRebuild routes: open/start/complete/cancel plus listings (PRD 3.4)."""
from flask import Blueprint, g, request

import db
import services
from envelope import success
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_REFERENCE_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_UNAUTHORIZED,
    ERR_FIRM_CAPACITY_VIOLATION,
)
from helpers import (
    body, bad, req_str, req_instant, req_decimal, paginate,
)
from middleware import require_roles
from routes_pumps import get_pump_or_404, station_of
from serializers import ser_rebuild

bp = Blueprint("pump_rebuilds", __name__)

REBUILD_READ_ROLES = ("UtilityAdmin", "OperationsSupervisor", "MaintenancePlanner")


def get_rebuild_or_404(rid):
    r = db.pump_rebuilds.get(rid)
    if r is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Pump rebuild not found")
    return r


@bp.post("/pump-rebuilds")
def create_rebuild():
    require_roles("MaintenancePlanner")
    b = body()
    # body FK existence (priority 5)
    pump_id = b.get("pump_id")
    if pump_id is None:
        bad("pump_id is required")
    if not isinstance(pump_id, str):
        bad("pump_id must be a string")
    pump = db.pumps.get(pump_id)
    if pump is None:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, 422, "pump_id does not resolve")
    st = station_of(pump)
    # state (priority 6): opening a rebuild drives IN_SERVICE -> REBUILD
    if pump["status"] != "IN_SERVICE":
        raise ApiError(
            ERR_INVALID_STATE, 409,
            "Only an IN_SERVICE pump can enter REBUILD",
        )
    # posture gate (priority 7)
    services.check_posture(st)
    # business safety (priority 8): at least one IN_SERVICE pump must remain
    in_service = sum(
        1 for q in db.pumps.values()
        if q["station_id"] == st["id"] and q["status"] == "IN_SERVICE"
    )
    if in_service <= 1:
        raise ApiError(
            ERR_FIRM_CAPACITY_VIOLATION, 422,
            "Rebuild would leave the station without an IN_SERVICE pump",
        )
    # shape (priority 30)
    work_order_ref = req_str(b, "work_order_ref")
    started = req_instant(b, "started_at")
    cost = req_decimal(b, "cost_usd", 2)
    if cost < 0:
        bad("cost_usd must be >= 0")
    pump["status"] = "REBUILD"
    db.touch(pump)
    r = {
        "id": db.new_id(),
        "pump_id": pump_id,
        "work_order_ref": work_order_ref,
        "started_at": started,
        "completed_at": None,
        "status": "OPEN",
        "cost_usd": cost,
        "pre_rebuild_runtime_hours": None,
    }
    db.stamp(r)
    db.pump_rebuilds[r["id"]] = r
    services.sync_station(st)
    return success(ser_rebuild(r), 201)


@bp.get("/pump-rebuilds")
def list_rebuilds():
    require_roles(*REBUILD_READ_ROLES)
    items = list(db.pump_rebuilds.values())
    pump_id = request.args.get("pump_id")
    if pump_id is not None:
        items = [r for r in items if r["pump_id"] == pump_id]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, meta = paginate(items)
    return success([ser_rebuild(r) for r in page], 200, meta)


@bp.get("/pumps/<pid>/rebuilds")
def list_pump_rebuilds(pid):
    require_roles(*REBUILD_READ_ROLES)
    get_pump_or_404(pid)
    items = [r for r in db.pump_rebuilds.values() if r["pump_id"] == pid]
    page, meta = paginate(items)
    return success([ser_rebuild(r) for r in page], 200, meta)


@bp.get("/pump-rebuilds/<rid>")
def get_rebuild(rid):
    require_roles(*REBUILD_READ_ROLES)
    return success(ser_rebuild(get_rebuild_or_404(rid)))


# --------------------------------------------------------------------- lifecycle


@bp.post("/pump-rebuilds/<rid>/start")
def start_rebuild(rid):
    require_roles("MaintenancePlanner")
    r = get_rebuild_or_404(rid)
    pump = db.pumps[r["pump_id"]]
    st = station_of(pump)
    if r["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an OPEN rebuild can be started")
    services.check_posture(st)
    if pump["status"] != "REBUILD":
        raise ApiError(ERR_INVALID_STATE, 409, "Pump is not in REBUILD")
    r["pre_rebuild_runtime_hours"] = pump["runtime_since_rebuild_hours"]
    r["status"] = "IN_PROGRESS"
    db.touch(r)
    return success(ser_rebuild(r))


@bp.post("/pump-rebuilds/<rid>/complete")
def complete_rebuild(rid):
    require_roles("MaintenancePlanner")
    r = get_rebuild_or_404(rid)
    pump = db.pumps[r["pump_id"]]
    st = station_of(pump)
    if r["status"] != "IN_PROGRESS":
        raise ApiError(
            ERR_INVALID_STATE, 409, "Only an IN_PROGRESS rebuild can be completed"
        )
    services.check_posture(st)
    if pump["status"] != "REBUILD":
        raise ApiError(ERR_INVALID_STATE, 409, "Pump is not in REBUILD")
    r["completed_at"] = db.now()
    r["status"] = "COMPLETED"
    db.touch(r)
    pump["status"] = "IN_SERVICE"
    from decimal import Decimal
    pump["runtime_since_rebuild_hours"] = Decimal("0.00")
    pump["rebuild_count"] += 1
    db.touch(pump)
    services.sync_station(st)
    return success(ser_rebuild(r))


@bp.post("/pump-rebuilds/<rid>/cancel")
def cancel_rebuild(rid):
    require_roles("MaintenancePlanner", "OperationsSupervisor")
    r = get_rebuild_or_404(rid)
    pump = db.pumps[r["pump_id"]]
    st = station_of(pump)
    # OPEN -> CANCELLED is the MaintenancePlanner path; IN_PROGRESS ->
    # CANCELLED is the OperationsSupervisor override.
    if r["status"] == "OPEN":
        if g.user_role != "MaintenancePlanner":
            raise ApiError(
                ERR_UNAUTHORIZED, 403,
                "Only a MaintenancePlanner may cancel an OPEN rebuild",
            )
    elif r["status"] == "IN_PROGRESS":
        if g.user_role != "OperationsSupervisor":
            raise ApiError(
                ERR_UNAUTHORIZED, 403,
                "Only an OperationsSupervisor may cancel an IN_PROGRESS rebuild",
            )
    else:
        raise ApiError(
            ERR_INVALID_STATE, 409,
            "Rebuild in %s cannot be cancelled" % r["status"],
        )
    services.check_posture(st)
    r["status"] = "CANCELLED"
    db.touch(r)
    pump["status"] = "OUT_OF_SERVICE"
    db.touch(pump)
    services.sync_station(st)
    return success(ser_rebuild(r))
