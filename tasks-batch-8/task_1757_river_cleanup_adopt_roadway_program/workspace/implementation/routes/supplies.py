"""SupplyDistribution endpoints (PRD 3.5): reads and the return/reconcile flow."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_SUPPLY_NOT_FOUND,
    ERR_SUPPLY_ALREADY_RECONCILED,
    ERR_RETURN_EXCEEDS_ISSUED,
)
from middleware import get_caller, check_role, check_ownership, COORD, LEADER
from response import success_object
from routes.helpers import list_response
from services.core import touch, public
from validate import get_body, req_int, opt_bool, require_resource

bp = Blueprint("supplies", __name__)


def _distribution_owner(dist):
    ev = db["events"].get(dist["event_id"]) if dist else None
    if ev is None:
        return None
    ag = db["agreements"].get(ev["agreement_id"])
    return ag["group_id"] if ag else None


@bp.get("/program/supplies")
def list_supplies():
    caller = get_caller()
    check_role(caller, [COORD, LEADER])
    filters = {
        "event_id": request.args.get("event_id"),
        "depot_id": request.args.get("depot_id"),
        "status": request.args.get("status"),
    }
    return list_response("supplies", caller, filters=filters,
                         owner_of=_distribution_owner)


@bp.get("/program/supplies/<sid>")
def get_supply(sid):
    caller = get_caller()
    check_role(caller, [COORD, LEADER])
    rec = require_resource("supplies", sid, ERR_SUPPLY_NOT_FOUND)
    check_ownership(caller, _distribution_owner(rec))
    return success_object(public(rec))


@bp.post("/program/supplies/<sid>/return")
def return_supplies(sid):
    caller = get_caller()
    check_role(caller, [COORD, LEADER])
    dist = require_resource("supplies", sid, ERR_SUPPLY_NOT_FOUND)
    check_ownership(caller, _distribution_owner(dist))
    body = get_body()
    ret_v = req_int(body, "returned_vests", minimum=0)
    ret_g = req_int(body, "returned_grabbers", minimum=0)
    mark_lost = opt_bool(body, "mark_remaining_lost", False)
    # family 6: a RECONCILED distribution refuses further returns
    if dist["status"] not in ("ISSUED", "PARTIALLY_RETURNED"):
        raise_error(ERR_SUPPLY_ALREADY_RECONCILED,
                    "distribution is already RECONCILED")
    # family 9: cumulative returns must not exceed issued quantities
    new_ret_v = dist["vests_returned"] + ret_v
    new_ret_g = dist["grabbers_returned"] + ret_g
    if new_ret_v > dist["vests_issued"] or new_ret_g > dist["grabbers_issued"]:
        raise_error(ERR_RETURN_EXCEEDS_ISSUED,
                    "cumulative returns would exceed issued quantities")
    depot = db["depots"].get(dist["depot_id"])
    dist["vests_returned"] = new_ret_v
    dist["grabbers_returned"] = new_ret_g
    if depot is not None and (ret_v or ret_g):
        depot["vests_on_hand"] += ret_v
        depot["grabbers_on_hand"] += ret_g
    if mark_lost:
        # outstanding balance is written off, not restocked
        lost_v = dist["vests_issued"] - dist["vests_returned"] - dist["lost_vests"]
        lost_g = dist["grabbers_issued"] - dist["grabbers_returned"] - dist["lost_grabbers"]
        dist["lost_vests"] += lost_v
        dist["lost_grabbers"] += lost_g
        if depot is not None and (lost_v or lost_g):
            depot["lost_vests_total"] += lost_v
            depot["lost_grabbers_total"] += lost_g
        dist["status"] = "RECONCILED"
    elif dist["vests_returned"] == dist["vests_issued"] \
            and dist["grabbers_returned"] == dist["grabbers_issued"]:
        dist["status"] = "RECONCILED"
    else:
        dist["status"] = "PARTIALLY_RETURNED"
    touch(dist)
    if depot is not None:
        touch(depot)
    return success_object(public(dist))
