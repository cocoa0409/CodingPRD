"""DisclosureReport endpoints (PRD 3.9)."""

from flask import Blueprint

from auth import ROLE_BURSAR, ROLE_COMPLIANCE, ROLE_PROGRAM_ADMIN, authenticate
from domain import (affordability_metrics, agreements_pricing_term, get_report,
                    get_term, report_json)
from errors import fail
from response import apply_filters, object_response, paginate
from store import base_record, db, in_order, now, today, touch
from validate import f_str, get_body

bp = Blueprint("disclosure", __name__)


@bp.post("/disclosure-reports")
def create_report():
    authenticate(ROLE_COMPLIANCE)
    body = get_body(("term_id", "reporting_state_code"))
    term_id = f_str(body, "term_id")
    state_code = f_str(body, "reporting_state_code", min_len=2, max_len=2,
                       pattern=r"^[A-Z]{2}$")

    term = get_term(term_id)
    for existing in db.reports.values():
        if (existing["term_id"] == term["id"]
                and existing["reporting_state_code"] == state_code):
            fail("ERR_DUPLICATE_RESOURCE_KEY")

    report = base_record()
    report.update({
        "term_id": term["id"],
        "reporting_state_code": state_code,
        "status": "DRAFT",
        "certified_by_user_id": None,
        "certified_at": None,
        "published_at": None,
        "amendment_note": None,
        "amendment_count": 0,
    })
    report.update(affordability_metrics(term["id"]))
    db.reports[report["id"]] = report
    return object_response(report_json(report), 201)


@bp.get("/disclosure-reports/<report_id>")
def read_report(report_id):
    authenticate(ROLE_PROGRAM_ADMIN, ROLE_COMPLIANCE, ROLE_BURSAR)
    return object_response(report_json(get_report(report_id)))


@bp.get("/disclosure-reports")
def list_reports():
    authenticate(ROLE_PROGRAM_ADMIN, ROLE_COMPLIANCE, ROLE_BURSAR)
    items = apply_filters(in_order(db.reports.values()), [
        ("term_id", "term_id"),
        ("reporting_state_code", "reporting_state_code"),
        ("status", "status"),
        ("compliance_status", "compliance_status"),
    ])
    return paginate(items, report_json)


@bp.post("/disclosure-reports/<report_id>/certify")
def certify_report(report_id):
    actor = authenticate(ROLE_COMPLIANCE)
    get_body(())
    report = get_report(report_id)
    term = get_term(report["term_id"])

    if report["status"] != "DRAFT":
        fail("ERR_INVALID_STATE")
    for agreement in agreements_pricing_term(term["id"]):
        if agreement["reconciliation_status"] not in ("COMPUTED", "DISPUTED", "SETTLED"):
            fail("ERR_RECONCILIATION_NOT_CURRENT")
    if today() > term["disclosure_deadline_date"]:
        fail("ERR_DISCLOSURE_DEADLINE_PASSED")

    report.update(affordability_metrics(term["id"]))
    report["status"] = "CERTIFIED"
    report["certified_at"] = now()
    report["certified_by_user_id"] = actor.user_id
    touch(report)
    return object_response(report_json(report))


@bp.post("/disclosure-reports/<report_id>/amend")
def amend_report(report_id):
    authenticate(ROLE_COMPLIANCE)
    body = get_body(("amendment_note",))
    note = f_str(body, "amendment_note")
    report = get_report(report_id)
    term = get_term(report["term_id"])

    if report["status"] != "CERTIFIED":
        fail("ERR_INVALID_STATE")

    report.update(affordability_metrics(term["id"]))
    report["status"] = "DRAFT"
    report["amendment_count"] += 1
    report["amendment_note"] = note
    report["certified_at"] = None
    report["certified_by_user_id"] = None
    touch(report)
    return object_response(report_json(report))
