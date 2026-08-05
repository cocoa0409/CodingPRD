"""Routes: cost centers and allocation approval."""
from flask import Blueprint, g

import core
from core import (db, ApiError, ok, ok_list, guard, get_body, require,
                  base_common, touch, serialize, ordered, paginate, find)

bp = Blueprint("costcenter", __name__)


@bp.route("/cost-centers", methods=["POST"])
@guard(["SystemAdmin"])
def create_cost_center():
    body = get_body()
    require(body, ["code", "gl_account", "owner_user_id"])
    cc = base_common({
        "code": body["code"],
        "gl_account": body["gl_account"],
        "owner_user_id": body["owner_user_id"],
        "status": "ACTIVE",
    })
    db.cost_centers[cc["id"]] = cc
    return ok(serialize(cc), status=201)


@bp.route("/cost-centers/<cid>", methods=["GET"])
@guard(core.ALL_ROLES)
def get_cost_center(cid):
    cc = find(db.cost_centers, cid, "ERR_COST_CENTER_NOT_FOUND")
    return ok(serialize(cc))


@bp.route("/cost-centers/<cid>/freeze", methods=["POST"])
@guard(["SystemAdmin"])
def freeze_cost_center(cid):
    cc = find(db.cost_centers, cid, "ERR_COST_CENTER_NOT_FOUND")
    if cc["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Cost center is not ACTIVE.")
    cc["status"] = "FROZEN"
    touch(cc)
    return ok(serialize(cc))


@bp.route("/cost-centers/<cid>/allocations", methods=["GET"])
@guard(core.ALL_ROLES)
def list_cost_center_allocations(cid):
    find(db.cost_centers, cid, "ERR_COST_CENTER_NOT_FOUND")
    items = ordered([a for a in db.allocations.values()
                     if a["cost_center_id"] == cid])
    page, meta = paginate(items)
    return ok_list([serialize(a) for a in page], meta)


@bp.route("/allocations/<aid>/approve", methods=["POST"])
@guard(["CostCenterOwner"])
def approve_allocation(aid):
    a = find(db.allocations, aid, "ERR_ALLOCATION_NOT_FOUND")
    # band 5: allocation state
    if a["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Allocation is not DRAFT.")
    cc = db.cost_centers[a["cost_center_id"]]
    # band 6: cross-entity referential state (cost center not FROZEN)
    if cc["status"] != "ACTIVE":
        raise ApiError("ERR_COST_CENTER_FROZEN", 409, "Cost center is FROZEN.")
    # band 8: ownership
    if g.user_id != cc["owner_user_id"]:
        raise ApiError("ERR_NOT_COST_CENTER_OWNER", 403,
                       "Caller is not the cost center owner.")
    a["status"] = "POSTED"
    touch(a)
    return ok(serialize(a))
