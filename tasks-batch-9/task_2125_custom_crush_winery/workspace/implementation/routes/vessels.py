"""Cooperage: vessels and their condition cycle."""

from flask import Blueprint

import domain
from auth import ALL_ROLES, CELLAR_SUPERVISOR, FACILITY_ADMIN, guard
from envelope import respond
from errors import ApiError, ERR_DUPLICATE_VESSEL_CODE, ERR_INVALID_STATE
from helpers import declared, run_list
from store import db, new_entity, touch
from validation import v_enum, v_number, v_string

bp = Blueprint("vessels", __name__)

VESSEL_TYPES = {"TANK", "BARREL"}
FACILITY_ZONES = {"ZONE_A", "ZONE_B", "BARREL_HALL"}
VESSEL_ACTIONS = {
    "CLEAN": [CELLAR_SUPERVISOR],
    "DECOMMISSION": [FACILITY_ADMIN],
    "RECOMMISSION": [FACILITY_ADMIN],
}


@bp.route("/vessels", methods=["POST"])
def create_vessel():
    ctx = guard([FACILITY_ADMIN])
    body = ctx.body
    code = v_string(body, "vessel_code")
    vessel_type = v_enum(body, "vessel_type", VESSEL_TYPES)
    capacity = v_number(body, "capacity_gallons", gt=0)
    zone = v_enum(body, "facility_zone", FACILITY_ZONES)

    for existing in db.vessels.values():
        if existing["vessel_code"] == code:
            raise ApiError(ERR_DUPLICATE_VESSEL_CODE,
                           "Vessel code '%s' is already held." % code)

    vessel = new_entity({
        "vessel_code": code,
        "vessel_type": vessel_type,
        "capacity_gallons": capacity,
        "facility_zone": zone,
        "condition": "CLEAN",
        "last_released_at": None,
    })
    db.vessels[vessel["id"]] = vessel
    return respond(domain.serialize(vessel), 201)


@bp.route("/vessels/<vessel_id>", methods=["GET"])
def read_vessel(vessel_id):
    guard(ALL_ROLES, read_body=False)
    return respond(domain.serialize(domain.get_vessel(vessel_id)))


@bp.route("/vessels", methods=["GET"])
def list_vessels():
    ctx = guard(ALL_ROLES, read_body=False)
    return run_list(db.vessels.values(), ctx, domain.serialize,
                    filters=(("vessel_type", "vessel_type"),
                             ("condition", "condition"),
                             ("facility_zone", "facility_zone")))


@bp.route("/vessels/<vessel_id>/condition", methods=["POST"])
def vessel_condition(vessel_id):
    ctx = guard([FACILITY_ADMIN, CELLAR_SUPERVISOR], VESSEL_ACTIONS)
    action = v_enum(ctx.body, "action", set(VESSEL_ACTIONS))
    vessel = domain.get_vessel(vessel_id)

    if action == "CLEAN":
        declared(vessel["condition"] == "DIRTY")
        vessel["condition"] = "CLEAN"
    elif action == "DECOMMISSION":
        declared(vessel["condition"] in ("CLEAN", "DIRTY"))
        for allocation in db.allocations.values():
            if (allocation["vessel_id"] == vessel["id"]
                    and allocation["status"] in domain.LIVE_ALLOCATION_STATUSES):
                raise ApiError(ERR_INVALID_STATE,
                               "The vessel still carries a live allocation.")
        vessel["condition"] = "OUT_OF_SERVICE"
    else:  # RECOMMISSION
        declared(vessel["condition"] == "OUT_OF_SERVICE")
        vessel["condition"] = "CLEAN"

    touch(vessel)
    return respond(domain.serialize(vessel))
