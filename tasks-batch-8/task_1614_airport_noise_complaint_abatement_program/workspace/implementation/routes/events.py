"""Noise event lifecycle: screening, classification (cascade B), verification."""
from flask import Blueprint, request

from db import db, new_id
from errors import err
from middleware import get_caller, require_role, get_body
from response import success_object, success_list
from serialize import ser_event
import services
from services import touch, classification_confidence, recompute_correlation
from util import now
from validate import validate, parse_pagination

bp = Blueprint("events", __name__)

STAFF = ["NoiseOfficeAdmin", "NoiseAnalyst", "CommunityLiaison",
         "StudyCoordinator", "BoardMember"]

CLASSIFIED_STATES = {"CLASSIFIED_AIRCRAFT", "CLASSIFIED_COMMUNITY", "CLASSIFIED_MIXED"}


def _get_event(eid):
    e = db.events.get(eid)
    if e is None:
        raise err("ERR_NOT_FOUND", f"NoiseEvent {eid} not found")
    return e


def _auto_notification_for_event_flight(flight, event):
    operator = db.operators.get(flight["operator_id"])
    t = now()
    n = {
        "id": new_id(),
        "operator_id": flight["operator_id"],
        "complaint_id": None,
        "noise_event_id": event["id"],
        "severity": "ADVISORY",
        "subject": f"Noise advisory: flight {flight['flight_number']}",
        "body": "Automatic advisory: linked classified event threshold reached.",
        "status": "DRAFT",
        "sent_at": None,
        "due_at": None,
        "acknowledged_at": None,
        "responded_at": None,
        "closed_at": None,
        "response_text": None,
        "escalation_reason": None,
        "closed_outcome": None,
        "created_at": t,
        "updated_at": t,
        "version": 1,
    }
    db.notifications[n["id"]] = n
    if operator is not None:
        operator["notifications_draft"] += 1
        touch(operator)


@bp.get("/noise-events")
def list_events():
    caller = get_caller()
    require_role(caller, STAFF)
    limit, offset = parse_pagination(request.args)
    f_monitor = request.args.get("monitor_id")
    f_flight = request.args.get("flight_id")
    f_status = request.args.get("status")
    f_quarter = request.args.get("quarter")
    items = sorted(db.events.values(), key=lambda e: e["created_at"])
    if f_monitor is not None:
        items = [e for e in items if e["monitor_id"] == f_monitor]
    if f_flight is not None:
        items = [e for e in items if e.get("flight_id") == f_flight]
    if f_status is not None:
        items = [e for e in items if e["status"] == f_status]
    if f_quarter is not None:
        items = [e for e in items if e["quarter_key"] == f_quarter]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_event(e) for e in page], limit, offset, total)


@bp.get("/noise-events/<eventId>")
def get_event(eventId):
    caller = get_caller()
    require_role(caller, STAFF)
    e = _get_event(eventId)
    return success_object(ser_event(e))


@bp.post("/noise-events/<eventId>/begin-screening")
def begin_screening(eventId):
    caller = get_caller()
    get_body()
    require_role(caller, ["NoiseAnalyst"])
    e = _get_event(eventId)
    if e["status"] != "CAPTURED":
        raise err("ERR_INVALID_EVENT_STATE",
                  "begin-screening requires status CAPTURED")
    e["status"] = "SCREENING"
    touch(e)
    return success_object(ser_event(e))


