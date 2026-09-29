"""Transport segment and manifest entry endpoints."""

from flask import Blueprint

import calc
import cascades
import derive
import serializers
from auth import ALL_DMC_ROLES, ROLE_OPS_COORDINATOR, endpoint
from common import (apply_filters, manifest_entry_or_404, program_or_404, respond_list,
                    segment_or_404)
from envelope import created, ok
from errors import fail
from store import clock_now, day_end, db, new_row, plus_minutes, touch
from validation import (body, opt_bool, opt_int, ref_id, req_dt, req_enum, req_int,
                        req_str, strictly_after)

bp = Blueprint("transport", __name__)

SEGMENT_TYPES = ("ARRIVAL_TRANSFER", "DEPARTURE_TRANSFER", "SHUTTLE_LOOP",
                 "DINE_AROUND_LEG")
SEGMENT_STATUSES = ("SCHEDULED", "DEPARTED", "CANCELLED")
ENTRY_STATUSES = ("ASSIGNED", "CHECKED_IN", "RELEASED", "NO_SHOW")


def _check_manifest_gates(segment, seat_count, mobility_assist, guest_ref,
                          exclude_entry_id=None):
    if mobility_assist and not segment["wheelchair_accessible"]:
        fail("ERR_ACCESSIBILITY_UNMET",
             "The segment's vehicle is not wheelchair accessible.")
    booked = derive.booked_seat_count(segment["id"])
    if exclude_entry_id is not None:
        entry = db.manifest_entries.get(exclude_entry_id)
        if entry is not None and entry["segment_id"] == segment["id"] \
                and entry["status"] in derive.SEAT_OCCUPYING_STATUSES:
            booked -= int(entry["seat_count"])
    if booked + int(seat_count) > int(segment["seat_capacity"]):
        fail("ERR_SEGMENT_CAPACITY_EXCEEDED",
             "The vehicle does not have enough seats left.")
    for entry in derive.entries_of_segment(segment["id"]):
        if entry["id"] == exclude_entry_id:
            continue
        if entry["status"] in derive.SEAT_OCCUPYING_STATUSES \
                and entry["guest_ref"] == guest_ref:
            fail("ERR_DUPLICATE_MANIFEST_ENTRY",
                 "That guest_ref is already manifested on this segment.")


# --------------------------------------------------------------------------
# transport segments
# --------------------------------------------------------------------------

@bp.post("/dmc/transport-segments")
@endpoint((ROLE_OPS_COORDINATOR,))
def create_segment():
    data = body()
    program = None
    program_ref = ref_id(data, "program_id")
    if program_ref is not None:
        program = program_or_404(program_ref)

    program_id = req_str(data, "program_id", min_len=1)
    segment_type = req_enum(data, "segment_type", SEGMENT_TYPES)
    vehicle_code = req_str(data, "vehicle_code", min_len=1)
    origin = req_str(data, "origin", min_len=1)
    destination = req_str(data, "destination", min_len=1)
    depart_at = req_dt(data, "depart_at")
    arrive_at = req_dt(data, "arrive_at")
    strictly_after(arrive_at, depart_at, "arrive_at", "depart_at")
    seat_capacity = req_int(data, "seat_capacity", minimum=1)
    wheelchair_accessible = opt_bool(data, "wheelchair_accessible", default=False)
    if wheelchair_accessible is None:
        wheelchair_accessible = False

    if depart_at < program["arrival_date"] or arrive_at > day_end(program["departure_date"]):
        fail("ERR_ELEMENT_OUTSIDE_PROGRAM_WINDOW",
             "The movement does not sit inside the programme window.")

    row = new_row(
        program_id=program_id,
        segment_type=segment_type,
        vehicle_code=vehicle_code,
        origin=origin,
        destination=destination,
        depart_at=depart_at,
        arrive_at=arrive_at,
        seat_capacity=seat_capacity,
        wheelchair_accessible=wheelchair_accessible,
        status="SCHEDULED",
        departed_at=None,
    )
    db.segments[row["id"]] = row
    return created(serializers.segment(row))


@bp.get("/dmc/transport-segments/<segment_id>")
@endpoint(ALL_DMC_ROLES)
def read_segment(segment_id):
    return ok(serializers.segment(segment_or_404(segment_id)))


@bp.get("/dmc/transport-segments")
@endpoint(ALL_DMC_ROLES)
def list_segments():
    rows = apply_filters(list(db.segments.values()), [
        ("program_id", "program_id", None),
        ("status", "status", SEGMENT_STATUSES),
    ])
    return respond_list(rows, serializers.segment)


@bp.post("/dmc/transport-segments/<segment_id>/depart")
@endpoint((ROLE_OPS_COORDINATOR,))
def depart_segment(segment_id):
    segment = segment_or_404(segment_id)
    if segment["status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE_TRANSITION", "depart requires status SCHEDULED.")
    program = db.programs.get(segment["program_id"])
    if program is None or program["execution_status"] != "IN_EXECUTION":
        fail("ERR_PROGRAM_NOT_IN_EXECUTION", "The programme is not IN_EXECUTION.")
    if clock_now() < segment["depart_at"]:
        fail("ERR_SEGMENT_NOT_DUE", "The movement is not due to depart yet.")
    if derive.booked_seat_count(segment_id) < 1:
        fail("ERR_EMPTY_MANIFEST", "The manifest is empty.")

    segment["status"] = "DEPARTED"
    segment["departed_at"] = clock_now()
    for entry in derive.entries_of_segment(segment_id):
        if entry["status"] == "ASSIGNED":
            entry["status"] = "NO_SHOW"
            touch(entry)
    for assignment in derive.assignments_of_segment(segment_id):
        if assignment["status"] == "CHECKED_IN":
            cascades.complete_assignment(assignment)
    touch(segment)
    return ok(serializers.segment(segment))


