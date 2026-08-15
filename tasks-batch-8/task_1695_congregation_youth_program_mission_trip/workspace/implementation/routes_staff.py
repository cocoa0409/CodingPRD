"""Chaperones, background checks, assignments, itinerary items, lodging."""
from datetime import timedelta

from flask import request

from store import DB
from util import (
    ApiError, success_object, get_body, req_str, opt_str, req_int, req_enum,
    req_datetime, req_date, fmt_clock, parse_date_value, trip_end_instant,
    trip_start_instant,
)
import domain as D
from web import (
    app, PREFIX, caller, require_role, paginate,
    get_program, get_trip, get_chaperone, get_check, get_assignment, get_lodging,
)

TRIP_ASSIGNABLE = ["DRAFT", "REGISTRATION_OPEN", "REGISTRATION_CLOSED", "ROSTER_LOCKED"]


def _chaperone_cleared_through(chaperone_id, end_instant):
    for chk in D.checks_of_chaperone(chaperone_id):
        if chk["status"] == "CLEARED" and chk.get("_expires_dt") is not None \
                and chk["_expires_dt"] >= end_instant:
            return True
    return False


# ---------------------------------------------------------------------------
# Chaperones
# ---------------------------------------------------------------------------

@app.post(f"{PREFIX}/chaperones")
def create_chaperone():
    uid, role = caller()
    body = get_body()
    program_id = req_str(body, "program_id")
    first_name = req_str(body, "first_name")
    last_name = req_str(body, "last_name")
    email = req_str(body, "email")
    phone = req_str(body, "phone")
    require_role(role, ["ProgramDirector"])
    program = get_program(program_id)
    if program["status"] != "OPEN":
        raise ApiError("ERR_PROGRAM_NOT_OPEN", "Program is not OPEN", 409)
    chaperone = {
        "program_id": program_id,
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "phone": phone,
        "current_screening_expires_at": "",
    }
    DB.stamp_created(chaperone)
    DB.chaperones[chaperone["id"]] = chaperone
    return success_object(D.ser_chaperone(chaperone), 201)


@app.get(f"{PREFIX}/chaperones")
def list_chaperones():
    uid, role = caller()
    require_role(role, ["ProgramDirector", "TripLeader"])
    items = list(DB.chaperones.values())
    program_id = request.args.get("program_id")
    if program_id is not None:
        items = [c for c in items if c["program_id"] == program_id]
    return paginate(items, D.ser_chaperone)


@app.get(f"{PREFIX}/chaperones/<cid>")
def read_chaperone(cid):
    uid, role = caller()
    require_role(role, ["ProgramDirector", "TripLeader", "Chaperone"])
    chaperone = get_chaperone(cid)
    if role == "Chaperone" and chaperone["id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Chaperone may read only their own record", 403)
    return success_object(D.ser_chaperone(chaperone))


# ---------------------------------------------------------------------------
# Background checks
# ---------------------------------------------------------------------------

@app.post(f"{PREFIX}/chaperones/<cid>/background-checks")
def create_background_check(cid):
    uid, role = caller()
    body = get_body()
    vendor_reference = opt_str(body, "vendor_reference", "")
    require_role(role, ["ProgramDirector"])
    chaperone = get_chaperone(cid)
    for chk in D.checks_of_chaperone(cid):
        if chk["status"] in ("INITIATED", "SCREENING"):
            raise ApiError("ERR_SCREENING_IN_PROGRESS_EXISTS",
                           "Chaperone already has a check in INITIATED or SCREENING", 409)
    check = {
        "chaperone_id": cid,
        "status": "INITIATED",
        "vendor_reference": vendor_reference,
        "cleared_at": "",
        "expires_at": "",
        "_expires_dt": None,
    }
    DB.stamp_created(check)
    DB.background_checks[check["id"]] = check
    return success_object(D.ser_check(check), 201)


@app.get(f"{PREFIX}/chaperones/<cid>/background-checks")
def list_background_checks(cid):
    uid, role = caller()
    require_role(role, ["ProgramDirector", "TripLeader", "Chaperone"])
    chaperone = get_chaperone(cid)
    if role == "Chaperone" and chaperone["id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Chaperone may read only their own checks", 403)
    return paginate(D.checks_of_chaperone(cid), D.ser_check)


