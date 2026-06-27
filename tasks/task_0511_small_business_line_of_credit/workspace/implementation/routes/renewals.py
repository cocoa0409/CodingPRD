"""RenewalOffer routes (PRD §3.7). Create (fee-vs-APR view), accept (cross-entity
reprice), decline."""
from flask import Blueprint, request

import db
import serialize
from common import parse_body, require_fields, require_int, stamp_create, touch, list_response
from errors import err, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_VALIDATION
from lookups import get_credit_line, get_renewal_offer
from middleware import auth_and_role
from response import object_response
from services import calc

bp = Blueprint("renewals", __name__)


@bp.post("/credit-lines/<rid>/renewal-offers")
def create_renewal(rid):
    auth_and_role(["CreditOfficer"])
    cl = get_credit_line(rid)
    body = parse_body()
    require_fields(body, ["new_fee_factor_bps", "term_days"])
    # well-formedness: must be integers. Positivity is a semantic check (ERR_VALIDATION).
    new_fee = body["new_fee_factor_bps"]
    term_days = body["term_days"]
    if isinstance(new_fee, bool) or not isinstance(new_fee, int):
        raise err(ERR_INVALID_REQUEST, "new_fee_factor_bps must be an integer")
    if isinstance(term_days, bool) or not isinstance(term_days, int):
        raise err(ERR_INVALID_REQUEST, "term_days must be an integer")
    # semantic validation (ERR_VALIDATION 422): term_days strictly positive.
    if term_days <= 0:
        raise err(ERR_VALIDATION, "term_days must be strictly positive")
    if new_fee <= 0:
        raise err(ERR_VALIDATION, "new_fee_factor_bps must be strictly positive")

    total_fee = calc.renewal_total_fee(credit_limit_cents=cl["credit_limit_cents"],
                                       new_fee_factor_bps=new_fee)
    apr = calc.equivalent_apr(new_fee_factor_bps=new_fee, term_days=term_days)

    record = {
        "credit_line_id": cl["id"],
        "new_fee_factor_bps": new_fee,
        "term_days": term_days,
        "total_fee_cents": total_fee,
        "equivalent_apr_bps": apr,
        "status": "OFFERED",
    }
    stamp_create(record)
    db.renewal_offers[record["id"]] = record
    return object_response(serialize.renewal_offer(record), 201)


@bp.get("/renewal-offers/<rid>")
def fetch_renewal(rid):
    auth_and_role(["Underwriter", "Servicer", "CreditOfficer"])
    ro = get_renewal_offer(rid)
    return object_response(serialize.renewal_offer(ro), 200)


@bp.get("/credit-lines/<rid>/renewal-offers")
def list_renewals_for_line(rid):
    auth_and_role(["Underwriter", "Servicer", "CreditOfficer"])
    get_credit_line(rid)
    status = request.args.get("status")
    items = [x for x in db.renewal_offers.values() if x["credit_line_id"] == rid]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    return list_response(items, serialize.renewal_offer)


@bp.post("/renewal-offers/<rid>/accept")
def accept_renewal(rid):
    auth_and_role(["Servicer"])
    ro = get_renewal_offer(rid)
    cl = db.credit_lines[ro["credit_line_id"]]
    # state legality (priority 6): offer OFFERED AND parent line ACTIVE (cross-entity guard).
    if ro["status"] != "OFFERED":
        raise err(ERR_INVALID_STATE, "Renewal offer is not OFFERED")
    if cl["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Parent line is not ACTIVE")
    ro["status"] = "ACCEPTED"
    touch(ro)
    # cross-entity: reprice line fee_factor_bps, bump line version.
    cl["fee_factor_bps"] = ro["new_fee_factor_bps"]
    touch(cl)
    return object_response(serialize.renewal_offer(ro), 200)


@bp.post("/renewal-offers/<rid>/decline")
def decline_renewal(rid):
    auth_and_role(["Servicer"])
    ro = get_renewal_offer(rid)
    if ro["status"] != "OFFERED":
        raise err(ERR_INVALID_STATE, "Renewal offer is not OFFERED")
    ro["status"] = "DECLINED"
    touch(ro)
    return object_response(serialize.renewal_offer(ro), 200)
