import re
from datetime import timedelta

from flask import Blueprint

import calc
import derive
import find
import serialize
import services
import validators as v
from auth import endpoint
from envelope import object_response, paginate
from errors import ApiError
from store import db, new_record, sorted_records, touch

bp = Blueprint("stops", __name__)

STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")
STOP_TYPES = ("SHOW", "REHEARSAL_ONLY")
ROLES = ["CorpsDirector", "TourManager", "MembershipCoordinator", "BusinessManager"]
TRAINER_REHEARSAL_MINUTES = 240
TRAINER_HEAT_INDEX = 95
MINORS_PER_CHAPERONE = 10
MEMBERS_PER_COOK = 40


def _write_transport(record):
    total_cuft, total_lbs, trucks = calc.transport_plan(
        record["uniform_trunks"], record["instrument_cases"], record["prop_units"],
        record["travel_miles_from_previous"])
    record["total_load_cuft"] = total_cuft
    record["total_load_lbs"] = total_lbs
    record["trucks_required"] = trucks
    record["required_travel_minutes"] = calc.travel_feasibility(
        record["travel_miles_from_previous"], record["previous_stop_id"] is not None)


@bp.route("/tour-stops", methods=["POST"])
@endpoint(["TourManager"])
def create_stop():
    body = v.get_body()
    season_id = v.req_str(body, "season_id")
    previous_stop_id = v.opt_str(body, "previous_stop_id")
    stop_type = v.req_enum(body, "stop_type", STOP_TYPES)
    venue_name = v.req_str(body, "venue_name")
    city = v.req_str(body, "city")
    state_code = v.req_str(body, "state_code")
    arrive_raw, arrive_at = v.req_instant(body, "arrive_at")
    depart_raw, depart_at = v.req_instant(body, "depart_at")
    show_raw, show_start_at = v.opt_instant(body, "show_start_at")
    travel_miles = v.req_int(body, "travel_miles_from_previous")
    uniform_trunks = v.req_int(body, "uniform_trunks")
    instrument_cases = v.req_int(body, "instrument_cases")
    prop_units = v.req_int(body, "prop_units")
    truck_count = v.req_int(body, "truck_count")
    rehearsal_minutes = v.req_int(body, "rehearsal_minutes")
    heat_index = v.req_int(body, "heat_index_f")
    v.check(bool(STATE_CODE_RE.match(state_code)), "state_code",
            "must be exactly two uppercase letters")
    v.check(0 <= heat_index <= 140, "heat_index_f", "must be between 0 and 140")
    for field, value in (("uniform_trunks", uniform_trunks),
                         ("instrument_cases", instrument_cases),
                         ("prop_units", prop_units),
                         ("truck_count", truck_count)):
        v.check(value >= 0, field, "must be at least 0")
    # Rung 4 -- depart_at must be later than arrive_at.
    v.date_range(depart_at > arrive_at, "depart_at must be later than arrive_at.")
    # Rung 5 -- conditional fields.
    if stop_type == "SHOW":
        v.conditional(show_start_at is not None,
                      "show_start_at is required when stop_type is SHOW.")
    else:
        v.conditional(show_raw is None,
                      "show_start_at is only permitted when stop_type is SHOW.")
    if previous_stop_id is None:
        v.conditional(travel_miles == 0,
                      "travel_miles_from_previous must be 0 when no predecessor is named.")
    else:
        v.conditional(travel_miles > 0,
                      "travel_miles_from_previous must be greater than 0 when a predecessor is named.")
    # Rung 8 -- season then previous stop.
    find.season(season_id)
    if previous_stop_id is not None:
        find.stop(previous_stop_id)

    record = new_record()
    record.update({
        "season_id": season_id,
        "previous_stop_id": previous_stop_id,
        "stop_type": stop_type,
        "venue_name": venue_name,
        "city": city,
        "state_code": state_code,
        "arrive_at": arrive_raw,
        "depart_at": depart_raw,
        "show_start_at": show_raw,
        "_arrive_at": arrive_at,
        "_depart_at": depart_at,
        "travel_miles_from_previous": travel_miles,
        "uniform_trunks": uniform_trunks,
        "instrument_cases": instrument_cases,
        "prop_units": prop_units,
        "truck_count": truck_count,
        "rehearsal_minutes": rehearsal_minutes,
        "heat_index_f": heat_index,
        "roster_head_count": 0,
        "minor_head_count": 0,
        "required_chaperone_count": 0,
        "required_cook_count": 0,
        "meal_cost_cents": 0,
        "status": "PLANNED",
        "settlement_state": "NONE",
        "cancel_reason": None,
    })
    _write_transport(record)
    db.stops[record["id"]] = record
    return object_response(serialize.stop(record), 201)


@bp.route("/tour-stops/<tour_stop_id>", methods=["GET"])
@endpoint(ROLES)
def get_stop(tour_stop_id):
    return object_response(serialize.stop(find.stop(tour_stop_id)))


@bp.route("/tour-stops", methods=["GET"])
@endpoint(ROLES)
def list_stops():
    season_id = v.arg_str("season_id")
    previous_stop_id = v.arg_str("previous_stop_id")
    stop_type = v.arg_str("stop_type")
    status = v.arg_str("status")
    records = []
    for record in sorted_records(db.stops):
        if season_id is not None and record["season_id"] != season_id:
            continue
        if previous_stop_id is not None and record["previous_stop_id"] != previous_stop_id:
            continue
        if stop_type is not None and record["stop_type"] != stop_type:
            continue
        if status is not None and record["status"] != status:
            continue
        records.append(record)
    return paginate(records, serialize.stop)