@bp.post("/dmc/transport-segments/<segment_id>/cancel")
@endpoint((ROLE_OPS_COORDINATOR,))
def cancel_segment(segment_id):
    segment = segment_or_404(segment_id)
    body()
    if segment["status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE_TRANSITION", "cancel requires status SCHEDULED.")
    program = db.programs.get(segment["program_id"])
    cascades.cancel_segment(segment, program)
    return ok(serializers.segment(segment))


# --------------------------------------------------------------------------
# manifest entries
# --------------------------------------------------------------------------

@bp.post("/dmc/manifest-entries")
@endpoint((ROLE_OPS_COORDINATOR,))
def create_manifest_entry():
    data = body()
    segment = None
    segment_ref = ref_id(data, "segment_id")
    if segment_ref is not None:
        segment = segment_or_404(segment_ref)

    segment_id = req_str(data, "segment_id", min_len=1)
    guest_ref = req_str(data, "guest_ref", min_len=1)
    guest_name = req_str(data, "guest_name", min_len=1)
    seat_count = opt_int(data, "seat_count", default=1, minimum=1)
    if seat_count is None:
        seat_count = 1
    mobility_assist = opt_bool(data, "mobility_assist", default=False)
    if mobility_assist is None:
        mobility_assist = False

    _check_manifest_gates(segment, seat_count, mobility_assist, guest_ref)

    row = new_row(
        segment_id=segment_id,
        guest_ref=guest_ref,
        guest_name=guest_name,
        seat_count=seat_count,
        mobility_assist=mobility_assist,
        status="ASSIGNED",
        move_count=0,
    )
    db.manifest_entries[row["id"]] = row
    return created(serializers.manifest_entry(row))


@bp.get("/dmc/manifest-entries/<manifest_entry_id>")
@endpoint(ALL_DMC_ROLES)
def read_manifest_entry(manifest_entry_id):
    return ok(serializers.manifest_entry(manifest_entry_or_404(manifest_entry_id)))


@bp.get("/dmc/manifest-entries")
@endpoint(ALL_DMC_ROLES)
def list_manifest_entries():
    rows = apply_filters(list(db.manifest_entries.values()), [
        ("segment_id", "segment_id", None),
        ("status", "status", ENTRY_STATUSES),
    ])
    return respond_list(rows, serializers.manifest_entry)


@bp.post("/dmc/manifest-entries/<manifest_entry_id>/move")
@endpoint((ROLE_OPS_COORDINATOR,))
def move_manifest_entry(manifest_entry_id):
    entry = manifest_entry_or_404(manifest_entry_id)
    data = body()
    target = None
    target_ref = ref_id(data, "target_segment_id")
    if target_ref is not None:
        target = segment_or_404(target_ref)
    target_segment_id = req_str(data, "target_segment_id", min_len=1)
    if target_segment_id == entry["segment_id"]:
        fail("ERR_INVALID_REQUEST",
             "target_segment_id must differ from the entry's current segment.")

    source = db.segments.get(entry["segment_id"])
    if entry["status"] != "ASSIGNED":
        fail("ERR_INVALID_STATE_TRANSITION", "move requires entry status ASSIGNED.")
    if source is None or source["status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE_TRANSITION", "The source segment is not SCHEDULED.")
    if target["status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE_TRANSITION", "The target segment is not SCHEDULED.")

    _check_manifest_gates(target, entry["seat_count"], entry["mobility_assist"],
                          entry["guest_ref"], exclude_entry_id=entry["id"])

    if target["program_id"] != source["program_id"]:
        fail("ERR_SEGMENT_PROGRAM_MISMATCH",
             "The target segment belongs to a different programme.")

    entry["segment_id"] = target_segment_id
    entry["move_count"] = int(entry["move_count"]) + 1
    touch(entry)
    return ok(serializers.manifest_entry(entry))


@bp.post("/dmc/manifest-entries/<manifest_entry_id>/check-in")
@endpoint((ROLE_OPS_COORDINATOR,))
def check_in_manifest_entry(manifest_entry_id):
    entry = manifest_entry_or_404(manifest_entry_id)
    if entry["status"] != "ASSIGNED":
        fail("ERR_INVALID_STATE_TRANSITION", "check-in requires entry status ASSIGNED.")
    segment = db.segments.get(entry["segment_id"])
    if segment is None or segment["status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE_TRANSITION", "The segment is not SCHEDULED.")
    program = db.programs.get(segment["program_id"])
    if program is None or program["execution_status"] != "IN_EXECUTION":
        fail("ERR_PROGRAM_NOT_IN_EXECUTION", "The programme is not IN_EXECUTION.")
    window_opens = plus_minutes(segment["depart_at"], -calc.MANIFEST_CHECKIN_LEAD_MINUTES)
    if clock_now() < window_opens:
        fail("ERR_CHECKIN_WINDOW_NOT_OPEN", "Curb-side check-in has not opened yet.")

    entry["status"] = "CHECKED_IN"
    touch(entry)
    return ok(serializers.manifest_entry(entry))
