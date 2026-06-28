"""FinancingApplication endpoints (PRD §3.6)."""
from flask import Blueprint, request

import db
import errors
import helpers
from middleware import authenticate, authorize, get_json_body, get_pagination
from response import object_response, array_response
from serializers import serialize, serialize_list
from services import calculations, factory

bp = Blueprint("financing", __name__)

VALID_TERMS = [12, 24, 36, 60]
DECISIONS = ["APPROVE", "DECLINE"]


@bp.route("/financing-applications", methods=["POST"])
def create_application():
    _uid, role = authenticate()
    authorize(role, ["Homeowner"])
    body = get_json_body()
    # body FK check (priority 4): job_id, quote_id.
    helpers.require_fields(body, ["job_id", "quote_id"])
    job = helpers.fk_or_422(db.jobs, body["job_id"], "Job")
    quote = helpers.fk_or_422(db.quotes, body["quote_id"], "Quote")

    # request validity (priority 5): term_months present + integer.
    term_months = helpers.require_int(body, "term_months")
    # business validation: term must be one of 12/24/36/60 -> ERR_VALIDATION.
    if term_months not in VALID_TERMS:
        raise errors.err(errors.ERR_VALIDATION, "term_months must be one of 12, 24, 36, 60")

    # state: Job SOLD with financing_status NONE (PRD §3.6).
    if job["lifecycle_status"] != "SOLD" or job["financing_status"] != "NONE":
        raise errors.err(errors.ERR_INVALID_STATE, "Financing requires a SOLD job with financing_status NONE")

    homeowner = db.homeowners.items.get(job["homeowner_id"])
    credit_band = homeowner["credit_band"]
    # amount pinned to the accepted quote total.
    amount_financed_cents = quote["total_cents"]
    apr_bps = calculations.compute_apr_bps(credit_band, term_months)
    monthly_payment_cents = calculations.amortize(amount_financed_cents, apr_bps, term_months)

    app = factory.create_financing_application(
        body["job_id"], body["quote_id"], term_months,
        amount_financed_cents, apr_bps, monthly_payment_cents,
    )
    job["financing_status"] = "APPLIED"
    helpers.touch(job)
    return object_response(serialize(app), status=201)


@bp.route("/financing-applications/<app_id>", methods=["GET"])
def get_application(app_id):
    _uid, role = authenticate()
    authorize(role, ["Homeowner", "FinancePartner"])
    entity = helpers.find_or_404(db.financing_applications, app_id)
    return object_response(serialize(entity), status=200)


@bp.route("/financing-applications", methods=["GET"])
def list_applications():
    _uid, role = authenticate()
    authorize(role, ["Homeowner", "FinancePartner"])
    limit, offset = get_pagination()
    job_id = request.args.get("job_id")
    quote_id = request.args.get("quote_id")
    status = request.args.get("status")

    def pred(a):
        if job_id is not None and a["job_id"] != job_id:
            return False
        if quote_id is not None and a["quote_id"] != quote_id:
            return False
        if status is not None and a["status"] != status:
            return False
        return True

    page, total = helpers.paginate_list(db.financing_applications, limit, offset, pred)
    return array_response(serialize_list(page), limit, offset, total)


@bp.route("/financing-applications/<app_id>/decide", methods=["POST"])
def decide_application(app_id):
    _uid, role = authenticate()
    authorize(role, ["FinancePartner"])
    app = helpers.find_or_404(db.financing_applications, app_id)
    body = get_json_body()
    decision = helpers.require_enum(body, "decision", DECISIONS)

    job = db.jobs.items.get(app["job_id"])
    # state: application SUBMITTED and Job.financing_status APPLIED (PRD §3.6).
    if app["status"] != "SUBMITTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Only a SUBMITTED application can be decided")
    if job is None or job["financing_status"] != "APPLIED":
        raise errors.err(errors.ERR_INVALID_STATE, "Decision requires the job financing_status APPLIED")

    if decision == "APPROVE":
        # business rule (priority 13): finance limit.
        homeowner = db.homeowners.items.get(job["homeowner_id"])
        ceiling = calculations.max_finance_cents(homeowner["credit_band"])
        if app["amount_financed_cents"] > ceiling:
            raise errors.err(errors.ERR_FINANCE_LIMIT_EXCEEDED, "Financed amount exceeds the credit band ceiling")
        app["status"] = "APPROVED"
        helpers.touch(app)
        job["financing_status"] = "APPROVED"
        helpers.touch(job)
    else:
        app["status"] = "DECLINED"
        helpers.touch(app)
        job["financing_status"] = "DECLINED"
        helpers.touch(job)
    return object_response(serialize(app), status=200)


@bp.route("/financing-applications/<app_id>/withdraw", methods=["POST"])
def withdraw_application(app_id):
    _uid, role = authenticate()
    authorize(role, ["Homeowner"])
    app = helpers.find_or_404(db.financing_applications, app_id)
    job = db.jobs.items.get(app["job_id"])
    # state: application DECLINED and Job.financing_status DECLINED (PRD §3.6).
    if app["status"] != "DECLINED":
        raise errors.err(errors.ERR_INVALID_STATE, "Only a DECLINED application can be withdrawn")
    if job is None or job["financing_status"] != "DECLINED":
        raise errors.err(errors.ERR_INVALID_STATE, "Withdraw requires the job financing_status DECLINED")
    app["status"] = "WITHDRAWN"
    helpers.touch(app)
    job["financing_status"] = "NONE"
    helpers.touch(job)
    return object_response(serialize(app), status=200)
