"""RouteSegment, StagingArea, LineupAssignment, and MarshalAssignment endpoints."""
from datetime import timedelta

from flask import Blueprint, request

import db
from auth import ALL_ROLES, guarded, require_owner
from db import STORE, make_record, touch
from errors import api_err
from logic import (
    entry_or_404,
    ensure_not_frozen,
    lineup_or_404,
    marshal_or_404,
    parade_or_404,
    reserved_slots,
    segment_or_404,
    ser_lineup,
    ser_marshal,
    ser_segment,
    ser_staging,
    staging_or_404,
    _cancel_entry_intro_items,
)
from util import body, paged, req_dt, req_int, req_num, req_str, respond_object

bp = Blueprint("ops", __name__)

CA = ("CommitteeAdmin",)
SEGMENT_READERS = ("CommitteeAdmin", "AgencyReviewer", "Marshal")
STAGING_READERS = ("CommitteeAdmin", "AgencyReviewer", "Entrant")
LINEUP_READERS = ("CommitteeAdmin", "AgencyReviewer", "Entrant")
MARSHAL_READERS = ("CommitteeAdmin", "AgencyReviewer", "Marshal")
MARSHAL = ("Marshal",)

STAGING_BUFFER = timedelta(minutes=15)


def add(rule, methods, view):
    bp.add_url_rule(rule, view_func=view, methods=methods, strict_slashes=False)


def _minute_floor(dt):
    return dt.replace(second=0, microsecond=0)


# --- RouteSegment --------------------------------------------------------------

def create_segment(uid, role, id):
    parade_or_404(id)
    data = body()
    order_index = req_int(data, "order_index")
    name = req_str(data, "name")
    length_meters = req_num(data, "length_meters", minimum=0, exclusive_min=True)
    lane = req_num(data, "emergency_lane_width_m", minimum=3.0)
    start = req_dt(data, "segment_window_start")
    end = req_dt(data, "segment_window_end")
    if not end > start:
        raise api_err("ERR_VALIDATION", "segment_window_end must be strictly after segment_window_start")
    rec = make_record()
    rec.update(
        {
            "parade_id": id,
            "order_index": order_index,
            "name": name,
            "length_meters": length_meters,
            "emergency_lane_width_m": lane,
            "segment_window_start": start,
            "segment_window_end": end,
        }
    )
    STORE.route_segments[rec["id"]] = rec
    return respond_object(ser_segment(rec), 201)


def list_segments(uid, role, id):
    parade_or_404(id)
    items = [s for s in STORE.route_segments.values() if s["parade_id"] == id]
    return paged(items, ser_segment)


def get_segment(uid, role, id):
    return respond_object(ser_segment(segment_or_404(id)))


add("/parades/<id>/route-segments", ["POST"], guarded(CA)(create_segment))
add("/parades/<id>/route-segments", ["GET"], guarded(ALL_ROLES)(list_segments))
add("/route-segments/<id>", ["GET"], guarded(SEGMENT_READERS)(get_segment))


# --- StagingArea -----------------------------------------------------------------

def create_staging(uid, role, id):
    parade_or_404(id)
    data = body()
    name = req_str(data, "name")
    capacity = req_int(data, "capacity", minimum=1)
    open_time = req_dt(data, "open_time")
    close_time = req_dt(data, "close_time")
    if not close_time > open_time:
        raise api_err("ERR_VALIDATION", "close_time must be strictly after open_time")
    rec = make_record()
    rec.update(
        {
            "parade_id": id,
            "name": name,
            "capacity": capacity,
            "open_time": open_time,
            "close_time": close_time,
        }
    )
    STORE.staging_areas[rec["id"]] = rec
    return respond_object(ser_staging(rec), 201)


def list_staging(uid, role, id):
    parade_or_404(id)
    items = [s for s in STORE.staging_areas.values() if s["parade_id"] == id]
    return paged(items, ser_staging)


def get_staging(uid, role, id):
    return respond_object(ser_staging(staging_or_404(id)))


add("/parades/<id>/staging-areas", ["POST"], guarded(CA)(create_staging))
add("/parades/<id>/staging-areas", ["GET"], guarded(STAGING_READERS)(list_staging))
add("/staging-areas/<id>", ["GET"], guarded(STAGING_READERS)(get_staging))


# --- LineupAssignment ------------------------------------------------------------

