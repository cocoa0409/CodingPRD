"""Agent appointments and the bounded overlap window (PRD 3.3)."""

import envelope
import listing
import lookup
import serializers
import timeutil
from constants import AGENT_RESIGNATION_NOTICE_DAYS
from dispatch import endpoint
from errors import ApiError
from services import registrations as registration_service
from store import DB, new_row, touch

ALL_ROLES_READ = ["PlatformAdmin", "ComplianceOfficer", "FilingAgent", "SopHandler"]


@endpoint(
    "POST",
    "/registrations/{id}/agent-appointments",
    roles=["ComplianceOfficer"],
    success_code=201,
)
def propose_appointment(context):
    registration = context.row
    body = context.body
    provider_name = body.string("provider_name", required=True)
    appointed_on = body.date("appointed_on", required=True)
    expected = body.integer("expected_registration_version", required=True)
    if expected != registration["version"]:  # rung 15
        raise ApiError("ERR_STALE_VERSION")
    row = new_row(
        DB.appointments,
        {
            "registration_id": registration["id"],
            "superseded_by_appointment_id": None,
            "provider_name": provider_name,
            "appointed_on": appointed_on,
            "status": "PROPOSED",
            "resignation_noticed_on": None,
            "resignation_effective_on": None,
            "of_record": False,
        },
    )
    touch(registration)
    return envelope.object_response(serializers.agent_appointment(row), 201)


@endpoint("GET", "/agent-appointments", roles=ALL_ROLES_READ, success_code=200)
def list_appointments(context):
    rows = list(DB.appointments.values())
    rows = listing.apply_filters(
        rows,
        [
            ("registration_id", "registration_id"),
            ("superseded_by_appointment_id", "superseded_by_appointment_id"),
            ("status", "status"),
        ],
    )
    return listing.respond(rows, serializers.agent_appointment)


@endpoint("GET", "/agent-appointments/{id}", roles=ALL_ROLES_READ, success_code=200)
def read_appointment(context):
    return envelope.object_response(serializers.agent_appointment(context.row))


@endpoint("POST", "/agent-appointments/{id}/accept", roles=["FilingAgent"], success_code=200)
def accept_appointment(context):
    appointment = context.row
    registration = DB.registrations.get(appointment["registration_id"])
    if appointment["status"] != "PROPOSED" or registration is None or registration[
        "status"
    ] not in ("PENDING", "ACTIVE", "DELINQUENT"):  # rung 16
        raise ApiError("ERR_INVALID_STATE")
    appointment["status"] = "APPOINTED"
    for sibling in lookup.appointments_of_registration(registration["id"]):
        if sibling["id"] == appointment["id"]:
            continue
        if sibling["status"] == "APPOINTED":
            sibling["status"] = "TRANSFERRED_OUT"
            sibling["superseded_by_appointment_id"] = appointment["id"]
            sibling["of_record"] = False
            touch(sibling)
    registration_service.refresh_agent_of_record(registration)
    touch(appointment)
    touch(registration)
    return envelope.object_response(serializers.agent_appointment(appointment))


@endpoint("POST", "/agent-appointments/{id}/reject", roles=["FilingAgent"], success_code=200)
def reject_appointment(context):
    appointment = context.row
    if appointment["status"] != "PROPOSED":  # rung 16
        raise ApiError("ERR_INVALID_STATE")
    appointment["status"] = "REJECTED"
    touch(appointment)
    # Rejection touches nothing else: no sibling, no registration, no re-run.
    return envelope.object_response(serializers.agent_appointment(appointment))


@endpoint(
    "POST",
    "/agent-appointments/{id}/notice-resignation",
    roles=["ComplianceOfficer"],
    success_code=200,
)
def notice_resignation(context):
    appointment = context.row
    if appointment["status"] != "APPOINTED" or not appointment["of_record"]:  # rung 16
        raise ApiError("ERR_INVALID_STATE")
    noticed_on = timeutil.today()
    appointment["status"] = "RESIGNATION_NOTICED"
    appointment["resignation_noticed_on"] = noticed_on
    appointment["resignation_effective_on"] = timeutil.add_days(
        noticed_on, AGENT_RESIGNATION_NOTICE_DAYS
    )
    registration = DB.registrations.get(appointment["registration_id"])
    if registration is not None:
        registration_service.refresh_agent_of_record(registration)
        touch(registration)
    touch(appointment)
    return envelope.object_response(serializers.agent_appointment(appointment))
