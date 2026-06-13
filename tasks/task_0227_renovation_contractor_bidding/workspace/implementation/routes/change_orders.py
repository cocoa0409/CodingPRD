"""Change order routes: propose, fetch, list, approve (OCC on bid), reject."""
from flask import Blueprint, request

import db
import errors
import response
from middleware import require_roles
from services import common, lookups

bp = Blueprint("change_orders", __name__)


@bp.route("/change-orders", methods=["POST"])
def create_change_order():
    user_id, role = require_roles("Homeowner", "Contractor")
    body = common.get_body()
    project_id = common.as_str(common.require_field(body, "project_id"), "project_id")
    bid_id = common.as_str(common.require_field(body, "bid_id"), "bid_id")
    description = common.as_str(common.require_field(body, "description"), "description")
    delta = common.as_int(common.require_field(body, "delta_cents"), "delta_cents")
    # existence
    project = lookups.get_project(project_id)
    bid = lookups.get_bid(bid_id)
    # ownership: homeowner owns project; contractor owns the awarded bid
    if role == "Homeowner" and project["homeowner_id"] != user_id:
        raise errors.not_owner("Homeowner does not own this project.")
    if role == "Contractor" and bid["contractor_id"] != user_id:
        raise errors.not_owner("Contractor does not own this bid.")

    rec = {
        "project_id": project_id,
        "bid_id": bid_id,
        "description": description,
        "delta_cents": delta,
        "status": "PROPOSED",
    }
    common.stamp_new(rec)
    db.change_orders[rec["id"]] = rec
    return response.success(common.public(rec), 201)


@bp.route("/change-orders/<rid>", methods=["GET"])
def get_change_order(rid):
    require_roles("Homeowner", "Contractor", "PlatformAdmin")
    rec = lookups.get_change_order(rid)
    return response.success(common.public(rec), 200)


@bp.route("/change-orders", methods=["GET"])
def list_change_orders():
    require_roles("Homeowner", "Contractor", "PlatformAdmin")
    items = list(db.change_orders.values())
    for field in ("project_id", "bid_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [c for c in items if c.get(field) == val]
    page, limit, offset, total = common.paginate(items)
    return response.success_list(page, limit, offset, total, 200)


@bp.route("/change-orders/<rid>/approve", methods=["POST"])
def approve_change_order(rid):
    user_id, role = require_roles("Homeowner")
    co = lookups.get_change_order(rid)
    project = lookups.get_project(co["project_id"])
    if role == "Homeowner" and project["homeowner_id"] != user_id:
        raise errors.not_owner("Homeowner does not own this project.")
    body = common.get_body()
    expected_bid_version = common.as_int(
        common.require_field(body, "expected_bid_version"), "expected_bid_version")

    bid = lookups.get_bid(co["bid_id"])
    # state (priority 5)
    if co["status"] != "PROPOSED":
        raise errors.invalid_state("Only a PROPOSED change order can be approved.")
    if project["status"] != "IN_PROGRESS":
        raise errors.invalid_state("Project must be IN_PROGRESS to approve a change order.")
    # OCC (priority 6): expected_bid_version == awarded bid version
    if expected_bid_version != bid["version"]:
        raise errors.ApiError(errors.ERR_STALE_BID_VERSION, 412,
                              "expected_bid_version does not match the awarded bid version.")
    # fiscal bounds (priority 15)
    new_value = project["contract_value_cents"] + co["delta_cents"]
    escrow = lookups.escrow_for_project(co["project_id"])
    committed = 0
    if escrow is not None:
        committed = escrow["released_cents"] + escrow["retained_cents"]
    if new_value > project["budget_cap_cents"] or new_value < committed:
        raise errors.ApiError(errors.ERR_BUDGET_EXCEEDED, 409,
                              "Change order would breach budget or drop below committed funds.")

    co["status"] = "APPROVED"
    common.touch(co)
    project["contract_value_cents"] = new_value
    common.touch(project)
    # increment awarded bid version by 1
    common.touch(bid)
    return response.success(common.public(co), 200)


@bp.route("/change-orders/<rid>/reject", methods=["POST"])
def reject_change_order(rid):
    user_id, role = require_roles("Homeowner")
    co = lookups.get_change_order(rid)
    project = lookups.get_project(co["project_id"])
    if role == "Homeowner" and project["homeowner_id"] != user_id:
        raise errors.not_owner("Homeowner does not own this project.")
    if co["status"] != "PROPOSED":
        raise errors.invalid_state("Only a PROPOSED change order can be rejected.")
    if project["status"] != "IN_PROGRESS":
        raise errors.invalid_state("Project must be IN_PROGRESS to reject a change order.")
    co["status"] = "REJECTED"
    common.touch(co)
    return response.success(common.public(co), 200)