def _approved_shifts(stop_id, duty):
    return [s for s in db.staff.values()
            if s["tour_stop_id"] == stop_id and s["duty"] == duty and s["status"] == "APPROVED"]


@bp.route("/tour-stops/<tour_stop_id>/confirm", methods=["POST"])
@endpoint(["TourManager"])
def confirm_stop(tour_stop_id):
    stop = find.stop(tour_stop_id)
    # Rung 20 -- the stop must be PLANNED and its predecessor already locked in.
    if stop["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STOP_STATE", "Only a PLANNED stop may be confirmed.")
    predecessor = None
    if stop["previous_stop_id"] is not None:
        predecessor = db.stops.get(stop["previous_stop_id"])
        if predecessor is None or predecessor["status"] not in ("CONFIRMED", "COMPLETED"):
            raise ApiError("ERR_INVALID_STOP_STATE",
                           "The predecessor stop has not reached CONFIRMED or COMPLETED.")

    # The live touring roster at the instant of confirmation.
    roster = [m for m in derive.season_members(stop["season_id"])
              if m["membership_status"] == "ON_TOUR"]
    roster_head_count = len(roster)
    minor_head_count = len([m for m in roster if m["is_minor"]])
    required_chaperone = calc.ceil_div(minor_head_count, MINORS_PER_CHAPERONE)
    required_cook = calc.ceil_div(roster_head_count, MEMBERS_PER_COOK)

    # Rungs 32, 33, 34 -- member safety and compliance.
    if len(_approved_shifts(stop["id"], "CHAPERONE")) < required_chaperone:
        raise ApiError("ERR_CHAPERONE_COVERAGE_INSUFFICIENT",
                       "Approved chaperone coverage is short for the minors on the roster.")
    if len(_approved_shifts(stop["id"], "COOK")) < required_cook:
        raise ApiError("ERR_COOK_COVERAGE_INSUFFICIENT",
                       "Approved cook coverage is short for the touring roster.")
    trainer_required = (stop["rehearsal_minutes"] >= TRAINER_REHEARSAL_MINUTES
                        or stop["heat_index_f"] >= TRAINER_HEAT_INDEX)
    if trainer_required and len(_approved_shifts(stop["id"], "TRAINER")) < 1:
        raise ApiError("ERR_TRAINER_COVERAGE_REQUIRED",
                       "This stop is strenuous or hot and requires an approved trainer shift.")

    required_minutes = calc.travel_feasibility(
        stop["travel_miles_from_previous"], stop["previous_stop_id"] is not None)
    # Rung 38 -- temporal feasibility.
    if predecessor is not None:
        latest = predecessor["_depart_at"] + timedelta(minutes=required_minutes)
        if latest > stop["_arrive_at"]:
            raise ApiError("ERR_TRAVEL_TIME_INFEASIBLE",
                           "The convoy cannot reach this stop in time.")
    # Rung 55 -- capacity.
    total_cuft, total_lbs, trucks_required = calc.transport_plan(
        stop["uniform_trunks"], stop["instrument_cases"], stop["prop_units"],
        stop["travel_miles_from_previous"])
    if stop["truck_count"] < trucks_required:
        raise ApiError("ERR_INSUFFICIENT_TRUCKS",
                       "truck_count falls below the computed trucks_required.")

    counts = {}
    for member in roster:
        flag = member["dietary_flag"]
        counts[flag] = counts.get(flag, 0) + 1

    stop["roster_head_count"] = roster_head_count
    stop["minor_head_count"] = minor_head_count
    stop["required_chaperone_count"] = required_chaperone
    stop["required_cook_count"] = required_cook
    stop["total_load_cuft"] = total_cuft
    stop["total_load_lbs"] = total_lbs
    stop["trucks_required"] = trucks_required
    stop["required_travel_minutes"] = required_minutes
    stop["meal_cost_cents"] = calc.stop_meal_cost(counts)
    stop["status"] = "CONFIRMED"
    for booking in sorted_records(db.bookings):
        if booking["tour_stop_id"] == stop["id"] and booking["status"] == "HELD":
            booking["status"] = "CONFIRMED"
            touch(booking)
    touch(stop)
    return object_response(serialize.stop(stop))


@bp.route("/tour-stops/<tour_stop_id>/complete", methods=["POST"])
@endpoint(["TourManager"])
def complete_stop(tour_stop_id):
    stop = find.stop(tour_stop_id)
    if stop["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STOP_STATE", "Only a CONFIRMED stop may be completed.")
    # Rung 46 -- the clock must have reached the stop's depart_at.
    if db.clock < stop["_depart_at"]:
        raise ApiError("ERR_STOP_NOT_DEPARTED",
                       "The logical clock has not reached this stop's depart_at.")
    stop["status"] = "COMPLETED"
    if stop["stop_type"] == "SHOW":
        stop["settlement_state"] = "PENDING"
    touch(stop)
    return object_response(serialize.stop(stop))


@bp.route("/tour-stops/<tour_stop_id>/cancel", methods=["POST"])
@endpoint(["CorpsDirector"])
def cancel_stop(tour_stop_id):
    body = v.get_body()
    reason = v.req_str(body, "cancel_reason")
    stop = find.stop(tour_stop_id)
    if stop["status"] not in ("PLANNED", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STOP_STATE",
                       "Only a PLANNED or CONFIRMED stop may be cancelled.")
    services.cancel_stop(stop, reason)
    return object_response(serialize.stop(stop))