def _entry_in_parade(entry_id, parade_id):
    entry = STORE.entries.get(entry_id)
    if entry is None or entry["parade_id"] != parade_id:
        raise api_err("ERR_ENTRY_NOT_FOUND", "No EntryApplication with the given id in this parade")
    return entry


def _staging_in_parade(staging_area_id, parade_id):
    area = STORE.staging_areas.get(staging_area_id)
    if area is None or area["parade_id"] != parade_id:
        raise api_err("ERR_STAGING_AREA_NOT_FOUND", "No StagingArea with the given id in this parade")
    return area


def _check_within_staging_hours(area, arrive_at, depart_at):
    if arrive_at < area["open_time"] or depart_at > area["close_time"]:
        raise api_err(
            "ERR_WINDOW_OUTSIDE_STAGING_HOURS",
            "[arrive_at, depart_at] must be contained in the staging area [open_time, close_time]",
        )


def create_lineup(uid, role, id):
    parade = parade_or_404(id)
    data = body()
    entry_id = req_str(data, "entry_id")
    staging_area_id = req_str(data, "staging_area_id")
    position_number = req_int(data, "position_number")
    arrive_at = req_dt(data, "arrive_at")
    depart_at = req_dt(data, "depart_at")
    if not depart_at > arrive_at:
        raise api_err("ERR_VALIDATION", "depart_at must be strictly after arrive_at")
    entry = _entry_in_parade(entry_id, id)
    area = _staging_in_parade(staging_area_id, id)
    if entry["status"] != "APPROVED":
        raise api_err("ERR_ENTRY_NOT_APPROVED", "Lineup creation requires the entry APPROVED")
    if parade["status"] not in ("PERMIT_GRANTED", "LOCKED"):
        raise api_err("ERR_INVALID_STATE", "Parade must be in PERMIT_GRANTED or LOCKED")
    _check_within_staging_hours(area, arrive_at, depart_at)
    rec = make_record()
    rec.update(
        {
            "parade_id": id,
            "entry_id": entry_id,
            "staging_area_id": staging_area_id,
            "position_number": position_number,
            "arrive_at": arrive_at,
            "depart_at": depart_at,
            "status": "TENTATIVE",
        }
    )
    STORE.lineup_assignments[rec["id"]] = rec
    return respond_object(ser_lineup(rec), 201)


