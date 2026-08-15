"""Rides: register, read, list, verify-assembly, dismantle, resume."""
from flask import Blueprint

import db
from db import store, serialize, touch
from errors import (
    raise_err,
    ERR_FAIR_INVALID_STATE,
    ERR_INVALID_REQUEST,
    ERR_RIDE_INVALID_STATE,
    ERR_RIDE_NOT_LICENSED,
    ERR_INVALID_DAY_POSTURE,
    ERR_ANNUAL_CERT_EXPIRED,
    ERR_WIND_ABOVE_LIMIT,
    ERR_INCIDENTS_OPEN,
)
from helpers import (
    get_or_404,
    paginate,
    qparam,
    require_covering_shift,
    _parse_date,
)
from middleware import authenticate, scope_to_fair
from response import ok
from services.calculations import RIDE_RESUME_HYSTERESIS_MPH
from validators import get_body, reject_unknown, req_str, req_int, req_enum, req_date

bp = Blueprint("rides", __name__)

ALL = ["StateProgramAdmin", "StateInspector", "FairManager", "RideOperator", "TicketClerk", "CrewMember"]

RIDE_FIELDS = {
    "fair_id",
    "name",
    "manufacturer",
    "model",
    "serial_number",
    "ride_class",
    "capacity_per_cycle",
    "min_rider_height_in",
    "max_rider_height_in",
    "wind_limit_mph",
    "cycle_inspection_interval",
    "annual_cert_expires_on",
}

RIDE_CLASSES = ["KIDDIE", "FAMILY", "THRILL", "EXTREME"]


@bp.post("/rides")
def create_ride():
    ctx = authenticate(["FairManager"])
    body = get_body()
    reject_unknown(body, RIDE_FIELDS)
    fair_id = req_str(body, "fair_id")
    name = req_str(body, "name")
    manufacturer = req_str(body, "manufacturer")
    model = req_str(body, "model")
    serial = req_str(body, "serial_number")
    ride_class = req_enum(body, "ride_class", RIDE_CLASSES)
    capacity = req_int(body, "capacity_per_cycle", lo=1)
    min_h = req_int(body, "min_rider_height_in", lo=20, hi=96)
    max_h = req_int(body, "max_rider_height_in", lo=20, hi=96)
    wind = req_int(body, "wind_limit_mph", lo=5, hi=60)
    interval = req_int(body, "cycle_inspection_interval", lo=1)
    cert_expires = req_date(body, "annual_cert_expires_on")
    if min_h > max_h:
        raise_err(ERR_INVALID_REQUEST, "min_rider_height_in must be <= max_rider_height_in")
    scope_to_fair(ctx, fair_id if db.get("fairs", fair_id) else None)
    fair = get_or_404("fairs", fair_id)
    scope_to_fair(ctx, fair["id"])
    if fair["status"] not in ("SETUP", "PERMIT_REQUESTED", "PERMITTED"):
        raise_err(ERR_FAIR_INVALID_STATE, "Rides can only be registered while the fair is SETUP, PERMIT_REQUESTED, or PERMITTED")
    ride = db.register(
        "rides",
        {
            "fair_id": fair_id,
            "name": name,
            "manufacturer": manufacturer,
            "model": model,
            "serial_number": serial,
            "ride_class": ride_class,
            "capacity_per_cycle": capacity,
            "min_rider_height_in": min_h,
            "max_rider_height_in": max_h,
            "wind_limit_mph": wind,
            "cycle_inspection_interval": interval,
            "annual_cert_expires_on": body["annual_cert_expires_on"],
            "cycles_since_inspection": 0,
            "minor_incidents_today": 0,
            "setup_status": "INSTALLED",
            "license_status": "PENDING",
            "daily_status": "CLOSED",
        },
    )
    touch(fair)  # inventory ledger sync
    return ok(serialize(ride), 201)


@bp.get("/rides/<rid>")
def get_ride(rid):
    ctx = authenticate(ALL)
    ride = get_or_404("rides", rid)
    scope_to_fair(ctx, ride["fair_id"])
    return ok(serialize(ride))


@bp.get("/rides")
def list_rides():
    authenticate(ALL)
    return paginate(
        "rides",
        {
            "fair_id": qparam("fair_id"),
            "setup_status": qparam("setup_status"),
            "license_status": qparam("license_status"),
            "daily_status": qparam("daily_status"),
        },
    )


