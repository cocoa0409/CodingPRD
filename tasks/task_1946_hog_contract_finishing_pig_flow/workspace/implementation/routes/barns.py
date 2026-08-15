"""Barns (PRD §3.2, §3.6): inventory, downtime release, service status."""

from flask import Blueprint, request

from db import store
from errors import (
    conflict,
    ERR_INVALID_STATE_TRANSITION,
    ERR_DUPLICATE_BARN_CODE,
    ERR_BARN_DOWNTIME_ACTIVE,
    ERR_BARN_OCCUPIED,
    ERR_TICKETS_OPEN,
)
from middleware import (
    require_roles, check_grower_ownership, barn_owner_id,
    ROLE_INTEGRATOR_ADMIN, ROLE_FIELD_TECH, ROLE_GROWER,
)
from response import success_object, paginate
from services.core import (
    new_record, touch, ser_barn, reconcile_site_capacity, TICKET_OPEN_STATUSES,
)
from util import get_body, req, as_str, as_int, load_or_404

bp = Blueprint("barns", __name__)

ROLES_READ = [ROLE_INTEGRATOR_ADMIN, ROLE_FIELD_TECH, ROLE_GROWER]


@bp.route("/barns", methods=["POST"])
def create_barn():
    require_roles([ROLE_INTEGRATOR_ADMIN])
    body = get_body()
    site_id = as_str(req(body, "site_id"), "site_id")
    load_or_404(store.sites, site_id, "Site")
    barn_code = as_str(req(body, "barn_code"), "barn_code")
    capacity_head = as_int(req(body, "capacity_head"), "capacity_head", 1)
    floor_space = as_int(req(body, "floor_space_sqft"), "floor_space_sqft", 0)
    # barn_code unique within its site (priority 11)
    for b in store.barns.values():
        if b["site_id"] == site_id and b["barn_code"] == barn_code:
            raise conflict(ERR_DUPLICATE_BARN_CODE,
                           f"barn_code already in use on this site: {barn_code}")
    rec = new_record()
    rec.update({
        "site_id": site_id, "barn_code": barn_code,
        "capacity_head": capacity_head, "floor_space_sqft": floor_space,
        "barn_status": "AVAILABLE", "wash_required": False,
        "downtime_until": None, "current_group_id": None,
    })
    store.barns[rec["id"]] = rec
    reconcile_site_capacity(site_id)
    return success_object(ser_barn(rec), 201)


@bp.route("/barns", methods=["GET"])
def list_barns():
    require_roles(ROLES_READ)
    site_id = request.args.get("site_id")
    status = request.args.get("barn_status")
    items = list(store.barns.values())
    if site_id is not None:
        items = [b for b in items if b["site_id"] == site_id]
    if status is not None:
        items = [b for b in items if b["barn_status"] == status]
    return paginate(items, request.args, ser_barn)


@bp.route("/barns/<bid>", methods=["GET"])
def get_barn(bid):
    role, user_id = require_roles(ROLES_READ)
    barn = load_or_404(store.barns, bid, "Barn")
    check_grower_ownership(role, user_id, barn_owner_id(barn))
    return success_object(ser_barn(barn))


@bp.route("/barns/<bid>/release", methods=["POST"])
def release_barn(bid):
    require_roles([ROLE_INTEGRATOR_ADMIN])
    barn = load_or_404(store.barns, bid, "Barn")
    if barn["barn_status"] != "DOWNTIME":
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       f"Cannot release a barn in {barn['barn_status']}")
    # biosecurity downtime gate: clock must have reached downtime_until (inclusive)
    if store.now() < barn["downtime_until"]:
        raise conflict(ERR_BARN_DOWNTIME_ACTIVE,
                       "Barn downtime has not elapsed yet")
    barn["barn_status"] = "AVAILABLE"
    barn["wash_required"] = False
    barn["downtime_until"] = None
    touch(barn)
    return success_object(ser_barn(barn))


@bp.route("/barns/<bid>/mark-out-of-service", methods=["POST"])
def mark_out_of_service(bid):
    require_roles([ROLE_INTEGRATOR_ADMIN])
    barn = load_or_404(store.barns, bid, "Barn")
    if barn["barn_status"] == "OCCUPIED":
        raise conflict(ERR_BARN_OCCUPIED,
                       "An occupied barn cannot be taken out of service")
    if barn["barn_status"] not in ("AVAILABLE", "WASH_REQUIRED", "WASHING", "DOWNTIME"):
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       f"Cannot mark out of service from {barn['barn_status']}")
    barn["barn_status"] = "OUT_OF_SERVICE"
    touch(barn)
    reconcile_site_capacity(barn["site_id"])
    return success_object(ser_barn(barn))


@bp.route("/barns/<bid>/return-to-service", methods=["POST"])
def return_to_service(bid):
    require_roles([ROLE_INTEGRATOR_ADMIN])
    barn = load_or_404(store.barns, bid, "Barn")
    if barn["barn_status"] != "OUT_OF_SERVICE":
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       f"Cannot return to service from {barn['barn_status']}")
    # blocked while any maintenance ticket for the barn is still live
    for t in store.maintenance_tickets.values():
        if t["barn_id"] == bid and t["ticket_status"] in TICKET_OPEN_STATUSES:
            raise conflict(ERR_TICKETS_OPEN,
                           "Barn has maintenance tickets still open")
    # dual target: cleanliness picks AVAILABLE vs WASH_REQUIRED
    barn["barn_status"] = "AVAILABLE" if not barn["wash_required"] else "WASH_REQUIRED"
    touch(barn)
    reconcile_site_capacity(barn["site_id"])
    return success_object(ser_barn(barn))
