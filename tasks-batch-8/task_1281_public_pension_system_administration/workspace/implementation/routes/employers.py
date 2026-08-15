"""Employer endpoints plus employer-scoped contribution report creation."""

from datetime import date

from flask import Blueprint

from db import store, make_entity, public, sort_key
from errors import err_not_found, err_invalid_request, err_report_period_overlap
from middleware import (
    auth,
    require_roles,
    body,
    req_field,
    as_int,
    as_str,
    pagination,
    check_clerk_employer_path,
    check_clerk_employer,
)
from response import ok, ok_list
from utils import parse_date

bp = Blueprint("employers", __name__)

EMPLOYER_VIEW_ROLES = {"FundAdmin", "MemberServicesAnalyst", "EmployerClerk"}


def get_employer(employer_id):
    emp = store.employers.get(employer_id)
    if emp is None:
        raise err_not_found("Employer not found")
    return emp


@bp.post("/employers")
def create_employer():
    ctx = auth()
    require_roles(ctx, {"FundAdmin"})
    data = body()
    name = as_str(req_field(data, "name"), "name")
    employer_code = as_str(req_field(data, "employer_code"), "employer_code")
    for existing in store.employers.values():
        if existing["employer_code"] == employer_code:
            raise err_invalid_request("employer_code must be unique across employers")
    emp = make_entity({"name": name, "employer_code": employer_code})
    store.employers[emp["id"]] = emp
    return ok(public(emp), 201)


@bp.get("/employers/<employer_id>")
def read_employer(employer_id):
    ctx = auth()
    require_roles(ctx, EMPLOYER_VIEW_ROLES)
    check_clerk_employer_path(ctx, employer_id)
    return ok(public(get_employer(employer_id)))


@bp.get("/employers/<employer_id>/members")
def list_employer_members(employer_id):
    ctx = auth()
    require_roles(ctx, EMPLOYER_VIEW_ROLES)
    check_clerk_employer_path(ctx, employer_id)
    get_employer(employer_id)
    limit, offset = pagination()
    members = [m for m in store.members.values() if m["employer_id"] == employer_id]
    members.sort(key=sort_key)
    page = members[offset:offset + limit]
    return ok_list([public(m) for m in page], limit, offset, len(members))


@bp.get("/employers/<employer_id>/contribution-reports")
def list_employer_reports(employer_id):
    ctx = auth()
    require_roles(ctx, EMPLOYER_VIEW_ROLES)
    check_clerk_employer_path(ctx, employer_id)
    get_employer(employer_id)
    limit, offset = pagination()
    reports = [r for r in store.reports.values() if r["employer_id"] == employer_id]
    reports.sort(key=sort_key)
    page = reports[offset:offset + limit]
    return ok_list([public(r) for r in page], limit, offset, len(reports))


@bp.post("/employers/<employer_id>/contribution-reports")
def create_report(employer_id):
    ctx = auth()
    require_roles(ctx, {"EmployerClerk"})
    check_clerk_employer(ctx, employer_id)
    get_employer(employer_id)
    data = body()
    period_start = parse_date(req_field(data, "period_start"))
    if period_start is None:
        raise err_invalid_request("period_start must be an ISO date")
    period_end = parse_date(req_field(data, "period_end"))
    if period_end is None:
        raise err_invalid_request("period_end must be an ISO date")
    declared = as_int(req_field(data, "declared_total_cents"), "declared_total_cents")
    if period_end <= period_start:
        raise err_invalid_request("period_end must be after period_start")
    # Half-open [period_start, period_end): overlap iff start < other.end and
    # other.start < end; adjacency (start == prior end) is allowed.
    for other in store.reports.values():
        if other["employer_id"] != employer_id:
            continue
        if period_start < other["_period_end"] and other["_period_start"] < period_end:
            raise err_report_period_overlap()
    report = make_entity(
        {
            "employer_id": employer_id,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "declared_total_cents": declared,
            "accepted_total_cents": 0,
            "status": "DRAFT",
            "_period_start": period_start,
            "_period_end": period_end,
        }
    )
    store.reports[report["id"]] = report
    return ok(public(report), 201)