@bp.post("/rides/<rid>/verify-assembly")
def verify_assembly(rid):
    ctx = authenticate(["CrewMember"])
    ride = get_or_404("rides", rid)
    scope_to_fair(ctx, ride["fair_id"])
    body = get_body()
    reject_unknown(body, set())
    fair = db.get("fairs", ride["fair_id"])
    if fair["status"] not in ("SETUP", "PERMIT_REQUESTED"):
        raise_err(ERR_FAIR_INVALID_STATE, "Assembly verification requires the fair to be SETUP or PERMIT_REQUESTED")
    if ride["setup_status"] != "INSTALLED":
        raise_err(ERR_RIDE_INVALID_STATE, "Only an INSTALLED ride can be verified")
    if _parse_date(ride["annual_cert_expires_on"]) < _parse_date(fair["closing_date"]):
        raise_err(ERR_ANNUAL_CERT_EXPIRED, "Annual certification does not cover the season")
    require_covering_shift(ctx["user_id"], "SETUP")
    ride["setup_status"] = "SETUP_VERIFIED"
    touch(ride)
    return ok(serialize(ride))


@bp.post("/rides/<rid>/dismantle")
def dismantle(rid):
    ctx = authenticate(["CrewMember"])
    ride = get_or_404("rides", rid)
    scope_to_fair(ctx, ride["fair_id"])
    body = get_body()
    reject_unknown(body, set())
    fair = db.get("fairs", ride["fair_id"])
    if ride["setup_status"] != "SETUP_VERIFIED":
        raise_err(ERR_RIDE_INVALID_STATE, "Only a SETUP_VERIFIED ride can be dismantled")
    if fair["status"] != "TEARDOWN":
        raise_err(ERR_FAIR_INVALID_STATE, "Dismantling requires the fair to be in TEARDOWN")
    if ride["daily_status"] != "CLOSED":
        raise_err(ERR_RIDE_INVALID_STATE, "The ride's daily status must be CLOSED")
    require_covering_shift(ctx["user_id"], "TEARDOWN")
    ride["setup_status"] = "DISMANTLED"
    if ride["license_status"] != "REVOKED":
        ride["license_status"] = "REVOKED"
    touch(ride)
    return ok(serialize(ride))


@bp.post("/rides/<rid>/resume")
def resume_ride(rid):
    ctx = authenticate(["FairManager"])
    ride = get_or_404("rides", rid)
    scope_to_fair(ctx, ride["fair_id"])
    body = get_body()
    reject_unknown(body, set())
    if ride["daily_status"] not in ("WEATHER_HOLD", "INCIDENT_HOLD"):
        raise_err(ERR_RIDE_INVALID_STATE, "Only a ride in WEATHER_HOLD or INCIDENT_HOLD can be resumed")
    day = _current_open_day(ride["fair_id"])
    if day is None:
        raise_err(ERR_INVALID_DAY_POSTURE, "The operating day must be OPEN to resume a ride")
    if ride["license_status"] != "LICENSED":
        raise_err(ERR_RIDE_NOT_LICENSED, "The ride must be LICENSED to resume")
    if ride["daily_status"] == "WEATHER_HOLD":
        latest = _latest_observation(day["id"])
        if latest is None or latest["wind_speed_mph"] > ride["wind_limit_mph"] - RIDE_RESUME_HYSTERESIS_MPH:
            raise_err(ERR_WIND_ABOVE_LIMIT, "Latest wind reading is above the resume threshold")
    else:  # INCIDENT_HOLD
        for inc in store["incidents"].values():
            if (
                inc["ride_id"] == ride["id"]
                and inc["operating_day_id"] == day["id"]
                and inc["status"] in ("FILED", "SHUTDOWN_ORDERED")
            ):
                raise_err(ERR_INCIDENTS_OPEN, "An open incident remains for this ride and day")
    ride["daily_status"] = "OPEN"
    touch(ride)
    return ok(serialize(ride))


def _current_open_day(fair_id):
    days = [
        d
        for d in store["operating_days"].values()
        if d["fair_id"] == fair_id and d["posture"] == "OPEN"
    ]
    if not days:
        return None
    days.sort(key=lambda d: (d["date"], d["_seq"]), reverse=True)
    return days[0]


def _latest_observation(day_id):
    obs = [o for o in store["observations"].values() if o["operating_day_id"] == day_id]
    if not obs:
        return None
    obs.sort(key=lambda o: (o["created_at"], o["_seq"]))
    return obs[-1]
