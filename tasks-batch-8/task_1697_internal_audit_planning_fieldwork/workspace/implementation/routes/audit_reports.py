"""AuditReport endpoints (PRD 3.8): draft -> submit -> approve -> issue ->
distribute lifecycle with the CAE revision loop; issuance is the point of no
return (findings -> FINAL, workpapers locked)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_DISTRIBUTION_LIST_EMPTY,
    ERR_ENGAGEMENT_INVALID_STATE,
    ERR_FINDINGS_NOT_RESOLVED,
    ERR_REPORT_ALREADY_ISSUED,
    ERR_REPORT_INVALID_STATE,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, query_str
from services.cascades import issue_report_cascade
from services.core import new_record, public, touch
from util import CLOCK
from validate import (
    body_ref,
    check_unknown_fields,
    get_body,
    opt_enum,
    req_str,
    req_str_list,
    require_path,
)

bp = Blueprint("audit_reports", __name__)

CREATE_FIELDS = {"engagement_id", "title", "overall_conclusion"}
DISTRIBUTE_FIELDS = {"distribution_list"}
CONCLUSIONS = ("SATISFACTORY", "NEEDS_IMPROVEMENT", "UNSATISFACTORY")
RESOLVED_FINDING_STATUSES = ("AGREED", "ESCALATED", "FINAL")


@bp.post("/audit/audit-reports")
def create_report():
    authorized(["AuditManager"])
    body = get_body()
    # Stage 4: body FK existence
    body_ref(body, "engagement_id", "engagements")
    # Stage 5: shape
    check_unknown_fields(body, CREATE_FIELDS)
    engagement_id = req_str(body, "engagement_id")
    title = req_str(body, "title")
    overall_conclusion = opt_enum(body, "overall_conclusion", CONCLUSIONS)
    eng = db["engagements"][engagement_id]
    # Stage 7: drafting requires the engagement to be in REPORTING
    if eng["status"] != "REPORTING":
        raise_error(ERR_ENGAGEMENT_INVALID_STATE,
                    f"report drafting requires REPORTING, not {eng['status']}")
    rec = new_record("audit_reports", {
        "engagement_id": engagement_id,
        "title": title,
        "overall_conclusion": overall_conclusion,
        "status": "DRAFT",
        "issued_at": None,
        "distributed_at": None,
        "distribution_list": None,
    })
    return success_object(public(rec), status=201)


@bp.get("/audit/audit-reports")
def list_reports():
    filters = {
        "engagement_id": query_str("engagement_id"),
        "status": query_str("status"),
    }
    return list_response("audit_reports", filters)


@bp.get("/audit/audit-reports/<rid>")
def get_report(rid):
    return get_one("audit_reports", rid)


@bp.post("/audit/audit-reports/<rid>/submit")
def submit_report(rid):
    authorized(["AuditManager"])
    rep = require_path("audit_reports", rid)
    if rep["status"] != "DRAFT":
        raise_error(ERR_REPORT_INVALID_STATE, "report is not DRAFT")
    rep["status"] = "PENDING_APPROVAL"
    touch(rep)
    return success_object(public(rep))


@bp.post("/audit/audit-reports/<rid>/approve")
def approve_report(rid):
    authorized(["ChiefAuditExecutive"])
    rep = require_path("audit_reports", rid)
    if rep["status"] != "PENDING_APPROVAL":
        raise_error(ERR_REPORT_INVALID_STATE, "report is not PENDING_APPROVAL")
    rep["status"] = "APPROVED"
    touch(rep)
    return success_object(public(rep))


@bp.post("/audit/audit-reports/<rid>/return")
def return_report(rid):
    authorized(["ChiefAuditExecutive"])
    rep = require_path("audit_reports", rid)
    if rep["status"] != "PENDING_APPROVAL":
        raise_error(ERR_REPORT_INVALID_STATE, "report is not PENDING_APPROVAL")
    # Revision loop: CAE returns the draft for rework
    rep["status"] = "DRAFT"
    touch(rep)
    return success_object(public(rep))


@bp.post("/audit/audit-reports/<rid>/issue")
def issue_report(rid):
    authorized(["ChiefAuditExecutive"])
    rep = require_path("audit_reports", rid)
    # Stage 7: report must be APPROVED; engagement still in REPORTING
    if rep["status"] != "APPROVED":
        raise_error(ERR_REPORT_INVALID_STATE, "report is not APPROVED")
    eng = db["engagements"][rep["engagement_id"]]
    if eng["status"] != "REPORTING":
        raise_error(ERR_ENGAGEMENT_INVALID_STATE,
                    f"issuance requires REPORTING, not {eng['status']}")
    # Stage 9: no other report of the engagement already issued
    for other in db["audit_reports"].values():
        if (other["id"] != rep["id"] and other["engagement_id"] == rep["engagement_id"]
                and other["status"] in ("ISSUED", "DISTRIBUTED")):
            raise_error(ERR_REPORT_ALREADY_ISSUED,
                        "another report of this engagement is already ISSUED/DISTRIBUTED")
    # Stage 11: every finding resolved
    for f in db["findings"].values():
        if f["engagement_id"] == rep["engagement_id"] and f["status"] not in RESOLVED_FINDING_STATUSES:
            raise_error(ERR_FINDINGS_NOT_RESOLVED,
                        "all findings must be AGREED, ESCALATED, or FINAL before issuance")
    rep["status"] = "ISSUED"
    rep["issued_at"] = CLOCK.now_iso()
    touch(rep)
    issue_report_cascade(rep)
    return success_object(public(rep))


@bp.post("/audit/audit-reports/<rid>/distribute")
def distribute_report(rid):
    authorized(["ChiefAuditExecutive"])
    rep = require_path("audit_reports", rid)
    # Stage 5: shape (distribution_list required array)
    body = get_body()
    check_unknown_fields(body, DISTRIBUTE_FIELDS)
    distribution_list = req_str_list(body, "distribution_list")
    # Stage 7: must be ISSUED
    if rep["status"] != "ISSUED":
        raise_error(ERR_REPORT_INVALID_STATE, "report is not ISSUED")
    # Stage 11: non-empty recipient list (empty-set boundary)
    if len(distribution_list) == 0:
        raise_error(ERR_DISTRIBUTION_LIST_EMPTY, "distribution_list must be non-empty")
    rep["status"] = "DISTRIBUTED"
    rep["distributed_at"] = CLOCK.now_iso()
    rep["distribution_list"] = distribution_list
    touch(rep)
    return success_object(public(rep))
