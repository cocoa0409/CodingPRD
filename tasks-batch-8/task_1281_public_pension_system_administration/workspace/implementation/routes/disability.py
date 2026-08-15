"""Disability application endpoints: file / get / decision (fresh-eyes rule)
/ appeal (60-day window)."""

from datetime import timedelta

from flask import Blueprint

from db import store, make_entity, touch, public, now, fmt_dt
from errors import (
    err_not_found,
    err_invalid_request,
    err_invalid_state,
    err_member_deceased,
    err_member_not_active,
    err_active_application_exists,
    err_not_vested,
    err_segregation,
    err_appeal_window_closed,
)
from middleware import (
    auth,
    require_roles,
    body,
    req_field,
    as_str,
    as_enum,
    check_member_path,
    check_member_resource,
)
from response import ok
from services import calcs, cascades

bp = Blueprint("disability", __name__)

DISABILITY_TYPES = {"DUTY", "NON_DUTY"}
DECISION_OUTCOMES = {"APPROVE", "DENY"}
APP_VIEW_ROLES = {
    "FundAdmin",
    "MemberServicesAnalyst",
    "MedicalReviewer",
    "BenefitApprover",
    "Member",
}


def get_app(app_id):
    app = store.disability_apps.get(app_id)
    if app is None:
        raise err_not_found("Disability application not found")
    return app


@bp.post("/members/<member_id>/disability-applications")
def create_application(member_id):
    ctx = auth()
    require_roles(ctx, {"Member", "MemberServicesAnalyst"})
    check_member_path(ctx, member_id)
    member = store.members.get(member_id)
    if member is None:
        raise err_not_found("Member not found")
    if member["status"] == "DECEASED":
        raise err_member_deceased()
    for existing in calcs.member_disability_apps(member_id):
        if existing["status"] in ("UNDER_MEDICAL_REVIEW", "DENIED"):
            raise err_active_application_exists()
    data = body()
    dtype = as_enum(req_field(data, "disability_type"), "disability_type", DISABILITY_TYPES)
    description = data.get("description")
    if description is not None and not isinstance(description, str):
        raise err_invalid_request("description must be a string")
    # Enters UNDER_MEDICAL_REVIEW immediately upon creation.
    app = make_entity(
        {
            "member_id": member_id,
            "disability_type": dtype,
            "description": description,
            "status": "UNDER_MEDICAL_REVIEW",
            "submitted_by_user_id": ctx.user_id,
            "last_reviewer_user_id": None,
            "appeal_count": 0,
            "decided_at": None,
            "_decided_dt": None,
        }
    )
    store.disability_apps[app["id"]] = app
    return ok(public(app), 201)


@bp.get("/disability-applications/<app_id>")
def read_application(app_id):
    ctx = auth()
    require_roles(ctx, APP_VIEW_ROLES)
    app = get_app(app_id)
    check_member_resource(ctx, app["member_id"])
    return ok(public(app))


@bp.post("/disability-applications/<app_id>/decision")
def decide_application(app_id):
    ctx = auth()
    require_roles(ctx, {"MedicalReviewer"})
    app = get_app(app_id)
    # Fresh-eyes segregation (priority 2.5): after an appeal, the deciding
    # reviewer must differ from the reviewer of the previous decision.
    if app["appeal_count"] > 0 and ctx.user_id == app["last_reviewer_user_id"]:
        raise err_segregation("An appealed case must be decided by a different reviewer")
    data = body()
    outcome = as_enum(req_field(data, "outcome"), "outcome", DECISION_OUTCOMES)
    if app["status"] != "UNDER_MEDICAL_REVIEW":
        raise err_invalid_state("Only an application UNDER_MEDICAL_REVIEW can be decided")

    member = store.members.get(app["member_id"])
    if outcome == "APPROVE":
        # Disability approval accepts ACTIVE or INACTIVE members.
        if member is None or member["status"] not in ("ACTIVE", "INACTIVE"):
            raise err_member_not_active()
        # DUTY carries no vesting requirement; NON_DUTY does.
        if app["disability_type"] == "NON_DUTY" and calcs.dec(
            member["total_service_years"]
        ) < calcs.VESTING_YEARS:
            raise err_not_vested()
        monthly = calcs.disability_monthly_cents(member["id"])
        app["status"] = "APPROVED"
        app["decided_at"] = fmt_dt(now())
        app["_decided_dt"] = now()
        app["last_reviewer_user_id"] = ctx.user_id
        touch(app)
        cascades.create_benefit(member, "DISABILITY", monthly)
        cascades.retire_member(member)
    else:  # DENY
        app["status"] = "DENIED"
        app["decided_at"] = fmt_dt(now())
        app["_decided_dt"] = now()
        app["last_reviewer_user_id"] = ctx.user_id
        touch(app)
    return ok(public(app))


@bp.post("/disability-applications/<app_id>/appeal")
def appeal_application(app_id):
    ctx = auth()
    require_roles(ctx, {"Member", "MemberServicesAnalyst"})
    app = get_app(app_id)
    check_member_resource(ctx, app["member_id"])
    if app["status"] != "DENIED":
        raise err_invalid_state("Only a DENIED application can be appealed")
    if now() > app["_decided_dt"] + timedelta(days=calcs.APPEAL_WINDOW_DAYS):
        raise err_appeal_window_closed()
    app["status"] = "UNDER_MEDICAL_REVIEW"
    app["appeal_count"] += 1
    touch(app)
    return ok(public(app))
