"""IntegrationEvent (error queue) and ExceptionRecord endpoints."""
from datetime import timedelta

from flask import Blueprint, request

from engine import dispatch_event
from errors import ApiError
from serialize import ser_event, ser_exception
from services import MAX_RETRY, bump, get_or_404
from store import db
from util import (
    ALL_ROLES, auth, body, clock_date, inv, list_page, ok, parse_date_val,
    req_field,
)

bp = Blueprint("ops", __name__)


@bp.get("/hris/integration-events")
def list_events():
    auth(ALL_ROLES)
    items = list(db.events.values())
    for key in ("worker_id", "change_request_id", "batch_id", "channel", "status"):
        v = request.args.get(key)
        if v is not None:
            items = [e for e in items if e[key] == v]
    return list_page(items, ser_event)


@bp.get("/hris/integration-events/<eventId>")
def get_event(eventId):
    auth(ALL_ROLES)
    e = get_or_404(db.events, eventId, "ERR_INTEGRATION_EVENT_NOT_FOUND")
    return ok(ser_event(e))


@bp.post("/hris/integration-events/<eventId>/dispatch")
def dispatch(eventId):
    auth(["IntegrationOperator"])
    e = get_or_404(db.events, eventId, "ERR_INTEGRATION_EVENT_NOT_FOUND")
    b = body()
    outcome = req_field(b, "outcome")
    if outcome not in ("ACKNOWLEDGED", "FAILED"):
        raise inv("outcome must be ACKNOWLEDGED or FAILED")
    dispatch_event(e, outcome)
    return ok(ser_event(e))


@bp.post("/hris/integration-events/<eventId>/retry")
def retry(eventId):
    auth(["IntegrationOperator"])
    e = get_or_404(db.events, eventId, "ERR_INTEGRATION_EVENT_NOT_FOUND")
    if e["status"] != "FAILED" or e["retry_count"] >= MAX_RETRY:
        raise ApiError("ERR_EVENT_INVALID_STATE", 409,
                       "Retry requires FAILED with retry_count < 3")
    e["status"] = "QUEUED"
    bump(e)
    return ok(ser_event(e))


@bp.post("/hris/integration-events/<eventId>/resolve")
def resolve_event(eventId):
    auth(["IntegrationOperator"])
    e = get_or_404(db.events, eventId, "ERR_INTEGRATION_EVENT_NOT_FOUND")
    b = body()
    note = req_field(b, "resolution_note")
    if not isinstance(note, str) or not note:
        raise inv("resolution_note must be a non-empty string")
    if e["status"] != "DEAD_LETTERED":
        raise ApiError("ERR_EVENT_INVALID_STATE", 409,
                       "Resolve requires DEAD_LETTERED")
    e["status"] = "RESOLVED"
    e["resolution_note"] = note
    bump(e)
    return ok(ser_event(e))


# --------------------------------------------------------------- exceptions
@bp.get("/hris/exception-records")
def list_exceptions():
    auth(ALL_ROLES)
    items = list(db.exceptions.values())
    for key in ("rule_id", "change_request_id", "batch_id", "worker_id",
                "field_id", "status"):
        v = request.args.get(key)
        if v is not None:
            items = [x for x in items if x[key] == v]
    return list_page(items, ser_exception)


@bp.get("/hris/exception-records/<exceptionId>")
def get_exception(exceptionId):
    auth(ALL_ROLES)
    x = get_or_404(db.exceptions, exceptionId, "ERR_EXCEPTION_NOT_FOUND")
    return ok(ser_exception(x))


@bp.post("/hris/exception-records/<exceptionId>/resolve")
def resolve_exception(exceptionId):
    auth(["DataSteward"])
    x = get_or_404(db.exceptions, exceptionId, "ERR_EXCEPTION_NOT_FOUND")
    b = body()
    note = req_field(b, "resolution_note")
    if not isinstance(note, str):
        raise inv("resolution_note must be a string")
    if x["status"] != "OPEN":
        raise ApiError("ERR_EXCEPTION_NOT_OPEN", 409, "Resolve requires OPEN")
    x["status"] = "RESOLVED"
    x["resolution_note"] = note
    bump(x)
    return ok(ser_exception(x))


@bp.post("/hris/exception-records/<exceptionId>/waive")
def waive_exception(exceptionId):
    auth(["DataSteward"])
    x = get_or_404(db.exceptions, exceptionId, "ERR_EXCEPTION_NOT_FOUND")
    b = body()
    expiry = parse_date_val(req_field(b, "waiver_expiry_date"), "waiver_expiry_date")
    note = b.get("resolution_note")
    if note is not None and not isinstance(note, str):
        raise inv("resolution_note must be a string")
    if x["status"] != "OPEN":
        raise ApiError("ERR_EXCEPTION_NOT_OPEN", 409, "Waive requires OPEN")
    if expiry > clock_date() + timedelta(days=90):
        raise ApiError("ERR_WAIVER_WINDOW_EXCEEDED", 422,
                       "waiver_expiry_date may not exceed clock date + 90 days")
    x["status"] = "WAIVED"
    x["waiver_expiry_date"] = expiry
    if note is not None:
        x["resolution_note"] = note
    bump(x)
    return ok(ser_exception(x))
