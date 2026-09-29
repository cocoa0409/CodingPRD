"""Safety events, suppression and closure (PRD 3.7)."""

from flask import Blueprint

import db
import errors
import middleware
import response
import validators as v
from errors import ApiError
from services import core

bp = Blueprint("safety", __name__)

EVENT_TYPES = ("THERMAL_ANOMALY", "THERMAL_RUNAWAY", "OFFGAS_DETECTED",
               "SMOKE_DETECTED")
SEVERITIES = ("ADVISORY", "WARNING", "CRITICAL")
STATUSES = ("OPEN", "SUPPRESSION_ACTIVE", "CLOSED")


@bp.post("/safety-events")
def report_event():
    user_id, _role = middleware.authorize("SafetyOfficer", "ControlRoomOperator")
    body = v.json_body()

    asset_id = v.ident(body, "asset_id")
    event_type = v.enum(body, "event_type", EVENT_TYPES)
    severity = v.enum(body, "severity", SEVERITIES)
    detected_temp = v.num(body, "detected_max_cell_temp_c")

    asset = core.get_asset(asset_id)
    event = core.open_safety_event(asset, event_type, severity, detected_temp,
                                   "MANUAL", user_id)
    return response.created(db.serialize(event))


@bp.get("/safety-events/<event_id>")
def read_event(event_id):
    middleware.any_role()
    return response.ok(db.serialize(core.get_event(event_id)))


@bp.get("/safety-events")
def list_events():
    middleware.any_role()
    limit, offset = v.pagination()
    asset_id = v.query_str("asset_id")
    source_dispatch_id = v.query_str("source_dispatch_id")
    status = v.query_enum("status", STATUSES)
    severity = v.query_enum("severity", SEVERITIES)

    rows = list(db.safety_events.values())
    if asset_id is not None:
        rows = [r for r in rows if r["asset_id"] == asset_id]
    if source_dispatch_id is not None:
        rows = [r for r in rows if r["source_dispatch_id"] == source_dispatch_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if severity is not None:
        rows = [r for r in rows if r["severity"] == severity]
    rows = core.newest_first(rows)
    page, total = core.paginate(rows, limit, offset)
    return response.ok_list([db.serialize(r) for r in page], limit, offset, total)


@bp.post("/safety-events/<event_id>/discharge-suppression")
def discharge_suppression(event_id):
    middleware.authorize("SafetyOfficer")
    body = v.json_body()
    agent_kg = v.num(body, "suppression_agent_kg", ge=0)

    event = core.get_event(event_id)
    if event["status"] != "OPEN" or event["suppression_discharged"]:
        raise ApiError(errors.ERR_EVENT_NOT_OPEN, 409,
                       "The event is not OPEN with suppression undischarged.")

    event["status"] = "SUPPRESSION_ACTIVE"
    event["suppression_discharged"] = True
    event["suppression_agent_kg"] = agent_kg
    db.touch(event)
    return response.ok(db.serialize(event))


@bp.post("/safety-events/<event_id>/close")
def close_event(event_id):
    user_id, _role = middleware.authorize("SafetyOfficer")
    body = v.json_body(required=False)
    ack_raw, _ack = v.timestamp(body, "emergency_response_ack_at", required=False,
                                default=None)
    agencies = v.string_array(body, "emergency_ack_agencies", required=False,
                              default=None)
    responder_cleared = v.boolean(body, "responder_cleared", required=False,
                                  default=None)

    event = core.get_event(event_id)

    # separation of duties (screening step 8) outranks the state precondition
    if user_id == event["opened_by_user_id"]:
        raise ApiError(errors.ERR_SEGREGATION_OF_DUTIES, 403,
                       "A safety event may not be closed by the user who "
                       "opened it.")

    if event["status"] not in ("OPEN", "SUPPRESSION_ACTIVE"):
        raise ApiError(errors.ERR_EVENT_NOT_SUPPRESSING, 409,
                       "The event is neither OPEN nor SUPPRESSION_ACTIVE.")

    imposes_lockout = event["imposed_safety_state"] == "LOCKOUT"
    if event["status"] == "OPEN" and imposes_lockout:
        raise ApiError(errors.ERR_SUPPRESSION_NOT_DISCHARGED, 409,
                       "A lockout-imposing event may only be closed after "
                       "suppression has discharged.")

    if event["severity"] == "CRITICAL":
        if (ack_raw is None or responder_cleared is not True
                or not agencies):
            raise ApiError(errors.ERR_EMERGENCY_ACK_REQUIRED, 422,
                           "Emergency-response coordination must be on the "
                           "record before a CRITICAL event is closed.")
    elif imposes_lockout and ack_raw is None:
        raise ApiError(errors.ERR_EMERGENCY_ACK_REQUIRED, 422,
                       "emergency_response_ack_at is required to close a "
                       "lockout-imposing event.")

    event["status"] = "CLOSED"
    event["closed_by_user_id"] = user_id
    if ack_raw is not None:
        event["emergency_response_ack_at"] = ack_raw
    if agencies is not None:
        event["emergency_ack_agencies"] = agencies
    if responder_cleared is not None:
        event["responder_cleared"] = responder_cleared
    db.touch(event)

    asset = db.assets.get(event["asset_id"])
    if asset is not None:
        core.safety_resume_recompute(asset, db.clock_now())
        db.touch(asset)
    return response.ok(db.serialize(event))
