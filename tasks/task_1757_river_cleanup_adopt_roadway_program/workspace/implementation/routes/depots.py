"""SupplyDepot endpoints (PRD 3.5, 2.7): creation pins the pool baselines."""
from flask import Blueprint

from db import db
from errors import ERR_DEPOT_NOT_FOUND
from middleware import get_caller, check_role, COORD, LEADER
from response import success_object
from services.core import stamp_new, public
from validate import get_body, req_str, req_int, require_resource

bp = Blueprint("depots", __name__)


@bp.post("/program/depots")
def create_depot():
    caller = get_caller()
    check_role(caller, [COORD])
    body = get_body()
    name = req_str(body, "name")
    bags = req_int(body, "bags_on_hand", minimum=0)
    vests = req_int(body, "vests_on_hand", minimum=0)
    grabbers = req_int(body, "grabbers_on_hand", minimum=0)
    rec = stamp_new({
        "name": name,
        "bags_on_hand": bags,
        "vests_on_hand": vests,
        "grabbers_on_hand": grabbers,
        # conserved-quantity baselines, pinned at creation and never changed
        "vests_pool_total": vests,
        "grabbers_pool_total": grabbers,
        "lost_vests_total": 0,
        "lost_grabbers_total": 0,
    })
    db["depots"][rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.get("/program/depots/<did>")
def get_depot(did):
    caller = get_caller()
    check_role(caller, [COORD, LEADER])
    rec = require_resource("depots", did, ERR_DEPOT_NOT_FOUND)
    return success_object(public(rec))
