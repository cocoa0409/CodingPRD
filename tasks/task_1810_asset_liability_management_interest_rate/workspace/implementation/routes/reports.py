"""AlcoReport endpoints (PRD 3.8): the monthly ALCO pack."""

import store
from envelope import list_response, object_response
from errors import ApiError
from serializers import report_json
from services import find_open_report, new_report, touch
from validate import req_month

from routes.common import READ_ROLES, endpoint, get_or_404


@endpoint("POST", "/books/<book_id>/alco-reports", roles=["TreasuryAnalyst"])
def create_report(ctx):
    book = get_or_404(store.books, ctx.param("book_id"))
    period_month = req_month(ctx.body, "period_month")  # rung 4
    # Rung 8: only one non-terminal report per (book, period_month).
    if find_open_report(book["id"], period_month) is not None:
        raise ApiError("ERR_REPORT_PERIOD_CONFLICT")
    report = new_report(book["id"], period_month)  # DRAFT, aggregates initialized
    return object_response(report_json(report), 201)


@endpoint("GET", "/books/<book_id>/alco-reports", roles=READ_ROLES)
def list_reports(ctx):
    book = get_or_404(store.books, ctx.param("book_id"))
    rows = [r for r in store.reports.values() if r["book_id"] == book["id"]]
    status = ctx.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_response(rows, ctx.args, report_json)


@endpoint("GET", "/alco-reports/<report_id>", roles=READ_ROLES)
def get_report(ctx):
    report = get_or_404(store.reports, ctx.param("report_id"))
    return object_response(report_json(report))


@endpoint("POST", "/alco-reports/<report_id>/submit", roles=["TreasuryAnalyst"])
def submit_report(ctx):
    report = get_or_404(store.reports, ctx.param("report_id"))
    # Rung 6: DRAFT -> SUBMITTED.
    if report["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    # Rung 12: complete regulatory coverage is required.
    if not report["regulatory_coverage_complete"]:
        raise ApiError("ERR_REGULATORY_COVERAGE_INCOMPLETE")
    report["status"] = "SUBMITTED"
    report["submitted_by_user_id"] = ctx.user_id
    touch(report)
    return object_response(report_json(report))


@endpoint("POST", "/alco-reports/<report_id>/acknowledge", roles=["ALCOChair"])
def acknowledge_report(ctx):
    report = get_or_404(store.reports, ctx.param("report_id"))
    # Rung 6: SUBMITTED -> ACKNOWLEDGED.
    if report["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    # Rung 7: segregation of duties - acknowledger must differ from submitter.
    if ctx.user_id == report["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    # Rung 12: zero open breaches.
    if report["open_breach_count"] != 0:
        raise ApiError("ERR_OPEN_BREACHES_REMAIN")
    report["status"] = "ACKNOWLEDGED"
    report["acknowledged_by_user_id"] = ctx.user_id
    touch(report)
    return object_response(report_json(report))
