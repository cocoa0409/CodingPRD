"""ReportFiling endpoints (PRD §3.5): create, compile, submit, record-decision,
reopen."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_STUDY_NOT_REPORTABLE,
    ERR_DUPLICATE_FILING,
    ERR_FILING_INVALID_STATE,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, public
from services.calculations import compile_band_rows
from services.core import new_record, touch
from util import clock_now_iso, clock_today, parse_date
from validate import get_body, req_int, req_enum, req_date, opt_str, opt_nullable_str, require_path_resource, require_fk

bp = Blueprint("filings", __name__)

REPORT_TYPES = {"EEO_WORKFORCE_COMP", "STATE_PAY_DATA"}
REPORTABLE_STATES = {"PRIVILEGED_FINAL", "REMEDIATION_OPEN", "MONITORING", "CLOSED"}
FILING_DECISIONS = {"ACCEPTED", "REJECTED"}


@bp.post("/report-filings")
def create_filing():
    authorized(["ComplianceReporter"])
    body = get_body()
    study_id = body.get("study_id")
    if study_id is None or not isinstance(study_id, str) or study_id.strip() == "":
        raise_error(ERR_INVALID_REQUEST, "missing or invalid field: study_id")
    # Priority 3: body FK existence, left-to-right
    study = require_fk("pay_equity_studies", study_id, "study_id")
    jurisdiction_rule_id = opt_nullable_str(body, "jurisdiction_rule_id", None)
    if jurisdiction_rule_id is not None:
        require_fk("jurisdiction_rules", jurisdiction_rule_id, "jurisdiction_rule_id")
    # Priority 3.7: shape
    report_type = req_enum(body, "report_type", REPORT_TYPES)
    reporting_year = req_int(body, "reporting_year")
    due_date = req_date(body, "due_date")
    if report_type == "STATE_PAY_DATA" and jurisdiction_rule_id is None:
        raise_error(ERR_INVALID_REQUEST,
                    "jurisdiction_rule_id is required for STATE_PAY_DATA")
    # Priority 4: state — study must be reportable
    if study["status"] not in REPORTABLE_STATES:
        raise_error(ERR_STUDY_NOT_REPORTABLE,
                    "filing creation requires the study to be PRIVILEGED_FINAL, "
                    "REMEDIATION_OPEN, MONITORING, or CLOSED")
    # Priority 7: unique per (study, report_type, reporting_year)
    for f in db["report_filings"].values():
        if (f["study_id"] == study_id and f["report_type"] == report_type
                and f["reporting_year"] == reporting_year):
            raise_error(ERR_DUPLICATE_FILING,
                        "a filing already exists for (study, report_type, reporting_year)")

    rec = new_record("report_filings", {
        "study_id": study_id,
        "report_type": report_type,
        "jurisdiction_rule_id": jurisdiction_rule_id,
        "reporting_year": reporting_year,
        "due_date": due_date,
        "band_rows": None,
        "total_headcount": None,
        "submitted_at": None,
        "late_submission": None,
        "status": "COMPILING",
    })
    return success_object(public(rec), status=201)


@bp.get("/report-filings")
def list_filings():
    return list_response("report_filings", {
        "study_id": request.args.get("study_id"),
        "status": request.args.get("status"),
        "jurisdiction_rule_id": request.args.get("jurisdiction_rule_id"),
    })


@bp.get("/report-filings/<rid>")
def get_filing(rid):
    return get_one("report_filings", rid)


@bp.post("/report-filings/<rid>/compile")
def compile_filing(rid):
    authorized(["ComplianceReporter"])
    filing = require_path_resource("report_filings", rid)
    if filing["status"] != "COMPILING":
        raise_error(ERR_FILING_INVALID_STATE, "compile requires a COMPILING filing")
    band_rows, total = compile_band_rows(filing["study_id"])
    filing["band_rows"] = band_rows
    filing["total_headcount"] = total
    filing["status"] = "INTERNAL_REVIEW"
    touch(filing)
    return success_object(public(filing))


@bp.post("/report-filings/<rid>/submit")
def submit_filing(rid):
    authorized(["ComplianceReporter"])
    filing = require_path_resource("report_filings", rid)
    if filing["status"] != "INTERNAL_REVIEW":
        raise_error(ERR_FILING_INVALID_STATE, "submit requires an INTERNAL_REVIEW filing")
    filing["submitted_at"] = clock_now_iso()
    # Late iff the clock's UTC date is strictly after due_date; submitting
    # exactly on the due date is NOT late (PRD §3.5).
    filing["late_submission"] = clock_today() > parse_date(filing["due_date"])
    filing["status"] = "SUBMITTED"
    touch(filing)
    return success_object(public(filing))


@bp.post("/report-filings/<rid>/record-decision")
def record_decision(rid):
    authorized(["ComplianceReporter"])
    filing = require_path_resource("report_filings", rid)
    body = get_body()
    # Priority 3.7 (shape) before priority 4 (state)
    decision = req_enum(body, "decision", FILING_DECISIONS)
    opt_str(body, "notes", None)
    if filing["status"] != "SUBMITTED":
        raise_error(ERR_FILING_INVALID_STATE,
                    "record-decision requires a SUBMITTED filing")
    filing["status"] = decision
    touch(filing)
    return success_object(public(filing))


@bp.post("/report-filings/<rid>/reopen")
def reopen_filing(rid):
    authorized(["ComplianceReporter"])
    filing = require_path_resource("report_filings", rid)
    if filing["status"] != "REJECTED":
        raise_error(ERR_FILING_INVALID_STATE, "reopen requires a REJECTED filing")
    filing["band_rows"] = None
    filing["total_headcount"] = None
    filing["submitted_at"] = None
    filing["late_submission"] = None
    filing["status"] = "COMPILING"
    touch(filing)
    return success_object(public(filing))
