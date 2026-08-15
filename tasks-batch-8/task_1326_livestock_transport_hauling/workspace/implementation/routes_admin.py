"""Shippers, drivers, duty events."""
from flask import Blueprint, g, request

import db
import hos
import services as svc
from errors import (
    raise_err, ERR_SHIPPER_NOT_FOUND, ERR_DRIVER_NOT_FOUND,
    ERR_DUPLICATE_LICENSE_NO, ERR_OWNERSHIP_MISMATCH, ERR_EVENT_IN_FUTURE,
    ERR_DUTY_INTERVAL_OVERLAP, ERR_DUTY_EVENT_SEQUENCE,
)
from middleware import require_role
from response import success
from util import get_body, v_str, v_num, v_int, v_enum, v_dt, paginate

bp = Blueprint("admin", __name__)

EVENT_TYPES = {"DUTY_ON", "DUTY_OFF", "DRIVING_ON", "DRIVING_OFF", "BREAK_START", "BREAK_END"}

# legal manual transitions from a duty sub-state
LEGAL_FROM = {
    "DUTY_ON": {hos.OFF},
    "DRIVING_ON": {hos.DUTY},
    "DRIVING_OFF": {hos.DRIVING},
    "BREAK_START": {hos.DUTY},
    "BREAK_END": {hos.ON_BREAK},
    "DUTY_OFF": {hos.DUTY, hos.DRIVING, hos.ON_BREAK},
}


# ---------------------------------------------------------------- shippers
@bp.post("/haul/shippers")
def create_shipper():
    require_role("CarrierAdmin")
    body = get_body()
    name = v_str(body, "name")
    email = v_str(body, "contact_email")
    pct = v_num(body, "default_shrink_allowance_pct", required=False, default=2.0,
                min_value=0)
    rec = svc.new_common()
    rec.update({"name": name, "contact_email": email,
                "default_shrink_allowance_pct": pct})
    db.store["shippers"][rec["id"]] = rec
    return success(svc.shipper_json(rec), status=201)


@bp.get("/haul/shippers")
def list_shippers():
    items = sorted(db.store["shippers"].values(), key=lambda s: s["seq"])
    page, meta = paginate([svc.shipper_json(s) for s in items])
    return success(page, response_type="array", pagination=meta)


@bp.get("/haul/shippers/<sid>")
def get_shipper(sid):
    s = db.store["shippers"].get(sid)
    if s is None:
        raise_err(ERR_SHIPPER_NOT_FOUND)
    return success(svc.shipper_json(s))


# ---------------------------------------------------------------- drivers
@bp.post("/haul/drivers")
def create_driver():
    require_role("CarrierAdmin")
    body = get_body()
    name = v_str(body, "name")
    license_no = v_str(body, "license_no")
    for d in db.store["drivers"].values():
        if d["license_no"] == license_no:
            raise_err(ERR_DUPLICATE_LICENSE_NO, "license_no already registered")
    rec = svc.new_common()
    rec.update({"name": name, "license_no": license_no, "status": "ACTIVE"})
    db.store["drivers"][rec["id"]] = rec
    return success(svc.driver_json(rec), status=201)


@bp.get("/haul/drivers")
def list_drivers():
    now = db.now()
    items = [svc.driver_json(d, now)
             for d in sorted(db.store["drivers"].values(), key=lambda d: d["seq"])]
    status_f = request.args.get("status")
    hos_f = request.args.get("hos_status")
    if status_f is not None:
        items = [d for d in items if d["status"] == status_f]
    if hos_f is not None:
        items = [d for d in items if d["hos_status"] == hos_f]
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)


@bp.get("/haul/drivers/<did>")
def get_driver(did):
    d = db.store["drivers"].get(did)
    if d is None:
        raise_err(ERR_DRIVER_NOT_FOUND)
    return success(svc.driver_json(d))


@bp.post("/haul/drivers/<did>/duty-events")
def append_duty_event(did):
    require_role("CarrierAdmin", "Driver")
    # Layer 3: driver ownership (checkable from the path id itself).
    if g.user_role == "Driver" and g.user_id != did:
        raise_err(ERR_OWNERSHIP_MISMATCH, "drivers may only append to their own log")
    d = db.store["drivers"].get(did)
    if d is None:
        raise_err(ERR_DRIVER_NOT_FOUND)
    body = get_body()
    event_type = v_enum(body, "event_type", EVENT_TYPES)
    occurred_at = v_dt(body, "occurred_at")
    now = db.now()
    if occurred_at > now:
        raise_err(ERR_EVENT_IN_FUTURE, "occurred_at is after the current time")
    events = hos.driver_events(did)
    if events and occurred_at < events[-1]["occurred_at"]:
        raise_err(ERR_DUTY_INTERVAL_OVERLAP,
                  "occurred_at precedes the previous event's occurred_at")
    _, state = hos.replay(did, now)
    if state not in LEGAL_FROM[event_type]:
        raise_err(ERR_DUTY_EVENT_SEQUENCE,
                  "%s is not legal from the current duty sub-state" % event_type)
    before = hos.hos_snapshot(did, now)
    rec = svc.insert_duty_event(did, event_type, occurred_at, "MANUAL", None)
    after = hos.hos_snapshot(did, now)
    if before != after:
        svc.touch(d)
    return success(svc.duty_event_json(rec), status=201)


@bp.get("/haul/drivers/<did>/duty-events")
def list_duty_events(did):
    d = db.store["drivers"].get(did)
    if d is None:
        raise_err(ERR_DRIVER_NOT_FOUND)
    events = hos.driver_events(did)
    page, meta = paginate([svc.duty_event_json(e) for e in events])
    return success(page, response_type="array", pagination=meta)
