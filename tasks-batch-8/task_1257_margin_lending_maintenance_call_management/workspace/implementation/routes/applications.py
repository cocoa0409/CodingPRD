"""Account applications (PRD 3.1): SUBMITTED -> COMPLIANCE_REVIEW ->
APPROVED / REJECTED, with a REJECTED -> SUBMITTED resubmission cycle."""
from flask import Blueprint, request

from authz import ANALYST, ANY_ROLE, CUSTOMER, SUPERVISOR, check_customer_ownership, require_roles
from db import store
from errors import (
    account_already_exists,
    application_not_found,
    customer_not_found,
    invalid_request,
    segregation_of_duties,
    suitability_not_met,
    application_invalid_state,
)
from response import success
from serialize import ser_application
from store_ops import (
    json_body,
    new_id,
    opt_int,
    paginate,
    req_int,
    req_str,
    sorted_by_creation,
    stamp_new,
    touch,
)

bp = Blueprint("applications", __name__)

SUITABILITY_MIN_NET_WORTH_CENTS = 200000
SUITABILITY_MIN_EXPERIENCE_YEARS = 1


def _get_application(app_id):
    app = store.applications.get(app_id)
    if app is None:
        raise application_not_found()
    return app


@bp.route("/margin/account-applications", methods=["POST"])
def create_application():
    data = json_body()
    customer_id = req_str(data, "customer_id")
    annual_income = req_int(data, "annual_income_cents")
    net_worth = req_int(data, "liquid_net_worth_cents")
    experience = req_int(data, "investment_experience_years")
    uid, _ = require_roles([CUSTOMER])
    # Priority 3 (existence) then 4 (ownership).
    if customer_id not in store.customers:
        raise customer_not_found()
    check_customer_ownership(uid, customer_id)
    app = {
        "id": new_id(),
        "customer_id": customer_id,
        "annual_income_cents": annual_income,
        "liquid_net_worth_cents": net_worth,
        "investment_experience_years": experience,
        "application_status": "SUBMITTED",
        "reviewed_by_user_id": None,
        "decided_by_user_id": None,
        "rejection_reason": None,
        "account_id": None,
    }
    stamp_new(app)
    store.applications[app["id"]] = app
    return success(ser_application(app), status=201)


@bp.route("/margin/account-applications/<aid>", methods=["GET"])
def get_application(aid):
    require_roles(ANY_ROLE)
    return success(ser_application(_get_application(aid)))


@bp.route("/margin/account-applications", methods=["GET"])
def list_applications():
    require_roles(ANY_ROLE)
    customer_id = request.args.get("customer_id")
    account_id = request.args.get("account_id")
    items = list(store.applications.values())
    if customer_id is not None:
        items = [a for a in items if a["customer_id"] == customer_id]
    if account_id is not None:
        items = [a for a in items if a["account_id"] == account_id]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_application(a) for a in page], response_type="array",
                   pagination=pagination)


@bp.route("/margin/account-applications/<aid>/review", methods=["POST"])
def review_application(aid):
    uid, _ = require_roles([ANALYST])
    app = _get_application(aid)
    if app["application_status"] != "SUBMITTED":
        raise application_invalid_state()
    app["application_status"] = "COMPLIANCE_REVIEW"
    app["reviewed_by_user_id"] = uid
    touch(app)
    return success(ser_application(app))


@bp.route("/margin/account-applications/<aid>/approve", methods=["POST"])
def approve_application(aid):
    uid, _ = require_roles([SUPERVISOR])
    app = _get_application(aid)
    # PRD 3.1 pins the check order: state -> SoD -> suitability -> uniqueness.
    if app["application_status"] != "COMPLIANCE_REVIEW":
        raise application_invalid_state()
    if uid == app["reviewed_by_user_id"]:
        raise segregation_of_duties()
    if (app["liquid_net_worth_cents"] < SUITABILITY_MIN_NET_WORTH_CENTS
            or app["investment_experience_years"] < SUITABILITY_MIN_EXPERIENCE_YEARS):
        raise suitability_not_met()
    if any(a["customer_id"] == app["customer_id"] for a in store.accounts.values()):
        raise account_already_exists()

    account = {
        "id": new_id(),
        "customer_id": app["customer_id"],
        "application_id": app["id"],
        "account_status": "ACTIVE",
        "cash_balance_cents": 0,
        "equity_realtime_cents": 0,
        "equity_official_cents": 0,
        "reg_req_official_cents": 0,
        "house_req_official_cents": 0,
        "reg_req_realtime_cents": 0,
        "house_req_realtime_cents": 0,
        "buying_power_cents": 0,
        "pdt_flag": False,
        "pdt_flagged_at": None,
    }
    stamp_new(account)
    store.accounts[account["id"]] = account

    app["application_status"] = "APPROVED"
    app["decided_by_user_id"] = uid
    app["account_id"] = account["id"]
    touch(app)
    return success(ser_application(app))


@bp.route("/margin/account-applications/<aid>/reject", methods=["POST"])
def reject_application(aid):
    data = json_body()
    reason = data.get("reason")
    if reason is not None and (isinstance(reason, bool) or not isinstance(reason, str)):
        raise invalid_request("Field reason must be a string")
    uid, _ = require_roles([SUPERVISOR])
    app = _get_application(aid)
    if app["application_status"] != "COMPLIANCE_REVIEW":
        raise application_invalid_state()
    if uid == app["reviewed_by_user_id"]:
        raise segregation_of_duties()
    app["application_status"] = "REJECTED"
    app["decided_by_user_id"] = uid
    app["rejection_reason"] = reason
    touch(app)
    return success(ser_application(app))


@bp.route("/margin/account-applications/<aid>/resubmit", methods=["POST"])
def resubmit_application(aid):
    data = json_body()
    annual_income = opt_int(data, "annual_income_cents")
    net_worth = opt_int(data, "liquid_net_worth_cents")
    experience = opt_int(data, "investment_experience_years")
    uid, _ = require_roles([CUSTOMER])
    app = _get_application(aid)
    check_customer_ownership(uid, app["customer_id"])
    if app["application_status"] != "REJECTED":
        raise application_invalid_state()
    if annual_income is not None:
        app["annual_income_cents"] = annual_income
    if net_worth is not None:
        app["liquid_net_worth_cents"] = net_worth
    if experience is not None:
        app["investment_experience_years"] = experience
    app["application_status"] = "SUBMITTED"
    app["reviewed_by_user_id"] = None
    app["decided_by_user_id"] = None
    app["rejection_reason"] = None
    touch(app)
    return success(ser_application(app))
