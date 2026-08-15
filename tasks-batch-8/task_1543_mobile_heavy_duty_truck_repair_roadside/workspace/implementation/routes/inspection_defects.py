"""InspectionDefect endpoints: file, attach correcting call, mark corrected,
verify."""
from datetime import timedelta

from flask import Blueprint, request

from db import store, new_record, touch
from errors import (ApiError, err_not_found, err_invalid_state,
                    err_forbidden_ownership)
from middleware import auth, require_fleet_ownership
from response import success
from serializers import serialize
from services.cascades import wall_now
from services.pricing import service_dispatch
from util import Field, validate_body, parse_pagination, paginate

bp = Blueprint("inspection_defects", __name__)

SOURCES = {"ROADSIDE_DOT_INSPECTION", "ANNUAL_INSPECTION", "DRIVER_REPORT"}
SEVERITIES = {"OOS", "NON_OOS"}
READ_ROLES = ["OpsAdmin", "Dispatcher", "Technician", "SafetyOfficer",
              "FleetManager"]
LIST_ROLES = ["OpsAdmin", "Dispatcher", "SafetyOfficer", "FleetManager"]
CORRECTION_WINDOW_DAYS = 15


def _get_defect(defect_id):
    d = store.inspection_defects.get(defect_id)
    if d is None:
        raise err_not_found("InspectionDefect not found")
    return d


def _bump_vehicle(vehicle_id):
    v = store.vehicles.get(vehicle_id)
    if v is not None:
        touch(v, wall_now())


@bp.route("/roadside/vehicles/<vehicleId>/inspection-defects", methods=["POST"])
def create_defect(vehicleId):
    auth(["SafetyOfficer", "OpsAdmin"])
    vehicle = store.vehicles.get(vehicleId)
    if vehicle is None:
        raise err_not_found("Vehicle not found")
    vals = validate_body(request.get_json(silent=True), [
        Field("source", "enum", required=True, enum=SOURCES),
        Field("defect_code", "string", required=True),
        Field("severity", "enum", required=True, enum=SEVERITIES),
        Field("citation_reference", "string", nullable=True),
        Field("discovered_at", "datetime", required=True),
    ])
    rec = new_record()
    now = wall_now()
    rec.update({
        "_created": now, "_updated": now,
        "vehicle_id": vehicle["id"],
        "source": vals["source"],
        "defect_code": vals["defect_code"],
        "severity": vals["severity"],
        "citation_reference": vals.get("citation_reference"),
        "discovered_at": vals["discovered_at"],
        "correction_deadline_at": (vals["discovered_at"]
                                   + timedelta(days=CORRECTION_WINDOW_DAYS)),
        "correcting_service_call_id": None,
        "status": "OPEN",
        "correction_note": None,
        "verified_by": None,
        "verified_at": None,
        "escalation_count": 0,
    })
    store.inspection_defects[rec["id"]] = rec
    _bump_vehicle(vehicle["id"])  # roadworthiness derivation may flip
    return success(serialize("defect", rec), status=201)


@bp.route("/roadside/inspection-defects/<inspectionDefectId>", methods=["GET"])
def get_defect(inspectionDefectId):
    uid, role = auth(READ_ROLES)
    d = _get_defect(inspectionDefectId)
    if role == "FleetManager":
        v = store.vehicles.get(d["vehicle_id"])
        require_fleet_ownership(uid, v.get("fleet_account_id") if v else None)
    return success(serialize("defect", d))


