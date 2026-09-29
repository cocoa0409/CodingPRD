"""Leak events (PRD 3.4)."""
from flask import Blueprint, request

import constants
import db
import response
import validate
from errors import ApiError, invalid
from middleware import COMPLIANCE_MANAGER, REGULATOR, endpoint, read_endpoint
from services import events, guards, ledger, posture

bp = Blueprint("leak_events", __name__)


@bp.post("/leak-events")
@endpoint([COMPLIANCE_MANAGER, REGULATOR])
def create_leak_event():
    payload = validate.body()
    system_id = validate.req_id(payload, "system_id")
    detected_at = validate.req_instant(payload, "detected_at")
    detection_method = validate.req_enum(payload, "detection_method",
                                         constants.MANUAL_DETECTION_METHODS)
    system = db.require("systems", system_id)
    # PRD 3.4: three preconditions guard an explicit declaration, in this order.
    guards.require_active_system(system)
    if system["applicability"] != "REGULATED":
        raise invalid("the system is not subject to leak-rate regulation")
    if ledger.non_terminal_event(system["id"]) is not None:
        raise ApiError("ERR_OPEN_LEAK_EVENT_EXISTS")
    guards.require_not_after_clock(detected_at)

    event = events.open_leak_event(system, detected_at, detection_method)
    posture.system_cascade(system)
    return response.created(event)


@bp.get("/leak-events")
@read_endpoint
def list_leak_events():
    filters = {
        "system_id": request.args.get("system_id"),
        "triggering_service_record_id": request.args.get("triggering_service_record_id"),
        "status": request.args.get("status"),
    }
    return response.listing(db.values("leak_events"), filters)


@bp.get("/leak-events/<event_id>")
@read_endpoint
def get_leak_event(event_id):
    return response.ok(db.require("leak_events", event_id))
