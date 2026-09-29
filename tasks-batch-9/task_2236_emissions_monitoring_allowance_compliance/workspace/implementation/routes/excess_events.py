"""Excess emission events: reporting, review and the three dispositions
(PRD 3.8). Events are only ever created by a permit-limit evaluation.
"""

from flask import Blueprint

from constants import (
    API_PREFIX,
    EXCESS_EVENT_DECISIONS,
    EXCESS_EVENT_STATUSES,
    ROLE_PREPARER,
    ROLE_REGULATORY_REVIEWER,
)
from db import db, public, public_list, sort_rows, touch
from errors import fail
from lookup import facility_of_unit, get
from middleware import ANY_ROLE, authenticate
from response import array_response, object_response
from services.allowances import posture_and_dispatch
from validation import (
    apply_pagination,
    body_dict,
    enum_field,
    match_filters,
    pagination,
    query_filters,
    str_field,
)

bp = Blueprint("excess_events", __name__)


@bp.route(API_PREFIX + "/excess-emission-events", methods=["GET"])
def list_events():
    authenticate(ANY_ROLE)
    filters = query_filters(
        {"permit_limit_id": "str", "unit_id": "str", "status": EXCESS_EVENT_STATUSES}
    )
    limit, offset = pagination()
    rows = match_filters(list(db.excess_events.values()), filters)
    rows = sort_rows(rows)
    return array_response(
        public_list(apply_pagination(rows, limit, offset)), limit, offset, len(rows)
    )


@bp.route(API_PREFIX + "/excess-emission-events/<event_id>", methods=["GET"])
def read_event(event_id):
    authenticate(ANY_ROLE)
    return object_response(public(get("excess_event", event_id)))


@bp.route(API_PREFIX + "/excess-emission-events/<event_id>/report", methods=["POST"])
def report_event(event_id):
    authenticate((ROLE_PREPARER,))
    body = body_dict()

    narrative = str_field(body, "narrative", required=True, min_len=1)
    corrective_action = str_field(body, "corrective_action", required=True, min_len=1)

    event = get("excess_event", event_id)
    if event["status"] != "DETECTED":
        fail("ERR_INVALID_STATE_TRANSITION", "Only a DETECTED event may be reported.")

    event["narrative"] = narrative
    event["corrective_action"] = corrective_action
    event["status"] = "REPORTED"
    touch(event)
    return object_response(public(event))


@bp.route(API_PREFIX + "/excess-emission-events/<event_id>/review", methods=["POST"])
def review_event(event_id):
    authenticate((ROLE_REGULATORY_REVIEWER,))
    body_dict()

    event = get("excess_event", event_id)
    if event["status"] != "REPORTED":
        fail("ERR_INVALID_STATE_TRANSITION", "Only a REPORTED event may enter review.")

    event["status"] = "UNDER_REVIEW"
    touch(event)
    return object_response(public(event))


@bp.route(API_PREFIX + "/excess-emission-events/<event_id>/disposition", methods=["POST"])
def dispose_event(event_id):
    authenticate((ROLE_REGULATORY_REVIEWER,))
    body = body_dict()

    decision = enum_field(body, "decision", EXCESS_EVENT_DECISIONS, required=True)
    reason = str_field(body, "reason")

    event = get("excess_event", event_id)
    if event["status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE_TRANSITION", "Only an UNDER_REVIEW event may be disposed.")

    if decision in ("RETURN", "EXCUSE") and (reason is None or not reason.strip()):
        fail("ERR_REASON_REQUIRED", "reason is required for a %s disposition." % decision)

    if decision == "RETURN":
        event["disposition_reason"] = reason
        event["return_count"] = event["return_count"] + 1
        event["status"] = "REPORTED"
        touch(event)
    elif decision == "EXCUSE":
        event["disposition_reason"] = reason
        event["status"] = "EXCUSED"
        touch(event)
    else:  # ENFORCE -- the penalty tonnage now belongs to the allowance obligation
        event["status"] = "ENFORCEABLE"
        touch(event)
        unit = db.units.get(event["unit_id"])
        facility = facility_of_unit(unit)
        if facility is not None:
            posture_and_dispatch(facility)

    return object_response(public(event))
