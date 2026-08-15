"""AssistanceReferral endpoints (PRD §3.9)."""

from flask import Blueprint

import db
from errors import (not_found, ApiError, ERR_INVALID_STATE, ERR_DUPLICATE_REFERRAL)
from middleware import authenticate, check_ownership
from response import success_object, success_list
from serializers import referral as ser_referral
from validate import (get_body, validate_shape, parse_pagination, parse_filters,
                      paginate, sort_by_creation)

bp = Blueprint("referrals", __name__)

REFERRAL_STATUSES = {"INITIATED", "COMPLETED", "EXPIRED"}
GET_ROLES = ["Customer", "CustomerServiceRep", "ProgramAdmin"]
LIST_ROLES = ["CustomerServiceRep", "ProgramAdmin"]


@bp.route("/assistance/referrals", methods=["POST"])
def create_referral():
    authenticate(["CustomerServiceRep"])
    body = validate_shape(get_body(allow_empty=False), [
        ("account_id", "string", True, None),
        ("agency_code", "string", True, None),
    ])
    account = db.accounts.get(body["account_id"])
    if account is None:
        raise not_found("Account not found")
    for r in db.referrals.values():
        if (r["account_id"] == account["id"]
                and r["agency_code"] == body["agency_code"]
                and r["status"] == "INITIATED"):
            raise ApiError(ERR_DUPLICATE_REFERRAL, 422,
                           "An INITIATED referral already exists for this "
                           "account and agency_code")
    referral = {
        "id": db.new_id(),
        "account_id": account["id"],
        "agency_code": body["agency_code"],
        "status": "INITIATED",
        "initiated_on": db.CLOCK.date(),
        "completed_on": None,
    }
    db.stamp_common(referral)
    db.referrals[referral["id"]] = referral
    return success_object(ser_referral(referral), status=201)


@bp.route("/assistance/referrals/<referral_id>", methods=["GET"])
def get_referral(referral_id):
    actor = authenticate(GET_ROLES)
    r = db.referrals.get(referral_id)
    if r is not None:
        check_ownership(actor, r["account_id"])
    if r is None:
        raise not_found("Referral not found")
    return success_object(ser_referral(r))


@bp.route("/assistance/referrals", methods=["GET"])
def list_referrals():
    authenticate(LIST_ROLES)
    limit, offset = parse_pagination()
    filters = parse_filters({"account_id": "str", "status": REFERRAL_STATUSES})
    items = sort_by_creation(db.referrals.values())
    if "account_id" in filters:
        items = [x for x in items if x["account_id"] == filters["account_id"]]
    if "status" in filters:
        items = [x for x in items if x["status"] == filters["status"]]
    page, total = paginate(items, limit, offset)
    return success_list([ser_referral(x) for x in page], limit, offset, total)


@bp.route("/assistance/referrals/<referral_id>/complete", methods=["POST"])
def complete_referral(referral_id):
    authenticate(["CustomerServiceRep"])
    r = db.referrals.get(referral_id)
    if r is None:
        raise not_found("Referral not found")
    if r["status"] != "INITIATED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Complete requires referral status INITIATED")
    r["status"] = "COMPLETED"
    r["completed_on"] = db.CLOCK.date()
    db.touch(r)
    return success_object(ser_referral(r))
