"""Retirement application endpoints: create / get / submit / review / approve
(OCC + segregation of duties) / cancel."""

from flask import Blueprint

from db import store, make_entity, touch, public, now
from errors import (
    err_not_found,
    err_invalid_request,
    err_invalid_state,
    err_member_deceased,
    err_member_not_active,
    err_active_application_exists,
    err_not_vested,
    err_under_retirement_age,
    err_outstanding_balance,
    err_segregation,
    err_stale_version,
)
from middleware import (
    auth,
    require_roles,
    body,
    req_field,
    as_int,
    as_str,
    as_enum,
    check_member_path,
    check_member_resource,
)
from response import ok
from services import calcs, cascades
from utils import parse_date, age_completed

bp = Blueprint("retirement", __name__)

OPTION_ELECTIONS = {"SINGLE_LIFE", "JOINT_50", "JOINT_100"}
APP_VIEW_ROLES = {"FundAdmin", "MemberServicesAnalyst", "BenefitApprover", "Member"}
REVIEW_OUTCOMES = {"REVIEW_OK", "RETURN"}


def get_app(app_id):
    app = store.retirement_apps.get(app_id)
    if app is None:
        raise err_not_found("Retirement application not found")
    return app


@bp.post("/members/<member_id>/retirement-applications")
def create_application(member_id):
    ctx = auth()
    require_roles(ctx, {"Member", "MemberServicesAnalyst"})
    check_member_path(ctx, member_id)
    member = store.members.get(member_id)
    if member is None:
        raise err_not_found("Member not found")
    if member["status"] == "DECEASED":
        raise err_member_deceased()
    # Single-active-application guard (priority 5) before the option-field
    # shape check (priority 6).
    for existing in calcs.member_retirement_apps(member_id):
        if existing["status"] in cascades.NONTERMINAL_RETIREMENT_STATES:
            raise err_active_application_exists()
    data = body()
    option = as_enum(req_field(data, "option_election"), "option_election", OPTION_ELECTIONS)
    beneficiary_name = data.get("beneficiary_name")
    beneficiary_dob_raw = data.get("beneficiary_date_of_birth")
    beneficiary_dob = None
    if option in ("JOINT_50", "JOINT_100"):
        if not beneficiary_name or not isinstance(beneficiary_name, str):
            raise err_invalid_request("beneficiary_name is required for JOINT options")
        beneficiary_dob = parse_date(beneficiary_dob_raw)
        if beneficiary_dob is None:
            raise err_invalid_request(
                "beneficiary_date_of_birth is required for JOINT options and must be an ISO date"
            )
    app = make_entity(
        {
            "member_id": member_id,
            "option_election": option,
            "beneficiary_name": beneficiary_name,
            "beneficiary_date_of_birth": beneficiary_dob.isoformat() if beneficiary_dob else None,
            "status": "DRAFT",
            "provisional_monthly_cents": None,
            "final_monthly_cents": None,
            "reviewed_by_user_id": None,
            "_beneficiary_dob": beneficiary_dob,
        }
    )
    store.retirement_apps[app["id"]] = app
    return ok(public(app), 201)


@bp.get("/retirement-applications/<app_id>")
def read_application(app_id):
    ctx = auth()
    require_roles(ctx, APP_VIEW_ROLES)
    app = get_app(app_id)
    check_member_resource(ctx, app["member_id"])
    return ok(public(app))


@bp.post("/retirement-applications/<app_id>/submit")
def submit_application(app_id):
    ctx = auth()
    require_roles(ctx, {"Member", "MemberServicesAnalyst"})
    app = get_app(app_id)
    check_member_resource(ctx, app["member_id"])
    if app["status"] != "DRAFT":
        raise err_invalid_state("Only a DRAFT application can be submitted")
    member = store.members.get(app["member_id"])
    if member is None or member["status"] != "ACTIVE":
        raise err_member_not_active()
    if calcs.dec(member["total_service_years"]) < calcs.VESTING_YEARS:
        raise err_not_vested()
    if age_completed(member["_dob"], now().date()) < calcs.RETIREMENT_AGE_GATE:
        raise err_under_retirement_age()
    est = calcs.benefit_estimate(
        member, "PROVISIONAL", app["option_election"], app.get("_beneficiary_dob")
    )
    app["provisional_monthly_cents"] = est["monthly_cents"]
    app["status"] = "SUBMITTED"
    touch(app)
    return ok(public(app))


