"""Downtime / standby events (PRD 3.5)."""

from flask import Blueprint, request

from db import store
from errors import invalid_state, not_found
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from services.calculations import (compute_downtime_closure,
                                   recompute_standby_accrual)
from util import get_body, list_paginated, new_entity, now, req_field, touch

bp = Blueprint("downtime", __name__)

CAUSES = ["CUSTOMER_DELAY", "WEATHER", "REGULATORY_HOLD", "SAFETY_STOP",
          "CONTRACTOR_FAULT"]
DOWNTIME_STATUSES = ["OPEN", "CLOSED", "BILLED"]


def _get_event(event_id):
    event = store.downtime_events.get(event_id)
    if event is None:
        raise not_found("Downtime event not found")
    return event


@bp.post("/v1/downtime-events")
def create_downtime_event():
    require_roles(["FieldSupervisor"])
    body = get_body()
    job_id = req_field(body, "job_id")
    cause = req_field(body, "cause", choices=CAUSES)
    job = store.jobs.get(job_id)
    if job is None:
        raise not_found("Job not found")
    if job["execution_status"] != "IN_PROGRESS":
        raise invalid_state(
            "Downtime events can only be opened while the job is IN_PROGRESS")
    started = now()
    event = new_entity(store.downtime_events, {
        "job_id": job_id,
        "cause": cause,
        "started_at": started,
        "ended_at": None,
        "closure_day": started.strftime("%Y-%m-%d"),
        "duration_minutes": None,
        "grace_minutes_applied": None,
        "billable_minutes": None,
        "billed_blocks": None,
        "billed_amount_cents": None,
        "invoice_id": None,
        "status": "OPEN",
    })
    return success_object(event, status=201)


@bp.get("/v1/downtime-events")
def list_downtime_events():
    require_roles(ALL_ROLES)
    filters = {}
    for param in ("job_id", "invoice_id", "status"):
        if request.args.get(param) is not None:
            filters[param] = request.args[param]
    page, limit, offset, total = list_paginated(store.downtime_events, filters,
                                                request.args)
    return success_list(page, limit, offset, total)


@bp.get("/v1/downtime-events/<eventId>")
def get_downtime_event(eventId):
    require_roles(ALL_ROLES)
    return success_object(_get_event(eventId))


@bp.post("/v1/downtime-events/<eventId>/close")
def close_downtime_event(eventId):
    require_roles(["FieldSupervisor"])
    event = _get_event(eventId)
    if event["status"] != "OPEN":
        raise invalid_state("Only an OPEN downtime event can be closed")
    compute_downtime_closure(event, now())
    event["status"] = "CLOSED"
    touch(event)
    job = store.jobs[event["job_id"]]
    recompute_standby_accrual(job)
    touch(job)
    return success_object(event)
