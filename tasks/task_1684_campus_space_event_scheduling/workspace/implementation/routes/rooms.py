"""Rooms (PRD 3.2): inventory, rate cards, outages, utilization analytics."""

from datetime import timedelta

import db
import serializers
from clock import clock, parse_instant
from constants import FEATURES
from errors import ApiError
from middleware import endpoint
from routes.common import invalid, one
from services.cascade import bump_event
from services.intervals import is_bumpable, occupancy_interval, overlap
from services.pricing import rhu_div
from validate import get_room, opt_enum_array, opt_int, req_dt, req_int, req_str

ALL_READ_ROLES = ["Scheduler", "FacilitiesManager", "ServiceCoordinator", "FinanceAdmin", "OrgRequester"]


@endpoint("POST", "/campus/rooms", roles=["FacilitiesManager"], code=201)
def create_room(ctx):
    body = ctx.body
    row = db.new_row(
        db.rooms,
        name=req_str(body, "name"),
        building_code=req_str(body, "building_code"),
        capacity=req_int(body, "capacity"),
        features=opt_enum_array(body, "features", FEATURES),
        turnaround_buffer_minutes=opt_int(body, "turnaround_buffer_minutes", 30),
        internal_hourly_rate_cents=req_int(body, "internal_hourly_rate_cents"),
        student_hourly_rate_cents=req_int(body, "student_hourly_rate_cents"),
        external_hourly_rate_cents=req_int(body, "external_hourly_rate_cents"),
        peak_multiplier_bps=opt_int(body, "peak_multiplier_bps", 12500),
        key_count=opt_int(body, "key_count", 0),
        status="ACTIVE",
        outage_start_at=None,
        outage_end_at=None,
        outage_windows=[],
        _outage_start=None,
        _outage_end=None,
        _outages=[],
    )
    return one(serializers.room(row), status=201)


@endpoint("GET", "/campus/rooms/{id}", roles=ALL_READ_ROLES, code=200)
def get_room_detail(ctx):
    return one(serializers.room(get_room(ctx.id)))


@endpoint("PATCH", "/campus/rooms/{id}", roles=["FacilitiesManager"], code=200)
def patch_room(ctx):
    room = get_room(ctx.id)
    body = ctx.body

    new_values = {}
    if "capacity" in body:
        new_values["capacity"] = opt_int(body, "capacity")
    if "features" in body:
        new_values["features"] = opt_enum_array(body, "features", FEATURES)
    if "turnaround_buffer_minutes" in body:
        new_values["turnaround_buffer_minutes"] = opt_int(body, "turnaround_buffer_minutes")
    if "internal_hourly_rate_cents" in body:
        new_values["internal_hourly_rate_cents"] = opt_int(body, "internal_hourly_rate_cents")
    if "student_hourly_rate_cents" in body:
        new_values["student_hourly_rate_cents"] = opt_int(body, "student_hourly_rate_cents")
    if "external_hourly_rate_cents" in body:
        new_values["external_hourly_rate_cents"] = opt_int(body, "external_hourly_rate_cents")
    if "peak_multiplier_bps" in body:
        new_values["peak_multiplier_bps"] = opt_int(body, "peak_multiplier_bps")
    if "key_count" in body:
        new_values["key_count"] = opt_int(body, "key_count")

    # A capacity reduction is rejected outright when a CONFIRMED or
    # IN_PROGRESS event would exceed the new capacity.
    capacity_cut = "capacity" in new_values and new_values["capacity"] < room["capacity"]
    if capacity_cut:
        for event in db.event_reservations.values():
            if event.get("room_id") != room["id"]:
                continue
            if event.get("status") in ("CONFIRMED", "IN_PROGRESS") and (
                event.get("expected_attendance", 0) > new_values["capacity"]
            ):
                raise ApiError(
                    "ERR_ROOM_EDIT_BLOCKED",
                    "The capacity reduction would leave a confirmed or in-progress event over capacity.",
                )

    for name, value in new_values.items():
        room[name] = value
    db.touch(room)

    # Over-capacity REQUESTED/APPROVED events are auto-bumped with the full
    # bump cascade.
    if capacity_cut:
        for event in db.all_of(db.event_reservations):
            if event.get("room_id") != room["id"]:
                continue
            if event.get("status") in ("REQUESTED", "APPROVED") and (
                event.get("expected_attendance", 0) > new_values["capacity"]
            ):
                bump_event(event)

    return one(serializers.room(room))


