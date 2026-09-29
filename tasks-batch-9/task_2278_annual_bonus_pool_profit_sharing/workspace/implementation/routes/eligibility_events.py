"""EligibilityEvent routes: the append-only event stream that drives proration."""

from datetime import timedelta

from flask import Blueprint

import db
from errors import ApiError
from middleware import (COMPENSATION_COMMITTEE, FINANCE_CONTROLLER,
                        HR_BUSINESS_PARTNER, PLAN_ADMIN, authenticate,
                        bad_request, get_body, opt_bool, opt_id, opt_string,
                        query_param, req_date, req_enum, req_id, req_int,
                        req_string)
from response import object_response
from routes.common import paginated
from serialize import event_out
from services import cascade, lookup

bp = Blueprint("eligibility_events", __name__)

READ_ROLES = [PLAN_ADMIN, HR_BUSINESS_PARTNER, COMPENSATION_COMMITTEE,
              FINANCE_CONTROLLER]

EVENT_TYPES = {"TRANSFER", "LEAVE", "TERMINATION"}
TERMINATION_REASONS = {"VOLUNTARY_RESIGNATION", "TERMINATED_FOR_CAUSE",
                       "REDUNDANCY", "RETIREMENT", "DEATH", "DISABILITY"}


def _live_of_type(participant_id, kind, excluded_id):
    out = []
    for event in db.eligibility_events.values():
        if event["participant_id"] != participant_id:
            continue
        if event["event_type"] != kind or event["superseded"]:
            continue
        if excluded_id is not None and event["id"] == excluded_id:
            continue
        out.append(event)
    out.sort(key=lambda e: (e["effective_date"], e["_seq"]))
    return out


@bp.route("/eligibility-events", methods=["POST"])
def create_eligibility_event():
    authenticate([HR_BUSINESS_PARTNER])
    body = get_body()

    # --- ladder 4: request shape, including the conditionally-required fields
    participant_id = req_id(body, "participant_id")
    event_type = req_enum(body, "event_type", EVENT_TYPES)
    effective_date = req_date(body, "effective_date")

    new_job_level = None
    new_base_salary_cents = None
    new_business_unit_id = None
    leave_end_date = None
    termination_reason = None

    if event_type == "TRANSFER":
        new_job_level = req_string(body, "new_job_level")
        new_base_salary_cents = req_int(body, "new_base_salary_cents", minimum=1)
        new_business_unit_id = req_id(body, "new_business_unit_id")
    elif event_type == "LEAVE":
        leave_end_date = req_date(body, "leave_end_date")
    else:
        termination_reason = req_enum(body, "termination_reason", TERMINATION_REASONS)

    paid_leave = opt_bool(body, "paid_leave", default=False)
    supersedes_event_id = opt_id(body, "supersedes_event_id")
    note = opt_string(body, "note")

    # --- ladder 5: body FKs, in declaration order
    participant = lookup.participant(participant_id)
    if new_business_unit_id is not None:
        lookup.business_unit(new_business_unit_id)
    if supersedes_event_id is not None:
        lookup.event(supersedes_event_id)

    plan = lookup.plan(participant["plan_id"])

    # --- ladder 11: temporal integrity
    plan_start = db.as_date(plan["plan_period_start"])
    plan_end = db.as_date(plan["plan_period_end"])
    if not (plan_start <= effective_date < plan_end):
        raise ApiError("ERR_EVENT_DATE_OUTSIDE_PLAN_PERIOD")

    hire_date = db.as_date(participant["hire_date"])
    if effective_date < hire_date:
        raise ApiError("ERR_EVENT_DATE_BEFORE_HIRE")
    if event_type == "LEAVE" and leave_end_date < effective_date:
        raise ApiError("ERR_EVENT_DATE_BEFORE_HIRE",
                       "leave_end_date must be on or after effective_date")

    if event_type == "LEAVE":
        new_start = effective_date
        new_end_exclusive = leave_end_date + timedelta(days=1)
        for existing in _live_of_type(participant_id, "LEAVE", supersedes_event_id):
            other_start = db.as_date(existing["effective_date"])
            other_end_exclusive = db.as_date(existing["leave_end_date"]) + timedelta(days=1)
            if new_start < other_end_exclusive and other_start < new_end_exclusive:
                raise ApiError("ERR_LEAVE_INTERVAL_OVERLAP")

    for existing in _live_of_type(participant_id, "TERMINATION", supersedes_event_id):
        if effective_date > db.as_date(existing["effective_date"]):
            raise ApiError("ERR_PARTICIPANT_ALREADY_TERMINATED")
        if event_type == "TERMINATION":
            raise ApiError("ERR_PARTICIPANT_ALREADY_TERMINATED",
                           "A TERMINATION already exists; supersede it instead")

    # --- ladder 12: referential integrity of the correction pointer
    superseded_event = None
    if supersedes_event_id is not None:
        superseded_event = db.eligibility_events[supersedes_event_id]
        if superseded_event["participant_id"] != participant_id \
                or superseded_event["superseded"]:
            raise ApiError("ERR_SUPERSEDES_EVENT_INVALID")

    event = db.base_record(versioned=False)
    event.update({
        "participant_id": participant_id,
        "event_type": event_type,
        "effective_date": effective_date.isoformat(),
        "new_job_level": new_job_level,
        "new_base_salary_cents": new_base_salary_cents,
        "new_business_unit_id": new_business_unit_id,
        "leave_end_date": leave_end_date.isoformat() if leave_end_date else None,
        "paid_leave": bool(paid_leave),
        "termination_reason": termination_reason,
        "supersedes_event_id": supersedes_event_id,
        "superseded": False,
        "note": note,
    })
    db.eligibility_events[event["id"]] = event

    if superseded_event is not None:
        superseded_event["superseded"] = True

    cascade.cascade_participant(plan, participant)
    return object_response(event_out(event), 201)


@bp.route("/eligibility-events/<event_id>", methods=["GET"])
def get_eligibility_event(event_id):
    authenticate(READ_ROLES)
    return object_response(event_out(lookup.event(event_id)))


@bp.route("/eligibility-events", methods=["GET"])
def list_eligibility_events():
    authenticate(READ_ROLES)
    participant_id = query_param("participant_id")
    new_business_unit_id = query_param("new_business_unit_id")
    supersedes_event_id = query_param("supersedes_event_id")
    event_type = query_param("event_type")
    superseded = query_param("superseded")

    records = list(db.eligibility_events.values())
    records.sort(key=lambda e: (e["effective_date"], e["created_at"], e["_seq"]))

    if participant_id is not None:
        records = [r for r in records if r["participant_id"] == participant_id]
    if new_business_unit_id is not None:
        records = [r for r in records
                   if r["new_business_unit_id"] == new_business_unit_id]
    if supersedes_event_id is not None:
        records = [r for r in records
                   if r["supersedes_event_id"] == supersedes_event_id]
    if event_type is not None:
        records = [r for r in records if r["event_type"] == event_type]
    if superseded is not None:
        lowered = superseded.lower()
        if lowered not in ("true", "false"):
            raise bad_request("Query parameter 'superseded' must be true or false")
        records = [r for r in records if r["superseded"] is (lowered == "true")]
    return paginated(records, event_out)
