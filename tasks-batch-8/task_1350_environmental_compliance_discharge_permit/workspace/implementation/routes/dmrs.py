"""DischargeMonitoringReport endpoints."""

import uuid
from datetime import timedelta
from flask import Blueprint, request

import db
from errors import (
    err,
    ERR_INVALID_REQUEST,
    ERR_OUTFALL_NOT_FOUND,
    ERR_DMR_NOT_FOUND,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_DMR_NOT_DRAFT,
    ERR_DMR_NOT_CERTIFIED,
    ERR_DMR_NOT_SUBMITTED,
    ERR_DMR_NOT_REJECTED,
    ERR_DMR_MONITORING_INCOMPLETE,
    ERR_DMR_EXCEEDANCES_UNRESOLVED,
)
from middleware import require_roles
from response import success, list_success
from util import get_body, require_fields, parse_iso
from services.core import (
    base_entity,
    touch,
    append_audit,
    serialize_dmr,
    paginate,
)
from services.dmr_calc import compute_dmr_picture

bp = Blueprint("dmrs", __name__)


def _period_exceedances(outfall_id, period_start, period_end):
    return [
        e
        for e in db.exceedances.values()
        if e["outfall_id"] == outfall_id and period_start <= e["detected_at"] <= period_end
    ]


def _recompute_is_late(dmr):
    now = db.clock.now()
    if dmr["submitted_at"] is None:
        dmr["is_late"] = now > dmr["due_date"]
    else:
        dmr["is_late"] = dmr["submitted_at"] > dmr["due_date"]


@bp.route("/npdes/dmrs", methods=["POST"])
def create_dmr():
    user_id, role = require_roles(["ComplianceOfficer"])
    body = get_body()
    require_fields(body, ["outfall_id", "period_start", "period_end"])
    outfall = db.outfalls.get(body["outfall_id"])
    if outfall is None:
        raise err(ERR_OUTFALL_NOT_FOUND, 404, "Outfall not found")
    period_start = parse_iso(body["period_start"], "period_start")
    period_end = parse_iso(body["period_end"], "period_end")
    if period_end < period_start:
        raise err(ERR_INVALID_REQUEST, 400, "period_end must not be before period_start")

    picture = compute_dmr_picture(outfall["id"], period_start, period_end)

    dmr = base_entity("DischargeMonitoringReport")
    dmr["id"] = str(uuid.uuid4())
    dmr.update(
        {
            "outfall_id": outfall["id"],
            "period_start": period_start,
            "period_end": period_end,
            "due_date": period_end + timedelta(days=15),
            "status": "DRAFT",
            "prepared_by_user_id": user_id,
            "certified_by_user_id": None,
            "submitted_at": None,
            "is_late": False,
            "required_sample_count": picture["required_sample_count"],
            "total_validated_results": picture["total_validated_results"],
            "monitoring_completeness_ratio": picture["monitoring_completeness_ratio"],
            "summary_lines": picture["summary_lines"],
            "deficiency_notes": None,
        }
    )
    _recompute_is_late(dmr)
    db.dmrs[dmr["id"]] = dmr
    append_audit("DischargeMonitoringReport", dmr["id"], "DMR_CREATED", user_id, role)
    return success(serialize_dmr(dmr), 201)


@bp.route("/npdes/dmrs", methods=["GET"])
def list_dmrs():
    require_roles(["Any"])
    items = list(db.dmrs.values())
    outfall_id = request.args.get("outfall_id")
    if outfall_id:
        items = [d for d in items if d["outfall_id"] == outfall_id]
    status = request.args.get("status")
    if status:
        items = [d for d in items if d["status"] == status]
    # Refresh is_late for read freshness
    for d in items:
        _recompute_is_late(d)
    page, total, limit, offset = paginate(items, request.args)
    return list_success([serialize_dmr(d) for d in page], total, limit, offset)


@bp.route("/npdes/dmrs/<did>", methods=["GET"])
def get_dmr(did):
    require_roles(["Any"])
    dmr = db.dmrs.get(did)
    if dmr is None:
        raise err(ERR_DMR_NOT_FOUND, 404, "DMR not found")
    _recompute_is_late(dmr)
    return success(serialize_dmr(dmr), 200)


