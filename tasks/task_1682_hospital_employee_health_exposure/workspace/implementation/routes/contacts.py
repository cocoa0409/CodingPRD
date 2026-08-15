"""Exposure contacts: enrollment, symptom reporting, conversion / lost-to-followup."""
from flask import Blueprint

from db import base_fields, now, serialize, store, touch
from errors import ApiError
from middleware import auth, body, check_enum, list_response, require_role
from response import success_list, success_object
from routes.common import get_or_404, staff_scope_check
from services.core import create_restriction
from util import add_days, parse_dt

bp = Blueprint("contacts", __name__)

CONTACT_TARGETS = {"CONVERTED_TO_CASE", "LOST_TO_FOLLOWUP"}

_READ_ROLES = {
    "EmployeeHealthNurse", "EmployeeHealthPhysician", "ComplianceOfficer",
    "SafetyOfficer", "StaffEmployee",
}


@bp.post("/employee-health/communicable-events/<event_id>/contacts")
def enroll_contact(event_id):
    user_id, role = auth()
    require_role(role, {"SafetyOfficer"})
    event = get_or_404(store.events, event_id)
    data = body()

    contact_employee_id = data.get("contact_employee_id")
    contact_date = parse_dt(data.get("contact_date"))

    # Referential coherence: contact must exist and may not be the index case.
    if contact_employee_id is not None and contact_employee_id not in store.employees:
        raise ApiError("ERR_NOT_FOUND", "Resource not found: %s" % contact_employee_id)
    if contact_employee_id is not None and contact_employee_id == event["index_employee_id"]:
        raise ApiError("ERR_SELF_CONTACT", "A contact may not be the event's index case")

    # Temporal: contact_date within [infectious_start, now], inclusive of both.
    if contact_date is not None and (
        contact_date < event["infectious_start"] or contact_date > now()
    ):
        raise ApiError(
            "ERR_CONTACT_DATE_OUT_OF_RANGE",
            "contact_date must fall between infectious_start and the current time",
        )

    # Uniqueness: one enrollment per (event, employee).
    if contact_employee_id is not None and any(
        c["event_id"] == event["id"] and c["contact_employee_id"] == contact_employee_id
        for c in store.contacts.values()
    ):
        raise ApiError(
            "ERR_DUPLICATE_CONTACT", "Contact already enrolled for this event"
        )

    # Field shape.
    if contact_employee_id is None:
        raise ApiError("ERR_INVALID_REQUEST", "Missing required field: contact_employee_id")
    if contact_date is None:
        raise ApiError("ERR_INVALID_REQUEST", "contact_date must be a valid ISO 8601 timestamp")

    contact = base_fields()
    contact.update(
        {
            "event_id": event["id"],
            "contact_employee_id": contact_employee_id,
            "contact_date": contact_date,
            "monitoring_start": contact_date,
            "monitoring_end": add_days(contact_date, event["monitoring_window_days"]),
            "symptom_onset_reported": False,
            "symptom_onset_date": None,
            "status": "MONITORING",
        }
    )
    store.contacts[contact["id"]] = contact
    return success_object(serialize(contact), status=201)


@bp.get("/employee-health/exposure-contacts")
def list_contacts():
    user_id, role = auth()
    require_role(role, _READ_ROLES)
    scope = (
        (lambda c: c["contact_employee_id"] == user_id) if role == "StaffEmployee" else None
    )
    items, meta = list_response(
        store.contacts.values(),
        {
            "event_id": lambda c: c["event_id"],
            "contact_employee_id": lambda c: c["contact_employee_id"],
            "status": lambda c: c["status"],
        },
        scope_fn=scope,
    )
    return success_list(items, meta)


@bp.get("/employee-health/exposure-contacts/<rid>")
def get_contact(rid):
    user_id, role = auth()
    require_role(role, _READ_ROLES)
    contact = get_or_404(store.contacts, rid)
    staff_scope_check(role, user_id, contact["contact_employee_id"])
    return success_object(serialize(contact))


@bp.post("/employee-health/exposure-contacts/<rid>/report-symptom")
def report_symptom(rid):
    user_id, role = auth()
    require_role(role, {"StaffEmployee", "EmployeeHealthNurse"})
    contact = get_or_404(store.contacts, rid)
    # A StaffEmployee may report only on their own contact row.
    staff_scope_check(role, user_id, contact["contact_employee_id"])
    data = body()

    if contact["status"] != "MONITORING":
        raise ApiError("ERR_INVALID_STATE", "Contact is not MONITORING")
    onset = parse_dt(data.get("symptom_onset_date"))
    if onset is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", "symptom_onset_date must be a valid ISO 8601 timestamp"
        )

    contact["symptom_onset_reported"] = True
    contact["symptom_onset_date"] = onset
    touch(contact)
    return success_object(serialize(contact))


@bp.post("/employee-health/exposure-contacts/<rid>/transition")
def transition_contact(rid):
    user_id, role = auth()
    require_role(role, {"EmployeeHealthNurse", "SafetyOfficer"})
    data = body()
    to_state = data.get("to_state")

    # Per-transition role authorization.
    if to_state == "CONVERTED_TO_CASE" and role != "EmployeeHealthNurse":
        raise ApiError("ERR_FORBIDDEN_ROLE", "Only a nurse may convert a contact to a case")
    if to_state == "LOST_TO_FOLLOWUP" and role != "SafetyOfficer":
        raise ApiError("ERR_FORBIDDEN_ROLE", "Only a safety officer may mark lost to followup")

    contact = get_or_404(store.contacts, rid)

    if to_state not in CONTACT_TARGETS:
        raise ApiError(
            "ERR_INVALID_ENUM", "to_state must be one of %s" % sorted(CONTACT_TARGETS)
        )
    if contact["status"] != "MONITORING":
        raise ApiError("ERR_INVALID_STATE", "Contact is not MONITORING")

    if to_state == "CONVERTED_TO_CASE":
        if not contact["symptom_onset_reported"]:
            raise ApiError("ERR_NO_SYMPTOMS_REPORTED", "No symptoms have been reported")
        contact["status"] = "CONVERTED_TO_CASE"
        touch(contact)
        # Conversion escalates the parent event from MONITORING.
        event = store.events[contact["event_id"]]
        if event["status"] == "MONITORING":
            event["status"] = "ESCALATED"
            touch(event)
        # Automatic open-ended FULL_EXCLUSION starting at the current logical time.
        create_restriction(
            contact["contact_employee_id"],
            "FULL_EXCLUSION",
            now(),
            None,
            "CONTACT_CONVERSION",
        )
    else:  # LOST_TO_FOLLOWUP
        contact["status"] = "LOST_TO_FOLLOWUP"
        touch(contact)

    return success_object(serialize(contact))
