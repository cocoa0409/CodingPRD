from flask import Blueprint, g, request

import errors
from auth import require
from common import (
    get_body,
    lookup,
    paginate,
    parse_pagination,
    require_enum,
    require_int,
    require_string,
)
from constants import (
    DEFICIENCY_SEVERITIES,
    INSPECTION_BUFFER_PERIODS,
    INSPECTION_TYPES,
    INTERVAL_MONTHS,
    RESOLUTION_GRACE_MONTHS,
)
from envelope import array_response, object_response
from services import logic
from services.logic import serialize_inspection
from store import base_fields, db, touch

bp = Blueprint("inspections", __name__)


@bp.route("/inspections", methods=["POST"])
@require("Registrar")
def create_inspection():
    body = get_body()
    device_id = require_string(body, "device_id")
    itype = require_enum(body, "type", INSPECTION_TYPES)
    start = require_int(body, "scheduled_start_period")
    end = require_int(body, "scheduled_end_period")
    lookup(db.devices, device_id, "ERR_DEVICE_NOT_FOUND")

    insp = base_fields()
    insp.update({
        "device_id": device_id,
        "assigned_inspector_id": None,
        "type": itype,
        "scheduled_start_period": start,
        "scheduled_end_period": end,
        "performed_period": None,
        "status": "SCHEDULED",
    })
    db.inspections[insp["id"]] = insp
    return object_response(serialize_inspection(insp), 201)


@bp.route("/inspections/<inspection_id>", methods=["GET"])
@require("Registrar", "SafetyAdministrator", "LicensedInspector", "BuildingOwner")
def get_inspection(inspection_id):
    insp = lookup(db.inspections, inspection_id, "ERR_INSPECTION_NOT_FOUND")
    return object_response(serialize_inspection(insp), 200)


@bp.route("/inspections", methods=["GET"])
@require("Registrar", "SafetyAdministrator", "LicensedInspector")
def list_inspections():
    limit, offset = parse_pagination()
    device_id = request.args.get("device_id")
    assigned = request.args.get("assigned_inspector_id")
    status = request.args.get("status")
    items = list(db.inspections.values())
    if device_id is not None:
        items = [i for i in items if i["device_id"] == device_id]
    if assigned is not None:
        items = [i for i in items if i.get("assigned_inspector_id") == assigned]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    page, total = paginate(items, limit, offset)
    return array_response([serialize_inspection(i) for i in page], limit, offset, total)


@bp.route("/inspections/<inspection_id>/assign", methods=["POST"])
@require("Registrar")
def assign_inspection(inspection_id):
    insp = lookup(db.inspections, inspection_id, "ERR_INSPECTION_NOT_FOUND")
    body = get_body()
    inspector_id = require_string(body, "assigned_inspector_id")
    inspector = lookup(db.inspectors, inspector_id, "ERR_INSPECTOR_NOT_FOUND")
    device = db.devices[insp["device_id"]]

    if insp["status"] != "SCHEDULED":
        raise errors.ApiError("ERR_INSPECTION_NOT_SCHEDULED", 409,
                              "Inspection is not in SCHEDULED status.")
    # Certification + unexpired license (priority 10)
    certified = device["category"] in inspector["certified_categories"]
    unexpired = db.current_period_index <= inspector["license_expiry_period"]
    if not (certified and unexpired):
        raise errors.ApiError("ERR_INSPECTOR_NOT_CERTIFIED", 403,
                              "Inspector is not certified for this device category or license expired.")
    # Schedule conflict (priority 14)
    ns, ne = insp["scheduled_start_period"], insp["scheduled_end_period"]
    for other in db.inspections.values():
        if other["id"] == insp["id"]:
            continue
        if other.get("assigned_inspector_id") != inspector_id:
            continue
        if other["status"] not in ("ASSIGNED", "IN_PROGRESS"):
            continue
        os_, oe = other["scheduled_start_period"], other["scheduled_end_period"]
        if ns < oe + INSPECTION_BUFFER_PERIODS and os_ < ne + INSPECTION_BUFFER_PERIODS:
            raise errors.ApiError("ERR_INSPECTOR_SCHEDULE_CONFLICT", 409,
                                  "Inspection window conflicts with the inspector's schedule.")

    insp["assigned_inspector_id"] = inspector_id
    insp["status"] = "ASSIGNED"
    touch(insp)
    return object_response(serialize_inspection(insp), 200)


@bp.route("/inspections/<inspection_id>/start", methods=["POST"])
@require("LicensedInspector")
def start_inspection(inspection_id):
    insp = lookup(db.inspections, inspection_id, "ERR_INSPECTION_NOT_FOUND")
    if insp.get("assigned_inspector_id") != g.user_id:
        raise errors.not_resource_owner()
    if insp["status"] != "ASSIGNED":
        raise errors.ApiError("ERR_INSPECTION_NOT_ASSIGNED", 409,
                              "Inspection is not in ASSIGNED status.")
    device = db.devices[insp["device_id"]]
    if device["status"] in ("OUT_OF_SERVICE", "DECOMMISSIONED"):
        raise errors.ApiError("ERR_DEVICE_NOT_OPERABLE", 409,
                              "Device is not operable.")
    insp["status"] = "IN_PROGRESS"
    touch(insp)
    return object_response(serialize_inspection(insp), 200)


