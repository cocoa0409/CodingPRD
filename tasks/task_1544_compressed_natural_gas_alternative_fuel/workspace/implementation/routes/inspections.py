"""SafetyInspection endpoints."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, request

from db import STORE, new_id, now_utc
from errors import (
    ApiError,
    ERR_STATION_NOT_FOUND,
    ERR_INSPECTION_NOT_FOUND,
    ERR_INSPECTION_NOT_COMPLETABLE,
    ERR_INSPECTION_NOT_APPROVABLE,
    ERR_SEGREGATION_OF_DUTIES,
)
from middleware import get_caller, require_role
from response import success_object, success_list
from serializers import safety_inspection_out
from services.core import (
    touch,
    void_sessions_for_inspection_fail,
    INSPECTION_INTERVALS_DAYS,
)
from validators import (
    body, require_fields, require_string, require_enum, require_datetime,
    parse_pagination, paginate,
)

bp = Blueprint("inspections", __name__)

_ALL_READ = ["NetworkOperator", "StationManager", "ComplianceOfficer",
             "FleetAccountManager", "FleetDriver"]
_TYPES = {"ANNUAL_COMPREHENSIVE", "ODORIZATION_CHECK", "PRESSURE_VESSEL"}
_RESULTS = {"PASS", "PASS_WITH_DEFICIENCIES", "FAIL"}


def get_inspection_or_404(iid: str) -> dict:
    i = STORE.safety_inspections.get(iid)
    if i is None:
        raise ApiError(ERR_INSPECTION_NOT_FOUND, 404, "Safety inspection id does not exist")
    return i


@bp.post("/cng/safety-inspections")
def create_inspection():
    caller = get_caller()
    require_role(caller, ["StationManager"])
    data = body()
    require_fields(data, ["station_id", "inspection_type", "scheduled_for"])
    station_id = require_string(data, "station_id")
    inspection_type = require_enum(data, "inspection_type", _TYPES)
    scheduled_for = require_datetime(data, "scheduled_for")
    if station_id not in STORE.stations:
        raise ApiError(ERR_STATION_NOT_FOUND, 404, "Station id does not exist")
    now = now_utc()
    insp = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "station_id": station_id,
        "inspection_type": inspection_type,
        "scheduled_for": scheduled_for,
        "status": "SCHEDULED",
        "result": None,
        "findings": None,
        "performed_by": None,
        "approved_by": None,
        "completed_at": None,
    }
    STORE.safety_inspections[insp["id"]] = insp
    return success_object(safety_inspection_out(insp), status=201)


@bp.get("/cng/safety-inspections")
def list_inspections():
    caller = get_caller()
    require_role(caller, _ALL_READ)
    limit, offset = parse_pagination()
    station_id = request.args.get("station_id")
    status = request.args.get("status")
    inspection_type = request.args.get("inspection_type")
    items = sorted(STORE.safety_inspections.values(), key=lambda i: (i["created_at"], i["id"]))
    if station_id is not None:
        items = [i for i in items if i["station_id"] == station_id]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    if inspection_type is not None:
        items = [i for i in items if i["inspection_type"] == inspection_type]
    page, total = paginate(items, limit, offset)
    return success_list([safety_inspection_out(i) for i in page], limit, offset, total)


@bp.get("/cng/safety-inspections/<inspectionId>")
def get_inspection(inspectionId: str):
    caller = get_caller()
    require_role(caller, _ALL_READ)
    return success_object(safety_inspection_out(get_inspection_or_404(inspectionId)))


@bp.post("/cng/safety-inspections/<inspectionId>/complete")
def complete_inspection(inspectionId: str):
    caller = get_caller()
    require_role(caller, ["StationManager"])
    data = body()
    require_fields(data, ["result"])
    result = require_enum(data, "result", _RESULTS)
    findings = data.get("findings")
    if findings is not None and not isinstance(findings, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "findings must be a string")
    insp = get_inspection_or_404(inspectionId)
    if insp["status"] not in ("SCHEDULED", "OVERDUE"):
        raise ApiError(ERR_INSPECTION_NOT_COMPLETABLE, 409,
                       "Inspection complete requires SCHEDULED or OVERDUE")
    now = now_utc()
    insp["status"] = "COMPLETED"
    insp["result"] = result
    insp["findings"] = findings
    insp["performed_by"] = caller.user_id
    insp["completed_at"] = now
    touch(insp)
    return success_object(safety_inspection_out(insp))


@bp.post("/cng/safety-inspections/<inspectionId>/approve")
def approve_inspection(inspectionId: str):
    caller = get_caller()
    require_role(caller, ["ComplianceOfficer"])
    insp = get_inspection_or_404(inspectionId)
    if insp["status"] != "COMPLETED":
        raise ApiError(ERR_INSPECTION_NOT_APPROVABLE, 409,
                       "Inspection approve requires COMPLETED")
    # Segregation of duties (safety stage)
    if caller.user_id == insp["performed_by"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403,
                       "Inspection approver must differ from performer")
    insp["status"] = "APPROVED"
    insp["approved_by"] = caller.user_id
    touch(insp)

    if insp["result"] == "FAIL":
        station = STORE.stations.get(insp["station_id"])
        if station is not None and station["status"] == "ACTIVE":
            station["status"] = "SUSPENDED"
            touch(station)
        void_sessions_for_inspection_fail(insp["station_id"])
    else:
        # PASS / PASS_WITH_DEFICIENCIES: auto-create next inspection
        interval_days = INSPECTION_INTERVALS_DAYS[insp["inspection_type"]]
        next_insp = {
            "id": new_id(),
            "created_at": now_utc(),
            "updated_at": now_utc(),
            "version": 1,
            "station_id": insp["station_id"],
            "inspection_type": insp["inspection_type"],
            "scheduled_for": insp["completed_at"] + timedelta(days=interval_days),
            "status": "SCHEDULED",
            "result": None,
            "findings": None,
            "performed_by": None,
            "approved_by": None,
            "completed_at": None,
        }
        STORE.safety_inspections[next_insp["id"]] = next_insp

    return success_object(safety_inspection_out(insp))
