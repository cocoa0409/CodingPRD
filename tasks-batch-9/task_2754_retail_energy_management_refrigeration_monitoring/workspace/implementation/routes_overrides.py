"""Lighting overrides and the monthly kWh allowance (PRD 3.5)."""

from flask import Blueprint, g

import calc
import cascade
import common
import derive
import envelope
import serial
import validate as v
from common import OVERRIDE_TYPES, ZONES
from db import db, new_row
from errors import ApiError
from security import ENERGY_MANAGER, STORE_MANAGER, roles, require_store_scope
from util import D, exact_hours, rhu

bp = Blueprint("overrides", __name__)


def _overlaps(new_start, new_end, other_start, other_end):
    """Half-open windows: a request starting exactly at an end is admitted."""
    return new_start < other_end and other_start < new_end


@bp.route("/stores/<store_id>/lighting-overrides", methods=["POST"])
@roles(STORE_MANAGER)
def create_override(store_id):
    body = v.body()
    zone = v.get_enum(body, "zone", ZONES)
    override_type = v.get_enum(body, "override_type", OVERRIDE_TYPES)
    start_iso = v.get_dt(body, "start_iso")
    end_iso = v.get_dt(body, "end_iso")
    zone_load_kw = v.get_num(body, "zone_load_kw", 1, gt=0)
    requested_reason = v.get_str(body, "requested_reason", min_len=1)
    v.window(start_iso, end_iso, "start_iso", "end_iso")
    if exact_hours(start_iso, end_iso) > calc.OVERRIDE_MAX_HOURS:
        v.bad("override window exceeds the twelve-hour ceiling")
    store = common.get_store(store_id)
    require_store_scope(store_id)
    if store["energy_posture"] == "LOCKED":
        raise ApiError("ERR_FOOD_SAFETY_HOLD")
    common.require_bms_commissioned(store)
    for other in derive.store_overrides(store_id):
        if other["state"] not in ("SCHEDULED", "ACTIVE"):
            continue
        if other["zone"] != zone:
            continue
        if _overlaps(start_iso, end_iso, other["start_iso"], other["end_iso"]):
            raise ApiError("ERR_OVERRIDE_WINDOW_CONFLICT")
    projected_kwh = calc.override_projection(zone_load_kw, start_iso, end_iso)
    used = derive.override_kwh_used_month(store_id)
    if rhu(D(used) + projected_kwh, 2) > D(store["override_budget_kwh_month"]):
        raise ApiError("ERR_OVERRIDE_BUDGET_EXCEEDED")
    live = start_iso <= db.clock < end_iso
    override = new_row(db.overrides, {
        "store_id": store_id,
        "zone": zone,
        "override_type": override_type,
        "start_iso": start_iso,
        "end_iso": end_iso,
        "zone_load_kw": zone_load_kw,
        "requested_reason": requested_reason,
        "projected_kwh": projected_kwh,
        "state": "ACTIVE" if live else "SCHEDULED",
        "revoke_source": None,
        "revoked_by_user_id": None,
    })
    cascade.touch(store)
    return envelope.created(serial.override(override))


@bp.route("/lighting-overrides/<override_id>/revoke", methods=["POST"])
@roles(ENERGY_MANAGER)
def revoke_override(override_id):
    override = common.get_override(override_id)
    if override["state"] not in ("SCHEDULED", "ACTIVE"):
        raise ApiError("ERR_OVERRIDE_STATE_INVALID")
    override["state"] = "REVOKED"
    override["revoke_source"] = "USER"
    override["revoked_by_user_id"] = g.user_id
    cascade.touch(override)
    store = db.stores.get(override["store_id"])
    cascade.touch(store)
    return envelope.ok(serial.override(override))
