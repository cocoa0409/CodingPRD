"""Pathology report routing, finalization and amendment."""
from flask import Blueprint

from core import by_seq, db, fail, touch
from core import respond_list, respond_object
from validation import (
    apply_page,
    auth,
    body,
    filter_enum,
    filter_value,
    opt_bool,
    pagination,
    req_string,
)
from services import (
    derive_findings,
    get_report,
    pathology_finalize_cascade,
    validate_specimens,
)

bp = Blueprint("pathology", __name__)

REPORT_STATUSES = ("RECEIVED", "FINALIZED", "AMENDED")


@bp.get("/pathology-reports/<report_id>")
def read_report(report_id):
    auth("Pathologist", "Endoscopist", "PracticeAdmin", "QualityOfficer")
    return respond_object(get_report(report_id))


@bp.get("/pathology-reports")
def list_reports():
    auth("Pathologist", "Endoscopist", "PracticeAdmin", "QualityOfficer")
    limit, offset = pagination()
    booking_id = filter_value("booking_id")
    routed_to = filter_value("routed_to_endoscopist_id")
    status = filter_enum("status", REPORT_STATUSES)
    rows = by_seq(list(db.reports.values()))
    if booking_id is not None:
        rows = [r for r in rows if r["booking_id"] == booking_id]
    if routed_to is not None:
        rows = [r for r in rows if r["routed_to_endoscopist_id"] == routed_to]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, meta = apply_page(rows, limit, offset)
    return respond_list(page, meta)


@bp.post("/pathology-reports/<report_id>/finalize")
def finalize_report(report_id):
    auth("Pathologist")
    report = get_report(report_id)
    if report["status"] not in ("RECEIVED", "AMENDED"):
        fail("ERR_INVALID_PATHOLOGY_STATE",
             "Finalization is not admitted from %s." % report["status"])
    if not report["specimens"]:
        fail("ERR_NO_SPECIMENS", "The report carries no specimens.")

    booking = db.bookings[report["booking_id"]]
    episode = db.episodes[booking["episode_id"]]
    pathology_finalize_cascade(report, booking, episode)
    return respond_object(report)


@bp.post("/pathology-reports/<report_id>/amend")
def amend_report(report_id):
    auth("Pathologist")
    data = body()
    specimens = validate_specimens(data, "specimens")
    high_grade_dysplasia = opt_bool(data, "high_grade_dysplasia", False)
    amendment_reason = req_string(data, "amendment_reason")

    report = get_report(report_id)
    if report["status"] != "FINALIZED":
        fail("ERR_INVALID_PATHOLOGY_STATE",
             "Amendment is not admitted from %s." % report["status"])

    report["specimens"] = specimens
    report["high_grade_dysplasia"] = high_grade_dysplasia
    findings = derive_findings(specimens)
    report.update(findings)
    report["status"] = "AMENDED"
    report["amendment_count"] = int(report["amendment_count"]) + 1
    report["amendment_reason"] = amendment_reason
    touch(report)
    return respond_object(report)
