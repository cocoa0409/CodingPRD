"""Excursion departures: scheduling, allocation, tender waves and operations."""

from flask import Blueprint

from db import db
from errors import fail
from middleware import MANAGER, PORT_AGENT, endpoint
from response import list_response, object_response
from routes import API_PREFIX
from serializers import departure_json
from services.allocation import bookings_of, recompute_seats
from services.cascades import (cancel_departure, complete_departure, dispatch_departure,
                               materialize_departure)
from services.occupancy import check_congestion
from services.tender import attach_wave, release_wave, select_wave
from services.timing import recompute_projections
from validation import (departure_or_404, excursion_or_404, f, meeting_point_or_404,
                        paginate, pagination, port_call_or_404, query_values,
                        validate_body)

bp = Blueprint("departures", __name__)

DEPARTURE_STATUSES = ("SCHEDULED", "SELLING", "CLOSED", "OPERATING", "COMPLETED",
                      "CANCELLED_WEATHER", "CANCELLED_OPERATIONAL")
CANCEL_CAUSES = ("WEATHER", "OPERATIONAL")
OPERATIONS = ("DISPATCH", "COMPLETE")
REBALANCEABLE = ("SCHEDULED", "SELLING", "CLOSED")

DEPARTURE_CREATE = [
    f("excursion_id", "string", required=True),
    f("port_call_id", "string", required=True),
    f("meeting_point_id", "string", required=True),
    f("meeting_time_utc", "instant", required=True),
    f("dispatch_dwell_minutes", "int", required=True, lo=5, hi=120),
    f("total_capacity", "int", required=True, lo=1, hi=500),
    f("precruise_allocation", "int", required=True, lo=0),
    f("onboard_allocation", "int", required=True, lo=0),
]

ALLOCATION_REBALANCE = [
    f("expected_departure_version", "int", required=True, lo=0),
    f("precruise_allocation", "int", required=True, lo=0),
    f("onboard_allocation", "int", required=True, lo=0),
    f("total_capacity", "int", lo=1, hi=500),
]

RESCHEDULE = [
    f("meeting_time_utc", "instant", required=True),
    f("dispatch_dwell_minutes", "int", lo=5, hi=120),
]

CANCEL = [
    f("cause", "enum", required=True, enum=CANCEL_CAUSES),
    f("offer_alternative", "bool"),
    f("note", "string"),
]

OPERATION = [
    f("action", "enum", required=True, enum=OPERATIONS),
    f("actual_return_utc", "instant"),
]


@bp.post(API_PREFIX + "/departures")
@endpoint(MANAGER)
def create_departure(caller):
    body = validate_body(DEPARTURE_CREATE)
    excursion = excursion_or_404(body["excursion_id"])
    call = port_call_or_404(body["port_call_id"])
    meeting_point = meeting_point_or_404(body["meeting_point_id"])

    meeting_time = body["meeting_time_utc"]
    if not (call["arrival_utc"] <= meeting_time <= call["all_aboard_utc"]):
        fail("ERR_MEETING_TIME_OUTSIDE_CALL",
             "meeting_time_utc must lie inside the port call's published window")

    check_congestion(meeting_point, meeting_time, body["dispatch_dwell_minutes"])

    if body["precruise_allocation"] + body["onboard_allocation"] != body["total_capacity"]:
        fail("ERR_ALLOCATION_MISMATCH",
             "precruise_allocation and onboard_allocation must sum to total_capacity")

    row = db.insert("departures", {
        "excursion_id": excursion["id"],
        "port_call_id": call["id"],
        "meeting_point_id": meeting_point["id"],
        "tender_wave_id": None,
        "meeting_time_utc": meeting_time,
        "dispatch_dwell_minutes": body["dispatch_dwell_minutes"],
        "total_capacity": body["total_capacity"],
        "precruise_allocation": body["precruise_allocation"],
        "onboard_allocation": body["onboard_allocation"],
        "precruise_sold_seats": 0,
        "onboard_sold_seats": 0,
        "seats_available_total": body["total_capacity"],
        "effective_precruise_available": 0,
        "effective_onboard_available": 0,
        "status": "SCHEDULED",
        "cancellation_cause": None,
        "return_guarantee_eligible": False,
        "actual_return_utc": None,
        "forgone_gross_ticket_cents": 0,
    })
    recompute_projections(row)
    if excursion["catalog_status"] == "PUBLISHED" and call["status"] == "OPEN_FOR_SALE":
        row["status"] = "SELLING"
        row["return_guarantee_eligible"] = bool(
            excursion["return_guarantee"] and row["timing_risk_band_scheduled"] != "RED")
    recompute_seats(row)
    return object_response(departure_json(row), 201)