@app.post(f"{PREFIX}/background-checks/<cid>/advance")
def advance_background_check(cid):
    uid, role = caller()
    body = get_body()
    to_status = req_enum(body, "to_status", ["SCREENING", "CLEARED", "FLAGGED"])
    vendor_reference = opt_str(body, "vendor_reference", None)
    require_role(role, ["ProgramDirector"])
    check = get_check(cid)

    reachable = {
        "INITIATED": {"SCREENING"},
        "SCREENING": {"CLEARED", "FLAGGED"},
    }
    if to_status not in reachable.get(check["status"], set()):
        raise ApiError("ERR_CHECK_STATE_FORBIDS_ACTION",
                       f"Cannot advance from {check['status']} to {to_status}", 409)

    if vendor_reference is not None:
        check["vendor_reference"] = vendor_reference

    if to_status == "SCREENING":
        check["status"] = "SCREENING"
        DB.touch("background_checks", check["id"])
    elif to_status == "CLEARED":
        cleared_dt = DB.clock_dt
        expires_dt = cleared_dt + timedelta(days=730)
        check["status"] = "CLEARED"
        check["cleared_at"] = fmt_clock(cleared_dt)
        check["expires_at"] = fmt_clock(expires_dt)
        check["_expires_dt"] = expires_dt
        DB.touch("background_checks", check["id"])
        chaperone = get_chaperone(check["chaperone_id"])
        D.recompute_chaperone_screening(chaperone)
        # A mutation of the CLEARED-check set ripples into trip ratio rollups
        affected = {a["trip_id"] for a in DB.chaperone_assignments.values()
                    if a["chaperone_id"] == check["chaperone_id"]
                    and a["status"] in ("PROPOSED", "CONFIRMED")}
        for tid in affected:
            trip = DB.trips.get(tid)
            if trip is not None:
                D.recompute_trip(trip)
    else:  # FLAGGED
        check["status"] = "FLAGGED"
        DB.touch("background_checks", check["id"])
        affected_trips = set()
        for a in DB.chaperone_assignments.values():
            if a["chaperone_id"] == check["chaperone_id"] and a["status"] in ("PROPOSED", "CONFIRMED"):
                a["status"] = "REMOVED"
                a["removal_reason"] = "AUTO_SCREENING"
                DB.touch("chaperone_assignments", a["id"])
                affected_trips.add(a["trip_id"])
        for tid in affected_trips:
            trip = DB.trips.get(tid)
            if trip is not None:
                D.recompute_trip(trip)
        chaperone = get_chaperone(check["chaperone_id"])
        D.recompute_chaperone_screening(chaperone)
    return success_object(D.ser_check(check))


# ---------------------------------------------------------------------------
# Chaperone assignments
# ---------------------------------------------------------------------------

@app.post(f"{PREFIX}/chaperone-assignments")
def create_assignment():
    uid, role = caller()
    body = get_body()
    trip_id = req_str(body, "trip_id")
    chaperone_id = req_str(body, "chaperone_id")
    assign_role = req_enum(body, "role", D.ASSIGNMENT_ROLES)
    require_role(role, ["ProgramDirector", "TripLeader"])
    trip = get_trip(trip_id)
    chaperone = get_chaperone(chaperone_id)
    if trip["status"] not in TRIP_ASSIGNABLE:
        raise ApiError("ERR_TRIP_STATE_FORBIDS_ACTION",
                       "Trip state does not admit new assignments", 409)
    # SAFETY: screening valid through the trip end instant (boundary inclusive)
    end_inst = trip_end_instant(trip["end_date"])
    if not _chaperone_cleared_through(chaperone_id, end_inst):
        raise ApiError("ERR_SCREENING_NOT_VALID_THROUGH_TRIP",
                       "Chaperone has no CLEARED check valid through the trip end", 422)
    # CONSTRAINTS
    if assign_role == "LEAD":
        for a in D.assignments_of_trip(trip_id):
            if a["role"] == "LEAD" and a["status"] in ("PROPOSED", "CONFIRMED"):
                raise ApiError("ERR_DUPLICATE_LEAD_CHAPERONE",
                               "Trip already has a LEAD assignment", 409)
    for a in D.assignments_of_trip(trip_id):
        if a["chaperone_id"] == chaperone_id and a["status"] in ("PROPOSED", "CONFIRMED"):
            raise ApiError("ERR_DUPLICATE_ASSIGNMENT",
                           "A non-terminal assignment already exists for this trip and chaperone", 409)
    this_start = parse_date_value(trip["start_date"])
    this_end = parse_date_value(trip["end_date"])
    for a in DB.chaperone_assignments.values():
        if a["chaperone_id"] != chaperone_id or a["status"] not in ("PROPOSED", "CONFIRMED"):
            continue
        if a["trip_id"] == trip_id:
            continue
        other = DB.trips.get(a["trip_id"])
        if other is None:
            continue
        other_start = parse_date_value(other["start_date"])
        other_end = parse_date_value(other["end_date"])
        # closed-interval intersection; shared boundary dates DO conflict
        if other_start <= this_end and this_start <= other_end:
            raise ApiError("ERR_CHAPERONE_TRIP_OVERLAP",
                           "Chaperone is already assigned to an overlapping trip", 409)

    assignment = {
        "trip_id": trip_id,
        "chaperone_id": chaperone_id,
        "role": assign_role,
        "status": "PROPOSED",
        "removal_reason": "",
    }
    DB.stamp_created(assignment)
    DB.chaperone_assignments[assignment["id"]] = assignment
    return success_object(D.ser_assignment(assignment), 201)


