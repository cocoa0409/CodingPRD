"""Finish booths and the cure clock (PRD 3.7)."""

from datetime import timedelta

from flask import Blueprint

import auth
import calc
import domain
import store
import validate as v
from constants import FINISH_SYSTEMS, RUN_STATUSES
from envelope import object_response, paginate
from errors import ApiError
from serialize import run_view
from store import ORDERS, ROOMS, RUNS, new_record, touch

bp = Blueprint("finish", __name__)

NON_TERMINAL = ("SPRAYING", "CURING", "CURE_SUSPENDED", "BUFFING")


def _run(finish_run_id):
    return v.fetch(RUNS, finish_run_id, "ERR_FINISH_RUN_NOT_FOUND")


def _require_booth_in_spec(booth):
    """Rung 11: the booth is the governing room for every finish operation."""
    if booth is None:
        return
    if booth["climate_status"] == "QUARANTINED":
        raise ApiError("ERR_ROOM_QUARANTINED", "the booth is quarantined")
    if booth["climate_status"] != "IN_SPEC":
        raise ApiError("ERR_ROOM_CLIMATE_OUT_OF_SPEC",
                       "the booth is out of specification")


@bp.post("/finish-runs")
def create_run():
    auth.require(auth.FINISH_TECH)
    body = v.body()
    order_id = v.get_id(body, "build_order_id")
    booth_id = v.get_id(body, "booth_id")
    finish_system = v.get_enum(body, "finish_system", FINISH_SYSTEMS)
    coat_count = v.get_int(body, "coat_count", minimum=1, maximum=24)
    expected = v.get_int(body, "expected_build_order_version")
    order = v.fetch(ORDERS, order_id, "ERR_BUILD_ORDER_NOT_FOUND")
    booth = v.fetch(ROOMS, booth_id, "ERR_STORAGE_ROOM_NOT_FOUND")
    if finish_system != order["finish_system"]:
        v.bad("finish_system must match the order's own finish system")
    if order["build_stage"] != "IN_ASSEMBLY":
        raise ApiError("ERR_BUILD_STAGE_INVALID",
                       "a booth is booked from IN_ASSEMBLY")
    if expected != order["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "the build order has moved on since it was read")
    _require_booth_in_spec(booth)
    if booth["room_type"] != "FINISH_BOOTH":
        raise ApiError("ERR_BOOTH_ROOM_TYPE_INVALID",
                       "the named room is not a finish booth")

    hold_from = store.now_utc()
    hold_until = hold_from + timedelta(
        hours=calc.booth_hold_hours(finish_system, coat_count))
    overlapping = domain.booth_overlaps(booth["id"], hold_from, hold_until)
    for other in overlapping:
        if other["finish_system"] != finish_system:
            raise ApiError("ERR_BOOTH_FINISH_INCOMPATIBLE",
                           "another chemistry is holding this booth")
    if len(overlapping) + 1 > booth["capacity_slots"]:
        raise ApiError("ERR_BOOTH_CAPACITY_EXCEEDED",
                       "the booth has no free slot over that window")

    rec = new_record(RUNS, {
        "build_order_id": order["id"],
        "booth_id": booth["id"],
        "finish_system": finish_system,
        "coat_count": coat_count,
        "spray_started_at": hold_from,
        "spray_completed_at": None,
        "cure_hours": None,
        "cure_suspended_minutes": 0,
        "cure_suspend_started_at": None,
        "cure_ready_at": None,
        "booth_hold_from": hold_from,
        "booth_hold_until": hold_until,
        "status": "SPRAYING",
    })
    order["build_stage"] = "IN_FINISH"
    touch(order)
    return object_response(run_view(rec), 201)


@bp.get("/finish-runs/<finish_run_id>")
def read_run(finish_run_id):
    auth.require_staff()
    return object_response(run_view(_run(finish_run_id)))


@bp.get("/finish-runs")
def list_runs():
    auth.require_staff()
    rows = v.apply_filters(list(RUNS.values()), [
        ("build_order_id", v.filter_value("build_order_id")),
        ("booth_id", v.filter_value("booth_id")),
        ("finish_system", v.filter_enum("finish_system", FINISH_SYSTEMS)),
        ("status", v.filter_enum("status", RUN_STATUSES)),
    ])
    rows.sort(key=lambda r: (r["booth_hold_from"], r["created_at"], r["_seq"]))
    return paginate(rows, run_view)


def _cure_ready(rec):
    return (rec["spray_completed_at"]
            + timedelta(hours=int(rec["cure_hours"]))
            + timedelta(minutes=rec["cure_suspended_minutes"]))


@bp.post("/finish-runs/<finish_run_id>/complete-spray")
def complete_spray(finish_run_id):
    auth.require(auth.FINISH_TECH)
    rec = _run(finish_run_id)
    if rec["status"] != "SPRAYING":
        raise ApiError("ERR_FINISH_RUN_STATE_INVALID",
                       "only a SPRAYING run may close its booth door")
    booth = ROOMS.get(rec["booth_id"])
    _require_booth_in_spec(booth)
    rec["spray_completed_at"] = store.now_utc()
    rec["cure_hours"] = calc.cure_hours_for(
        rec["finish_system"], rec["coat_count"],
        booth["latest_rh_pct"], booth["latest_temp_c"])
    rec["cure_ready_at"] = _cure_ready(rec)
    rec["status"] = "CURING"
    touch(rec)
    return object_response(run_view(rec))


@bp.post("/finish-runs/<finish_run_id>/resume-cure")
def resume_cure(finish_run_id):
    auth.require(auth.FINISH_TECH)
    rec = _run(finish_run_id)
    if rec["status"] != "CURE_SUSPENDED":
        raise ApiError("ERR_FINISH_RUN_STATE_INVALID",
                       "only a suspended cure may be resumed")
    booth = ROOMS.get(rec["booth_id"])
    _require_booth_in_spec(booth)
    now = store.now_utc()
    started = rec["cure_suspend_started_at"]
    if started is not None:
        elapsed = int((now - started).total_seconds() // 60)
        if elapsed > 0:
            rec["cure_suspended_minutes"] += elapsed
    rec["cure_suspend_started_at"] = None
    rec["cure_ready_at"] = _cure_ready(rec)
    rec["status"] = "CURING"
    touch(rec)
    order = ORDERS.get(rec["build_order_id"])
    if order is not None and order["build_stage"] == "FINISH_HELD":
        order["build_stage"] = "IN_FINISH"
        touch(order)
    return object_response(run_view(rec))


@bp.post("/finish-runs/<finish_run_id>/buff")
def buff(finish_run_id):
    auth.require(auth.FINISH_TECH)
    rec = _run(finish_run_id)
    if rec["status"] != "CURING":
        raise ApiError("ERR_FINISH_RUN_STATE_INVALID",
                       "only a CURING run may go to the buffing wheel")
    booth = ROOMS.get(rec["booth_id"])
    _require_booth_in_spec(booth)
    if store.now_utc() < rec["cure_ready_at"]:
        raise ApiError("ERR_CURE_NOT_COMPLETE", "the cure has not run out")
    rec["status"] = "BUFFING"
    touch(rec)
    return object_response(run_view(rec))


@bp.post("/finish-runs/<finish_run_id>/complete")
def complete_run(finish_run_id):
    auth.require(auth.FINISH_TECH)
    rec = _run(finish_run_id)
    if rec["status"] != "BUFFING":
        raise ApiError("ERR_FINISH_RUN_STATE_INVALID",
                       "only a BUFFING run may be completed")
    rec["status"] = "COMPLETED"
    touch(rec)
    order = ORDERS.get(rec["build_order_id"])
    if order is not None and order["build_stage"] == "IN_FINISH":
        order["build_stage"] = "FINISH_CURED"
        touch(order)
    return object_response(run_view(rec))


@bp.post("/finish-runs/<finish_run_id>/reject")
def reject_run(finish_run_id):
    auth.require(auth.QUALITY_INSPECTOR)
    body = v.body()
    v.get_str(body, "reason", required=False)
    rec = _run(finish_run_id)
    if rec["status"] not in ("CURING", "CURE_SUSPENDED", "BUFFING"):
        raise ApiError("ERR_FINISH_RUN_STATE_INVALID",
                       "the run is not in a condemnable status")
    rec["status"] = "REJECTED"
    touch(rec)
    order = ORDERS.get(rec["build_order_id"])
    if order is not None and order["build_stage"] in ("IN_FINISH",
                                                      "FINISH_HELD"):
        order["build_stage"] = "IN_ASSEMBLY"
        order["refinish_count"] += 1
        touch(order)
    return object_response(run_view(rec))
