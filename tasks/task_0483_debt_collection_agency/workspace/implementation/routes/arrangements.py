"""PaymentArrangement endpoints: propose, accept/counter/reject, payoff-quote."""
from flask import Blueprint, request

from clock import clock, parse_iso8601
from db import db, stamp_create, touch
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_INVALID_REQUEST,
    ERR_ACCOUNT_NOT_WORKABLE, ERR_TIME_BARRED, ERR_SETTLEMENT_BELOW_FLOOR,
)
from middleware import require_roles
from response import object_response, array_response
from serializers import serialize_arrangement
from pagination import paginate
from validation import get_body, require_str, require_enum, optional_int, invalid
from money import round_half_up
from services.accounts import compute_time_barred
from services.arrangements import settlement_floor_bps, payoff_quote

bp = Blueprint("arrangements", __name__)

ARRANGEMENT_TYPES = {"PLAN", "SETTLEMENT"}
AS_OF_MODES = {"QUOTE_DATE", "GOOD_THROUGH"}


@bp.route("/arrangements", methods=["POST"])
@require_roles("Collector")
def propose():
    body = get_body()
    account_id = require_str(body, "account_id")
    account = db.accounts.get(account_id)
    if account is None:
        raise ApiError(*ERR_NOT_FOUND, message="Account not found")
    arrangement_type = require_enum(body, "arrangement_type", ARRANGEMENT_TYPES)
    offer_pct_bps = None
    if arrangement_type == "SETTLEMENT":
        if "offer_pct_bps" not in body or body["offer_pct_bps"] is None:
            invalid("offer_pct_bps is required for SETTLEMENT")
        offer_pct_bps = body["offer_pct_bps"]
        if isinstance(offer_pct_bps, bool) or not isinstance(offer_pct_bps, int):
            invalid("offer_pct_bps must be an integer")
        if offer_pct_bps < 1 or offer_pct_bps > 10000:
            invalid("offer_pct_bps must be between 1 and 10000 inclusive")
    installment_count = optional_int(body, "installment_count", default=1)
    if installment_count < 1:
        invalid("installment_count must be >= 1")
    good_through = body.get("good_through")
    if good_through is not None:
        if not isinstance(good_through, str) or parse_iso8601(good_through) is None:
            invalid("good_through must be a valid ISO 8601 timestamp")

    a = stamp_create({
        "account_id": account_id,
        "arrangement_type": arrangement_type,
        "offer_pct_bps": offer_pct_bps,
        "settlement_amount_cents": None,
        "installment_count": installment_count,
        "good_through": good_through,
        "status": "PROPOSED",
    })
    db.arrangements[a["id"]] = a
    return object_response(serialize_arrangement(a), status=201)


@bp.route("/arrangements/<aid>", methods=["GET"])
@require_roles("Creditor", "Collector", "ComplianceOfficer", "System")
def get_arrangement(aid):
    a = db.arrangements.get(aid)
    if a is None:
        raise ApiError(*ERR_NOT_FOUND, message="Arrangement not found")
    return object_response(serialize_arrangement(a), status=200)


@bp.route("/arrangements", methods=["GET"])
@require_roles("Creditor", "Collector", "ComplianceOfficer", "System")
def list_arrangements():
    items = list(db.arrangements.values())
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    if account_id:
        items = [a for a in items if a["account_id"] == account_id]
    if status:
        items = [a for a in items if a["status"] == status]
    page, limit, offset, total = paginate(items)
    return array_response([serialize_arrangement(a) for a in page], limit, offset, total)


@bp.route("/arrangements/<aid>/payoff-quote", methods=["GET"])
@require_roles("Creditor", "Collector", "ComplianceOfficer", "System")
def get_payoff_quote(aid):
    a = db.arrangements.get(aid)
    if a is None:
        raise ApiError(*ERR_NOT_FOUND, message="Arrangement not found")
    as_of = request.args.get("as_of", "QUOTE_DATE")
    if as_of not in AS_OF_MODES:
        invalid("as_of must be QUOTE_DATE or GOOD_THROUGH")
    account = db.accounts.get(a["account_id"])
    if account is None:
        raise ApiError(*ERR_NOT_FOUND, message="Account not found")
    payoff = payoff_quote(a, account, as_of)
    return object_response({"payoff_cents": payoff, "as_of": as_of}, status=200)


@bp.route("/arrangements/<aid>/accept", methods=["POST"])
@require_roles("Collector")
def accept(aid):
    a = db.arrangements.get(aid)
    if a is None:
        raise ApiError(*ERR_NOT_FOUND, message="Arrangement not found")
    if a["status"] != "PROPOSED":
        raise ApiError(*ERR_INVALID_STATE, message="Arrangement is not PROPOSED")
    account = db.accounts.get(a["account_id"])
    if account is None:
        raise ApiError(*ERR_NOT_FOUND, message="Account not found")
    # Guardrails (priority order): workable, time-barred (SETTLEMENT), floor (SETTLEMENT).
    if account["work_status"] != "WORKING":
        raise ApiError(*ERR_ACCOUNT_NOT_WORKABLE, message="Account is not WORKING")
    if a["arrangement_type"] == "SETTLEMENT":
        if compute_time_barred(account):
            raise ApiError(*ERR_TIME_BARRED, message="Cannot accept settlement on time-barred account")
        floor = settlement_floor_bps(account)
        if a["offer_pct_bps"] < floor:
            raise ApiError(*ERR_SETTLEMENT_BELOW_FLOOR, message="Offer below settlement floor")
        a["settlement_amount_cents"] = round_half_up(
            account["balance_cents"] * a["offer_pct_bps"], 10000
        )
        # Snapshot balance at acceptance for fulfillment forgiveness arithmetic.
        a["balance_at_acceptance"] = account["balance_cents"]
    else:  # PLAN
        a["balance_at_acceptance"] = account["balance_cents"]
    a["status"] = "ACCEPTED"
    touch(a)
    return object_response(serialize_arrangement(a), status=200)


@bp.route("/arrangements/<aid>/counter", methods=["POST"])
@require_roles("Collector")
def counter(aid):
    a = db.arrangements.get(aid)
    if a is None:
        raise ApiError(*ERR_NOT_FOUND, message="Arrangement not found")
    # state: PROPOSED only; PLAN counter -> ERR_INVALID_STATE; non-PROPOSED -> ERR_INVALID_STATE.
    if a["status"] != "PROPOSED":
        raise ApiError(*ERR_INVALID_STATE, message="Arrangement is not PROPOSED")
    if a["arrangement_type"] != "SETTLEMENT":
        raise ApiError(*ERR_INVALID_STATE, message="Only a SETTLEMENT may be countered")
    a["status"] = "COUNTERED"
    touch(a)
    return object_response(serialize_arrangement(a), status=200)


@bp.route("/arrangements/<aid>/reject", methods=["POST"])
@require_roles("Collector")
def reject(aid):
    a = db.arrangements.get(aid)
    if a is None:
        raise ApiError(*ERR_NOT_FOUND, message="Arrangement not found")
    if a["status"] not in ("PROPOSED", "COUNTERED"):
        raise ApiError(*ERR_INVALID_STATE, message="Only PROPOSED or COUNTERED may be rejected")
    a["status"] = "REJECTED"
    touch(a)
    return object_response(serialize_arrangement(a), status=200)
