"""FieldReport endpoints."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_SITE_VISIT_INVALID_STATE,
    ERR_FIELD_REPORT_INVALID_STATE,
    ERR_SOD_REPORT_ISSUER_IS_PERFORMER,
    ERR_FIELD_REPORT_WINDOW_EXPIRED,
    ERR_NONCONFORMANCE_CLEARANCE_VISIT_INVALID,
)
from middleware import get_user_context, require_role, get_body
from response import success_object, success_list
from services.helpers import (
    base_entity, touch, paginate, get_site_visit, get_field_report,
    req_str, opt_str, opt_bool, opt_enum,
)

bp = Blueprint("field_reports", __name__)

ALL_ROLES = ("FirmAdmin", "ArchitectCA", "Contractor", "Owner")
CONFORMANCE_SUMMARIES = ("CONFORMING", "MINOR_DEVIATIONS", "NONCONFORMING")


def _field_report_for_visit(visit_id: str):
    for r in db.field_reports.values():
        if r["site_visit_id"] == visit_id:
            return r
    return None


@bp.post("/ca/field-reports")
def create_field_report():
    _, role = get_user_context()
    require_role(role, ("ArchitectCA",))
    body = get_body(required=True)
    site_visit_id = req_str(body, "site_visit_id")
    issued_by_user_id = req_str(body, "issued_by_user_id")
    conformance_summary = opt_enum(body, "conformance_summary", CONFORMANCE_SUMMARIES)
    nonconforming_work_flag = opt_bool(body, "nonconforming_work_flag", False)
    notes = opt_str(body, "notes", None)

    visit = get_site_visit(site_visit_id)
    if visit["status"] != "PERFORMED":
        raise ApiError(ERR_SITE_VISIT_INVALID_STATE, "field-report creation requires visit PERFORMED", 409)

    # Segregation of duties (stage 9) precedes the issuance window (stage 10).
    if issued_by_user_id == visit["performed_by_user_id"]:
        raise ApiError(
            ERR_SOD_REPORT_ISSUER_IS_PERFORMER,
            "Field report issued_by_user_id equals the visit's performed_by_user_id",
            422,
        )

    project = db.projects[visit["project_id"]]
    performed_date = db.LogicalClock.date_of(db.LogicalClock._parse(visit["performed_at"]))
    deadline = db.add_days(performed_date, project["field_report_window_days"])
    if db.today() > deadline:
        raise ApiError(
            ERR_FIELD_REPORT_WINDOW_EXPIRED,
            "Field report issued more than field_report_window_days after the visit was performed",
            409,
        )

    report = base_entity()
    report.update({
        "site_visit_id": site_visit_id,
        "issued_by_user_id": issued_by_user_id,
        "issued_at": db.now_iso(),
        "conformance_summary": conformance_summary,
        "nonconforming_work_flag": nonconforming_work_flag,
        "nonconformance_status": "OPEN" if nonconforming_work_flag else "NONE",
        "clearing_visit_id": None,
        "notes": notes,
    })
    db.field_reports[report["id"]] = report
    # The visit advances to REPORT_ISSUED (system transition), enforcing 1:1.
    visit["status"] = "REPORT_ISSUED"
    touch(visit)
    return success_object(report, 201)


@bp.get("/ca/field-reports")
def list_field_reports():
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    items = list(db.field_reports.values())
    site_visit_id = request.args.get("site_visit_id")
    if site_visit_id is not None:
        items = [r for r in items if r["site_visit_id"] == site_visit_id]
    issued_by = request.args.get("issued_by_user_id")
    if issued_by is not None:
        items = [r for r in items if r["issued_by_user_id"] == issued_by]
    clearing = request.args.get("clearing_visit_id")
    if clearing is not None:
        items = [r for r in items if r["clearing_visit_id"] == clearing]
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)


@bp.get("/ca/field-reports/<fid>")
def get_one_field_report(fid):
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    return success_object(get_field_report(fid))


@bp.post("/ca/field-reports/<fid>/clear-nonconformance")
def clear_nonconformance(fid):
    _, role = get_user_context()
    require_role(role, ("ArchitectCA",))
    body = get_body(required=True)
    clearing_visit_id = req_str(body, "clearing_visit_id")

    report = get_field_report(fid)
    clearing_visit = get_site_visit(clearing_visit_id)

    if report["nonconformance_status"] != "OPEN":
        raise ApiError(
            ERR_FIELD_REPORT_INVALID_STATE,
            "clear-nonconformance requires nonconformance_status OPEN",
            409,
        )

    flagged_visit = db.site_visits[report["site_visit_id"]]
    # Clearing visit validity: same project, REPORT_ISSUED, its own FieldReport
    # conforming, performed at or after the flagged visit.
    valid = (
        clearing_visit["project_id"] == flagged_visit["project_id"]
        and clearing_visit["status"] == "REPORT_ISSUED"
    )
    if valid:
        clearing_report = _field_report_for_visit(clearing_visit["id"])
        if clearing_report is None or clearing_report["nonconforming_work_flag"]:
            valid = False
    if valid:
        flagged_performed = db.LogicalClock._parse(flagged_visit["performed_at"])
        clearing_performed = db.LogicalClock._parse(clearing_visit["performed_at"])
        if clearing_performed < flagged_performed:
            valid = False
    if not valid:
        raise ApiError(
            ERR_NONCONFORMANCE_CLEARANCE_VISIT_INVALID,
            "clearing_visit_id is not a REPORT_ISSUED visit on the same project with a "
            "conforming report performed at or after the flagged visit",
            422,
        )

    report["nonconformance_status"] = "CLEARED"
    report["clearing_visit_id"] = clearing_visit_id
    touch(report)
    return success_object(report)