@endpoint("POST", "/campus/rooms/{id}/out-of-service", roles=["FacilitiesManager"], code=200)
def room_out_of_service(ctx):
    room = get_room(ctx.id)
    body = ctx.body
    start_raw, start_dt = req_dt(body, "outage_start_at")
    end_raw, end_dt = req_dt(body, "outage_end_at")
    if end_dt <= start_dt:
        raise ApiError("ERR_INVALID_TIME_RANGE", "outage_end_at must be later than outage_start_at.")
    if room["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "The room is already out of service.")

    now = clock.now
    overlapping = []
    for event in db.all_of(db.event_reservations):
        if event.get("room_id") != room["id"]:
            continue
        if event.get("status") not in ("REQUESTED", "APPROVED", "CONFIRMED", "IN_PROGRESS"):
            continue
        occ_start, occ_end = occupancy_interval(event, room)
        if overlap(occ_start, occ_end, start_dt, end_dt):
            overlapping.append(event)
    # Non-bumpable occupancy (shielded CONFIRMED or any IN_PROGRESS) refuses
    # the outage.
    for event in overlapping:
        if not is_bumpable(event, now):
            raise ApiError(
                "ERR_ROOM_BLOCKED",
                "The outage window overlaps a non-bumpable event.",
            )
    for event in overlapping:
        bump_event(event)

    room["status"] = "OUT_OF_SERVICE"
    room["outage_start_at"] = start_raw
    room["outage_end_at"] = end_raw
    room["_outage_start"] = start_dt
    room["_outage_end"] = end_dt
    room.setdefault("outage_windows", []).append({"start_at": start_raw, "end_at": end_raw})
    room.setdefault("_outages", []).append((start_dt, end_dt))
    db.touch(room)
    return one(serializers.room(room))


def _merged_seconds(intervals):
    """Merge half-open intervals and sum their lengths in seconds."""
    if not intervals:
        return 0
    intervals = sorted(intervals)
    total = 0
    cur_start, cur_end = intervals[0]
    for start, end in intervals[1:]:
        if start <= cur_end:
            if end > cur_end:
                cur_end = end
        else:
            total += (cur_end - cur_start).total_seconds()
            cur_start, cur_end = start, end
    total += (cur_end - cur_start).total_seconds()
    return total


def _minutes(seconds):
    return int(seconds // 60)


@endpoint("GET", "/campus/rooms/{id}/utilization", roles=["Scheduler", "FacilitiesManager"], code=200)
def room_utilization(ctx):
    room = get_room(ctx.id)
    window_start_raw = ctx.args.get("window_start")
    window_end_raw = ctx.args.get("window_end")
    window_start = parse_instant(window_start_raw) if window_start_raw is not None else None
    window_end = parse_instant(window_end_raw) if window_end_raw is not None else None
    if window_start is None or window_end is None:
        invalid("window_start and window_end are required ISO 8601 datetimes.")
    if window_end <= window_start:
        raise ApiError("ERR_INVALID_TIME_RANGE", "window_end must be later than window_start.")

    window_seconds = (window_end - window_start).total_seconds()
    outage_seconds = _merged_seconds(
        [
            (max(os_, window_start), min(oe, window_end))
            for os_, oe in room.get("_outages", [])
            if os_ < window_end and window_start < oe
        ]
    )

    def booked_seconds(statuses):
        intervals = []
        for event in db.event_reservations.values():
            if event.get("room_id") != room["id"] or event.get("status") not in statuses:
                continue
            # Booked interval: [start - setup, end + teardown) - the turnaround
            # buffer is never counted - clamped to the window.
            start = event["_start"]
            end = event["_end"]
            booked_start = start - timedelta(minutes=event.get("setup_minutes", 0))
            booked_end = end + timedelta(minutes=event.get("teardown_minutes", 0))
            clamped_start = max(booked_start, window_start)
            clamped_end = min(booked_end, window_end)
            if clamped_start < clamped_end:
                intervals.append((clamped_start, clamped_end))
        return _merged_seconds(intervals)

    scheduled_seconds = booked_seconds(("APPROVED", "CONFIRMED", "IN_PROGRESS", "COMPLETED"))
    realized_seconds = booked_seconds(("COMPLETED",))

    denominator_seconds = window_seconds - outage_seconds
    if denominator_seconds <= 0:
        scheduled_bps = None
        realized_bps = None
    else:
        scheduled_bps = rhu_div(10000 * int(scheduled_seconds), int(denominator_seconds))
        realized_bps = rhu_div(10000 * int(realized_seconds), int(denominator_seconds))

    return one(
        {
            "window_minutes": _minutes(window_seconds),
            "outage_minutes": _minutes(outage_seconds),
            "scheduled_minutes": _minutes(scheduled_seconds),
            "realized_minutes": _minutes(realized_seconds),
            "scheduled_utilization_bps": scheduled_bps,
            "realized_utilization_bps": realized_bps,
        }
    )
