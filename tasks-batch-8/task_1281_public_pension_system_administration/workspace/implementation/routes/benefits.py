"""Benefit endpoints: get / return-to-work earnings reports / reinstate."""

from flask import Blueprint

from db import store, touch, public, now, current_fund
from errors import (
    err_not_found,
    err_invalid_request,
    err_invalid_state,
    err_benefit_not_active,
)
from middleware import (
    auth,
    require_roles,
    body,
    req_field,
    as_int,
    check_member_resource,
    check_benefit_view,
)
from response import ok

bp = Blueprint("benefits", __name__)

BENEFIT_VIEW_ROLES = {
    "FundAdmin",
    "MemberServicesAnalyst",
    "BenefitApprover",
    "Member",
    "SurvivorClaimant",
}


def get_benefit(benefit_id):
    benefit = store.benefits.get(benefit_id)
    if benefit is None:
        raise err_not_found("Benefit not found")
    return benefit


@bp.get("/benefits/<benefit_id>")
def read_benefit(benefit_id):
    ctx = auth()
    require_roles(ctx, BENEFIT_VIEW_ROLES)
    benefit = get_benefit(benefit_id)
    check_benefit_view(ctx, benefit)
    return ok(public(benefit))


@bp.post("/benefits/<benefit_id>/earnings-reports")
def report_earnings(benefit_id):
    ctx = auth()
    require_roles(ctx, {"Member", "MemberServicesAnalyst"})
    benefit = get_benefit(benefit_id)
    check_member_resource(ctx, benefit["member_id"])
    # ACTIVE and SUSPENDED benefits accept earnings reports — a suspended
    # retiree may still be working; TERMINATED benefits do not.
    if benefit["status"] == "TERMINATED":
        raise err_benefit_not_active()
    data = body()
    calendar_year = as_int(req_field(data, "calendar_year"), "calendar_year")
    amount = as_int(req_field(data, "amount_cents"), "amount_cents")

    # Annual reset: the first report of a new calendar year starts a fresh
    # YTD bucket.
    if benefit["rtw_calendar_year"] != calendar_year:
        benefit["rtw_calendar_year"] = calendar_year
        benefit["rtw_ytd_earnings_cents"] = 0
    benefit["rtw_ytd_earnings_cents"] += amount

    fund = current_fund()
    limit = fund["earnings_limit_annual_cents"] if fund is not None else None
    # Strict comparison: landing exactly on the limit does NOT suspend.
    if limit is not None and benefit["rtw_ytd_earnings_cents"] > limit:
        if benefit["status"] == "ACTIVE":
            benefit["status"] = "SUSPENDED"
        member = store.members.get(benefit["member_id"])
        if member is not None and member["status"] == "RETIRED":
            member["status"] = "SUSPENDED_RTW"
            touch(member)
    touch(benefit)
    return ok(public(benefit))


@bp.post("/benefits/<benefit_id>/reinstate")
def reinstate_benefit(benefit_id):
    ctx = auth()
    require_roles(ctx, {"MemberServicesAnalyst"})
    benefit = get_benefit(benefit_id)
    if benefit["status"] != "SUSPENDED":
        raise err_invalid_state("Only a SUSPENDED benefit can be reinstated")
    fund = current_fund()
    limit = fund["earnings_limit_annual_cents"] if fund is not None else None
    # The current calendar year's YTD (zero when the bucket belongs to an
    # earlier year) must be within — at most — the fund limit.
    current_year = now().year
    ytd = (
        benefit["rtw_ytd_earnings_cents"]
        if benefit["rtw_calendar_year"] == current_year
        else 0
    )
    if limit is not None and ytd > limit:
        raise err_invalid_state("Current-year earnings exceed the fund limit")
    benefit["status"] = "ACTIVE"
    touch(benefit)
    member = store.members.get(benefit["member_id"])
    if member is not None and member["status"] == "SUSPENDED_RTW":
        member["status"] = "RETIRED"
        touch(member)
    return ok(public(benefit))