@bp.route("/roadside/inspection-defects", methods=["GET"])
def list_defects():
    uid, role = auth(LIST_ROLES)
    limit, offset = parse_pagination(request.args)
    veh_f = request.args.get("vehicle_id")
    call_f = request.args.get("correcting_service_call_id")
    status_f = request.args.get("status")
    sev_f = request.args.get("severity")
    items = sorted(store.inspection_defects.values(), key=lambda r: r["_seq"])
    if role == "FleetManager":
        items = [d for d in items
                 if (store.vehicles.get(d["vehicle_id"]) or {})
                 .get("fleet_account_id") == uid]
    if veh_f is not None:
        items = [d for d in items if d["vehicle_id"] == veh_f]
    if call_f is not None:
        items = [d for d in items if d.get("correcting_service_call_id") == call_f]
    if status_f is not None:
        items = [d for d in items if d["status"] == status_f]
    if sev_f is not None:
        items = [d for d in items if d["severity"] == sev_f]
    page, total, has_more = paginate(items, limit, offset)
    return success([serialize("defect", d) for d in page],
                   response_type="array",
                   pagination={"limit": limit, "offset": offset,
                               "total_count": total, "has_more": has_more})


@bp.route("/roadside/inspection-defects/<inspectionDefectId>/attach-call",
          methods=["POST"])
def attach_call(inspectionDefectId):
    auth(["SafetyOfficer", "OpsAdmin"])
    d = _get_defect(inspectionDefectId)
    vals = validate_body(request.get_json(silent=True), [
        Field("service_call_id", "string", required=True),
    ])
    call = store.service_calls.get(vals["service_call_id"])
    if call is None:
        raise err_not_found("ServiceCall not found")
    if d["status"] not in ("OPEN", "VERIFICATION_FAILED", "ESCALATED"):
        raise err_invalid_state(
            "Attach-call requires OPEN, VERIFICATION_FAILED, or ESCALATED")
    if call["vehicle_id"] != d["vehicle_id"]:
        raise ApiError("ERR_VEHICLE_MISMATCH",
                       "Linked call and defect refer to different vehicles", 409)
    d["correcting_service_call_id"] = call["id"]
    d["status"] = "REPAIR_SCHEDULED"
    touch(d, wall_now())
    call["linked_defect_id"] = d["id"]
    touch(call, wall_now())
    return success(serialize("defect", d))


@bp.route("/roadside/inspection-defects/<inspectionDefectId>/mark-corrected",
          methods=["POST"])
def mark_corrected(inspectionDefectId):
    uid, role = auth(["Technician"])
    d = _get_defect(inspectionDefectId)
    vals = validate_body(request.get_json(silent=True), [
        Field("correction_note", "string", required=True),
    ])
    if d["status"] != "REPAIR_SCHEDULED":
        raise err_invalid_state("Mark-corrected requires REPAIR_SCHEDULED")
    call = store.service_calls.get(d.get("correcting_service_call_id") or "")
    if call is None or call["status"] != "REPAIR_COMPLETED":
        raise err_invalid_state(
            "The linked correcting call must be REPAIR_COMPLETED")
    disp = service_dispatch(call)
    if disp is None or disp["technician_id"] != uid:
        raise err_forbidden_ownership(
            "Actor is not the linked call's dispatch technician")
    d["status"] = "CORRECTED"
    d["correction_note"] = vals["correction_note"]
    touch(d, wall_now())
    return success(serialize("defect", d))


@bp.route("/roadside/inspection-defects/<inspectionDefectId>/verify",
          methods=["POST"])
def verify(inspectionDefectId):
    uid, role = auth(["SafetyOfficer"])
    d = _get_defect(inspectionDefectId)
    vals = validate_body(request.get_json(silent=True), [
        Field("outcome", "enum", required=True, enum={"PASS", "FAIL"}),
        Field("verification_note", "string"),
    ])
    if d["status"] != "CORRECTED":
        raise ApiError("ERR_DEFECT_NOT_CORRECTED",
                       "Verify requires defect status CORRECTED", 409)
    if vals["outcome"] == "PASS":
        d["status"] = "VERIFIED"
        d["verified_by"] = uid
        d["verified_at"] = store.clock
    else:
        d["status"] = "VERIFICATION_FAILED"
    touch(d, wall_now())
    _bump_vehicle(d["vehicle_id"])  # roadworthiness recompute
    return success(serialize("defect", d))
