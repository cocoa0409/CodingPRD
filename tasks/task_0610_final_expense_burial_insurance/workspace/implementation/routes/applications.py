"""Application, HealthQuestionnaire, and the underwriting transitions
(PRD §3.2, §3.3, §3.5)."""
from flask import Blueprint, request

import db
from clock import get_now, format_iso_millis
from errors import err
from helpers import get_body, require_fields, serialize, paginate, sort_by_created
from middleware import get_identity, require_roles
from response import success
from services import underwriting, ledger, policy_calc

bp = Blueprint("applications", __name__)


@bp.route("/applications", methods=["POST"])
def create_application():
    _, role = get_identity()
    require_roles(role, {"Underwriter", "PolicyAdmin"})
    body = get_body()
    require_fields(body, ["applicant_id", "product_plan_id", "requested_face_amount_cents"])
    # Left-to-right existence on body references (PRD §2.6).
    if db.applicants.get(body["applicant_id"]) is None:
        raise err("ERR_NOT_FOUND", "Applicant not found")
    if db.product_plans.get(body["product_plan_id"]) is None:
        raise err("ERR_NOT_FOUND", "ProductPlan not found")
    face = body["requested_face_amount_cents"]
    if not isinstance(face, int) or isinstance(face, bool) or face <= 0:
        raise err("ERR_VALIDATION", "requested_face_amount_cents must be a positive integer")

    application = {
        "applicant_id": body["applicant_id"],
        "product_plan_id": body["product_plan_id"],
        "requested_face_amount_cents": face,
        "rating_class": None,
        "attained_age": None,
        "quoted_monthly_premium_cents": 0,
        "decline_reason": None,
        "status": "DRAFT",
    }
    with db.LOCK:
        db.stamp_full(application)
        db.applications[application["id"]] = application
    return success(serialize(application), status=201, response_type="object")


@bp.route("/applications/<app_id>", methods=["GET"])
def get_application(app_id):
    _, role = get_identity()
    require_roles(role, {"Underwriter", "PolicyAdmin", "ClaimsExaminer"})
    application = db.applications.get(app_id)
    if application is None:
        raise err("ERR_NOT_FOUND", "Application not found")
    return success(serialize(application), status=200, response_type="object")


@bp.route("/applications", methods=["GET"])
def list_applications():
    _, role = get_identity()
    require_roles(role, {"Underwriter", "PolicyAdmin"})
    items = list(db.applications.values())
    applicant_id = request.args.get("applicant_id")
    product_plan_id = request.args.get("product_plan_id")
    status = request.args.get("status")
    if applicant_id:
        items = [a for a in items if a["applicant_id"] == applicant_id]
    if product_plan_id:
        items = [a for a in items if a["product_plan_id"] == product_plan_id]
    if status:
        items = [a for a in items if a["status"] == status]
    items = sort_by_created(items)
    page, meta = paginate(items)
    return success([serialize(a) for a in page], status=200, response_type="array", pagination=meta)


@bp.route("/applications/<app_id>/questionnaire", methods=["POST"])
def attach_questionnaire(app_id):
    _, role = get_identity()
    require_roles(role, {"Underwriter", "PolicyAdmin"})
    application = db.applications.get(app_id)
    if application is None:
        raise err("ERR_NOT_FOUND", "Application not found")
    body = get_body()
    require_fields(body, ["terminal_illness", "aids_hiv", "nursing_home_confined", "major_condition_last_2y"])
    for f in ("terminal_illness", "aids_hiv", "nursing_home_confined", "major_condition_last_2y"):
        if not isinstance(body[f], bool):
            raise err("ERR_VALIDATION", "%s must be a boolean" % f)

    knockout = bool(body["terminal_illness"] or body["aids_hiv"] or body["nursing_home_confined"])
    questionnaire = {
        "application_id": app_id,
        "terminal_illness": body["terminal_illness"],
        "aids_hiv": body["aids_hiv"],
        "nursing_home_confined": body["nursing_home_confined"],
        "major_condition_last_2y": body["major_condition_last_2y"],
        "knockout_triggered": knockout,
    }
    with db.LOCK:
        db.stamp_light(questionnaire)
        db.health_questionnaires[questionnaire["id"]] = questionnaire
    return success(serialize(questionnaire), status=201, response_type="object")


