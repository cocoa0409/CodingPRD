"""Read-only listing/reads for event + junction records:
PledgeAddOn lines, PaymentAuthorizations, Refunds, FulfillmentSurveys."""
from flask import Blueprint, request

from db import db
from errors import err, ERR_NOT_FOUND
from middleware import require_role
from response import success, list_response
from services import domain
from util import parse_pagination, paginate

bp = Blueprint("events", __name__)

READ_ROLES = ["PlatformAdmin", "Creator", "Backer"]


# ---- PledgeAddOn ----
@bp.route("/pledge-add-ons", methods=["GET"])
def list_pledge_addons():
    require_role(READ_ROLES)
    limit, offset = parse_pagination()
    pledge_id = request.args.get("pledge_id")
    addon_id = request.args.get("addon_id")
    records = list(db.pledge_addons.values())
    if pledge_id is not None:
        records = [r for r in records if r["pledge_id"] == pledge_id]
    if addon_id is not None:
        records = [r for r in records if r["addon_id"] == addon_id]
    window, total = paginate(records, limit, offset)
    return list_response([domain.serialize(r) for r in window], limit, offset, total)


@bp.route("/pledge-add-ons/<pledge_addon_id>", methods=["GET"])
def get_pledge_addon(pledge_addon_id):
    require_role(READ_ROLES)
    rec = db.pledge_addons.get(pledge_addon_id)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Pledge add-on line not found")
    return success(domain.serialize(rec), status=200)


# ---- PaymentAuthorization ----
@bp.route("/authorizations", methods=["GET"])
def list_authorizations():
    require_role(READ_ROLES)
    limit, offset = parse_pagination()
    pledge_id = request.args.get("pledge_id")
    records = list(db.authorizations.values())
    if pledge_id is not None:
        records = [r for r in records if r["pledge_id"] == pledge_id]
    window, total = paginate(records, limit, offset)
    return list_response([domain.serialize(r) for r in window], limit, offset, total)


@bp.route("/authorizations/<authorization_id>", methods=["GET"])
def get_authorization(authorization_id):
    require_role(READ_ROLES)
    rec = db.authorizations.get(authorization_id)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Authorization not found")
    return success(domain.serialize(rec), status=200)


# ---- Refund ----
@bp.route("/refunds", methods=["GET"])
def list_refunds():
    require_role(READ_ROLES)
    limit, offset = parse_pagination()
    pledge_id = request.args.get("pledge_id")
    records = list(db.refunds.values())
    if pledge_id is not None:
        records = [r for r in records if r["pledge_id"] == pledge_id]
    window, total = paginate(records, limit, offset)
    return list_response([domain.serialize(r) for r in window], limit, offset, total)


@bp.route("/refunds/<refund_id>", methods=["GET"])
def get_refund(refund_id):
    require_role(READ_ROLES)
    rec = db.refunds.get(refund_id)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Refund not found")
    return success(domain.serialize(rec), status=200)


# ---- FulfillmentSurvey ----
@bp.route("/surveys", methods=["GET"])
def list_surveys():
    require_role(READ_ROLES)
    limit, offset = parse_pagination()
    pledge_id = request.args.get("pledge_id")
    records = list(db.surveys.values())
    if pledge_id is not None:
        records = [r for r in records if r["pledge_id"] == pledge_id]
    window, total = paginate(records, limit, offset)
    return list_response([domain.serialize(r) for r in window], limit, offset, total)


@bp.route("/surveys/<survey_id>", methods=["GET"])
def get_survey(survey_id):
    require_role(READ_ROLES)
    rec = db.surveys.get(survey_id)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Survey not found")
    return success(domain.serialize(rec), status=200)