def list_lineup(uid, role):
    items = list(STORE.lineup_assignments.values())
    parade_id = request.args.get("parade_id")
    entry_id = request.args.get("entry_id")
    staging_area_id = request.args.get("staging_area_id")
    status = request.args.get("status")
    if parade_id is not None:
        items = [a for a in items if a["parade_id"] == parade_id]
    if entry_id is not None:
        items = [a for a in items if a["entry_id"] == entry_id]
    if staging_area_id is not None:
        items = [a for a in items if a["staging_area_id"] == staging_area_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return paged(items, ser_lineup)


def get_lineup(uid, role, id):
    return respond_object(ser_lineup(lineup_or_404(id)))


def confirm_lineup(uid, role, id):
    a = lineup_or_404(id)
    if a["status"] != "TENTATIVE":
        raise api_err("ERR_INVALID_STATE", "Assignment must be in TENTATIVE to confirm")
    parade = parade_or_404(a["parade_id"])
    ensure_not_frozen(parade)
    entry = entry_or_404(a["entry_id"])
    if entry["status"] != "APPROVED":
        raise api_err("ERR_ENTRY_NOT_APPROVED", "Lineup confirm requires the entry APPROVED")
    # Safety gate: every float of the entry must be CERTIFIED.
    floats = [f for f in STORE.floats.values() if f["entry_id"] == entry["id"]]
    if floats and any(f["compliance_status"] != "CERTIFIED" for f in floats):
        raise api_err("ERR_FLOAT_UNCERTIFIED", "Every float of the entry must be CERTIFIED")
    # Constraint: position uniqueness among active assignments of the parade.
    if any(
        other["id"] != a["id"]
        and other["parade_id"] == a["parade_id"]
        and other["status"] in ("TENTATIVE", "CONFIRMED", "CHECKED_IN")
        and other["position_number"] == a["position_number"]
        for other in STORE.lineup_assignments.values()
    ):
        raise api_err("ERR_LINEUP_POSITION_TAKEN", "position_number is held by another active assignment")
    # Constraint: staging capacity (inclusive boundary: reserved == capacity rejects).
    area = staging_or_404(a["staging_area_id"])
    if reserved_slots(area["id"]) >= area["capacity"]:
        raise api_err("ERR_STAGING_CAPACITY_FULL", "Staging area is at capacity")
    # Temporal: expanded closed-window conflict on the same staging area.
    cand_start = _minute_floor(a["arrive_at"]) - STAGING_BUFFER
    cand_end = _minute_floor(a["depart_at"]) + STAGING_BUFFER
    for other in STORE.lineup_assignments.values():
        if (
            other["id"] != a["id"]
            and other["staging_area_id"] == a["staging_area_id"]
            and other["status"] in ("CONFIRMED", "CHECKED_IN")
        ):
            o_start = _minute_floor(other["arrive_at"]) - STAGING_BUFFER
            o_end = _minute_floor(other["depart_at"]) + STAGING_BUFFER
            if cand_start <= o_end and o_start <= cand_end:
                raise api_err(
                    "ERR_STAGING_WINDOW_CONFLICT",
                    "Expanded staging window intersects another active assignment",
                )
    # Temporal: staging-hours containment, re-checked at confirmation.
    _check_within_staging_hours(area, a["arrive_at"], a["depart_at"])
    # Fiscal gate, last.
    if not entry["fee_paid"]:
        raise api_err("ERR_ENTRY_FEE_OUTSTANDING", "The entry fee must be paid before confirmation")
    a["status"] = "CONFIRMED"
    touch(a)
    return respond_object(ser_lineup(a))


def check_in_lineup(uid, role, id):
    a = lineup_or_404(id)
    if a["status"] != "CONFIRMED":
        raise api_err("ERR_INVALID_STATE", "Assignment must be in CONFIRMED to check in")
    parade = parade_or_404(a["parade_id"])
    if parade["status"] != "LINEUP_PUBLISHED":
        raise api_err("ERR_LINEUP_NOT_PUBLISHED", "Check-in requires the lineup published")
    ensure_not_frozen(parade)
    now = db.now()
    if not (a["arrive_at"] <= now <= a["depart_at"]):
        raise api_err("ERR_CHECKIN_WINDOW_NOT_OPEN", "Check-in is outside [arrive_at, depart_at]")
    a["status"] = "CHECKED_IN"
    touch(a)
    return respond_object(ser_lineup(a))


def release_lineup(uid, role, id):
    a = lineup_or_404(id)
    if a["status"] != "CHECKED_IN":
        raise api_err("ERR_INVALID_STATE", "Assignment must be in CHECKED_IN to release")
    a["status"] = "RELEASED"
    touch(a)
    return respond_object(ser_lineup(a))


def no_show_lineup(uid, role, id):
    a = lineup_or_404(id)
    if a["status"] != "CONFIRMED":
        raise api_err("ERR_INVALID_STATE", "Assignment must be in CONFIRMED to mark no-show")
    if not db.now() > a["depart_at"]:
        raise api_err("ERR_CHECKIN_WINDOW_NOT_OPEN", "No-show is only legal after depart_at")
    a["status"] = "NO_SHOW"
    touch(a)
    _cancel_entry_intro_items(a["parade_id"], a["entry_id"])
    return respond_object(ser_lineup(a))


def pull_lineup(uid, role, id):
    a = lineup_or_404(id)
    if a["status"] not in ("TENTATIVE", "CONFIRMED"):
        raise api_err("ERR_INVALID_STATE", "Only TENTATIVE or CONFIRMED assignments can be pulled")
    a["status"] = "PULLED"
    touch(a)
    _cancel_entry_intro_items(a["parade_id"], a["entry_id"])
    return respond_object(ser_lineup(a))


add("/parades/<id>/lineup-assignments", ["POST"], guarded(CA)(create_lineup))
add("/lineup-assignments", ["GET"], guarded(LINEUP_READERS)(list_lineup))
add("/lineup-assignments/<id>", ["GET"], guarded(LINEUP_READERS)(get_lineup))
add("/lineup-assignments/<id>/confirm", ["POST"], guarded(CA)(confirm_lineup))
add("/lineup-assignments/<id>/check-in", ["POST"], guarded(CA)(check_in_lineup))
add("/lineup-assignments/<id>/release", ["POST"], guarded(CA)(release_lineup))
add("/lineup-assignments/<id>/no-show", ["POST"], guarded(CA)(no_show_lineup))
add("/lineup-assignments/<id>/pull", ["POST"], guarded(CA)(pull_lineup))


# --- MarshalAssignment -----------------------------------------------------------

def create_marshal(uid, role, id):
    parade_or_404(id)
    data = body()
    route_segment_id = req_str(data, "route_segment_id")
    marshal_user_id = req_str(data, "marshal_user_id")
    shift_start = req_dt(data, "shift_start")
    shift_end = req_dt(data, "shift_end")
    if not shift_end > shift_start:
        raise api_err("ERR_VALIDATION", "shift_end must be strictly after shift_start")
    segment = STORE.route_segments.get(route_segment_id)
    if segment is None or segment["parade_id"] != id:
        raise api_err("ERR_ROUTE_SEGMENT_NOT_FOUND", "No RouteSegment with the given id in this parade")
    # Half-open overlap rule per marshal across ASSIGNED/CONFIRMED shifts.
    for other in STORE.marshal_assignments.values():
        if (
            other["marshal_user_id"] == marshal_user_id
            and other["status"] in ("ASSIGNED", "CONFIRMED")
            and other["shift_start"] < shift_end
            and shift_start < other["shift_end"]
        ):
            raise api_err(
                "ERR_MARSHAL_WINDOW_OVERLAP",
                "The shift overlaps another ASSIGNED or CONFIRMED shift of the same marshal",
            )
    rec = make_record()
    rec.update(
        {
            "parade_id": id,
            "route_segment_id": route_segment_id,
            "marshal_user_id": marshal_user_id,
            "shift_start": shift_start,
            "shift_end": shift_end,
            "status": "ASSIGNED",
        }
    )
    STORE.marshal_assignments[rec["id"]] = rec
    return respond_object(ser_marshal(rec), 201)


def list_marshals(uid, role):
    items = list(STORE.marshal_assignments.values())
    parade_id = request.args.get("parade_id")
    route_segment_id = request.args.get("route_segment_id")
    marshal_user_id = request.args.get("marshal_user_id")
    status = request.args.get("status")
    if parade_id is not None:
        items = [m for m in items if m["parade_id"] == parade_id]
    if route_segment_id is not None:
        items = [m for m in items if m["route_segment_id"] == route_segment_id]
    if marshal_user_id is not None:
        items = [m for m in items if m["marshal_user_id"] == marshal_user_id]
    if status is not None:
        items = [m for m in items if m["status"] == status]
    return paged(items, ser_marshal)


def get_marshal(uid, role, id):
    return respond_object(ser_marshal(marshal_or_404(id)))


def confirm_marshal(uid, role, id):
    m = marshal_or_404(id)
    require_owner(uid, m["marshal_user_id"])
    if m["status"] != "ASSIGNED":
        raise api_err("ERR_INVALID_STATE", "Assignment must be in ASSIGNED to confirm")
    m["status"] = "CONFIRMED"
    touch(m)
    return respond_object(ser_marshal(m))


def complete_marshal(uid, role, id):
    m = marshal_or_404(id)
    require_owner(uid, m["marshal_user_id"])
    if m["status"] != "CONFIRMED":
        raise api_err("ERR_INVALID_STATE", "Assignment must be in CONFIRMED to complete")
    if not db.now() >= m["shift_end"]:
        raise api_err("ERR_CHECKIN_WINDOW_NOT_OPEN", "Completion is only legal at or after shift_end")
    m["status"] = "COMPLETED"
    touch(m)
    return respond_object(ser_marshal(m))


def no_show_marshal(uid, role, id):
    m = marshal_or_404(id)
    if m["status"] not in ("ASSIGNED", "CONFIRMED"):
        raise api_err("ERR_INVALID_STATE", "Assignment must be in ASSIGNED or CONFIRMED to mark no-show")
    m["status"] = "NO_SHOW"
    touch(m)
    return respond_object(ser_marshal(m))


add("/parades/<id>/marshal-assignments", ["POST"], guarded(CA)(create_marshal))
add("/marshal-assignments", ["GET"], guarded(MARSHAL_READERS)(list_marshals))
add("/marshal-assignments/<id>", ["GET"], guarded(MARSHAL_READERS)(get_marshal))
add("/marshal-assignments/<id>/confirm", ["POST"], guarded(MARSHAL)(confirm_marshal))
add("/marshal-assignments/<id>/complete", ["POST"], guarded(MARSHAL)(complete_marshal))
add("/marshal-assignments/<id>/no-show", ["POST"], guarded(CA)(no_show_marshal))
