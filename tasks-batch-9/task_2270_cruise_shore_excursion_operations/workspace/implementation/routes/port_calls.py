"""Port calls, their lifecycle transitions, arrival delays and tender waves."""

from flask import Blueprint

from db import db
from errors import fail
from middleware import MANAGER, PORT_AGENT, endpoint
from response import list_response, object_response
from routes import API_PREFIX
from serializers import port_call_json, tender_wave_json
from services.cascades import (cancel_call, close_call, open_call_sales, record_delay)
from services.tender import waves_of_call
from validation import (f, paginate, pagination, port_call_or_404, port_or_404,
                        query_values, tender_wave_or_404, validate_body)

bp = Blueprint("port_calls", __name__)

CALL_STATUSES = ("PLANNED", "OPEN_FOR_SALE", "IN_PORT", "CLOSED", "CANCELLED")
CALL_ACTIONS = ("OPEN_SALES", "ARRIVE", "CLOSE_ALL_ABOARD", "CANCEL")
PRIORITY_CLASSES = ("EXCURSION_PRIORITY", "GENERAL")

CALL_CREATE = [
    f("port_id", "string", required=True),
    f("voyage_code", "string", required=True),
    f("ship_code", "string", required=True),
    f("arrival_utc", "instant", required=True),
    f("all_aboard_utc", "instant", required=True),
    f("departure_utc", "instant", required=True),
]

CALL_TRANSITION = [
    f("action", "enum", required=True, enum=CALL_ACTIONS),
    f("note", "string"),
]

DELAY_CREATE = [
    f("additional_delay_minutes", "int", required=True, lo=0),
    f("reason_code", "string"),
]

WAVE_CREATE = [
    f("wave_index", "int", required=True, lo=1, hi=40),
    f("window_start_utc", "instant", required=True),
    f("window_end_utc", "instant", required=True),
    f("guest_capacity", "int", required=True, lo=1),
    f("priority_class", "enum", required=True, enum=PRIORITY_CLASSES),
]


@bp.post(API_PREFIX + "/port-calls")
@endpoint(PORT_AGENT, MANAGER)
def create_call(caller):
    body = validate_body(CALL_CREATE)
    port = port_or_404(body["port_id"])
    if not (body["arrival_utc"] < body["all_aboard_utc"] <= body["departure_utc"]):
        fail("ERR_INVALID_TIME_WINDOW",
             "arrival_utc must precede all_aboard_utc, which must be at or before departure_utc")
    row = db.insert("port_calls", {
        "port_id": port["id"],
        "voyage_code": body["voyage_code"],
        "ship_code": body["ship_code"],
        "arrival_utc": body["arrival_utc"],
        "all_aboard_utc": body["all_aboard_utc"],
        "departure_utc": body["departure_utc"],
        "delay_minutes": 0,
        "effective_arrival_utc": body["arrival_utc"],
        "status": "PLANNED",
    })
    return object_response(port_call_json(row), 201)


@bp.get(API_PREFIX + "/port-calls/<port_call_id>")
@endpoint()
def read_call(caller, port_call_id):
    return object_response(port_call_json(port_call_or_404(port_call_id)))


@bp.get(API_PREFIX + "/port-calls")
@endpoint()
def list_calls(caller):
    limit, offset = pagination()
    filters = query_values([
        f("port_id", "string"),
        f("status", "enum", enum=CALL_STATUSES),
        f("voyage_code", "string"),
    ])
    rows = db.ordered("port_calls")
    for key in ("port_id", "status", "voyage_code"):
        if key in filters:
            rows = [r for r in rows if r[key] == filters[key]]
    page, total = paginate(rows, limit, offset)
    return list_response([port_call_json(r) for r in page], limit, offset, total)


