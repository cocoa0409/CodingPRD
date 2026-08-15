"""Communicable-disease events: open, list/read, advance."""
from flask import Blueprint

from db import base_fields, serialize, store, touch
from errors import ApiError
from middleware import auth, body, check_enum, list_response, require_role
from response import success_list, success_object
from routes.common import get_or_404, staff_scope_check
from services.calculations import (DISEASE_INCUBATION_OFFSET_DAYS,
                                   DISEASE_MONITORING_WINDOW_DAYS)
from util import add_days, parse_dt

bp = Blueprint("events", __name__)

DISEASES = {"COVID", "INFLUENZA", "PERTUSSIS", "NOROVIRUS", "MEASLES"}
EVENT_TARGETS = {"TRACING", "MONITORING", "CLOSED"}
CONTACT_TERMINAL = {"CLEARED", "CONVERTED_TO_CASE", "LOST_TO_FOLLOWUP"}

_READ_ROLES = {
    "EmployeeHealthNurse", "EmployeeHealthPhysician", "ComplianceOfficer",
    "SafetyOfficer", "StaffEmployee",
}


@bp.post("/employee-health/communicable-events")
def create_event():
    user_id, role = auth()
    require_role(role, {"SafetyOfficer"})
    data = body()

    index_employee_id = data.get("index_employee_id")
    if index_employee_id is not None and index_employee_id not in store.employees:
        raise ApiError("ERR_NOT_FOUND", "Resource not found: %s" % index_employee_id)

    disease = check_enum(data.get("disease"), DISEASES, "disease")
    onset_date = parse_dt(data.get("onset_date"))
    if onset_date is None:
        raise ApiError("ERR_INVALID_REQUEST", "onset_date must be a valid ISO 8601 timestamp")
    if index_employee_id is None:
        raise ApiError("ERR_INVALID_REQUEST", "Missing required field: index_employee_id")

    event = base_fields()
    event.update(
        {
            "index_employee_id": index_employee_id,
            "disease": disease,
            "onset_date": onset_date,
            "infectious_start": add_days(onset_date, -DISEASE_INCUBATION_OFFSET_DAYS[disease]),
            "monitoring_window_days": DISEASE_MONITORING_WINDOW_DAYS[disease],
            "status": "OPEN",
        }
    )
    store.events[event["id"]] = event
    return success_object(serialize(event), status=201)


@bp.get("/employee-health/communicable-events")
def list_events():
    user_id, role = auth()
    require_role(role, _READ_ROLES)
    scope = (
        (lambda e: e["index_employee_id"] == user_id) if role == "StaffEmployee" else None
    )
    items, meta = list_response(
        store.events.values(),
        {
            "index_employee_id": lambda e: e["index_employee_id"],
            "disease": lambda e: e["disease"],
            "status": lambda e: e["status"],
        },
        scope_fn=scope,
    )
    return success_list(items, meta)


@bp.get("/employee-health/communicable-events/<rid>")
def get_event(rid):
    user_id, role = auth()
    require_role(role, _READ_ROLES)
    event = get_or_404(store.events, rid)
    staff_scope_check(role, user_id, event["index_employee_id"])
    return success_object(serialize(event))


@bp.post("/employee-health/communicable-events/<rid>/advance")
def advance_event(rid):
    user_id, role = auth()
    require_role(role, {"SafetyOfficer"})
    event = get_or_404(store.events, rid)
    data = body()
    to_state = data.get("to_state")

    if event["status"] == "CLOSED":
        raise ApiError("ERR_INVALID_STATE", "Event is CLOSED")

    if to_state == "TRACING":
        if event["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE", "Event must be OPEN to enter TRACING")
    elif to_state == "MONITORING":
        if event["status"] not in ("TRACING", "ESCALATED"):
            raise ApiError(
                "ERR_INVALID_STATE", "Event must be TRACING or ESCALATED to enter MONITORING"
            )
    elif to_state == "CLOSED":
        if event["status"] != "MONITORING":
            raise ApiError("ERR_INVALID_STATE", "Event closes only from MONITORING")
        if any(
            c["event_id"] == event["id"] and c["status"] not in CONTACT_TERMINAL
            for c in store.contacts.values()
        ):
            raise ApiError(
                "ERR_EVENT_CLOSE_BLOCKED", "Contacts are still MONITORING"
            )
    else:
        raise ApiError(
            "ERR_INVALID_ENUM", "to_state must be one of %s" % sorted(EVENT_TARGETS)
        )

    event["status"] = to_state
    touch(event)
    return success_object(serialize(event))
