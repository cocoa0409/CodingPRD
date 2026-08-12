"""Service of process (PRD 3.9)."""

import envelope
import listing
import lookup
import serializers
import timeutil
from constants import (
    SOP_ACK_DEADLINE_HOURS,
    SOP_CLASSES,
    SOP_DEFERRAL_BUSINESS_HOURS,
    SOP_ESCALATION_STEP_HOURS,
    SOP_LITIGATION_FORWARD_HOURS,
    SOP_MAX_ESCALATION_LEVEL,
    SOP_ORDINARY_FORWARD_HOURS,
)
from dispatch import endpoint
from errors import ApiError
from services import registrations as registration_service
from services import rollups
from store import DB, new_row, touch

CHANNELS = {1: "EMAIL", 2: "PHONE", 3: "ACCOUNT_MANAGER"}
READ_ROLES = ["PlatformAdmin", "ComplianceOfficer", "SopHandler", "ClientContact"]


def _client_of(document):
    registration = DB.registrations.get(document["registration_id"])
    return lookup.client_of_registration(registration)


@endpoint("POST", "/registrations/{id}/sop-documents", roles=["SopHandler"], success_code=201)
def receive_document(context):
    registration = context.row
    body = context.body
    sop_class = body.enum("sop_class", SOP_CLASSES, required=True)
    plaintiff_name = body.string("plaintiff_name", default=None, non_empty=False)
    court_case_number = body.string("court_case_number", default=None, non_empty=False)
    body.check_enums()  # rung 14

    received_at = timeutil.now()
    hours = (
        SOP_LITIGATION_FORWARD_HOURS if sop_class == "LITIGATION" else SOP_ORDINARY_FORWARD_HOURS
    )
    row = new_row(
        DB.sop_documents,
        {
            "registration_id": registration["id"],
            "sop_class": sop_class,
            "plaintiff_name": plaintiff_name,
            "court_case_number": court_case_number,
            "received_at": received_at,
            "scanned_at": None,
            "forwarded_at": None,
            "acknowledged_at": None,
            "forward_deadline_at": timeutil.advance_business_hours(received_at, hours),
            "ack_deadline_at": None,
            "escalation_level": 0,
            "deferred": False,
            "deferral_count": 0,
            "forwarded_late": False,
            "status": "RECEIVED",
        },
    )

    if sop_class == "LITIGATION":
        for sibling in lookup.sop_documents_of_registration(registration["id"]):
            if sibling["id"] == row["id"]:
                continue
            if sibling["sop_class"] != "ORDINARY":
                continue
            if sibling["status"] not in ("RECEIVED", "SCANNED"):
                continue
            sibling["forward_deadline_at"] = timeutil.advance_business_hours(
                sibling["forward_deadline_at"], SOP_DEFERRAL_BUSINESS_HOURS
            )
            sibling["deferred"] = True
            sibling["deferral_count"] += 1
            touch(sibling)
        registration_service.refresh_sop_priority_hold(registration)

    return envelope.object_response(serializers.sop_document(row), 201)


@endpoint("GET", "/registrations/{id}/sop-documents", roles=READ_ROLES, success_code=200)
def list_documents(context):
    rows = lookup.sop_documents_of_registration(context.row["id"])
    rows = listing.apply_filters(rows, [("status", "status"), ("sop_class", "sop_class")])
    return listing.respond(rows, serializers.sop_document)


@endpoint("GET", "/sop-documents/{id}", roles=READ_ROLES, success_code=200)
def read_document(context):
    return envelope.object_response(serializers.sop_document(context.row))


@endpoint("POST", "/sop-documents/{id}/scan", roles=["SopHandler"], success_code=200)
def scan_document(context):
    document = context.row
    not_our_entity = context.body.boolean("not_our_entity", default=False)
    if document["status"] != "RECEIVED":  # rung 16
        raise ApiError("ERR_INVALID_STATE")
    document["scanned_at"] = timeutil.now()
    document["status"] = "REJECTED_NOT_OUR_ENTITY" if not_our_entity else "SCANNED"
    touch(document)
    registration = DB.registrations.get(document["registration_id"])
    if registration is not None:
        registration_service.refresh_sop_priority_hold(registration)
    return envelope.object_response(serializers.sop_document(document))


@endpoint("POST", "/sop-documents/{id}/forward", roles=["SopHandler"], success_code=200)
def forward_document(context):
    document = context.row
    if document["status"] not in ("SCANNED", "ESCALATED"):  # rung 16
        raise ApiError("ERR_INVALID_STATE")
    forwarded_at = timeutil.now()
    document["status"] = "FORWARDED"
    document["forwarded_at"] = forwarded_at
    # strictly later than the deadline; forwarding exactly at it is on time
    document["forwarded_late"] = forwarded_at > document["forward_deadline_at"]
    document["ack_deadline_at"] = timeutil.advance_business_hours(
        forwarded_at, SOP_ACK_DEADLINE_HOURS
    )
    # escalation_level is deliberately left unchanged on a re-forward
    touch(document)
    client = _client_of(document)
    if client is not None:
        rollups.recompute_client(client)
    return envelope.object_response(serializers.sop_document(document))


@endpoint("POST", "/sop-documents/{id}/escalate", roles=["SopHandler"], success_code=200)
def escalate_document(context):
    document = context.row
    # declared gate order (PRD 2.9.1): 16, then 38, then 39
    if document["status"] not in ("FORWARDED", "ESCALATED"):  # rung 16
        raise ApiError("ERR_INVALID_STATE")
    instant = timeutil.now()
    if document["ack_deadline_at"] is None or instant < document["ack_deadline_at"]:  # rung 38
        raise ApiError("ERR_SOP_ACK_NOT_DUE")
    if document["escalation_level"] >= SOP_MAX_ESCALATION_LEVEL:  # rung 39
        raise ApiError("ERR_SOP_ESCALATION_CAP_REACHED")

    document["status"] = "ESCALATED"
    document["escalation_level"] += 1
    new_row(
        DB.sop_events,
        {
            "sop_document_id": document["id"],
            "level": document["escalation_level"],
            "raised_at": instant,
            "channel": CHANNELS[document["escalation_level"]],
        },
        versioned=False,
    )
    document["ack_deadline_at"] = timeutil.advance_business_hours(
        instant, SOP_ESCALATION_STEP_HOURS
    )
    touch(document)
    client = _client_of(document)
    if client is not None:
        rollups.recompute_client(client)
    return envelope.object_response(serializers.sop_document(document))


@endpoint("POST", "/sop-documents/{id}/acknowledge", roles=["ClientContact"], success_code=200)
def acknowledge_document(context):
    document = context.row
    if document["status"] not in ("FORWARDED", "ESCALATED"):  # rung 16
        raise ApiError("ERR_INVALID_STATE")
    document["status"] = "ACKNOWLEDGED"
    document["acknowledged_at"] = timeutil.now()
    # forward_deadline_at, forwarded_late and escalation_level are preserved
    touch(document)
    registration = DB.registrations.get(document["registration_id"])
    if registration is not None:
        registration_service.refresh_sop_priority_hold(registration)
    client = _client_of(document)
    if client is not None:
        rollups.recompute_client(client)
    return envelope.object_response(serializers.sop_document(document))


@endpoint("GET", "/sop-documents/{id}/escalations", roles=READ_ROLES, success_code=200)
def list_escalations(context):
    rows = [e for e in DB.sop_events.values() if e["sop_document_id"] == context.row["id"]]
    return listing.respond(rows, serializers.escalation_event)