@bp.get(API_PREFIX + "/departures/<departure_id>")
@endpoint()
def read_departure(caller, departure_id):
    departure = departure_or_404(departure_id)
    materialize_departure(departure)
    return object_response(departure_json(departure))


@bp.get(API_PREFIX + "/departures")
@endpoint()
def list_departures(caller):
    limit, offset = pagination()
    filters = query_values([
        f("excursion_id", "string"),
        f("port_call_id", "string"),
        f("meeting_point_id", "string"),
        f("tender_wave_id", "string"),
        f("status", "enum", enum=DEPARTURE_STATUSES),
    ])
    for departure in db.ordered("departures"):
        materialize_departure(departure)
    rows = db.ordered("departures")
    for key in ("excursion_id", "port_call_id", "meeting_point_id", "tender_wave_id", "status"):
        if key in filters:
            rows = [r for r in rows if r.get(key) == filters[key]]
    page, total = paginate(rows, limit, offset)
    return list_response([departure_json(r) for r in page], limit, offset, total)


@bp.post(API_PREFIX + "/departures/<departure_id>/allocation")
@endpoint(MANAGER)
def rebalance_allocation(caller, departure_id):
    body = validate_body(ALLOCATION_REBALANCE)
    departure = departure_or_404(departure_id)
    if body["expected_departure_version"] != departure["version"]:
        fail("ERR_STALE_DEPARTURE_VERSION", "the departure has been modified since it was read")

    materialize_departure(departure)
    if departure["status"] not in REBALANCEABLE:
        fail("ERR_INVALID_DEPARTURE_STATE",
             "a %s departure may not be rebalanced" % departure["status"])

    total_capacity = body.get("total_capacity", departure["total_capacity"])
    if body["precruise_allocation"] + body["onboard_allocation"] != total_capacity:
        fail("ERR_ALLOCATION_MISMATCH",
             "precruise_allocation and onboard_allocation must sum to total_capacity")
    if (body["precruise_allocation"] < departure["precruise_sold_seats"]
            or body["onboard_allocation"] < departure["onboard_sold_seats"]):
        fail("ERR_ALLOCATION_BELOW_SOLD", "a bucket may not fall below the seats already sold")

    departure["total_capacity"] = total_capacity
    departure["precruise_allocation"] = body["precruise_allocation"]
    departure["onboard_allocation"] = body["onboard_allocation"]
    recompute_projections(departure)
    recompute_seats(departure)
    db.touch(departure)
    return object_response(departure_json(departure))


@bp.post(API_PREFIX + "/departures/<departure_id>/tender-assignment")
@endpoint(PORT_AGENT, MANAGER)
def assign_tender_wave(caller, departure_id):
    validate_body([])
    departure = departure_or_404(departure_id)
    materialize_departure(departure)
    if departure["status"] not in REBALANCEABLE:
        fail("ERR_INVALID_DEPARTURE_STATE",
             "a %s departure may not be assigned a tender wave" % departure["status"])

    winner = select_wave(departure)
    if winner is None:
        fail("ERR_NO_ELIGIBLE_TENDER_WAVE", "no eligible tender wave can carry this departure")

    release_wave(departure)
    attach_wave(departure, winner)
    recompute_projections(departure)
    recompute_seats(departure)
    db.touch(departure)
    return object_response(departure_json(departure))


