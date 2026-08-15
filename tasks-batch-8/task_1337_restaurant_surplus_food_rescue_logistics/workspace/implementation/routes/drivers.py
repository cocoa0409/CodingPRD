"""VolunteerDriver and DriverAvailabilityWindow endpoints."""
from flask import Blueprint, request

from db import DB, new_id
from errors import ApiError
from middleware import auth
from response import ok
from services import (
    _intervals_conflict,
    get_driver,
    ser_driver,
    ser_window,
    stamp,
    suspend_driver_cascade,
    touch,
)
from util import (
    as_bool,
    as_enum,
    as_int,
    as_iso_dt,
    as_str,
    body,
    paginate,
    parse_dt,
    reject_unknown,
    required,
)

bp = Blueprint("drivers", __name__)

DRIVER_STATUSES = ("ONBOARDING", "ACTIVE", "SUSPENDED")


@bp.post("/api/volunteer-drivers")
def create_driver():
    auth(["DispatchAdmin"])
    data = body()
    reject_unknown(
        data,
        {"full_name", "email", "vehicle_capacity_lbs", "cooler_slot_count", "cold_chain_certified"},
    )
    full_name = as_str(required(data, "full_name"), "full_name")
    email = as_str(required(data, "email"), "email")
    vehicle_capacity_lbs = as_int(
        required(data, "vehicle_capacity_lbs"), "vehicle_capacity_lbs", minimum=0
    )
    cooler_slot_count = as_int(
        required(data, "cooler_slot_count"), "cooler_slot_count", minimum=0
    )
    certified = False
    if "cold_chain_certified" in data:
        certified = as_bool(data["cold_chain_certified"], "cold_chain_certified")
    rec = {
        "id": new_id(),
        "full_name": full_name,
        "email": email,
        "vehicle_capacity_lbs": vehicle_capacity_lbs,
        "cooler_slot_count": cooler_slot_count,
        "cold_chain_certified": certified,
        "status": "ONBOARDING",
        "reliability_score": 100,
        "completed_run_count": 0,
        "upheld_strike_count": 0,
    }
    stamp(rec)
    DB["drivers"][rec["id"]] = rec
    return ok(ser_driver(rec), status=201)


@bp.get("/api/volunteer-drivers/<did>")
def get_one_driver(did):
    user_id, role = auth(["DispatchAdmin", "VolunteerDriver"])
    return ok(ser_driver(get_driver(did, user_id, role)))


@bp.patch("/api/volunteer-drivers/<did>/status")
def patch_driver_status(did):
    auth(["DispatchAdmin"])
    data = body()
    reject_unknown(data, {"target_status"})
    target = as_enum(required(data, "target_status"), "target_status", DRIVER_STATUSES)
    driver = get_driver(did)
    cur = driver["status"]
    if target == "ACTIVE":
        if cur == "ONBOARDING":
            driver["status"] = "ACTIVE"
            touch(driver)
        elif cur == "SUSPENDED":
            driver["status"] = "ACTIVE"
            driver["reliability_score"] = 80
            touch(driver)
        else:
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION", 409,
                f"Cannot move driver from {cur} to ACTIVE",
            )
    elif target == "SUSPENDED":
        if cur != "ACTIVE":
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION", 409,
                f"Cannot move driver from {cur} to SUSPENDED",
            )
        suspend_driver_cascade(driver)
    else:  # ONBOARDING is never a valid target
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", 409,
            f"Cannot move driver from {cur} to {target}",
        )
    return ok(ser_driver(driver))


@bp.post("/api/volunteer-drivers/<did>/availability-windows")
def create_window(did):
    user_id, role = auth(["VolunteerDriver"])
    data = body()
    reject_unknown(data, {"window_start", "window_end"})
    window_start = as_iso_dt(required(data, "window_start"), "window_start")
    window_end = as_iso_dt(required(data, "window_end"), "window_end")
    if parse_dt(window_end) <= parse_dt(window_start):
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "window_end must be after window_start"
        )
    driver = get_driver(did, user_id, role)
    if driver["status"] != "ACTIVE":
        raise ApiError(
            "ERR_DRIVER_NOT_ACTIVE", 409, "Driver must be ACTIVE to declare windows"
        )
    s = parse_dt(window_start)
    e = parse_dt(window_end)
    for w in DB["windows"].values():
        if w["driver_id"] != driver["id"] or w["status"] not in ("OPEN", "BOOKED"):
            continue
        if _intervals_conflict(s, e, parse_dt(w["window_start"]), parse_dt(w["window_end"])):
            raise ApiError(
                "ERR_AVAILABILITY_WINDOW_OVERLAP", 409,
                "Window overlaps an existing window of this driver",
            )
    rec = {
        "id": new_id(),
        "driver_id": driver["id"],
        "window_start": window_start,
        "window_end": window_end,
        "status": "OPEN",
        "booked_run_id": None,
    }
    stamp(rec)
    DB["windows"][rec["id"]] = rec
    return ok(ser_window(rec), status=201)


@bp.get("/api/volunteer-drivers/<did>/availability-windows")
def list_windows(did):
    user_id, role = auth(["DispatchAdmin", "VolunteerDriver"])
    driver = get_driver(did, user_id, role)
    items = [w for w in DB["windows"].values() if w["driver_id"] == driver["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [w for w in items if w["status"] == status]
    return paginate(items, ser_window)
