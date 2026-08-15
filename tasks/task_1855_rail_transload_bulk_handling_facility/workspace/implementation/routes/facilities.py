"""Facility endpoints: create (config + posture root), get, patch config."""

from flask import Blueprint

from db import STORE, new_entity, touch, public
from errors import raise_err, ERR_NOT_FOUND
from middleware import auth_context, require_role, ALL_ROLES
from response import ok
from validate import body, req_str, opt_pos_int, opt_nonneg_int, opt_enum

bp = Blueprint("facilities", __name__)

CONTAMINATION_POLICIES = ("STRICT_MATRIX", "WEIGHTED_SCORE")


@bp.route("/transload/facilities", methods=["POST"])
def create_facility():
    _, role = auth_context()
    require_role(role, ["FacilityAdmin"])
    data = body()
    name = req_str(data, "name")
    free_demurrage_hours = opt_pos_int(data, "free_demurrage_hours", 48)
    sit_free_days = opt_nonneg_int(data, "sit_free_days", 2)
    switch_buffer_minutes = opt_pos_int(data, "switch_buffer_minutes", 30)
    free_switches_per_period = opt_nonneg_int(data, "free_switches_per_period", 0)
    contamination_policy = opt_enum(data, "contamination_policy", CONTAMINATION_POLICIES, "STRICT_MATRIX")
    fac = new_entity(STORE.facilities, {
        "name": name,
        "free_demurrage_hours": free_demurrage_hours,
        "sit_free_days": sit_free_days,
        "switch_buffer_minutes": switch_buffer_minutes,
        "free_switches_per_period": free_switches_per_period,
        "contamination_policy": contamination_policy,
        "safety_posture": "NORMAL",
        "open_incident_count": 0,
    })
    return ok(public(fac), status=201)


@bp.route("/transload/facilities/<fid>", methods=["GET"])
def get_facility(fid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    fac = STORE.facilities.get(fid)
    if fac is None:
        raise_err(ERR_NOT_FOUND, "facility id does not exist")
    return ok(public(fac))


@bp.route("/transload/facilities/<fid>", methods=["PATCH"])
def patch_facility(fid):
    _, role = auth_context()
    require_role(role, ["FacilityAdmin"])
    fac = STORE.facilities.get(fid)
    if fac is None:
        raise_err(ERR_NOT_FOUND, "facility id does not exist")
    data = body()
    free_demurrage_hours = opt_pos_int(data, "free_demurrage_hours", None)
    sit_free_days = opt_nonneg_int(data, "sit_free_days", None)
    switch_buffer_minutes = opt_pos_int(data, "switch_buffer_minutes", None)
    free_switches_per_period = opt_nonneg_int(data, "free_switches_per_period", None)
    contamination_policy = opt_enum(data, "contamination_policy", CONTAMINATION_POLICIES, None)
    if free_demurrage_hours is not None:
        fac["free_demurrage_hours"] = free_demurrage_hours
    if sit_free_days is not None:
        fac["sit_free_days"] = sit_free_days
    if switch_buffer_minutes is not None:
        fac["switch_buffer_minutes"] = switch_buffer_minutes
    if free_switches_per_period is not None:
        fac["free_switches_per_period"] = free_switches_per_period
    if contamination_policy is not None:
        fac["contamination_policy"] = contamination_policy
    touch(fac)
    return ok(public(fac))
