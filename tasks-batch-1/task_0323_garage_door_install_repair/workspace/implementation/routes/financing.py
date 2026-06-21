"""FinancingApplication routes (PRD §3.12)."""
from flask import Blueprint, request

import db
import errors
import lookup
import serialize
import services.calc as calc
import util
from middleware import authenticate, require_role
from response import success

bp = Blueprint("financing", __name__)

TERM_MONTHS = {6, 12, 24}
APPROVAL_CEILING_CENTS = 1500000


@bp.route("/financing-applications", methods=["POST"])
def create_application():
    _, role = authenticate()
    require_role(role, ["Customer", "ServiceManager"])
    body = util.get_body()
    util.require_fields(body, ["customer_id", "quote_id", "principal_cents", "term_months"])
    customer_id = body.get("customer_id")
    quote_id = body.get("quote_id")
    if not isinstance(customer_id, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "customer_id must be a string")
    if not isinstance(quote_id, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "quote_id must be a string")
    principal_cents = util.require_int(body, "principal_cents")
    term_months = body.get("term_months")
    if isinstance(term_months, bool) or not isinstance(term_months, int) or term_months not in TERM_MONTHS:
        raise errors.err(errors.ERR_INVALID_REQUEST, "term_months must be one of 6, 12, 24")
    lookup.customer(customer_id)
    lookup.quote(quote_id)
    f = {
        "customer_id": customer_id, "quote_id": quote_id,
        "principal_cents": principal_cents, "term_months": term_months,
        "status": "SUBMITTED", "monthly_payment_cents": None,
    }
    db.stamp_create(f, common_fields=True, versioned=True)
    db.financing_applications[f["id"]] = f
    return success(serialize.financing_application(f), status=201)


@bp.route("/financing-applications/<id>", methods=["GET"])
def get_application(id):
    _, role = authenticate()
    require_role(role, ["ServiceManager", "Customer"])
    f = lookup.financing_application(id)
    return success(serialize.financing_application(f))


@bp.route("/financing-applications", methods=["GET"])
def list_applications():
    _, role = authenticate()
    require_role(role, ["ServiceManager", "Customer"])
    limit, offset = util.parse_pagination()
    customer_id = request.args.get("customer_id")
    quote_id = request.args.get("quote_id")
    status = request.args.get("status")
    rows = []
    for f in db.financing_applications.values():
        if customer_id is not None and f["customer_id"] != customer_id:
            continue
        if quote_id is not None and f["quote_id"] != quote_id:
            continue
        if status is not None and f["status"] != status:
            continue
        rows.append(f)
    page, pagination = util.paginate(rows, limit, offset)
    return success([serialize.financing_application(f) for f in page], pagination=pagination)


@bp.route("/financing-applications/<id>/approve", methods=["POST"])
def approve(id):
    _, role = authenticate()
    require_role(role, ["ServiceManager"])
    f = lookup.financing_application(id)
    if f["status"] != "SUBMITTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Application must be SUBMITTED to approve")
    if f["principal_cents"] > APPROVAL_CEILING_CENTS:
        raise errors.err(errors.ERR_FINANCING_CEILING, "Principal above approval ceiling")
    f["status"] = "APPROVED"
    f["monthly_payment_cents"] = calc.financing_monthly_payment(
        f["principal_cents"], f["term_months"])
    db.touch(f)
    return success(serialize.financing_application(f))


@bp.route("/financing-applications/<id>/decline", methods=["POST"])
def decline(id):
    _, role = authenticate()
    require_role(role, ["ServiceManager"])
    f = lookup.financing_application(id)
    if f["status"] != "SUBMITTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Application must be SUBMITTED to decline")
    f["status"] = "DECLINED"
    db.touch(f)
    return success(serialize.financing_application(f))


@bp.route("/financing-applications/<id>/activate", methods=["POST"])
def activate(id):
    _, role = authenticate()
    require_role(role, ["ServiceManager"])
    f = lookup.financing_application(id)
    if f["status"] != "APPROVED":
        raise errors.err(errors.ERR_INVALID_STATE, "Application must be APPROVED to activate")
    quote = db.quotes.get(f["quote_id"])
    if quote is None or quote["status"] != "ACCEPTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Financed quote must be ACCEPTED")
    f["status"] = "ACTIVE"
    db.touch(f)
    return success(serialize.financing_application(f))


@bp.route("/financing-applications/<id>/default", methods=["POST"])
def default(id):
    _, role = authenticate()
    require_role(role, ["ServiceManager"])
    f = lookup.financing_application(id)
    if f["status"] != "ACTIVE":
        raise errors.err(errors.ERR_INVALID_STATE, "Application must be ACTIVE to default")
    f["status"] = "DEFAULTED"
    db.touch(f)
    cust = db.customers.get(f["customer_id"])
    if cust is not None:
        db.touch(cust)  # financing_standing derives live -> BLOCKED
    return success(serialize.financing_application(f))
