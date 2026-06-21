"""Facility + clock endpoints (PRD §3.1)."""
from flask import Blueprint, g

import errors
import response
from db import db
from middleware import require_roles
from services import serialize
from services.common import stamp_create, get_body, require_fields, parse_date
from services.clock import advance_clock

bp = Blueprint("facilities", __name__)

DEPOSIT_POLICIES = {"STANDARD", "STRICT", "NONE"}


def get_facility_or_404(fid):
    f = db.facilities.get(fid)
    if f is None:
        raise errors.err_not_found()
    return f


@bp.route("/facilities", methods=["POST"])
@require_roles("FacilityManager")
def create_facility():
    body = get_body()
    require_fields(body, ["name"])

    name = body["name"]
    if not isinstance(name, str) or name == "":
        raise errors.err_invalid_request("name must be a non-empty string.")

    daycare_cutoff_time = body.get("daycare_cutoff_time", "19:00")
    deposit_policy = body.get("deposit_policy", "STANDARD")
    if deposit_policy not in DEPOSIT_POLICIES:
        raise errors.err_invalid_request("deposit_policy must be STANDARD, STRICT, or NONE.")
    overbook_grace = body.get("overbook_grace", 0)
    if not isinstance(overbook_grace, int) or isinstance(overbook_grace, bool) or overbook_grace < 0:
        raise errors.err_invalid_request("overbook_grace must be a non-negative integer.")

    facility = {
        "name": name,
        "daycare_cutoff_time": daycare_cutoff_time,
        "deposit_policy": deposit_policy,
        "overbook_grace": overbook_grace,
        "current_date": "2026-01-01",
    }
    stamp_create(facility)
    db.facilities[facility["id"]] = facility
    return response.success(serialize.facility(facility), status=201)


@bp.route("/facilities/<fid>", methods=["GET"])
@require_roles("FacilityManager", "FacilityStaff", "Owner")
def get_facility(fid):
    f = get_facility_or_404(fid)
    return response.success(serialize.facility(f), status=200)


@bp.route("/facilities/<fid>/_clock/advance", methods=["POST"])
@require_roles("FacilityManager")
def clock_advance(fid):
    f = get_facility_or_404(fid)
    body = get_body()
    require_fields(body, ["to_date"])
    to_date = body["to_date"]
    parse_date(to_date)  # validate format
    advance_clock(f, to_date)
    return response.success(serialize.facility(f), status=200)