@bp.post(API_PREFIX + "/port-calls/<port_call_id>/transitions")
@endpoint(PORT_AGENT, MANAGER)
def transition_call(caller, port_call_id):
    body = validate_body(CALL_TRANSITION)
    call = port_call_or_404(port_call_id)
    action = body["action"]
    status = call["status"]
    now = db.now()

    allowed = {
        "OPEN_SALES": ("PLANNED",),
        "ARRIVE": ("OPEN_FOR_SALE",),
        "CLOSE_ALL_ABOARD": ("IN_PORT",),
        "CANCEL": ("PLANNED", "OPEN_FOR_SALE"),
    }[action]
    if status not in allowed:
        fail("ERR_INVALID_PORT_CALL_ACTION",
             "%s is not declared for a port call in %s" % (action, status))

    if action == "OPEN_SALES":
        if not (call["arrival_utc"] < call["all_aboard_utc"] <= call["departure_utc"]):
            fail("ERR_INVALID_TIME_WINDOW", "the call's published instants are not ordered")
        port = db.ports.get(call["port_id"])
        if port is not None and port["docking_mode"] == "TENDER":
            priority = [w for w in waves_of_call(call["id"])
                        if w["priority_class"] == "EXCURSION_PRIORITY"]
            if not priority:
                fail("ERR_NO_ELIGIBLE_TENDER_WAVE",
                     "a TENDER port call needs an EXCURSION_PRIORITY wave before sales open")
        open_call_sales(call)
    elif action == "ARRIVE":
        if now < call["effective_arrival_utc"]:
            fail("ERR_INVALID_PORT_CALL_ACTION", "the ship has not reached its effective arrival")
        call["status"] = "IN_PORT"
        db.touch(call)
    elif action == "CLOSE_ALL_ABOARD":
        if now < call["all_aboard_utc"]:
            fail("ERR_INVALID_PORT_CALL_ACTION", "the all-aboard deadline has not passed")
        close_call(call)
    else:  # CANCEL
        cancel_call(call)

    return object_response(port_call_json(call))


@bp.post(API_PREFIX + "/port-calls/<port_call_id>/delays")
@endpoint(PORT_AGENT)
def create_delay(caller, port_call_id):
    body = validate_body(DELAY_CREATE)
    call = port_call_or_404(port_call_id)
    if call["status"] in ("CLOSED", "CANCELLED"):
        fail("ERR_INVALID_PORT_CALL_ACTION", "a terminal port call accepts no further delay")
    record_delay(call, body["additional_delay_minutes"])
    return object_response(port_call_json(call))


@bp.post(API_PREFIX + "/port-calls/<port_call_id>/tender-waves")
@endpoint(PORT_AGENT)
def create_wave(caller, port_call_id):
    body = validate_body(WAVE_CREATE)
    call = port_call_or_404(port_call_id)
    if not body["window_start_utc"] < body["window_end_utc"]:
        fail("ERR_INVALID_TIME_WINDOW", "window_end_utc must be later than window_start_utc")

    peers = waves_of_call(call["id"])
    for wave in peers:
        if wave["wave_index"] == body["wave_index"]:
            fail("ERR_DUPLICATE_WAVE_INDEX", "wave_index is already used on this port call")
    for wave in peers:
        # closed intervals: touching endpoints collide
        if (body["window_start_utc"] <= wave["window_end_utc"]
                and wave["window_start_utc"] <= body["window_end_utc"]):
            fail("ERR_TENDER_WAVE_OVERLAP", "the wave window collides with another wave")

    row = db.insert("tender_waves", {
        "port_call_id": call["id"],
        "wave_index": body["wave_index"],
        "window_start_utc": body["window_start_utc"],
        "window_end_utc": body["window_end_utc"],
        "guest_capacity": body["guest_capacity"],
        "priority_class": body["priority_class"],
        "assigned_guest_count": 0,
        "assigned_departure_count": 0,
    })
    return object_response(tender_wave_json(row), 201)


@bp.get(API_PREFIX + "/tender-waves/<tender_wave_id>")
@endpoint()
def read_wave(caller, tender_wave_id):
    return object_response(tender_wave_json(tender_wave_or_404(tender_wave_id)))


@bp.get(API_PREFIX + "/tender-waves")
@endpoint()
def list_waves(caller):
    limit, offset = pagination()
    filters = query_values([
        f("port_call_id", "string"),
        f("priority_class", "enum", enum=PRIORITY_CLASSES),
    ])
    rows = db.ordered("tender_waves")
    for key in ("port_call_id", "priority_class"):
        if key in filters:
            rows = [r for r in rows if r[key] == filters[key]]
    page, total = paginate(rows, limit, offset)
    return list_response([tender_wave_json(r) for r in page], limit, offset, total)
