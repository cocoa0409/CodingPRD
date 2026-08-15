"""AssistanceApplication endpoints + lifecycle actions (PRD §3.2)."""

from flask import Blueprint

import db
from errors import (not_found, ApiError, ERR_SEGREGATION_OF_DUTIES,
                    ERR_STALE_ACCOUNT_VERSION, ERR_APPLICATION_NOT_REVIEWABLE,
                    ERR_INVALID_STATE, ERR_DOCUMENTS_OUTSTANDING)
from middleware import authenticate, check_ownership
from response import success_object, success_list
from serializers import application as ser_app
from services.common import touch_account
from services.tiers import provisional_tier, final_tier, DISCOUNT_PCT
from validate import (get_body, validate_shape, parse_pagination, parse_filters,
                      paginate, sort_by_creation)

bp = Blueprint("applications", __name__)

INCOME_SOURCES = {"WAGES", "SSI", "PENSION", "UNEMPLOYMENT", "OTHER"}
DENIAL_REASONS = {"INCOME_OVER_LIMIT", "DOCS_INSUFFICIENT", "OTHER"}
APP_STATUSES = {"SUBMITTED", "UNDER_REVIEW", "DOCS_PENDING", "VERIFIED",
                "DENIED", "WITHDRAWN"}
OPEN_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "DOCS_PENDING")

GET_ROLES = ["Customer", "CustomerServiceRep", "EligibilitySpecialist", "ProgramAdmin"]
LIST_ROLES = ["CustomerServiceRep", "EligibilitySpecialist", "ProgramAdmin"]


def get_application_or_404(application_id):
    x = db.applications.get(application_id)
    if x is None:
        raise not_found("Application not found")
    return x


def _segregation_check(actor, app):
    if actor.user_id == app["submitted_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403,
                       "Acting user must differ from the application submitter")


def _require_state(app, allowed):
    if app["status"] not in allowed:
        raise ApiError(ERR_APPLICATION_NOT_REVIEWABLE, 409,
                       f"Application is {app['status']}; requires {'|'.join(allowed)}")


@bp.route("/assistance/applications", methods=["POST"])
def create_application():
    actor = authenticate(["Customer", "CustomerServiceRep"])
    raw = get_body(allow_empty=False)
    if actor.is_customer and isinstance(raw.get("account_id"), str):
        check_ownership(actor, raw.get("account_id"))
    body = validate_shape(raw, [
        ("account_id", "string", True, None),
        ("household_size", "int", True, (1, 12)),
        ("gross_annual_income_cents", "int", True, (0, None)),
        ("current_month_income_cents", "int", True, (0, None)),
        ("income_source", "enum", False, INCOME_SOURCES),
        ("expected_account_version", "int", True, None),
    ])
    if actor.is_customer:
        check_ownership(actor, body["account_id"])
    account = db.accounts.get(body["account_id"])
    if account is None:
        raise not_found("Account not found")
    if body["expected_account_version"] != account["version"]:
        raise ApiError(ERR_STALE_ACCOUNT_VERSION, 412,
                       "expected_account_version does not match current version")
    # supersede any open application on the account
    for other in db.applications.values():
        if other["account_id"] == account["id"] and other["status"] in OPEN_STATUSES:
            other["status"] = "WITHDRAWN"
            other["denial_reason"] = None
            db.touch(other)
    app = {
        "id": db.new_id(),
        "account_id": account["id"],
        "household_size": body["household_size"],
        "gross_annual_income_cents": body["gross_annual_income_cents"],
        "current_month_income_cents": body["current_month_income_cents"],
        "income_source": body.get("income_source") or "OTHER",
        "status": "SUBMITTED",
        "submitted_by_user_id": actor.user_id,
        "reviewed_by_user_id": None,
        "docs_requested": False,
        "documents_received": False,
        "provisional_benefit_tier": None,
        "benefit_tier": None,
        "income_measure_used": "ANNUALIZED_CURRENT_MONTH",
        "denial_reason": None,
        "decided_at": None,
    }
    app["provisional_benefit_tier"] = provisional_tier(app)
    db.stamp_common(app)
    db.applications[app["id"]] = app
    touch_account(account)
    return success_object(ser_app(app), status=201)


@bp.route("/assistance/applications/<application_id>", methods=["GET"])
def get_application(application_id):
    actor = authenticate(GET_ROLES)
    app = db.applications.get(application_id)
    if app is not None:
        check_ownership(actor, app["account_id"])
    if app is None:
        raise not_found("Application not found")
    return success_object(ser_app(app))


