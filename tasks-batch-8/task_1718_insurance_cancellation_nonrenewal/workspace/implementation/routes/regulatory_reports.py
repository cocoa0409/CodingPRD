"""RegulatoryReport endpoints (PRD §2.10)."""

import clock
import db
import util
from errors import err_invalid_state, err_report_period_still_open
from middleware import require_roles
from response import success_list, success_object
from flask import Blueprint, request

bp = Blueprint("regulatory_reports", __name__)

REPORT_READERS = ("ComplianceOfficer", "Underwriter")


@bp.get("/carrier/regulatory-reports")
@require_roles(*REPORT_READERS)
def list_reports(_user_id, _role):
    limit, offset = util.get_pagination()
    records = util.apply_filters(
        list(db.regulatory_reports.values()),
        {
            "state_profile_id": request.args.get("state_profile_id"),
            "report_period": request.args.get("report_period"),
            "status": request.args.get("status"),
        },
    )
    records = util.sort_chronological(records)
    page = records[offset : offset + limit]
    return success_list([util.public(r) for r in page], limit, offset, len(records))


@bp.get("/carrier/regulatory-reports/<reportId>")
@require_roles(*REPORT_READERS)
def get_report(reportId, _user_id, _role):
    rec = util.resolve(db.regulatory_reports, reportId)
    return success_object(util.public(rec), 200)


@bp.post("/carrier/regulatory-reports/<reportId>/finalize")
@require_roles("ComplianceOfficer")
def finalize_report(reportId, _user_id, _role):
    rec = util.resolve(db.regulatory_reports, reportId)
    if rec["status"] != "OPEN":
        raise err_invalid_state("Only an OPEN report can be finalized")
    # Current clock month must be strictly later than the report period.
    if clock.today().isoformat()[:7] <= rec["report_period"]:
        raise err_report_period_still_open()
    rec["status"] = "FINALIZED"
    util.touch(rec)
    return success_object(util.public(rec), 200)
