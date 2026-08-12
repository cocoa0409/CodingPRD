"""ServiceCredit endpoints (PRD §3.6)."""

from flask import Blueprint, request

from db import STORE
from errors import (ApiError, ERR_SEGREGATION_OF_DUTIES,
                    err_invalid_state, err_not_found, err_resident_not_owner)
from middleware import require_roles
from response import success_list, success_object, parse_pagination
from services.core import credit_out, recompute_credit_balance

bp = Blueprint("credits", __name__)

READ_ROLES = ("Resident", "BillingClerk", "RouteSupervisor", "ProgramAdmin")


@bp.get("/service-credits")
def list_credits():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(STORE.credits.values())
    hid = request.args.get("household_id")
    sid = request.args.get("subscription_id")
    tid = request.args.get("missed_pickup_ticket_id")
    st = request.args.get("status")
    if hid is not None:
        items = [c for c in items if c["household_id"] == hid]
    if sid is not None:
        items = [c for c in items if c["subscription_id"] == sid]
    if tid is not None:
        items = [c for c in items if c["missed_pickup_ticket_id"] == tid]
    if st is not None:
        items = [c for c in items if c["status"] == st]
    items.sort(key=lambda c: (c["created_at"], c["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([credit_out(c) for c in page], limit, offset, total)


@bp.get("/service-credits/<cid>")
def get_credit(cid):
    require_roles(*READ_ROLES)
    c = STORE.credits.get(cid)
    if not c:
        raise err_not_found()
    return success_object(credit_out(c))


@bp.post("/service-credits/<cid>/approve")
def approve_credit(cid):
    user_id, role = require_roles("BillingClerk")
    c = STORE.credits.get(cid)
    if not c:
        raise err_not_found()
    if c["status"] != "PENDING_APPROVAL":
        raise err_invalid_state("Credit is not PENDING_APPROVAL")
    # segregation of duties
    if user_id == c["validated_by"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES,
                       "Approver must differ from validator", 409)
    c["status"] = "GRANTED"
    c["approved_by"] = user_id
    # balance recompute + Household.version bump
    recompute_credit_balance(c["household_id"], bump_version=True)
    return success_object(credit_out(c))


@bp.post("/service-credits/<cid>/void")
def void_credit(cid):
    user_id, role = require_roles("BillingClerk")
    c = STORE.credits.get(cid)
    if not c:
        raise err_not_found()
    if c["status"] != "GRANTED":
        raise err_invalid_state("Credit is not GRANTED")
    c["status"] = "VOIDED"
    recompute_credit_balance(c["household_id"], bump_version=True)
    return success_object(credit_out(c))
