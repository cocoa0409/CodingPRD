"""Contribution reporting & reconciliation: report get, line add/list/review,
submit, finalize — including the VARIANCE -> RECONCILED bubble-up."""

from datetime import date

from flask import Blueprint

from db import store, make_entity, touch, public, sort_key
from errors import (
    err_not_found,
    err_invalid_request,
    err_invalid_state,
    err_duplicate_line_period,
    err_lines_pending,
    err_reconciliation_variance,
)
from middleware import (
    auth,
    require_roles,
    body,
    req_field,
    as_int,
    pagination,
    check_clerk_employer,
)
from response import ok, ok_list
from services import calcs

bp = Blueprint("contributions", __name__)

REPORT_VIEW_ROLES = {"FundAdmin", "MemberServicesAnalyst", "EmployerClerk"}


def get_report(report_id):
    report = store.reports.get(report_id)
    if report is None:
        raise err_not_found("Contribution report not found")
    return report


def report_lines(report_id):
    out = [l for l in store.lines.values() if l["report_id"] == report_id]
    out.sort(key=sort_key)
    return out


def recompute_report_total(report):
    """accepted_total_cents = sum over ACCEPTED lines; bump the report's
    version when the stored value changed."""
    total = sum(
        l["contribution_amount_cents"]
        for l in report_lines(report["id"])
        if l["status"] == "ACCEPTED"
    )
    if total != report["accepted_total_cents"]:
        report["accepted_total_cents"] = total
        touch(report)


@bp.get("/contribution-reports/<report_id>")
def read_report(report_id):
    ctx = auth()
    require_roles(ctx, REPORT_VIEW_ROLES)
    report = get_report(report_id)
    check_clerk_employer(ctx, report["employer_id"])
    return ok(public(report))


@bp.post("/contribution-reports/<report_id>/lines")
def create_line(report_id):
    ctx = auth()
    require_roles(ctx, {"EmployerClerk"})
    report = get_report(report_id)
    check_clerk_employer(ctx, report["employer_id"])
    if report["status"] != "DRAFT":
        raise err_invalid_state("Lines may only be added while the report is DRAFT")
    data = body()
    member_id = req_field(data, "member_id")
    if not isinstance(member_id, str):
        raise err_invalid_request("member_id must be a string")
    if member_id not in store.members:
        raise err_not_found("Member not found")
    fiscal_year = as_int(req_field(data, "fiscal_year"), "fiscal_year")
    period_salary = as_int(req_field(data, "period_salary_cents"), "period_salary_cents")
    contribution = as_int(
        req_field(data, "contribution_amount_cents"), "contribution_amount_cents"
    )
    service_months = data.get("service_months")
    if service_months is None:
        service_months = 12
    else:
        service_months = as_int(service_months, "service_months")
        if service_months < 1 or service_months > 12:
            raise err_invalid_request("service_months must be between 1 and 12")
    # The credited fiscal year must fall inside the half-open report period.
    fy_start = date(fiscal_year, 1, 1)
    if not (report["_period_start"] <= fy_start < report["_period_end"]):
        raise err_invalid_request("fiscal_year falls outside the report period")
    for other in report_lines(report_id):
        if other["member_id"] == member_id and other["fiscal_year"] == fiscal_year:
            raise err_duplicate_line_period()
    line = make_entity(
        {
            "report_id": report_id,
            "member_id": member_id,
            "fiscal_year": fiscal_year,
            "period_salary_cents": period_salary,
            "contribution_amount_cents": contribution,
            "service_months": service_months,
            "status": "PENDING",
            "review_note": None,
        }
    )
    store.lines[line["id"]] = line
    return ok(public(line), 201)


@bp.get("/contribution-reports/<report_id>/lines")
def list_lines(report_id):
    ctx = auth()
    require_roles(ctx, REPORT_VIEW_ROLES)
    report = get_report(report_id)
    check_clerk_employer(ctx, report["employer_id"])
    limit, offset = pagination()
    lines = report_lines(report_id)
    page = lines[offset:offset + limit]
    return ok_list([public(l) for l in page], limit, offset, len(lines))


@bp.post("/contribution-reports/<report_id>/submit")
def submit_report(report_id):
    ctx = auth()
    require_roles(ctx, {"EmployerClerk"})
    report = get_report(report_id)
    check_clerk_employer(ctx, report["employer_id"])
    if report["status"] != "DRAFT":
        raise err_invalid_state("Only a DRAFT report can be submitted")
    if not report_lines(report_id):
        raise err_invalid_request("Cannot submit a report with no lines")
    report["status"] = "SUBMITTED"
    touch(report)
    return ok(public(report))


@bp.post("/contribution-reports/<report_id>/lines/<line_id>/review")
def review_line(report_id, line_id):
    ctx = auth()
    require_roles(ctx, {"MemberServicesAnalyst"})
    report = get_report(report_id)
    line = store.lines.get(line_id)
    if line is None or line["report_id"] != report_id:
        raise err_not_found("Contribution line not found")
    data = body()
    decision = data.get("decision")
    if decision not in ("ACCEPT", "REJECT"):
        raise err_invalid_request("decision must be ACCEPT or REJECT")
    review_note = data.get("review_note")

    if report["status"] not in ("SUBMITTED", "VARIANCE"):
        raise err_invalid_state("Lines may only be reviewed while the report is SUBMITTED or VARIANCE")

    if line["status"] == "PENDING":
        new_status = "ACCEPTED" if decision == "ACCEPT" else "REJECTED"
    elif line["status"] == "REJECTED" and decision == "ACCEPT" and report["status"] == "VARIANCE":
        # Repair path: re-review of a REJECTED line is permitted only in VARIANCE.
        new_status = "ACCEPTED"
    else:
        raise err_invalid_state(
            "Cannot apply decision %s to a line in %s" % (decision, line["status"])
        )

    line["status"] = new_status
    if review_note is not None:
        line["review_note"] = review_note
    touch(line)

    recompute_report_total(report)

    if new_status == "ACCEPTED":
        member = store.members.get(line["member_id"])
        if member is not None and calcs.recompute_member(member):
            touch(member)

    # Bubble-up: a VARIANCE report reconciles automatically when the review
    # leaves no PENDING/REJECTED lines and the totals match to the cent.
    if report["status"] == "VARIANCE":
        lines = report_lines(report_id)
        if (
            all(l["status"] not in ("PENDING", "REJECTED") for l in lines)
            and report["accepted_total_cents"] == report["declared_total_cents"]
        ):
            report["status"] = "RECONCILED"
            touch(report)

    return ok(public(line))


@bp.post("/contribution-reports/<report_id>/finalize")
def finalize_report(report_id):
    ctx = auth()
    require_roles(ctx, {"MemberServicesAnalyst"})
    report = get_report(report_id)
    if report["status"] != "SUBMITTED":
        raise err_invalid_state("Only a SUBMITTED report can be finalized")
    lines = report_lines(report_id)
    if any(l["status"] == "PENDING" for l in lines):
        raise err_lines_pending()
    if any(l["status"] == "REJECTED" for l in lines):
        report["status"] = "VARIANCE"
        touch(report)
        return ok(public(report))
    recompute_report_total(report)
    if report["accepted_total_cents"] != report["declared_total_cents"]:
        raise err_reconciliation_variance()
    report["status"] = "RECONCILED"
    touch(report)
    return ok(public(report))
