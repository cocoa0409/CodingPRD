"""Housing units: create, list, get, decommission, availability."""

from flask import Blueprint

import db
from errors import err
from middleware import require_roles, get_auth
from response import success_object, success_list
from services import core
from validate import (
    get_body, require_string, require_enum, require_int,
    parse_pagination, get_filter, sort_and_paginate,
)

bp = Blueprint("units", __name__)

UNIT_TYPES = {"FAMILY_UNIT", "SEASONAL_DORM"}


def _view(u):
    return {
        "id": u["id"],
        "building_id": u["building_id"],
        "site_id": u["site_id"],
        "unit_code": u["unit_code"],
        "unit_type": u["unit_type"],
        "max_occupancy": u["max_occupancy"],
        "monthly_rent_cents": u["monthly_rent_cents"],
        "status": u["status"],
        "current_occupancy": u["current_occupancy"],
        "habitability_score_cumulative": u["habitability_score_cumulative"],
        "habitability_score_worst_case": u["habitability_score_worst_case"],
        "under_pest_exclusion": u["under_pest_exclusion"],
        "pest_exclusion_end_date": u["pest_exclusion_end_date"],
        "created_at": u["created_at"],
        "updated_at": u["updated_at"],
        "version": u["version"],
    }


@bp.route("/housing-units", methods=["POST"])
def create_unit():
    require_roles("OperatorAdmin")
    body = get_body()
    building_id = require_string(body, "building_id")
    site_id = require_string(body, "site_id")
    unit_code = require_string(body, "unit_code")
    unit_type = require_enum(body, "unit_type", UNIT_TYPES)
    max_occupancy = require_int(body, "max_occupancy", min_value=1)
    monthly_rent_cents = require_int(body, "monthly_rent_cents", min_value=0)

    building = db.buildings.get(building_id)
    if building is None:
        raise err("ERR_NOT_FOUND")
    site = db.sites.get(site_id)
    if site is None:
        raise err("ERR_SITE_NOT_FOUND")
    if building["site_id"] != site_id:
        raise err("ERR_INVALID_REQUEST", "site_id must equal the building's site_id")

    now = db.now_ts()
    u = {
        "id": db.new_id(),
        "building_id": building_id,
        "site_id": site_id,
        "unit_code": unit_code,
        "unit_type": unit_type,
        "max_occupancy": max_occupancy,
        "monthly_rent_cents": monthly_rent_cents,
        "status": "REGISTERED",
        "current_occupancy": 0,
        "habitability_score_cumulative": 0,
        "habitability_score_worst_case": 0,
        "under_pest_exclusion": False,
        "pest_exclusion_end_date": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.units[u["id"]] = u
    return success_object(_view(u), status=201)


@bp.route("/housing-units", methods=["GET"])
def list_units():
    get_auth()
    limit, offset = parse_pagination()
    items = list(db.units.values())
    building_f = get_filter("building_id")
    site_f = get_filter("site_id")
    status_f = get_filter("status")
    if building_f is not None:
        items = [u for u in items if u["building_id"] == building_f]
    if site_f is not None:
        items = [u for u in items if u["site_id"] == site_f]
    if status_f is not None:
        items = [u for u in items if u["status"] == status_f]
    page, total = sort_and_paginate(items, limit, offset)
    return success_list([_view(u) for u in page], total, limit, offset)


@bp.route("/housing-units/<uid>", methods=["GET"])
def get_unit(uid):
    get_auth()
    u = db.units.get(uid)
    if u is None:
        raise err("ERR_UNIT_NOT_FOUND")
    # Refresh clock-dependent fields on read.
    core.recompute_pest_exclusion(uid)
    core.recompute_unit_occupancy(uid)
    return success_object(_view(u))


@bp.route("/housing-units/<uid>/availability", methods=["GET"])
def availability(uid):
    get_auth()
    u = db.units.get(uid)
    if u is None:
        raise err("ERR_UNIT_NOT_FOUND")
    core.recompute_pest_exclusion(uid)
    core.recompute_unit_occupancy(uid)
    has_valid = core.unit_has_valid_certification(uid)
    data = {
        "unit_status": u["status"],
        "current_occupancy": u["current_occupancy"],
        "available_beds": u["max_occupancy"] - u["current_occupancy"],
        "under_pest_exclusion": u["under_pest_exclusion"],
        "pest_exclusion_end_date": u["pest_exclusion_end_date"],
        "has_valid_certification": has_valid,
        "habitability_score_cumulative": u["habitability_score_cumulative"],
        "habitability_score_worst_case": u["habitability_score_worst_case"],
    }
    return success_object(data)


@bp.route("/housing-units/<uid>", methods=["PUT"])
def drive_unit(uid):
    require_roles("OperatorAdmin")
    body = get_body()
    target = require_enum(body, "status", {"DECOMMISSIONED"})
    u = db.units.get(uid)
    if u is None:
        raise err("ERR_UNIT_NOT_FOUND")
    if u["status"] not in ("REGISTERED", "CERTIFIED", "HABITABILITY_HOLD"):
        raise err("ERR_INVALID_STATE", f"Cannot decommission a unit in {u['status']}")
    # No live tenancies.
    for t in core.tenancies_of_unit(uid):
        if t["status"] in core.LIVE_TENANCY_STATUSES:
            raise err("ERR_ACTIVE_TENANCIES_REMAIN")
    u["status"] = "DECOMMISSIONED"
    u["updated_at"] = db.now_ts()
    u["version"] += 1
    core.recompute_site_posture(u["site_id"])
    return success_object(_view(u))