@bp.post("/noise-events/<eventId>/classify")
def classify(eventId):
    caller = get_caller()
    body = get_body()
    data = validate(body, [
        ("classification", "enum", True,
         {"enum": ["AIRCRAFT", "COMMUNITY", "MIXED"]}),
        ("flight_id", "str", False),
        ("classification_basis", "str", False),
    ])
    require_role(caller, ["NoiseAnalyst"])
    e = _get_event(eventId)
    if e["status"] != "SCREENING":
        raise err("ERR_INVALID_EVENT_STATE",
                  "classify requires status SCREENING")
    classification = data["classification"]
    flight = None
    if classification == "AIRCRAFT":
        if data.get("flight_id") is None:
            raise err("ERR_VALIDATION",
                      "flight_id is required for AIRCRAFT classification")
        flight = db.flights.get(data["flight_id"])
        if flight is None:
            raise err("ERR_FLIGHT_NOT_FOUND",
                      f"FlightOperation {data['flight_id']} not found")
    elif classification == "COMMUNITY":
        if data.get("flight_id") is not None:
            raise err("ERR_VALIDATION",
                      "flight_id is not allowed for COMMUNITY classification")
    else:  # MIXED, flight optional
        if data.get("flight_id") is not None:
            flight = db.flights.get(data["flight_id"])
            if flight is None:
                raise err("ERR_FLIGHT_NOT_FOUND",
                          f"FlightOperation {data['flight_id']} not found")

    e["status"] = {"AIRCRAFT": "CLASSIFIED_AIRCRAFT",
                   "COMMUNITY": "CLASSIFIED_COMMUNITY",
                   "MIXED": "CLASSIFIED_MIXED"}[classification]
    e["flight_id"] = flight["id"] if flight is not None else None
    if "classification_basis" in data:
        e["classification_basis"] = data["classification_basis"]
    e["classification_confidence"] = classification_confidence(
        e, flight is not None)

    if flight is not None:
        # cascade B hop 1 (AIRCRAFT, and MIXED-with-flight)
        before = flight["linked_event_count"]
        flight["linked_event_count"] = before + 1
        touch(flight)
        if classification == "AIRCRAFT":
            # hop 2: corroborated complaints recompute WITH bonus
            for c in list(db.complaints.values()):
                if (c.get("correlated_event_id") == e["id"]
                        and c["status"] == "CORRELATED"):
                    recompute_correlation(c)
            # hop 3: threshold crossing -> auto advisory draft
            if before < 3 and before + 1 >= 3:
                _auto_notification_for_event_flight(flight, e)
    touch(e)
    return success_object(ser_event(e))


@bp.post("/noise-events/<eventId>/verify")
def verify(eventId):
    caller = get_caller()
    get_body()
    require_role(caller, ["NoiseAnalyst"])
    e = _get_event(eventId)
    if e["status"] not in CLASSIFIED_STATES:
        raise err("ERR_INVALID_EVENT_STATE",
                  "verify requires a classified event")
    # gate 9 (data integrity): monitor uptime floor before the confidence gate
    uptime = services.monitor_uptime(e["monitor_id"])
    if uptime < 80.0:
        raise err("ERR_UPTIME_BELOW_FLOOR",
                  f"Monitor uptime {uptime}% is below the 80.0% floor")
    if e["classification_confidence"] < 70.0:
        raise err("ERR_CONFIDENCE_BELOW_THRESHOLD",
                  "classification_confidence below 70.0")
    e["status"] = "VERIFIED"
    touch(e)
    return success_object(ser_event(e))


@bp.post("/noise-events/<eventId>/discard")
def discard(eventId):
    caller = get_caller()
    body = get_body()
    validate(body, [("reason", "str", True)])
    require_role(caller, ["NoiseAnalyst"])
    e = _get_event(eventId)
    if e["status"] != "SCREENING":
        raise err("ERR_INVALID_EVENT_STATE",
                  "discard requires status SCREENING")
    e["status"] = "DISCARDED"
    touch(e)
    return success_object(ser_event(e))


@bp.post("/noise-events/<eventId>/reclassify")
def reclassify(eventId):
    caller = get_caller()
    get_body()
    require_role(caller, ["NoiseAnalyst"])
    e = _get_event(eventId)
    if e["status"] not in CLASSIFIED_STATES:
        raise err("ERR_INVALID_EVENT_STATE",
                  "reclassify requires a classified event")
    if e["reclassify_count"] >= 2:
        raise err("ERR_RECLASSIFY_LIMIT_REACHED",
                  "Event has already been reclassified twice")
    e["reclassify_count"] += 1
    # compensation: release the previously linked flight's event counter
    flight = db.flights.get(e.get("flight_id") or "")
    if flight is not None:
        flight["linked_event_count"] -= 1
        touch(flight)
    e["flight_id"] = None
    e["status"] = "SCREENING"
    e["classification_confidence"] = 0
    e["classification_basis"] = None
    # corroborated complaints recompute WITHOUT the bonus
    for c in list(db.complaints.values()):
        if (c.get("correlated_event_id") == e["id"]
                and c["status"] == "CORRELATED"):
            recompute_correlation(c)
    touch(e)
    return success_object(ser_event(e))
