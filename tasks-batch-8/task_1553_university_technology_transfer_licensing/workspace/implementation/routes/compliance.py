"""Federal compliance reports."""
from flask import Blueprint

from store import db, create_record, touch, now
from util import (ApiError, require, get_body, check_schema, v_str, v_enum,
                  v_dt, ok_object, ok_list, paginate)
from serializers import ser_compliance_report
from services import compute_compliance_due_date

bp = Blueprint("compliance", __name__)

REPORT_TYPES = ("INITIAL_DISCLOSURE", "ELECTION_OF_TITLE", "UTILIZATION_REPORT", "EXTENSION_REQUEST")
CLIENT_DATED_TYPES = ("UTILIZATION_REPORT", "EXTENSION_REQUEST")


def _get_disclosure_or_404(disclosure_id):
    disc = db.disclosures.get(disclosure_id)
    if disc is None:
        raise ApiError("ERR_DISCLOSURE_NOT_FOUND", 404, "Disclosure id does not exist")
    return disc


def _get_report_or_404(report_id):
    rep = db.compliance_reports.get(report_id)
    if rep is None:
        raise ApiError("ERR_COMPLIANCE_REPORT_NOT_FOUND", 404, "FederalComplianceReport id does not exist")
    return rep


@bp.route("/tlo/disclosures/<disclosureId>/compliance-reports", methods=["POST"])
def create_compliance_report(disclosureId):
    uid, _ = require("ComplianceOfficer")
    disc = _get_disclosure_or_404(disclosureId)
    data = check_schema(get_body(), {
        "report_type": (True, v_enum(*REPORT_TYPES)),
        "due_date": (False, v_dt),
    })
    if data["report_type"] in CLIENT_DATED_TYPES and "due_date" not in data:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "due_date is required for UTILIZATION_REPORT and EXTENSION_REQUEST")
    if disc["funding_source"] not in ("FEDERAL", "MIXED"):
        raise ApiError("ERR_NOT_FEDERALLY_FUNDED", 422,
                       "Compliance reports require funding_source FEDERAL or MIXED")
    due_date = compute_compliance_due_date(disc, data["report_type"], data.get("due_date"))
    rep = create_record(db.compliance_reports, {
        "disclosure_id": disc["id"],
        "report_type": data["report_type"],
        "due_date": due_date,
        "prepared_by_user_id": uid,
        "certified_by_user_id": None,
        "submitted_at": None,
        "late_flag": None,
        "rejection_reason": None,
        "status": "DRAFT",
    })
    return ok_object(ser_compliance_report(rep), status=201)


@bp.route("/tlo/disclosures/<disclosureId>/compliance-reports", methods=["GET"])
def list_compliance_reports(disclosureId):
    require()
    disc = _get_disclosure_or_404(disclosureId)
    records = [r for r in db.compliance_reports.values() if r["disclosure_id"] == disc["id"]]
    page, limit, offset, total = paginate(records)
    return ok_list([ser_compliance_report(r) for r in page], limit, offset, total)


@bp.route("/tlo/compliance-reports/<reportId>", methods=["GET"])
def get_compliance_report(reportId):
    require()
    return ok_object(ser_compliance_report(_get_report_or_404(reportId)))


@bp.route("/tlo/compliance-reports/<reportId>/submit", methods=["POST"])
def submit_compliance_report(reportId):
    require("ComplianceOfficer")
    rep = _get_report_or_404(reportId)
    check_schema(get_body(), {})
    if rep["status"] != "DRAFT":
        raise ApiError("ERR_COMPLIANCE_REPORT_INVALID_STATE", 409, "Submit requires report status DRAFT")
    rep["status"] = "PENDING_CERTIFICATION"
    touch(rep)
    return ok_object(ser_compliance_report(rep))


@bp.route("/tlo/compliance-reports/<reportId>/certify", methods=["POST"])
def certify_compliance_report(reportId):
    uid, _ = require("ComplianceDirector")
    rep = _get_report_or_404(reportId)
    check_schema(get_body(), {})
    if rep["status"] != "PENDING_CERTIFICATION":
        raise ApiError("ERR_COMPLIANCE_REPORT_INVALID_STATE", 409,
                       "Certify requires report status PENDING_CERTIFICATION")
    if uid == rep["prepared_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 409,
                       "Certifier must differ from the report's preparer")
    rep["certified_by_user_id"] = uid
    rep["submitted_at"] = now()
    rep["late_flag"] = rep["submitted_at"] > rep["due_date"]
    rep["status"] = "SUBMITTED"
    touch(rep)
    return ok_object(ser_compliance_report(rep))


@bp.route("/tlo/compliance-reports/<reportId>/reject", methods=["POST"])
def reject_compliance_report(reportId):
    require("ComplianceDirector")
    rep = _get_report_or_404(reportId)
    data = check_schema(get_body(), {"rejection_reason": (True, v_str)})
    if rep["status"] != "PENDING_CERTIFICATION":
        raise ApiError("ERR_COMPLIANCE_REPORT_INVALID_STATE", 409,
                       "Reject requires report status PENDING_CERTIFICATION")
    rep["status"] = "DRAFT"
    rep["rejection_reason"] = data["rejection_reason"]
    touch(rep)
    return ok_object(ser_compliance_report(rep))


@bp.route("/tlo/compliance-reports/<reportId>/agency-response", methods=["POST"])
def agency_response(reportId):
    require("ComplianceDirector")
    rep = _get_report_or_404(reportId)
    data = check_schema(get_body(), {
        "outcome": (True, v_enum("ACCEPTED", "REJECTED")),
        "agency_notes": (False, v_str),
    })
    if rep["status"] != "SUBMITTED":
        raise ApiError("ERR_COMPLIANCE_REPORT_INVALID_STATE", 409,
                       "Agency response requires report status SUBMITTED")
    if data["outcome"] == "ACCEPTED":
        rep["status"] = "AGENCY_ACCEPTED"
    else:
        rep["status"] = "DRAFT"
        rep["rejection_reason"] = data.get("agency_notes")
        rep["submitted_at"] = None
        rep["certified_by_user_id"] = None
        rep["late_flag"] = None
    touch(rep)
    return ok_object(ser_compliance_report(rep))
