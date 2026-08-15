"""Benefit investigations: open, list, verify with buy-and-bill routing (PRD 3.3)."""
from flask import Blueprint

from db import db, next_seq, touch
from errors import raise_error, ERR_INVALID_STATE, ERR_ROUTING_VIOLATION
from middleware import authorized
from response import success_object
from routes.helpers import get_request, get_investigation, policy_for_request, check_request_not_terminal, list_response
from serializers import serialize
from util import new_id, CLOCK
from validate import get_body, req_enum

bp = Blueprint("benefits", __name__)


@bp.post("/infusion/authorization-requests/<rid>/benefit-investigations")
def create_investigation(rid):
    authorized(["AuthCoordinator"])
    get_body()
    req = get_request(rid)
    check_request_not_terminal(req)
    now = CLOCK.now()
    rec = {
        "id": new_id(),
        "authorization_request_id": req["id"],
        "status": "INITIATED",
        "determined_channel": None,
        "routing": None,
        "verified_by_user_id": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }
    db["benefit_investigations"][rec["id"]] = rec
    return success_object(serialize(rec), 201)


@bp.get("/infusion/authorization-requests/<rid>/benefit-investigations")
def list_investigations(rid):
    authorized(["AuthCoordinator", "FinanceSpecialist", "MedicalDirector"])
    get_request(rid)
    items = [b for b in db["benefit_investigations"].values()
             if b["authorization_request_id"] == rid]
    return list_response(items)


@bp.post("/infusion/benefit-investigations/<bid>/verify")
def verify_investigation(bid):
    caller = authorized(["FinanceSpecialist"])
    body = get_body()
    determined_channel = req_enum(body, "determined_channel", ["MEDICAL", "PHARMACY"])

    investigation = get_investigation(bid)
    if investigation["status"] != "INITIATED":
        raise_error(ERR_INVALID_STATE,
                    f"benefit investigation is {investigation['status']}, not INITIATED")

    req = get_request(investigation["authorization_request_id"])
    policy = policy_for_request(req)
    if policy["buy_and_bill_required"] and determined_channel == "PHARMACY":
        raise_error(ERR_ROUTING_VIOLATION,
                    "policy requires buy-and-bill; PHARMACY verification is rejected")

    investigation["status"] = "VERIFIED"
    investigation["determined_channel"] = determined_channel
    investigation["routing"] = "BUY_AND_BILL" if determined_channel == "MEDICAL" else "SPECIALTY_PHARMACY"
    investigation["verified_by_user_id"] = caller.user_id
    touch(investigation, CLOCK.now())
    return success_object(serialize(investigation))