@bp.route("/npdes/dmrs/<did>/certify", methods=["POST"])
def certify_dmr(did):
    user_id, role = require_roles(["ComplianceOfficer"])
    dmr = db.dmrs.get(did)
    if dmr is None:
        raise err(ERR_DMR_NOT_FOUND, 404, "DMR not found")
    if dmr["status"] != "DRAFT":
        raise err(ERR_DMR_NOT_DRAFT, 409, "DMR is not DRAFT")
    if user_id == dmr["prepared_by_user_id"]:
        raise err(ERR_SEGREGATION_OF_DUTIES, 403, "Certifier must differ from preparer")
    # Re-evaluate completeness at certify time
    picture = compute_dmr_picture(dmr["outfall_id"], dmr["period_start"], dmr["period_end"])
    dmr["required_sample_count"] = picture["required_sample_count"]
    dmr["total_validated_results"] = picture["total_validated_results"]
    dmr["monitoring_completeness_ratio"] = picture["monitoring_completeness_ratio"]
    if dmr["monitoring_completeness_ratio"] < 0.5:
        raise err(ERR_DMR_MONITORING_INCOMPLETE, 422, "monitoring_completeness_ratio below 0.5")
    for exc in _period_exceedances(dmr["outfall_id"], dmr["period_start"], dmr["period_end"]):
        if exc["notification_status"] not in ("ORAL_NOTIFIED", "WRITTEN_OVERDUE", "WRITTEN_FILED", "CLOSED"):
            raise err(ERR_DMR_EXCEEDANCES_UNRESOLVED, 409, "A period exceedance has not been orally notified")
    dmr["certified_by_user_id"] = user_id
    dmr["status"] = "CERTIFIED"
    touch(dmr)
    append_audit("DischargeMonitoringReport", dmr["id"], "DMR_CERTIFIED", user_id, role)
    return success(serialize_dmr(dmr), 200)


@bp.route("/npdes/dmrs/<did>/submit", methods=["POST"])
def submit_dmr(did):
    user_id, role = require_roles(["ComplianceOfficer"])
    dmr = db.dmrs.get(did)
    if dmr is None:
        raise err(ERR_DMR_NOT_FOUND, 404, "DMR not found")
    if dmr["status"] != "CERTIFIED":
        raise err(ERR_DMR_NOT_CERTIFIED, 409, "DMR is not CERTIFIED")
    for exc in _period_exceedances(dmr["outfall_id"], dmr["period_start"], dmr["period_end"]):
        if exc["notification_status"] not in ("WRITTEN_FILED", "CLOSED"):
            raise err(ERR_DMR_EXCEEDANCES_UNRESOLVED, 409, "A period exceedance lacks a filed written report")
    dmr["submitted_at"] = db.clock.now()
    _recompute_is_late(dmr)
    dmr["status"] = "SUBMITTED"
    touch(dmr)
    append_audit("DischargeMonitoringReport", dmr["id"], "DMR_SUBMITTED", user_id, role)
    return success(serialize_dmr(dmr), 200)


@bp.route("/npdes/dmrs/<did>/agency-review", methods=["POST"])
def agency_review(did):
    user_id, role = require_roles(["Regulator"])
    dmr = db.dmrs.get(did)
    if dmr is None:
        raise err(ERR_DMR_NOT_FOUND, 404, "DMR not found")
    if dmr["status"] != "SUBMITTED":
        raise err(ERR_DMR_NOT_SUBMITTED, 409, "DMR is not SUBMITTED")
    body = get_body()
    require_fields(body, ["decision"])
    decision = body["decision"]
    if decision not in ("ACCEPTED", "REJECTED"):
        raise err(ERR_INVALID_REQUEST, 400, "decision must be ACCEPTED or REJECTED")
    if decision == "REJECTED":
        notes = body.get("deficiency_notes")
        if not isinstance(notes, str) or notes.strip() == "":
            raise err(ERR_INVALID_REQUEST, 400, "deficiency_notes required when rejecting")
        dmr["deficiency_notes"] = notes
        dmr["status"] = "REJECTED"
        touch(dmr)
        append_audit("DischargeMonitoringReport", dmr["id"], "DMR_REJECTED", user_id, role)
    else:
        dmr["status"] = "ACCEPTED"
        touch(dmr)
        append_audit("DischargeMonitoringReport", dmr["id"], "DMR_ACCEPTED", user_id, role)
    return success(serialize_dmr(dmr), 200)


@bp.route("/npdes/dmrs/<did>/revise", methods=["POST"])
def revise_dmr(did):
    user_id, role = require_roles(["ComplianceOfficer"])
    dmr = db.dmrs.get(did)
    if dmr is None:
        raise err(ERR_DMR_NOT_FOUND, 404, "DMR not found")
    if dmr["status"] != "REJECTED":
        raise err(ERR_DMR_NOT_REJECTED, 409, "DMR is not REJECTED")
    dmr["certified_by_user_id"] = None
    picture = compute_dmr_picture(dmr["outfall_id"], dmr["period_start"], dmr["period_end"])
    dmr["required_sample_count"] = picture["required_sample_count"]
    dmr["total_validated_results"] = picture["total_validated_results"]
    dmr["monitoring_completeness_ratio"] = picture["monitoring_completeness_ratio"]
    dmr["summary_lines"] = picture["summary_lines"]
    dmr["status"] = "DRAFT"
    touch(dmr)
    append_audit("DischargeMonitoringReport", dmr["id"], "DMR_REVISED", user_id, role)
    return success(serialize_dmr(dmr), 200)