@bp.post("/retirement-applications/<app_id>/review")
def review_application(app_id):
    ctx = auth()
    require_roles(ctx, {"MemberServicesAnalyst"})
    app = get_app(app_id)
    data = body()
    outcome = as_enum(req_field(data, "outcome"), "outcome", REVIEW_OUTCOMES)
    if outcome == "REVIEW_OK":
        # The review cycle is unbounded: SUBMITTED or RETURNED_FOR_CORRECTION
        # both lead back to UNDER_REVIEW, refreshing reviewed_by_user_id.
        if app["status"] not in ("SUBMITTED", "RETURNED_FOR_CORRECTION"):
            raise err_invalid_state(
                "Cannot review an application in %s" % app["status"]
            )
        app["status"] = "UNDER_REVIEW"
        app["reviewed_by_user_id"] = ctx.user_id
    else:  # RETURN
        # The RETURN loop repeats without bound: SUBMITTED -> RETURNED, and
        # after a REVIEW_OK the cycle returns UNDER_REVIEW -> RETURNED.
        if app["status"] not in ("SUBMITTED", "UNDER_REVIEW"):
            raise err_invalid_state(
                "Cannot return an application in %s" % app["status"]
            )
        app["status"] = "RETURNED_FOR_CORRECTION"
    touch(app)
    return ok(public(app))


@bp.post("/retirement-applications/<app_id>/approve")
def approve_application(app_id):
    ctx = auth()
    require_roles(ctx, {"BenefitApprover"})
    app = get_app(app_id)
    # Segregation of duties (priority 2.5) before OCC (3.5) and state (4).
    if app["reviewed_by_user_id"] is not None and ctx.user_id == app["reviewed_by_user_id"]:
        raise err_segregation("The reviewing caseworker may not approve the application")
    data = body()
    expected = data.get("expected_application_version")
    if expected is not None and as_int(expected, "expected_application_version") != app["version"]:
        raise err_stale_version("Application version has advanced; re-read before approving")
    if app["status"] != "UNDER_REVIEW":
        raise err_invalid_state("Only an UNDER_REVIEW application can be approved")
    member = store.members.get(app["member_id"])
    if member is None or member["status"] != "ACTIVE":
        raise err_member_not_active()
    if any(
        p["status"] == "PLAN_ACTIVE" for p in calcs.member_purchases(app["member_id"])
    ):
        raise err_outstanding_balance()

    est = calcs.benefit_estimate(
        member, "FINAL", app["option_election"], app.get("_beneficiary_dob")
    )
    app["final_monthly_cents"] = est["monthly_cents"]
    app["status"] = "APPROVED"
    touch(app)
    cascades.create_benefit(
        member, "SERVICE", est["monthly_cents"],
        origin_option=app["option_election"], origin_app_id=app["id"],
    )
    cascades.retire_member(member)
    return ok(public(app))


@bp.post("/retirement-applications/<app_id>/cancel")
def cancel_application(app_id):
    ctx = auth()
    require_roles(ctx, {"Member", "MemberServicesAnalyst"})
    app = get_app(app_id)
    check_member_resource(ctx, app["member_id"])
    if app["status"] not in cascades.NONTERMINAL_RETIREMENT_STATES:
        raise err_invalid_state("Application in %s cannot be cancelled" % app["status"])
    app["status"] = "CANCELLED"
    touch(app)
    return ok(public(app))