def _validate_deficiency_entries(entries):
    for e in entries:
        if not isinstance(e, dict):
            raise errors.invalid_request("Each deficiency must be an object.")
        code = e.get("code")
        severity = e.get("severity")
        description = e.get("description")
        if not isinstance(code, str) or code == "":
            raise errors.invalid_request("Deficiency code must be a non-empty string.")
        if severity not in DEFICIENCY_SEVERITIES:
            raise errors.invalid_request("Deficiency severity is invalid.")
        if not isinstance(description, str) or description == "":
            raise errors.invalid_request("Deficiency description must be a non-empty string.")


def _create_deficiency(insp, device, entry):
    d = base_fields()
    d.update({
        "inspection_id": insp["id"],
        "device_id": device["id"],
        "code": entry["code"],
        "severity": entry["severity"],
        "description": entry["description"],
        "resolution_due_period": insp["performed_period"] + RESOLUTION_GRACE_MONTHS[entry["severity"]],
        "status": "OPEN",
    })
    db.deficiencies[d["id"]] = d
    return d


@bp.route("/inspections/<inspection_id>/complete", methods=["POST"])
@require("LicensedInspector")
def complete_inspection(inspection_id):
    insp = lookup(db.inspections, inspection_id, "ERR_INSPECTION_NOT_FOUND")
    body = get_body()
    result = require_enum(body, "result", {"PASS", "FAIL", "CONDITIONAL"})
    deficiencies = body.get("deficiencies")
    if deficiencies is None:
        deficiencies = []
    if not isinstance(deficiencies, list):
        raise errors.invalid_request("deficiencies must be a list.")

    # Ownership (priority 5)
    if insp.get("assigned_inspector_id") != g.user_id:
        raise errors.not_resource_owner()
    # State (priority 7)
    if insp["status"] != "IN_PROGRESS":
        raise errors.ApiError("ERR_INSPECTION_NOT_IN_PROGRESS", 409,
                              "Inspection is not in IN_PROGRESS status.")

    device = db.devices[insp["device_id"]]

    if result == "PASS":
        if len(deficiencies) > 0:
            raise errors.ApiError("ERR_PASS_WITH_DEFICIENCIES", 409,
                                  "A passing inspection must carry no deficiencies.")
    elif result == "FAIL":
        if len(deficiencies) == 0:
            raise errors.ApiError("ERR_FAIL_WITHOUT_DEFICIENCIES", 409,
                                  "A failing inspection must carry deficiencies.")
        _validate_deficiency_entries(deficiencies)
    else:  # CONDITIONAL
        if len(deficiencies) == 0:
            raise errors.invalid_request("A conditional inspection must carry deficiencies.")
        _validate_deficiency_entries(deficiencies)
        if any(e["severity"] == "CRITICAL" for e in deficiencies):
            raise errors.invalid_request("A conditional inspection may not carry CRITICAL deficiencies.")

    # Common completion side effects
    insp["performed_period"] = db.current_period_index

    if result == "PASS":
        insp["status"] = "PASSED"
        device["next_inspection_due_period"] = insp["performed_period"] + INTERVAL_MONTHS[device["category"]]
        touch(device)
    elif result == "CONDITIONAL":
        insp["status"] = "CONDITIONAL"
        for entry in deficiencies:
            _create_deficiency(insp, device, entry)
    else:  # FAIL
        insp["status"] = "FAILED"
        created = [_create_deficiency(insp, device, entry) for entry in deficiencies]
        interval = INTERVAL_MONTHS[device["category"]]
        for d in created:
            if d["severity"] == "CRITICAL":
                citation = logic.issue_citation(d, device)
                logic.create_oos_order(
                    device,
                    reason="CRITICAL_DEFICIENCY",
                    start=db.current_period_index,
                    end=db.current_period_index + interval,
                    citation_id=citation["id"],
                )

    touch(insp)
    return object_response(serialize_inspection(insp), 200)


@bp.route("/inspections/<inspection_id>/cancel", methods=["POST"])
@require("Registrar")
def cancel_inspection(inspection_id):
    insp = lookup(db.inspections, inspection_id, "ERR_INSPECTION_NOT_FOUND")
    if insp["status"] not in ("SCHEDULED", "ASSIGNED"):
        raise errors.ApiError("ERR_INSPECTION_NOT_CANCELLABLE", 409,
                              "Inspection is not cancellable.")
    was_assigned = insp["status"] == "ASSIGNED"
    insp["status"] = "CANCELLED"
    if was_assigned:
        insp["assigned_inspector_id"] = None
    touch(insp)
    return object_response(serialize_inspection(insp), 200)
