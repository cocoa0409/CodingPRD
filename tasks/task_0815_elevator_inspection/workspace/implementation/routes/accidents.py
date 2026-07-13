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
from constants import ACCIDENT_SEVERITIES, INTERVAL_MONTHS, SEVERITY_WEIGHT
from envelope import array_response, object_response
from services import logic
from services.logic import serialize_accident
from store import base_fields, db, touch

bp = Blueprint("accidents", __name__)


@bp.route("/accident-reports", methods=["POST"])
@require("SafetyAdministrator", "BuildingOwner")
def create_accident():
    body = get_body()
    device_id = require_string(body, "device_id")
    severity = require_enum(body, "severity", ACCIDENT_SEVERITIES)
    occurred_period = require_int(body, "occurred_period")
    description = require_string(body, "description")
    lookup(db.devices, device_id, "ERR_DEVICE_NOT_FOUND")

    report = base_fields()
    report.update({
        "device_id": device_id,
        "lead_investigator_id": None,
        "severity": severity,
        "occurred_period": occurred_period,
        "description": description,
        "provisional_risk_score": SEVERITY_WEIGHT[severity],
        "final_risk_score": None,
        "status": "REPORTED",
    })
    db.accident_reports[report["id"]] = report
    return object_response(serialize_accident(report), 201)


@bp.route("/accident-reports/<report_id>", methods=["GET"])
@require("Registrar", "SafetyAdministrator", "LicensedInspector", "BuildingOwner")
def get_accident(report_id):
    r = lookup(db.accident_reports, report_id, "ERR_ACCIDENT_NOT_FOUND")
    return object_response(serialize_accident(r), 200)


@bp.route("/accident-reports", methods=["GET"])
@require("Registrar", "SafetyAdministrator", "LicensedInspector", "BuildingOwner")
def list_accidents():
    limit, offset = parse_pagination()
    device_id = request.args.get("device_id")
    lead = request.args.get("lead_investigator_id")
    status = request.args.get("status")
    items = list(db.accident_reports.values())
    if device_id is not None:
        items = [r for r in items if r["device_id"] == device_id]
    if lead is not None:
        items = [r for r in items if r.get("lead_investigator_id") == lead]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, total = paginate(items, limit, offset)
    return array_response([serialize_accident(r) for r in page], limit, offset, total)


@bp.route("/accident-reports/<report_id>/open-investigation", methods=["POST"])
@require("SafetyAdministrator")
def open_investigation(report_id):
    report = lookup(db.accident_reports, report_id, "ERR_ACCIDENT_NOT_FOUND")
    body = get_body()
    lead_id = require_string(body, "lead_investigator_id")
    inspector = lookup(db.inspectors, lead_id, "ERR_INSPECTOR_NOT_FOUND")
    device = db.devices[report["device_id"]]

    if report["status"] != "REPORTED":
        raise errors.ApiError("ERR_ACCIDENT_NOT_REPORTED", 409,
                              "Report is not in REPORTED status.")
    # Certification + unexpired license (priority 10)
    certified = device["category"] in inspector["certified_categories"]
    unexpired = db.current_period_index <= inspector["license_expiry_period"]
    if not (certified and unexpired):
        raise errors.ApiError("ERR_INSPECTOR_NOT_CERTIFIED", 403,
                              "Lead investigator is not certified or license expired.")
    # Segregation of duties (priority 11)
    for insp in db.inspections.values():
        if (insp["device_id"] == device["id"]
                and insp.get("assigned_inspector_id") == lead_id
                and insp["status"] in ("ASSIGNED", "IN_PROGRESS")):
            raise errors.ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                                  "Lead investigator is a current routine inspector of this device.")

    report["lead_investigator_id"] = lead_id
    report["status"] = "UNDER_INVESTIGATION"
    touch(report)
    # Cascade: ACTIVE OOS order (reason ACCIDENT) -> device OUT_OF_SERVICE -> cert SUSPENDED
    logic.create_oos_order(
        device,
        reason="ACCIDENT",
        start=db.current_period_index,
        end=db.current_period_index + INTERVAL_MONTHS[device["category"]],
    )
    return object_response(serialize_accident(report), 200)


@bp.route("/accident-reports/<report_id>/close", methods=["POST"])
@require("LicensedInspector")
def close_investigation(report_id):
    report = lookup(db.accident_reports, report_id, "ERR_ACCIDENT_NOT_FOUND")
    body = get_body()
    finding = require_enum(body, "finding", {"SUBSTANTIATED", "UNSUBSTANTIATED"})

    if report.get("lead_investigator_id") != g.user_id:
        raise errors.not_resource_owner()
    if report["status"] != "UNDER_INVESTIGATION":
        raise errors.ApiError("ERR_ACCIDENT_NOT_UNDER_INVESTIGATION", 409,
                              "Report is not under investigation.")

    device = db.devices[report["device_id"]]
    final = logic.compute_accident_final_score(report, device, finding)
    report["final_risk_score"] = final
    report["status"] = finding
    touch(report)
    device["accident_risk_score"] = final
    touch(device)
    return object_response(serialize_accident(report), 200)
