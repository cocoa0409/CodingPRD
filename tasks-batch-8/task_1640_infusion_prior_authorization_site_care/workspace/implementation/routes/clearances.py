"""Financial clearances, responsibility line items, clear/recompute (PRD 3.6)."""
from flask import Blueprint

from db import db, next_seq, touch
from errors import (
    raise_error,
    ERR_INVALID_STATE,
    ERR_AUTH_NOT_APPROVED,
    ERR_DUPLICATE_OPEN_CLEARANCE,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_BENEFIT_NOT_VERIFIED,
    ERR_PREPAY_LIMIT_EXCEEDED,
)
from middleware import authorized
from response import success_object
from routes.helpers import (
    get_request, get_clearance, get_line_item, policy_for_request,
    list_response, has_verified_benefit, clearance_in_statuses,
)
from serializers import serialize
from services.calculations import compute_estimate, recompute_clearance
from util import new_id, CLOCK
from validate import get_body, req_str, req_int

bp = Blueprint("clearances", __name__)

CLEARANCE_ROLES = ["FinanceSpecialist", "AuthCoordinator"]


@bp.post("/infusion/authorization-requests/<rid>/financial-clearances")
def create_clearance(rid):
    caller = authorized(["FinanceSpecialist"])
    get_body()
    req = get_request(rid)
    if req["status"] != "APPROVED":
        raise_error(ERR_AUTH_NOT_APPROVED,
                    f"financial clearance requires an APPROVED request, found {req['status']}")
    if clearance_in_statuses(req["id"], {"ESTIMATED", "CLEARED"}) is not None:
        raise_error(ERR_DUPLICATE_OPEN_CLEARANCE,
                    "the request already has a clearance in ESTIMATED or CLEARED status")

    policy = policy_for_request(req)
    now = CLOCK.now()
    rec = {
        "id": new_id(),
        "authorization_request_id": req["id"],
        "method": "ACCUMULATOR_METHOD" if policy["allowed_amount_known"] else "BILLED_CHARGES_METHOD",
        "status": "ESTIMATED",
        "estimated_patient_responsibility_cents": 0,
        "estimated_by_user_id": caller.user_id,
        "cleared_by_user_id": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }
    db["financial_clearances"][rec["id"]] = rec
    # initial estimate over zero line items
    rec["estimated_patient_responsibility_cents"] = compute_estimate(rec, now)
    return success_object(serialize(rec), 201)


@bp.get("/infusion/authorization-requests/<rid>/financial-clearances")
def list_clearances(rid):
    authorized(CLEARANCE_ROLES)
    get_request(rid)
    items = [c for c in db["financial_clearances"].values()
             if c["authorization_request_id"] == rid]
    return list_response(items)


@bp.get("/infusion/financial-clearances/<cid>")
def read_clearance(cid):
    authorized(CLEARANCE_ROLES)
    return success_object(serialize(get_clearance(cid)))


@bp.post("/infusion/financial-clearances/<cid>/line-items")
def add_line_item(cid):
    authorized(["FinanceSpecialist"])
    body = get_body()
    description = req_str(body, "description")
    allowed_amount_cents = req_int(body, "allowed_amount_cents")
    billed_charges_cents = req_int(body, "billed_charges_cents")

    clearance = get_clearance(cid)
    if clearance["status"] != "ESTIMATED":
        raise_error(ERR_INVALID_STATE,
                    f"line items may be added only while the clearance is ESTIMATED, "
                    f"found {clearance['status']}")

    now = CLOCK.now()
    rec = {
        "id": new_id(),
        "financial_clearance_id": clearance["id"],
        "description": description,
        "allowed_amount_cents": allowed_amount_cents,
        "billed_charges_cents": billed_charges_cents,
        "patient_share_cents": 0,
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }
    db["responsibility_line_items"][rec["id"]] = rec
    # rebuild the waterfall; the new line's computed share is set without a bump
    recompute_clearance(clearance, now, bump=True, skip_touch_ids={rec["id"]})
    return success_object(serialize(rec), 201)


@bp.get("/infusion/financial-clearances/<cid>/line-items")
def list_line_items(cid):
    authorized(CLEARANCE_ROLES)
    get_clearance(cid)
    items = [l for l in db["responsibility_line_items"].values()
             if l["financial_clearance_id"] == cid]
    return list_response(items)


@bp.post("/infusion/responsibility-line-items/<lid>/voids")
def void_line_item(lid):
    authorized(["FinanceSpecialist"])
    get_body()
    line = get_line_item(lid)
    clearance = get_clearance(line["financial_clearance_id"])
    if clearance["status"] != "ESTIMATED":
        raise_error(ERR_INVALID_STATE,
                    f"line items may be voided only while the clearance is ESTIMATED, "
                    f"found {clearance['status']}")
    if line["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE,
                    f"line item is {line['status']}; only ACTIVE lines may be voided")

    now = CLOCK.now()
    line["status"] = "VOIDED"
    touch(line, now)
    recompute_clearance(clearance, now, bump=True)
    return success_object(serialize(line))


@bp.post("/infusion/financial-clearances/<cid>/clear")
def clear_clearance(cid):
    caller = authorized(["FinanceSpecialist"])
    get_body()
    clearance = get_clearance(cid)
    # segregation of duties: clearer != estimator
    if caller.user_id == clearance["estimated_by_user_id"]:
        raise_error(ERR_SEGREGATION_OF_DUTIES,
                    "the estimating specialist may not clear the clearance")
    if clearance["status"] != "ESTIMATED":
        raise_error(ERR_INVALID_STATE,
                    f"clearance is {clearance['status']}; only ESTIMATED may be cleared")
    if not has_verified_benefit(clearance["authorization_request_id"]):
        raise_error(ERR_BENEFIT_NOT_VERIFIED,
                    "clear requires at least one VERIFIED benefit investigation")
    req = get_request(clearance["authorization_request_id"])
    policy = policy_for_request(req)
    if int(clearance["estimated_patient_responsibility_cents"]) > int(policy["prepay_limit_cents"]):
        raise_error(ERR_PREPAY_LIMIT_EXCEEDED,
                    f"estimate {clearance['estimated_patient_responsibility_cents']} exceeds "
                    f"prepay limit {policy['prepay_limit_cents']}")

    clearance["status"] = "CLEARED"
    clearance["cleared_by_user_id"] = caller.user_id
    touch(clearance, CLOCK.now())
    return success_object(serialize(clearance))


@bp.post("/infusion/financial-clearances/<cid>/recompute")
def recompute_clearance_route(cid):
    authorized(["FinanceSpecialist"])
    get_body()
    clearance = get_clearance(cid)
    if clearance["status"] != "ON_HOLD":
        raise_error(ERR_INVALID_STATE,
                    f"clearance is {clearance['status']}; only ON_HOLD may be recomputed")
    req = get_request(clearance["authorization_request_id"])
    if req["status"] != "APPROVED":
        raise_error(ERR_AUTH_NOT_APPROVED,
                    f"recompute requires the parent request APPROVED, found {req['status']}")

    now = CLOCK.now()
    recompute_clearance(clearance, now, bump=False)
    clearance["status"] = "ESTIMATED"
    touch(clearance, now)
    return success_object(serialize(clearance))