@app.get(f"{PREFIX}/chaperone-assignments")
def list_assignments():
    uid, role = caller()
    require_role(role, ["ProgramDirector", "TripLeader", "Chaperone"])
    items = list(DB.chaperone_assignments.values())
    if role == "Chaperone":
        items = [a for a in items if a["chaperone_id"] == uid]
    trip_id = request.args.get("trip_id")
    chaperone_id = request.args.get("chaperone_id")
    status = request.args.get("status")
    if trip_id is not None:
        items = [a for a in items if a["trip_id"] == trip_id]
    if chaperone_id is not None:
        items = [a for a in items if a["chaperone_id"] == chaperone_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return paginate(items, D.ser_assignment)


@app.get(f"{PREFIX}/chaperone-assignments/<aid>")
def read_assignment(aid):
    uid, role = caller()
    require_role(role, ["ProgramDirector", "TripLeader", "Chaperone"])
    assignment = get_assignment(aid)
    if role == "Chaperone" and assignment["chaperone_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Chaperone may read only their own assignments", 403)
    return success_object(D.ser_assignment(assignment))


@app.post(f"{PREFIX}/chaperone-assignments/<aid>/respond")
def respond_assignment(aid):
    uid, role = caller()
    body = get_body()
    decision = req_enum(body, "decision", ["ACCEPT", "DECLINE"])
    require_role(role, ["Chaperone"])
    assignment = get_assignment(aid)
    if assignment["chaperone_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Only the assigned chaperone may respond", 403)
    if assignment["status"] != "PROPOSED":
        raise ApiError("ERR_ASSIGNMENT_STATE_FORBIDS_ACTION", "Assignment is not PROPOSED", 409)
    if decision == "ACCEPT":
        assignment["status"] = "CONFIRMED"
        DB.touch("chaperone_assignments", assignment["id"])
        trip = DB.trips.get(assignment["trip_id"])
        if trip is not None:
            D.recompute_trip(trip)
    else:
        assignment["status"] = "DECLINED"
        DB.touch("chaperone_assignments", assignment["id"])
    return success_object(D.ser_assignment(assignment))


@app.post(f"{PREFIX}/chaperone-assignments/<aid>/remove")
def remove_assignment(aid):
    uid, role = caller()
    require_role(role, ["ProgramDirector", "TripLeader"])
    assignment = get_assignment(aid)
    if assignment["status"] not in ("PROPOSED", "CONFIRMED"):
        raise ApiError("ERR_ASSIGNMENT_STATE_FORBIDS_ACTION",
                       "Assignment is not PROPOSED or CONFIRMED", 409)
    assignment["status"] = "REMOVED"
    assignment["removal_reason"] = "MANUAL"
    DB.touch("chaperone_assignments", assignment["id"])
    trip = DB.trips.get(assignment["trip_id"])
    if trip is not None:
        D.recompute_trip(trip)
    return success_object(D.ser_assignment(assignment))


# ---------------------------------------------------------------------------
# Itinerary items
# ---------------------------------------------------------------------------

VEHICLE_BUFFER = timedelta(minutes=45)


@app.post(f"{PREFIX}/trips/<tid>/itinerary-items")
def create_itinerary_item(tid):
    uid, role = caller()
    body = get_body()
    segment_type = req_enum(body, "segment_type", D.SEGMENT_TYPES)
    title = req_str(body, "title")
    start_raw, start_dt = req_datetime(body, "start_at")
    end_raw, end_dt = req_datetime(body, "end_at")
    location = opt_str(body, "location", "")
    if segment_type == "TRAVEL":
        vehicle_code = req_str(body, "vehicle_code")
        if not vehicle_code:
            raise ApiError("ERR_INVALID_REQUEST",
                           "vehicle_code is required for TRAVEL segments", 400)
    else:
        vehicle_code = opt_str(body, "vehicle_code", "")
    if end_dt <= start_dt:
        raise ApiError("ERR_INVALID_DATE_RANGE", "end_at must be strictly after start_at", 400)
    require_role(role, ["TripLeader"])
    trip = get_trip(tid)
    if trip["status"] not in TRIP_ASSIGNABLE:
        raise ApiError("ERR_TRIP_STATE_FORBIDS_ACTION",
                       "Itinerary items may not be added once the trip is underway", 409)
    window_start = trip_start_instant(trip["start_date"])
    window_end = trip_end_instant(trip["end_date"])
    if start_dt < window_start or start_dt >= window_end or end_dt >= window_end:
        raise ApiError("ERR_ITINERARY_OUTSIDE_TRIP_WINDOW",
                       "Item times must sit inside the trip window", 422)
    if segment_type == "TRAVEL":
        for item in DB.itinerary_items.values():
            if item["trip_id"] != tid or item["segment_type"] != "TRAVEL":
                continue
            if item["vehicle_code"] != vehicle_code:
                continue
            if not (start_dt >= item["_end_dt"] + VEHICLE_BUFFER
                    or end_dt <= item["_start_dt"] - VEHICLE_BUFFER):
                raise ApiError("ERR_VEHICLE_SCHEDULE_CONFLICT",
                               "Vehicle requires a 45-minute turnaround gap", 409)
    item = {
        "trip_id": tid,
        "segment_type": segment_type,
        "title": title,
        "start_at": fmt_clock(start_dt),
        "end_at": fmt_clock(end_dt),
        "location": location,
        "vehicle_code": vehicle_code,
        "_start_dt": start_dt,
        "_end_dt": end_dt,
    }
    DB.stamp_created(item)
    DB.itinerary_items[item["id"]] = item
    return success_object(D.ser_itinerary_item(item), 201)


@app.get(f"{PREFIX}/trips/<tid>/itinerary-items")
def list_itinerary_items(tid):
    uid, role = caller()
    require_role(role, ["ProgramDirector", "TripLeader", "Chaperone"])
    trip = get_trip(tid)
    items = [i for i in DB.itinerary_items.values() if i["trip_id"] == tid]
    return paginate(items, D.ser_itinerary_item)


# ---------------------------------------------------------------------------
# Lodging reservations
# ---------------------------------------------------------------------------

@app.post(f"{PREFIX}/trips/<tid>/lodging-reservations")
def create_lodging(tid):
    uid, role = caller()
    body = get_body()
    site_name = req_str(body, "site_name")
    room_code = req_str(body, "room_code")
    in_raw, in_d = req_date(body, "check_in_date")
    out_raw, out_d = req_date(body, "check_out_date")
    room_capacity = req_int(body, "room_capacity", min_value=1)
    cost_cents = req_int(body, "cost_cents", min_value=0)
    if out_d <= in_d:
        raise ApiError("ERR_INVALID_DATE_RANGE",
                       "check_out_date must be strictly after check_in_date", 400)
    require_role(role, ["TripLeader"])
    trip = get_trip(tid)
    if trip["status"] not in D.TRIP_PRE_LOCK:
        raise ApiError("ERR_TRIP_STATE_FORBIDS_ACTION",
                       "Lodging is frozen from ROSTER_LOCKED onward", 409)
    for res in DB.lodging_reservations.values():
        if res["trip_id"] != tid or res["status"] != "CONFIRMED":
            continue
        if res["site_name"] != site_name or res["room_code"] != room_code:
            continue
        if in_raw < res["check_out_date"] and res["check_in_date"] < out_raw:
            raise ApiError("ERR_ROOM_ALREADY_BOOKED",
                           "Room stay interval overlaps an existing CONFIRMED reservation", 409)
    reservation = {
        "trip_id": tid,
        "site_name": site_name,
        "room_code": room_code,
        "check_in_date": in_raw,
        "check_out_date": out_raw,
        "room_capacity": room_capacity,
        "cost_cents": cost_cents,
        "status": "CONFIRMED",
    }
    DB.stamp_created(reservation)
    DB.lodging_reservations[reservation["id"]] = reservation
    D.recompute_trip(trip)
    D.recompute_provisional_shares(trip)
    return success_object(D.ser_lodging(reservation), 201)


@app.get(f"{PREFIX}/trips/<tid>/lodging-reservations")
def list_lodging(tid):
    uid, role = caller()
    require_role(role, ["ProgramDirector", "TripLeader"])
    trip = get_trip(tid)
    items = [r for r in DB.lodging_reservations.values() if r["trip_id"] == tid]
    return paginate(items, D.ser_lodging)


@app.post(f"{PREFIX}/lodging-reservations/<lid>/cancel")
def cancel_lodging(lid):
    uid, role = caller()
    require_role(role, ["TripLeader"])
    reservation = get_lodging(lid)
    if reservation["status"] != "CONFIRMED":
        raise ApiError("ERR_LODGING_STATE_FORBIDS_ACTION", "Reservation is not CONFIRMED", 409)
    trip = get_trip(reservation["trip_id"])
    if trip["status"] not in D.TRIP_PRE_LOCK:
        raise ApiError("ERR_TRIP_STATE_FORBIDS_ACTION",
                       "Lodging is frozen from ROSTER_LOCKED onward", 409)
    reservation["status"] = "CANCELLED"
    DB.touch("lodging_reservations", reservation["id"])
    D.recompute_trip(trip)
    D.recompute_provisional_shares(trip)
    return success_object(D.ser_lodging(reservation))
