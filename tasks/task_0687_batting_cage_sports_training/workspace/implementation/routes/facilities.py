"""Facility routes (PRD 3.1, 2.6 run-ops)."""
from flask import Blueprint

from clock import clock
from constants import MEMBER_MINUTE_CAP  # noqa: F401 (documentation of cap source)
from db import db
from errors import err, ERR_INVALID_REQUEST
from helpers import (
    get_json_body,
    require_fields,
    lookup,
    base_common_fields,
    parse_pagination,
    paginate,
)
from middleware import authenticate, require_role
from response import success
from serializers import facility_out
from services.derive import (
    recompute_lane,
    recompute_facility,
    recompute_machine,
    recompute_member_waiver,
    touch,
)

bp = Blueprint("facilities", __name__)

READ_ROLES = ["FacilityManager", "FrontDesk", "Member", "Instructor"]


@bp.post("/v1/facilities")
def create_facility():
    _, role = authenticate()
    require_role(role, ["FacilityManager"])
    body = get_json_body()
    require_fields(body, ["name"])

    open_minute = body.get("open_minute", 480)
    close_minute = body.get("close_minute", 1320)
    token_price_cents = body.get("token_price_cents", 500)
    hourly_rate_cents = body.get("hourly_rate_cents", 4000)

    _validate_int_range(open_minute, 0, 1440, "open_minute")
    _validate_int_range(close_minute, 0, 1440, "close_minute")
    if close_minute <= open_minute:
        raise err(ERR_INVALID_REQUEST, "close_minute must be greater than open_minute")
    if not isinstance(token_price_cents, int) or isinstance(token_price_cents, bool) or token_price_cents < 1:
        raise err(ERR_INVALID_REQUEST, "token_price_cents must be >= 1")
    if not isinstance(hourly_rate_cents, int) or isinstance(hourly_rate_cents, bool) or hourly_rate_cents < 0:
        raise err(ERR_INVALID_REQUEST, "hourly_rate_cents must be >= 0")

    facility = base_common_fields()
    facility.update({
        "name": body["name"],
        "timezone": body.get("timezone", "UTC"),
        "open_minute": open_minute,
        "close_minute": close_minute,
        "token_price_cents": token_price_cents,
        "hourly_rate_cents": hourly_rate_cents,
        "posture": "OPEN",
        "open_incident_count": 0,
        "epoch_index": 0,
    })
    db.facilities[facility["id"]] = facility
    return success(facility_out(facility), status=201)


def _validate_int_range(value, lo, hi, field):
    if not isinstance(value, int) or isinstance(value, bool) or value < lo or value > hi:
        raise err(ERR_INVALID_REQUEST, "%s out of range" % field)


@bp.get("/v1/facilities")
def list_facilities():
    _, role = authenticate()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    page, meta = paginate(list(db.facilities.values()), limit, offset)
    return success([facility_out(f) for f in page], status=200, pagination=meta)


@bp.get("/v1/facilities/<facility_id>")
def get_facility(facility_id):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    facility = lookup(db.facilities, facility_id)
    return success(facility_out(facility), status=200)


@bp.post("/v1/facilities/<facility_id>/run-ops")
def run_ops(facility_id):
    """PRD 2.6: epoch advance. No-show sweep, reset minutes+strikes, recompute."""
    _, role = authenticate()
    require_role(role, ["FacilityManager"])
    facility = lookup(db.facilities, facility_id)

    now = clock.now()
    from clock import parse_iso

    # 1. No-show sweep: CONFIRMED whose end_utc <= clock and never checked in.
    for booking in db.bookings.values():
        if booking["facility_id"] != facility_id:
            continue
        if booking["status"] != "CONFIRMED":
            continue
        if parse_iso(booking["end_utc"]) <= now:
            booking["status"] = "NO_SHOW"
            touch(booking)
            member = db.members.get(booking["member_id"])
            if member is not None:
                member["no_show_strikes"] += 1
                touch(member)
            # Lane interval released by status change (no longer active).

    # 2. Reset member monthly minutes and strikes to 0 (epoch boundary).
    for member in db.members.values():
        if member["facility_id"] != facility_id:
            continue
        changed = False
        if member["monthly_member_minutes_used"] != 0:
            member["monthly_member_minutes_used"] = 0
            changed = True
        if member["no_show_strikes"] != 0:
            member["no_show_strikes"] = 0
            changed = True
        if changed:
            touch(member)

    # 3. Recompute lane / machine / posture / waiver derived fields.
    for lane in db.lanes.values():
        if lane["facility_id"] == facility_id:
            recompute_lane(lane)
    for machine in db.machines.values():
        if machine["facility_id"] == facility_id:
            recompute_machine(machine)
    for member in db.members.values():
        if member["facility_id"] == facility_id:
            recompute_member_waiver(member)
    recompute_facility(facility)

    # 4. epoch_index += 1 (PRD 2.6) — always a mutation.
    facility["epoch_index"] += 1
    touch(facility)

    return success(facility_out(facility), status=200)
