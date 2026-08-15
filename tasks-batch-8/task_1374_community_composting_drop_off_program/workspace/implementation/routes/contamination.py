"""ContaminationReport endpoints."""

from flask import Blueprint, request

import db
import errors
from middleware import require_roles
from response import success_object, success_list
from routes.helpers import (
    body, require_fields, require_str, require_enum,
    get_program_or_404, get_site_or_404, get_report_or_404, get_drop_or_404,
    paginate, sort_created,
)
from services import posture as posture_svc
from services.drops import accept_drop, reject_drop
from services.programs import touch, site_posture_touch
from services.serializers import contamination_report as serialize_report

bp = Blueprint("contamination", __name__)

READ_ROLES = ("ProgramAdmin", "SiteHost", "MunicipalAuditor")
SEVERITIES = ("MINOR", "MAJOR", "CRITICAL")


@bp.route("/programs/<program_id>/sites/<site_id>/contamination-reports", methods=["POST"])
def create_report(program_id, site_id):
    user_id, _ = require_roles("MunicipalAuditor")
    get_program_or_404(program_id)
    site = get_site_or_404(site_id, program_id)
    data = body()
    require_fields(data, "auditor_id", "severity", "finding_note")
    auditor_id = require_str(data, "auditor_id")
    severity = require_enum(data, "severity", SEVERITIES)
    finding_note = require_str(data, "finding_note")
    drop_event_id = data.get("drop_event_id")

    drop = None
    if drop_event_id is not None:
        drop = get_drop_or_404(drop_event_id, site_id)

    now = db.iso_now()
    report = {
        "id": db.new_id(),
        "site_id": site["id"],
        "drop_event_id": drop_event_id,
        "auditor_id": auditor_id,
        "severity": severity,
        "finding_note": finding_note,
        "feedback_sent_at": None,
        "status": "OPEN",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.contamination_reports[report["id"]] = report

    # Side effect: linked drop -> FLAGGED_CONTAMINATED
    if drop is not None and drop["verification_state"] == "PENDING_AUDIT":
        drop["verification_state"] = "FLAGGED_CONTAMINATED"
        touch(drop)

    site_posture_touch(site)
    return success_object(serialize_report(report), status=201)


@bp.route("/programs/<program_id>/sites/<site_id>/contamination-reports", methods=["GET"])
def list_reports(program_id, site_id):
    require_roles(*READ_ROLES)
    get_program_or_404(program_id)
    get_site_or_404(site_id, program_id)
    items = [r for r in db.contamination_reports.values() if r["site_id"] == site_id]
    if request.args.get("status"):
        items = [r for r in items if r["status"] == request.args["status"]]
    if request.args.get("severity"):
        items = [r for r in items if r["severity"] == request.args["severity"]]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_report(r) for r in page], limit, offset, total)


@bp.route(
    "/programs/<program_id>/sites/<site_id>/contamination-reports/<report_id>/send-feedback",
    methods=["POST"],
)
def send_feedback(program_id, site_id, report_id):
    require_roles("ProgramAdmin")
    get_program_or_404(program_id)
    get_site_or_404(site_id, program_id)
    report = get_report_or_404(report_id, site_id)
    if report["status"] != "OPEN":
        errors.raise_err(errors.ERR_INVALID_STATE, "Report must be OPEN to send feedback")
    if report.get("drop_event_id") is None:
        errors.raise_err(
            errors.ERR_FEEDBACK_REQUIRES_DROP_LINK,
            "send-feedback requires the report to reference a DropEvent",
        )
    report["status"] = "FEEDBACK_SENT"
    report["feedback_sent_at"] = db.clock_now()
    touch(report)
    return success_object(serialize_report(report))


@bp.route(
    "/programs/<program_id>/sites/<site_id>/contamination-reports/<report_id>/resolve",
    methods=["POST"],
)
def resolve_report(program_id, site_id, report_id):
    require_roles("ProgramAdmin")
    get_program_or_404(program_id)
    site = get_site_or_404(site_id, program_id)
    report = get_report_or_404(report_id, site_id)
    if report["status"] == "FEEDBACK_SENT":
        report["status"] = "RESOLVED"
        # Linked drop in FLAGGED_CONTAMINATED -> ACCEPTED with credit side effects
        if report.get("drop_event_id"):
            drop = db.drops.get(report["drop_event_id"])
            if drop and drop["verification_state"] == "FLAGGED_CONTAMINATED":
                accept_drop(drop)
    elif report["status"] == "OPEN":
        if report.get("drop_event_id") is not None:
            errors.raise_err(
                errors.ERR_INVALID_STATE,
                "Drop-linked reports must go through feedback before resolving",
            )
        report["status"] = "RESOLVED"
    else:
        errors.raise_err(errors.ERR_INVALID_STATE, "Report cannot be resolved from current state")
    touch(report)
    site_posture_touch(site)
    return success_object(serialize_report(report))


@bp.route(
    "/programs/<program_id>/sites/<site_id>/contamination-reports/<report_id>/dismiss",
    methods=["POST"],
)
def dismiss_report(program_id, site_id, report_id):
    require_roles("MunicipalAuditor")
    get_program_or_404(program_id)
    site = get_site_or_404(site_id, program_id)
    report = get_report_or_404(report_id, site_id)
    if report["status"] != "OPEN":
        errors.raise_err(errors.ERR_INVALID_STATE, "Report must be OPEN to dismiss")
    report["status"] = "DISMISSED"
    touch(report)
    # CRITICAL + linked drop -> drop REJECTED
    if report["severity"] == "CRITICAL" and report.get("drop_event_id"):
        drop = db.drops.get(report["drop_event_id"])
        if drop and drop["verification_state"] == "FLAGGED_CONTAMINATED":
            reject_drop(drop)
    site_posture_touch(site)
    return success_object(serialize_report(report))


# --- Flat aliases ---

@bp.route("/contamination-reports", methods=["GET"])
def list_reports_flat():
    require_roles(*READ_ROLES)
    items = list(db.contamination_reports.values())
    if request.args.get("site_id"):
        items = [r for r in items if r["site_id"] == request.args["site_id"]]
    if request.args.get("drop_event_id"):
        items = [r for r in items if r.get("drop_event_id") == request.args["drop_event_id"]]
    if request.args.get("status"):
        items = [r for r in items if r["status"] == request.args["status"]]
    if request.args.get("severity"):
        items = [r for r in items if r["severity"] == request.args["severity"]]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_report(r) for r in page], limit, offset, total)


@bp.route("/contamination-reports/<report_id>", methods=["GET"])
def get_report_flat(report_id):
    require_roles(*READ_ROLES)
    report = get_report_or_404(report_id)
    return success_object(serialize_report(report))