@bp.post(API_PREFIX + "/departures/<departure_id>/reschedule-meeting")
@endpoint(MANAGER)
def reschedule_meeting(caller, departure_id):
    body = validate_body(RESCHEDULE)
    departure = departure_or_404(departure_id)
    materialize_departure(departure)
    if departure["status"] not in ("SCHEDULED", "SELLING"):
        fail("ERR_INVALID_DEPARTURE_STATE",
             "a %s departure may not be rescheduled" % departure["status"])

    call = db.port_calls.get(departure["port_call_id"])
    meeting_time = body["meeting_time_utc"]
    if call is not None and not (call["arrival_utc"] <= meeting_time <= call["all_aboard_utc"]):
        fail("ERR_MEETING_TIME_OUTSIDE_CALL",
             "meeting_time_utc must lie inside the port call's published window")

    dwell = body.get("dispatch_dwell_minutes", departure["dispatch_dwell_minutes"])
    meeting_point = db.meeting_points.get(departure["meeting_point_id"])
    if meeting_point is not None:
        check_congestion(meeting_point, meeting_time, dwell, exclude_departure_id=departure["id"])

    departure["meeting_time_utc"] = meeting_time
    departure["dispatch_dwell_minutes"] = dwell

    wave_id = departure.get("tender_wave_id")
    if wave_id:
        wave = db.tender_waves.get(wave_id)
        if wave is None or wave["window_end_utc"] > meeting_time:
            release_wave(departure)

    recompute_projections(departure)
    recompute_seats(departure)
    db.touch(departure)
    return object_response(departure_json(departure))


@bp.post(API_PREFIX + "/departures/<departure_id>/cancel")
@endpoint(MANAGER)
def cancel(caller, departure_id):
    body = validate_body(CANCEL)
    departure = departure_or_404(departure_id)
    materialize_departure(departure)
    if departure["status"] not in REBALANCEABLE:
        fail("ERR_INVALID_DEPARTURE_STATE",
             "a %s departure may not be cancelled" % departure["status"])
    cancel_departure(departure, body["cause"], bool(body.get("offer_alternative")))
    return object_response(departure_json(departure))


@bp.post(API_PREFIX + "/departures/<departure_id>/operations")
@endpoint(PORT_AGENT)
def operations(caller, departure_id):
    body = validate_body(OPERATION)
    departure = departure_or_404(departure_id)
    action = body["action"]

    if action == "COMPLETE":
        actual_return = body.get("actual_return_utc")
        if actual_return is None:
            fail("ERR_VALIDATION", "actual_return_utc is required to complete a departure")
        if actual_return < departure["meeting_time_utc"] or actual_return > db.now():
            fail("ERR_INVALID_TIME_WINDOW",
                 "actual_return_utc must fall between the meeting time and the clock")

    materialize_departure(departure)

    if action == "DISPATCH":
        if departure["status"] != "CLOSED":
            fail("ERR_INVALID_DEPARTURE_STATE",
                 "a %s departure may not be dispatched" % departure["status"])
        call = db.port_calls.get(departure["port_call_id"])
        if call is None or call["status"] != "IN_PORT":
            fail("ERR_INVALID_DEPARTURE_STATE", "the owning port call is not IN_PORT")
        if not any(b["fulfillment_status"] == "CHECKED_IN" for b in bookings_of(departure["id"])):
            fail("ERR_INVALID_DEPARTURE_STATE", "no guest has checked in for this departure")
        if departure["timing_risk_band_actual"] == "RED":
            fail("ERR_TIMING_RISK_RED", "the projected return leaves no slack before all-aboard")
        port = db.ports.get(call["port_id"])
        if port is not None and port["docking_mode"] == "TENDER" and not departure.get("tender_wave_id"):
            fail("ERR_NO_ELIGIBLE_TENDER_WAVE",
                 "a TENDER port departure needs an assigned tender wave before dispatch")
        dispatch_departure(departure)
    else:  # COMPLETE
        if departure["status"] != "OPERATING":
            fail("ERR_INVALID_DEPARTURE_STATE",
                 "a %s departure may not be completed" % departure["status"])
        complete_departure(departure, body["actual_return_utc"])

    return object_response(departure_json(departure))
