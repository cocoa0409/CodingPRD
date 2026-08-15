"""DisclosureReport endpoints."""

from flask import Blueprint

import db
from errors import ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE_TRANSITION
from middleware import ALL_ROLES, require_roles
from response import success_response
from services import get_or_404, public, touch
from validation import get_body, paginate, parse_pagination, sorted_by_creation

bp = Blueprint("reports", __name__)


@bp.get("/cecl/model-runs/<runId>/disclosure-reports")
def list_run_reports(runId):
    require_roles(ALL_ROLES)
    get_or_404(db.runs, runId, "ModelRun")
    limit, offset = parse_pagination()
    items = [r for r in db.reports.values() if r["run_id"] == runId]
    items = sorted_by_creation(items)
    page, pagination = paginate(items, limit, offset)
    return success_response([public(r) for r in page], 200, "array", pagination)


@bp.get("/cecl/disclosure-reports/<reportId>")
def get_report(reportId):
    require_roles(ALL_ROLES)
    report = get_or_404(db.reports, reportId, "DisclosureReport")
    return success_response(public(report), 200)


@bp.post("/cecl/disclosure-reports/<reportId>/submit_for_audit")
def submit_for_audit(reportId):
    require_roles(["CreditAnalyst"])
    get_body()
    report = get_or_404(db.reports, reportId, "DisclosureReport")
    if report["status"] != "PREPARED":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            409,
            "Only a PREPARED report can be submitted for audit",
        )
    report["status"] = "UNDER_AUDIT_REVIEW"
    touch(report)
    return success_response(public(report), 200)


@bp.post("/cecl/disclosure-reports/<reportId>/sign_off")
def sign_off_report(reportId):
    require_roles(["ExternalAuditor"])
    report = get_or_404(db.reports, reportId, "DisclosureReport")
    body = get_body()
    audit_reference = body.get("audit_reference")
    if not isinstance(audit_reference, str) or not audit_reference.strip():
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "audit_reference must be a non-empty string"
        )
    if report["status"] != "UNDER_AUDIT_REVIEW":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            409,
            "Only a report UNDER_AUDIT_REVIEW can be signed off",
        )
    report["audit_reference"] = audit_reference
    report["status"] = "RELEASED"
    touch(report)
    return success_response(public(report), 200)


@bp.post("/cecl/disclosure-reports/<reportId>/return_for_revision")
def return_for_revision(reportId):
    require_roles(["ExternalAuditor"])
    report = get_or_404(db.reports, reportId, "DisclosureReport")
    body = get_body()
    revision_notes = body.get("revision_notes")
    if not isinstance(revision_notes, str) or not revision_notes.strip():
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "revision_notes must be a non-empty string"
        )
    if report["status"] != "UNDER_AUDIT_REVIEW":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            409,
            "Only a report UNDER_AUDIT_REVIEW can be returned for revision",
        )
    report["revision_notes"] = revision_notes
    report["status"] = "PREPARED"
    touch(report)
    return success_response(public(report), 200)
