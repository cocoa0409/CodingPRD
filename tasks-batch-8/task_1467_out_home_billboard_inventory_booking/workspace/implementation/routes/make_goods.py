"""MakeGood endpoints (PRD 3.9)."""
from flask import Blueprint, request

import calc
import db
import domain
from errors import ApiError, err_invalid_request, err_invalid_state
from middleware import require_roles
from response import success
from serializers import make_good_out
from util import req_str, req_enum

bp = Blueprint("make_goods", __name__, url_prefix="/api")

REASONS = ("MISSED_POSTING", "ILLUMINATION_OUTAGE", "PERMIT_SUSPENSION",
           "UNDER_DELIVERY")


def get_make_good_or_404(mid):
    m = db.make_goods.get(mid)
    if m is None:
        raise ApiError("ERR_MAKE_GOOD_NOT_FOUND", 404, "Make-good not found")
    return m


@bp.route("/make-goods", methods=["POST"])
def create_make_good():
    user_id, _ = require_roles("OperationsAuditor")
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("Request body must be a JSON object")

    flight_id = body.get("flight_id")
    if isinstance(flight_id, str) and flight_id not in db.flights:
        raise ApiError("ERR_FLIGHT_NOT_FOUND", 404, "Flight not found")

    flight_id = req_str(body, "flight_id")
    reason = req_enum(body, "reason", REASONS)
    if reason != "UNDER_DELIVERY":
        raise err_invalid_request(
            "Manual make-good proposals require reason=UNDER_DELIVERY")

    flight = db.flights[flight_id]
    if flight["status"] != "COMPLETED":
        raise err_invalid_state(
            "A manual UNDER_DELIVERY make-good requires a COMPLETED flight")

    credit = calc.under_delivery_credit(flight)
    if credit is None:
        credit = 0

    m = db.new_resource()
    m.update({
        "flight_id": flight["id"],
        "reason": reason,
        "credit_cents": credit,
        "status": "PROPOSED",
        "proposed_by": user_id,
    })
    db.make_goods[m["id"]] = m
    return success(make_good_out(m), code=201)


@bp.route("/make-goods/<mid>", methods=["PUT"])
def update_make_good(mid):
    user_id, _ = require_roles("FinanceAnalyst")
    m = get_make_good_or_404(mid)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("Request body must be a JSON object")

    new_status = body.get("status")
    if not isinstance(new_status, str) or new_status not in (
            "PROPOSED", "APPROVED", "REJECTED", "APPLIED"):
        raise err_invalid_request("status is required and must be a valid "
                                  "make-good status")

    cur = m["status"]
    allowed = {
        ("PROPOSED", "APPROVED"),
        ("PROPOSED", "REJECTED"),
        ("APPROVED", "APPLIED"),
    }
    if (cur, new_status) not in allowed:
        raise err_invalid_state(
            "Make-good cannot transition %s -> %s" % (cur, new_status))

    if (cur, new_status) == ("PROPOSED", "APPROVED") \
            and m["proposed_by"] != "system" and user_id == m["proposed_by"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "The approver must differ from the proposing user")

    m["status"] = new_status
    db.touch(m)

    if new_status == "APPLIED":
        flight = db.flights.get(m["flight_id"])
        campaign = db.campaigns.get(flight["campaign_id"]) if flight else None
        advertiser = db.advertisers.get(campaign["advertiser_id"]) \
            if campaign else None
        if advertiser is not None:
            advertiser["credit_balance_cents"] += m["credit_cents"]
            db.touch(advertiser)
        if campaign is not None:
            domain.recompute_delivery_posture(campaign)

    return success(make_good_out(m))