@bp.route("/assistance/applications", methods=["GET"])
def list_applications():
    authenticate(LIST_ROLES)
    limit, offset = parse_pagination()
    filters = parse_filters({"account_id": "str", "status": APP_STATUSES})
    items = sort_by_creation(db.applications.values())
    if "account_id" in filters:
        items = [x for x in items if x["account_id"] == filters["account_id"]]
    if "status" in filters:
        items = [x for x in items if x["status"] == filters["status"]]
    page, total = paginate(items, limit, offset)
    return success_list([ser_app(x) for x in page], limit, offset, total)


@bp.route("/assistance/applications/<application_id>/begin-review", methods=["POST"])
def begin_review(application_id):
    actor = authenticate(["EligibilitySpecialist"])
    app = get_application_or_404(application_id)
    _segregation_check(actor, app)
    _require_state(app, ("SUBMITTED",))
    app["status"] = "UNDER_REVIEW"
    app["reviewed_by_user_id"] = actor.user_id
    db.touch(app)
    return success_object(ser_app(app))


@bp.route("/assistance/applications/<application_id>/request-documents", methods=["POST"])
def request_documents(application_id):
    authenticate(["EligibilitySpecialist"])
    app = get_application_or_404(application_id)
    _require_state(app, ("UNDER_REVIEW",))
    app["status"] = "DOCS_PENDING"
    app["docs_requested"] = True
    app["documents_received"] = False
    db.touch(app)
    return success_object(ser_app(app))


@bp.route("/assistance/applications/<application_id>/submit-documents", methods=["POST"])
def submit_documents(application_id):
    actor = authenticate(["Customer", "CustomerServiceRep"])
    app = db.applications.get(application_id)
    if app is not None:
        check_ownership(actor, app["account_id"])
    if app is None:
        raise not_found("Application not found")
    _require_state(app, ("DOCS_PENDING",))
    app["status"] = "UNDER_REVIEW"
    app["documents_received"] = True
    db.touch(app)
    return success_object(ser_app(app))


@bp.route("/assistance/applications/<application_id>/verify", methods=["POST"])
def verify(application_id):
    actor = authenticate(["EligibilitySpecialist"])
    app = get_application_or_404(application_id)
    _segregation_check(actor, app)
    _require_state(app, ("UNDER_REVIEW", "DOCS_PENDING"))
    if app["docs_requested"] and not app["documents_received"]:
        raise ApiError(ERR_DOCUMENTS_OUTSTANDING, 422,
                       "Requested documents have not been received")
    tier = final_tier(app)
    app["income_measure_used"] = "ANNUAL_GROSS"
    app["decided_at"] = db.CLOCK.now()
    if tier == "INELIGIBLE":
        app["status"] = "DENIED"
        app["denial_reason"] = "INCOME_OVER_LIMIT"
        app["benefit_tier"] = None
        db.touch(app)
        return success_object(ser_app(app))
    app["status"] = "VERIFIED"
    app["benefit_tier"] = tier
    db.touch(app)
    enrollment = {
        "id": db.new_id(),
        "account_id": app["account_id"],
        "application_id": app["id"],
        "tier": tier,
        "discount_pct": DISCOUNT_PCT[tier],
        "status": "PENDING",
        "activated_on": None,
        "recert_due_on": None,
        "lapsed_on": None,
    }
    db.stamp_common(enrollment)
    db.enrollments[enrollment["id"]] = enrollment
    return success_object(ser_app(app))


@bp.route("/assistance/applications/<application_id>/deny", methods=["POST"])
def deny(application_id):
    actor = authenticate(["EligibilitySpecialist"])
    body = validate_shape(get_body(allow_empty=False),
                          [("reason_code", "enum", True, DENIAL_REASONS)])
    app = get_application_or_404(application_id)
    _segregation_check(actor, app)
    _require_state(app, ("UNDER_REVIEW",))
    app["status"] = "DENIED"
    app["denial_reason"] = body["reason_code"]
    app["decided_at"] = db.CLOCK.now()
    db.touch(app)
    return success_object(ser_app(app))


@bp.route("/assistance/applications/<application_id>/withdraw", methods=["POST"])
def withdraw(application_id):
    actor = authenticate(["Customer", "CustomerServiceRep"])
    app = db.applications.get(application_id)
    if app is not None:
        check_ownership(actor, app["account_id"])
    if app is None:
        raise not_found("Application not found")
    if app["status"] not in OPEN_STATUSES:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a non-terminal application may be withdrawn")
    app["status"] = "WITHDRAWN"
    db.touch(app)
    return success_object(ser_app(app))
