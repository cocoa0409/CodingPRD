"""Facility routes: register, read, condition decisions (PRD 3.2)."""

from flask import Blueprint

import errors
import util
from db import store
from middleware import require_roles, ANY_ROLE
from response import success_object
from services import core

bp = Blueprint("facilities", __name__)

FACILITY_CLASSES = ("DIAMOND", "RECTANGLE", "MULTIPURPOSE")
CONDITION_STATUSES = ("OPEN", "LIMITED", "CLOSED")


@bp.post("/facilities")
def create_facility():
    require_roles("AthleticsAdmin")
    body = util.get_json_body()
    name = util.require_str(body, "name")
    facility_class = util.require_enum(body, "facility_class", FACILITY_CLASSES)
    has_lights = util.require_bool(body, "has_lights")
    capacity = util.require_int(body, "capacity", min_v=1)
    weekly_cap = util.require_int(body, "weekly_prime_hour_cap", min_v=1)
    light_cap = util.require_int(body, "nightly_light_block_cap", min_v=1)

    facility = util.new_entity({
        "name": name,
        "facility_class": facility_class,
        "has_lights": has_lights,
        "capacity": capacity,
        "weekly_prime_hour_cap": weekly_cap,
        "nightly_light_block_cap": light_cap,
        "condition_status": "OPEN",
        "condition_reason": "",
        "weekly_prime_hours_used": 0,
    })
    store.facilities[facility["id"]] = facility
    return success_object(facility, 201)


@bp.get("/facilities/<fid>")
def get_facility(fid):
    require_roles(*ANY_ROLE)
    return success_object(core.get_facility(fid))


@bp.post("/facilities/<fid>/condition")
def record_condition(fid):
    require_roles("FieldSupervisor")
    body = util.get_json_body()
    condition_status = util.require_enum(body, "condition_status", CONDITION_STATUSES)
    reason = util.optional_str(body, "reason", default="")
    expected = util.require_int(body, "expected_facility_version")

    facility = core.get_facility(fid)
    # All pairwise transitions among OPEN/LIMITED/CLOSED are legal; the only
    # defect possible here is a stale expected version (PRD 2.7).
    if expected != facility["version"]:
        raise errors.stale_version(
            "expected_facility_version does not match the facility's current version")

    facility["condition_status"] = condition_status
    facility["condition_reason"] = reason
    util.touch(facility)
    return success_object(facility)
