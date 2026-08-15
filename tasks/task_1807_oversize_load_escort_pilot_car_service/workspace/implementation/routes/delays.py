"""DelayEvent open/list/close with standby billing."""

from flask import Blueprint, request

import db
from errors import (
    ERR_INVALID_REQUEST,
    ERR_JOB_NOT_FOUND,
    ERR_JOB_INVALID_STATE,
    ERR_DELAY_EVENT_NOT_FOUND,
    ERR_DELAY_EVENT_INVALID_STATE,
    ERR_OPEN_DELAY_EVENT_EXISTS,
    raise_err,
)
from middleware import require_roles, ALL_ROLES
from mutate import mark
from response import success_object, paginate
from serializers import ser_delay_event
from services import calc, cascade
from util import body_json, req_enum, req_dt, new_id

bp = Blueprint("delays", __name__)


@bp.post("/jobs/<id>/delay-events")
def open_delay_event(id):
    require_roles("Dispatcher", "EscortOperator")
    data = body_json(request)
    cause = req_enum(data, "cause", calc.DELAY_CAUSES)
    started_at = req_dt(data, "started_at")
    if started_at > db.now():
        raise_err(ERR_INVALID_REQUEST, "started_at must not be later than the current time")
    job = db.jobs.get(id)
    if job is None:
        raise_err(ERR_JOB_NOT_FOUND, f"Job {id} not found")
    if job["job_status"] not in ("EN_ROUTE", "ON_HOLD"):
        raise_err(ERR_JOB_INVALID_STATE,
                  "Delay events may only be opened on an EN_ROUTE or ON_HOLD job")
    for d in cascade.delays_of_job(job["id"]):
        if d["delay_status"] == "OPEN":
            raise_err(ERR_OPEN_DELAY_EVENT_EXISTS, "The job already has an OPEN delay event")
    n = db.now()
    event = {
        "id": new_id(),
        "created_at": n,
        "updated_at": n,
        "version": 1,
        "_seq": db.next_seq(),
        "job_id": job["id"],
        "cause": cause,
        "started_at": started_at,
        "ended_at": None,
        "delay_status": "OPEN",
        "raw_minutes": None,
        "billable_minutes": None,
        "standby_amount_cents": None,
    }
    db.delay_events[event["id"]] = event
    return success_object(ser_delay_event(event), status=201)


@bp.get("/jobs/<id>/delay-events")
def list_delay_events(id):
    require_roles(*ALL_ROLES)
    if id not in db.jobs:
        raise_err(ERR_JOB_NOT_FOUND, f"Job {id} not found")
    rows = cascade.delays_of_job(id)
    rows.sort(key=lambda d: (d["created_at"], d["_seq"]))
    return paginate(request, [ser_delay_event(d) for d in rows])


@bp.post("/delay-events/<id>/close")
def close_delay_event(id):
    require_roles("Dispatcher", "EscortOperator")
    body_json(request)
    event = db.delay_events.get(id)
    if event is None:
        raise_err(ERR_DELAY_EVENT_NOT_FOUND, f"Delay event {id} not found")
    if event["delay_status"] != "OPEN":
        raise_err(ERR_DELAY_EVENT_INVALID_STATE, "Closing requires the delay event to be OPEN")
    n = db.now()
    job = db.jobs.get(event["job_id"])
    raw_minutes = int((n - event["started_at"]).total_seconds() // 60)
    positions = job["total_escort_positions"] if job is not None else 0
    billable, amount = calc.standby_billing(event["cause"], raw_minutes, positions)
    event["ended_at"] = n
    event["raw_minutes"] = raw_minutes
    event["billable_minutes"] = billable
    event["standby_amount_cents"] = amount
    event["delay_status"] = "CLOSED"
    mark(event)
    return success_object(ser_delay_event(event))
