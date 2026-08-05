"""Complaint intake, triage and administrative closure (PRD 3.2)."""

import datetime

from flask import Blueprint

import auth
import calc
import envelope
import flows
import lclock
import lookups
import serialize
import store
import valid
from errors import ApiError

bp = Blueprint("complaints", __name__)
P = "/vector-control"

COMPLAINT_TYPES = (
    "RODENT_SIGHTING",
    "HARBORAGE",
    "GARBAGE_ACCUMULATION",
    "DEAD_ANIMAL",
    "MOSQUITO_BREEDING",
)
REPORTER_TYPES = ("RESIDENT", "OWNER", "AGENCY", "ANONYMOUS")
SEVERITIES = ("ROUTINE", "HIGH", "CRITICAL")
INPUT_CLOSURE_REASONS = ("WITHDRAWN", "DUPLICATE")
CLOSURE_TO_STATUS = {"WITHDRAWN": "CLOSED_WITHDRAWN", "DUPLICATE": "CLOSED_DUPLICATE"}


def _posture_of(prop):
    zone = store.zones.get(prop["zone_id"])
    return zone["posture"] if zone is not None else "NORMAL"


@bp.post(P + "/complaints")
def create_complaint():
    caller = auth.guard("IntakeClerk", "PropertyOwner")
    data = valid.body()
    # step 3: existence of the body foreign key
    raw_property_id = data.get("property_id")
    prop = None
    if isinstance(raw_property_id, str) and raw_property_id:
        prop = lookups.prop(raw_property_id)
        # step 4: ownership
        auth.require_owner(caller, prop["owner_id"])
    # step 5: request shape
    property_id = valid.req_id(data, "property_id")
    complaint_type = valid.req_enum(data, "complaint_type", COMPLAINT_TYPES)
    reporter_type = valid.req_enum(data, "reporter_type", REPORTER_TYPES)
    description = valid.req_str(data, "description", min_len=1, max_len=1000)
    reporter_name = valid.opt_str(data, "reporter_name")
    reporter_phone = valid.opt_str(data, "reporter_phone")
    reported_severity = valid.opt_enum(data, "reported_severity", SEVERITIES, "ROUTINE")
    if prop is None:
        prop = lookups.prop(property_id)
    # step 10: no second open complaint of the same type inside 48 hours
    now = lclock.now()
    window = datetime.timedelta(hours=calc.DUPLICATE_COMPLAINT_WINDOW_HOURS)
    for existing in store.complaints.values():
        if existing["property_id"] != property_id:
            continue
        if existing["complaint_type"] != complaint_type:
            continue
        if existing["status"] in calc.CLOSED_COMPLAINT_STATUSES:
            continue
        if now - existing["created_at"] < window:
            raise ApiError("ERR_DUPLICATE_COMPLAINT")

    complaint = store.stamp_new(
        {
            "property_id": property_id,
            "zone_id": prop["zone_id"],
            "complaint_type": complaint_type,
            "reporter_type": reporter_type,
            "reporter_name": reporter_name,
            "reporter_phone": reporter_phone,
            "description": description,
            "reported_severity": reported_severity,
            "severity": reported_severity,
            "status": "RECEIVED",
            "priority_score": None,
            "response_due_at": None,
            "closure_reason": None,
            "triaged_at": None,
            "closed_at": None,
        }
    )
    complaint["priority_score"] = calc.complaint_priority_score(
        complaint["severity"], complaint_type, prop["chronic_flag"], _posture_of(prop)
    )
    complaint["response_due_at"] = calc.complaint_response_deadline(
        complaint["created_at"], complaint["severity"]
    )
    store.complaints[complaint["id"]] = complaint
    flows.zone_recompute(complaint["zone_id"])
    return envelope.obj(serialize.complaint(complaint), 201)


@bp.get(P + "/complaints/<complaint_id>")
def read_complaint(complaint_id):
    auth.guard("ProgramAdmin", "Supervisor", "Inspector", "IntakeClerk", "PropertyOwner")
    complaint = lookups.complaint(complaint_id)
    return envelope.obj(serialize.complaint(complaint))


@bp.get(P + "/complaints")
def list_complaints():
    auth.guard("ProgramAdmin", "Supervisor", "Inspector", "IntakeClerk")
    limit, offset = valid.pagination()
    property_id = valid.query_str("property_id")
    zone_id = valid.query_str("zone_id")
    status = valid.query_str("status")

    def keep(c):
        if property_id is not None and c["property_id"] != property_id:
            return False
        if zone_id is not None and c["zone_id"] != zone_id:
            return False
        if status is not None and c["status"] != status:
            return False
        return True

    rows = store.ordered(store.complaints, keep)
    return lookups.page(rows, limit, offset, serialize.complaint)


@bp.post(P + "/complaints/<complaint_id>/triage")
def triage_complaint(complaint_id):
    auth.guard("Supervisor")
    complaint = lookups.complaint(complaint_id)
    data = valid.body()
    severity = valid.req_enum(data, "severity", SEVERITIES)
    valid.opt_str(data, "triage_notes")
    if complaint["status"] != "RECEIVED":
        raise ApiError("ERR_INVALID_STATE", "Only a RECEIVED complaint may be triaged.")
    prop = store.properties.get(complaint["property_id"])
    posture = _posture_of(prop) if prop is not None else "NORMAL"
    if posture == "HOTSPOT" and severity == "ROUTINE":
        severity = "HIGH"
    complaint["severity"] = severity
    complaint["priority_score"] = calc.complaint_priority_score(
        severity,
        complaint["complaint_type"],
        prop["chronic_flag"] if prop is not None else False,
        posture,
    )
    complaint["response_due_at"] = calc.complaint_response_deadline(
        complaint["created_at"], severity
    )
    complaint["triaged_at"] = lclock.now()
    complaint["status"] = "TRIAGED"
    store.touch(complaint)
    return envelope.obj(serialize.complaint(complaint))


@bp.post(P + "/complaints/<complaint_id>/close")
def close_complaint(complaint_id):
    auth.guard("Supervisor")
    complaint = lookups.complaint(complaint_id)
    data = valid.body()
    closure_reason = valid.req_enum(data, "closure_reason", INPUT_CLOSURE_REASONS)
    valid.opt_str(data, "note")
    # step 7: the complaint's own status must permit the requested leg
    status = complaint["status"]
    if status == "RECEIVED":
        pass
    elif status == "TRIAGED" and closure_reason == "WITHDRAWN":
        pass
    else:
        raise ApiError(
            "ERR_INVALID_STATE",
            "A complaint in %s cannot be closed with reason %s." % (status, closure_reason),
        )
    # step 13: the parcel must be clear of live enforcement
    for order in store.orders.values():
        if (
            order["property_id"] == complaint["property_id"]
            and order["status"] in calc.NON_TERMINAL_ORDER_STATUSES
        ):
            raise ApiError("ERR_OPEN_ORDER_EXISTS")
    flows.close_complaint(complaint, CLOSURE_TO_STATUS[closure_reason], closure_reason)
    return envelope.obj(serialize.complaint(complaint))
