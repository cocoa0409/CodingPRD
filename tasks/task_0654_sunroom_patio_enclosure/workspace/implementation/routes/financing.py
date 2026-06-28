"""FinancingApplication endpoints (PRD §3.3)."""
from flask import Blueprint

import errors
import response
from db import db
from middleware import require_roles
from services import common, serialize, calculations

bp = Blueprint("financing", __name__)

VALID_TERMS = {12, 24, 36, 60}


@bp.route("/financing-applications", methods=["POST"])
def create_financing():
    user_id, role = require_roles({"Homeowner"})
    body = common.get_json()

    project_id = common.require_field(body, "project_id", expected_types=["string"])
    quote_id = common.require_field(body, "quote_id", expected_types=["string"])
    down_payment_cents = common.require_field(
        body, "down_payment_cents", expected_types=["integer"],
        validator=lambda v: v >= 0)
    term_months = common.require_field(
        body, "term_months", expected_types=["integer"],
        validator=lambda v: v in VALID_TERMS)
    credit_score = common.require_field(
        body, "credit_score", expected_types=["integer"],
        validator=lambda v: 300 <= v <= 850)

    # existence left-to-right (priority 4): project then quote
    project = common.get_project(project_id)
    quote = common.get_quote(quote_id)

    # ownership (priority 3) — Homeowner financing on a project they own
    if project["homeowner_id"] != user_id:
        raise errors.not_resource_owner("You do not own this project.")

    # business: down payment cannot exceed accepted Quote.total_cents (priority 19)
    if down_payment_cents > quote["total_cents"]:
        raise errors.ApiError(
            errors.ERR_DOWNPAYMENT_EXCEEDS_TOTAL, 422,
            "down_payment_cents cannot exceed the accepted quote total.")

    amount_financed = quote["total_cents"] - down_payment_cents

    entity = {
        "quote_id": quote_id,
        "project_id": project_id,
        "amount_financed_cents": amount_financed,
        "down_payment_cents": down_payment_cents,
        "term_months": term_months,
        "credit_score": credit_score,
        "apr_bps": None,
        "monthly_payment_cents": None,
        "status": "SUBMITTED",
    }
    common.stamp_create(entity)
    db.financing_applications[entity["id"]] = entity
    return response.success(serialize.financing(entity), status=201)


@bp.route("/financing-applications/<fid>/decide", methods=["POST"])
def decide_financing(fid):
    require_roles({"SalesDesigner"})
    common.get_json()
    app = common.get_financing(fid)

    # state (priority 5)
    if app["status"] != "SUBMITTED":
        raise errors.invalid_state("Financing application must be SUBMITTED to decide.")

    score = app["credit_score"]
    principal = app["amount_financed_cents"]

    # principal exceeded surfaces ERR_PRINCIPAL_EXCEEDED (HTTP 422) (PRD §3.3,
    # validation priority 18). The underwriting attempt surfaces the error; the
    # request fails (no state mutation on the error path).
    if principal > calculations.MAX_PRINCIPAL_CENTS:
        raise errors.ApiError(
            errors.ERR_PRINCIPAL_EXCEEDED, 422,
            "Financing principal exceeds the maximum.")

    if score < calculations.MIN_APPROVAL_SCORE:
        # declined: nothing computed
        app["status"] = "DECLINED"
        common.touch(app)
        return response.success(serialize.financing(app), status=200)

    # approved branch
    apr = calculations.financing_apr_tier(score)
    monthly = calculations.financing_monthly_payment(principal, apr, app["term_months"])
    app["apr_bps"] = apr
    app["monthly_payment_cents"] = monthly
    app["status"] = "APPROVED"
    common.touch(app)
    return response.success(serialize.financing(app), status=200)
