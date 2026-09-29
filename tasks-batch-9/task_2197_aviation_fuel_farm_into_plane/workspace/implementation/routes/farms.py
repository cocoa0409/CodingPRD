"""Logical clock, fuel farms and environmental permits."""
import re

from flask import Blueprint

import calc
import services as svc
from authz import (ALL_ROLES, auth, body, enum, opt_bool, opt_num, out_of_range,
                   req_dt, req_num, req_str, resolve, rng)
from core import (ApiError, D, base_row, created, db, f2, fmt_dt, listing, now,
                  now_iso, ok, parse_dt, public, touch)

bp = Blueprint("farms", __name__)

IATA3 = re.compile(r"^[A-Z]{3}$")


def farm_view(farm):
    svc.refresh_farm(farm)
    return public(farm)


def permit_view(permit):
    farm = db.farms.get(permit["fuel_farm_id"])
    if farm is not None:
        svc.refresh_farm(farm)
    return public(permit)


# ------------------------------------------------------------------ clock
@bp.post("/_clock/set_current_utc")
def set_clock():
    auth("ConsortiumAdmin")
    data = body()
    instant = req_dt(data, "to_iso8601")
    db.clock = instant

    for a in db.authorizations.values():
        svc.expire_authorization(a)
    for farm in list(db.farms.values()):
        calc.expire_permits(farm["id"])
    for asset in list(db.assets.values()):
        prev = asset["status"]
        calc.recompute_asset(asset)
        if asset["status"] != prev:
            touch(asset)
    for farm in list(db.farms.values()):
        # A clock advance recomputes posture and nothing more: PRD says the auto-transition
        # "raises the affected row's `version` by 1, and a permit expiry additionally
        # recomputes the farm's posture". The freeze cascade is named explicitly at the two
        # places it fires -- a permit suspension and a spill escalation -- and is not among
        # the effects the clock advance is given, so no child row is written here.
        svc.refresh_farm(farm)
    return ok({"current_utc": now_iso(), "to_iso8601": now_iso()})


# ------------------------------------------------------------------ farms
@bp.post("/fuel-farms")
def create_farm():
    auth("ConsortiumAdmin")
    data = body()
    iata = req_str(data, "iata_code")
    name = req_str(data, "name")
    hydrant = opt_bool(data, "hydrant_system_available", False)
    unpumpable = opt_num(data, "unpumpable_bottom_liters", "500.0")

    if not IATA3.match(iata):
        out_of_range("iata_code must be exactly 3 uppercase letters")
    rng(unpumpable, "unpumpable_bottom_liters", minimum=0)

    for f in db.farms.values():
        if f["iata_code"] == iata:
            raise ApiError("ERR_DUPLICATE_KEY", "iata_code %s already registered" % iata)

    farm = base_row()
    farm.update({
        "iata_code": iata,
        "name": name,
        "hydrant_system_available": hydrant,
        "unpumpable_bottom_liters": f2(unpumpable),
        "posture": "FROZEN",
        "active_permit_throughput_used_liters": 0.0,
        "in_service_asset_count": 0,
        "open_spill_count": 0,
    })
    db.farms[farm["id"]] = farm
    calc.recompute_farm(farm)
    return created(public(farm))


@bp.get("/fuel-farms/<fid>")
def get_farm(fid):
    auth(*ALL_ROLES)
    farm = resolve(db.farms, fid, "Fuel farm not found")
    return ok(farm_view(farm))


# ------------------------------------------------------------------ permits
@bp.post("/fuel-farms/<fid>/environmental-permits")
def create_permit(fid):
    auth("ConsortiumAdmin")
    farm = resolve(db.farms, fid, "Fuel farm not found")
    data = body()
    number = req_str(data, "permit_number")
    valid_from = req_dt(data, "valid_from_utc")
    valid_until = req_dt(data, "valid_until_utc")
    max_daily = req_num(data, "max_daily_throughput_liters")
    max_spill = opt_num(data, "max_reportable_spill_liters", "20.0")

    rng(max_daily, "max_daily_throughput_liters", minimum=0, exclusive_min=True)
    rng(max_spill, "max_reportable_spill_liters", minimum=0)

    for p in db.permits.values():
        if p["permit_number"] == number:
            raise ApiError("ERR_DUPLICATE_KEY", "permit_number %s already exists" % number)

    permit = base_row()
    permit.update({
        "fuel_farm_id": farm["id"],
        "permit_number": number,
        "valid_from_utc": fmt_dt(valid_from),
        "valid_until_utc": fmt_dt(valid_until),
        "max_daily_throughput_liters": f2(max_daily),
        "max_reportable_spill_liters": f2(max_spill),
        "status": "ACTIVE",
        "suspension_reason": None,
    })
    db.permits[permit["id"]] = permit
    svc.refresh_farm(farm)
    return created(public(permit))


@bp.get("/fuel-farms/<fid>/environmental-permits")
def list_permits(fid):
    auth("ConsortiumAdmin", "FarmOperator", "EnvironmentalOfficer")
    farm = resolve(db.farms, fid, "Fuel farm not found")
    svc.refresh_farm(farm)
    rows = [p for p in db.permits.values() if p["fuel_farm_id"] == farm["id"]]
    return listing(rows)


@bp.post("/environmental-permits/<pid>/suspend")
def suspend_permit(pid):
    auth("EnvironmentalOfficer")
    permit = resolve(db.permits, pid, "Environmental permit not found")
    data = body()
    reason = req_str(data, "suspension_reason")
    farm = db.farms.get(permit["fuel_farm_id"])
    calc.expire_permits(permit["fuel_farm_id"])
    if permit["status"] != "ACTIVE":
        raise ApiError("ERR_PERMIT_NOT_ACTIVE", "Permit is not ACTIVE")

    permit["status"] = "SUSPENDED"
    permit["suspension_reason"] = reason
    touch(permit)
    if farm is not None:
        svc.apply_posture_change(farm)
        touch(farm)
    return ok(public(permit))


@bp.post("/environmental-permits/<pid>/reinstate")
def reinstate_permit(pid):
    auth("EnvironmentalOfficer")
    permit = resolve(db.permits, pid, "Environmental permit not found")
    body()
    farm = db.farms.get(permit["fuel_farm_id"])
    if permit["status"] != "SUSPENDED":
        raise ApiError("ERR_PERMIT_NOT_ACTIVE", "Permit is not SUSPENDED")

    if now() >= parse_dt(permit["valid_until_utc"]):
        raise ApiError("ERR_PERMIT_NOT_ACTIVE", "Permit validity has elapsed")

    permit["status"] = "ACTIVE"
    touch(permit)
    if farm is not None:
        svc.apply_posture_change(farm)
        touch(farm)
    return ok(public(permit))