@bp.route("/health-questionnaires/<q_id>", methods=["GET"])
def get_questionnaire(q_id):
    _, role = get_identity()
    require_roles(role, {"Underwriter", "PolicyAdmin", "ClaimsExaminer"})
    q = db.health_questionnaires.get(q_id)
    if q is None:
        raise err("ERR_NOT_FOUND", "HealthQuestionnaire not found")
    return success(serialize(q), status=200, response_type="object")


@bp.route("/health-questionnaires", methods=["GET"])
def list_questionnaires():
    _, role = get_identity()
    require_roles(role, {"Underwriter", "PolicyAdmin", "ClaimsExaminer"})
    items = list(db.health_questionnaires.values())
    application_id = request.args.get("application_id")
    if application_id:
        items = [q for q in items if q["application_id"] == application_id]
    items = sort_by_created(items)
    page, meta = paginate(items)
    return success([serialize(q) for q in page], status=200, response_type="array", pagination=meta)


@bp.route("/applications/<app_id>/submit", methods=["POST"])
def submit_application(app_id):
    _, role = get_identity()
    require_roles(role, {"Underwriter"})
    application = db.applications.get(app_id)
    if application is None:
        raise err("ERR_NOT_FOUND", "Application not found")
    if application["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Application is not DRAFT")
    with db.LOCK:
        underwriting.submit(application)
        db.touch(application)
    return success(serialize(application), status=200, response_type="object")


@bp.route("/applications/<app_id>/approve", methods=["POST"])
def approve_application(app_id):
    _, role = get_identity()
    require_roles(role, {"Underwriter"})
    application = db.applications.get(app_id)
    if application is None:
        raise err("ERR_NOT_FOUND", "Application not found")
    with db.LOCK:
        underwriting.approve_referred(application)
        db.touch(application)
    return success(serialize(application), status=200, response_type="object")


@bp.route("/applications/<app_id>/decline", methods=["POST"])
def decline_application(app_id):
    _, role = get_identity()
    require_roles(role, {"Underwriter"})
    application = db.applications.get(app_id)
    if application is None:
        raise err("ERR_NOT_FOUND", "Application not found")
    with db.LOCK:
        underwriting.decline_referred(application)
        db.touch(application)
    return success(serialize(application), status=200, response_type="object")


@bp.route("/applications/<app_id>/withdraw", methods=["POST"])
def withdraw_application(app_id):
    _, role = get_identity()
    require_roles(role, {"Underwriter", "PolicyAdmin"})
    application = db.applications.get(app_id)
    if application is None:
        raise err("ERR_NOT_FOUND", "Application not found")
    if application["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Application is not DRAFT")
    with db.LOCK:
        application["status"] = "WITHDRAWN"
        db.touch(application)
    return success(serialize(application), status=200, response_type="object")


@bp.route("/applications/<app_id>/issue", methods=["POST"])
def issue_application(app_id):
    _, role = get_identity()
    require_roles(role, {"PolicyAdmin"})
    application = db.applications.get(app_id)
    if application is None:
        raise err("ERR_NOT_FOUND", "Application not found")
    if application["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Application is not APPROVED")
    body = get_body()
    policyholder_user_id = body.get("policyholder_user_id")
    if not policyholder_user_id:
        raise err("ERR_VALIDATION", "policyholder_user_id is required")

    with db.LOCK:
        application["status"] = "ISSUED"
        now_iso = format_iso_millis(get_now())
        plan = db.product_plans.get(application["product_plan_id"])
        policy = {
            "application_id": application["id"],
            "product_plan_id": application["product_plan_id"],
            "applicant_id": application["applicant_id"],
            "policyholder_user_id": policyholder_user_id,
            "face_amount_cents": application["requested_face_amount_cents"],
            "monthly_premium_cents": application["quoted_monthly_premium_cents"],
            "benefit_type": plan["benefit_type"],
            "issue_date": now_iso,
            "paid_through_date": now_iso,
            "due_date": now_iso,
            "coverage_status": "PENDING",
            "payment_status": "CURRENT",
            "total_premiums_paid_cents": 0,
            "gross_cash_value_cents": 0,
            "outstanding_loan_balance_cents": 0,
            "net_cash_value_cents": 0,
        }
        db.stamp_full(policy)
        # Auto-advance PENDING -> ACTIVE on issue.
        policy["coverage_status"] = "ACTIVE"
        db.policies[policy["id"]] = policy
        ledger.append(policy["id"], "CASH_VALUE_ACCRUED", 0, 0)
        db.touch(application)
    return success(serialize(policy), status=201, response_type="object")
