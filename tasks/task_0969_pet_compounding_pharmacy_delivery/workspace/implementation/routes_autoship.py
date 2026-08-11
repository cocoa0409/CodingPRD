from flask import Blueprint, request

import db
from errors import ApiError
from middleware import auth, body, require_ownership
from response import success, paged
from services import get_or_404
from util import (new_resource, touch, req, as_str, as_int, as_date_str)

bp = Blueprint("autoship", __name__)

SCHED_READ = ("Owner", "Pharmacist", "PharmacyTech", "PharmacyAdmin")


def _filter(items, names):
    out = []
    for it in items:
        ok = True
        for n in names:
            v = request.args.get(n)
            if v is not None and str(it.get(n)) != v:
                ok = False
                break
        if ok:
            out.append(it)
    return out


@bp.route("/auto-ship-schedules", methods=["POST"])
def create_schedule():
    auth("Owner")
    d = body()
    rx_id = d.get("prescription_id")
    enrollment_id = d.get("enrollment_id")
    if rx_id is not None:
        get_or_404(db.prescriptions, rx_id, "prescription")
    if enrollment_id is not None:
        get_or_404(db.enrollments, enrollment_id, "enrollment")
    rx_id = as_str(req(d, "prescription_id"), "prescription_id")
    rx = db.prescriptions[rx_id]
    interval = as_int(req(d, "interval_days"), "interval_days")
    if interval <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "interval_days must be > 0", 400)
    next_run = as_date_str(req(d, "next_run_date"), "next_run_date")
    expected = as_int(req(d, "expected_prescription_version"),
                      "expected_prescription_version")
    if expected != rx["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "expected_prescription_version does not match the "
                       "prescription's current version", 412)
    # supersede existing ACTIVE schedule on the same prescription
    for s in sorted(db.auto_ship_schedules.values(), key=lambda x: x["_seq"]):
        if s["prescription_id"] == rx_id and s["status"] == "ACTIVE":
            s["status"] = "CANCELLED"
            touch(s)
    s = new_resource({
        "prescription_id": rx_id, "enrollment_id": enrollment_id,
        "interval_days": interval, "next_run_date": next_run,
        "status": "ACTIVE", "consecutive_failures": 0, "last_fired_at": None,
    })
    db.auto_ship_schedules[s["id"]] = s
    touch(rx)
    return success(s, 201)


@bp.route("/auto-ship-schedules/<rid>", methods=["GET"])
def get_schedule(rid):
    auth(*SCHED_READ)
    return success(get_or_404(db.auto_ship_schedules, rid, "auto-ship schedule"))


@bp.route("/auto-ship-schedules", methods=["GET"])
def list_schedules():
    auth(*SCHED_READ)
    return paged(_filter(list(db.auto_ship_schedules.values()),
                         ["prescription_id", "enrollment_id", "status"]))


def _owned_schedule(rid):
    _, user_id = auth("Owner")
    s = get_or_404(db.auto_ship_schedules, rid, "auto-ship schedule")
    rx = db.prescriptions[s["prescription_id"]]
    require_ownership(user_id, rx["owner_id"])
    return s, rx


@bp.route("/auto-ship-schedules/<rid>/pause", methods=["POST"])
def pause_schedule(rid):
    s, _ = _owned_schedule(rid)
    if s["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "schedule is not ACTIVE", 409)
    s["status"] = "PAUSED"
    touch(s)
    return success(s)


@bp.route("/auto-ship-schedules/<rid>/resume", methods=["POST"])
def resume_schedule(rid):
    s, rx = _owned_schedule(rid)
    if s["status"] != "PAUSED":
        raise ApiError("ERR_INVALID_STATE", "schedule is not PAUSED", 409)
    if rx["status"] != "VERIFIED":
        raise ApiError("ERR_PRESCRIPTION_NOT_VERIFIED",
                       "prescription is not VERIFIED", 409)
    pet = db.pets[rx["pet_id"]]
    if pet["status"] != "ALIVE":
        raise ApiError("ERR_PET_DECEASED", "pet is deceased", 422)
    s["status"] = "ACTIVE"
    s["consecutive_failures"] = 0
    touch(s)
    return success(s)


@bp.route("/auto-ship-schedules/<rid>/cancel", methods=["POST"])
def cancel_schedule(rid):
    s, _ = _owned_schedule(rid)
    if s["status"] not in ("ACTIVE", "PAUSED"):
        raise ApiError("ERR_INVALID_STATE",
                       "schedule is not ACTIVE or PAUSED", 409)
    s["status"] = "CANCELLED"
    touch(s)
    return success(s)
