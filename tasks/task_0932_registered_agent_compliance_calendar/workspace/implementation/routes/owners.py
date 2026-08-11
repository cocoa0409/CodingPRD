"""Beneficial owners and name clearances (PRD 3.10, 3.2)."""

import envelope
import listing
import serializers
import timeutil
from constants import NAME_CLEARANCE_RESULTS, OWNER_STATUSES
from dispatch import endpoint
from services import boi
from store import DB, new_row, touch

REPORTABLE_OWNER_FIELDS = (
    "full_name",
    "residential_address",
    "id_document_number",
    "ownership_pct",
    "owner_status",
)


@endpoint(
    "POST",
    "/legal-entities/{id}/beneficial-owners",
    roles=["ComplianceOfficer"],
    success_code=201,
)
def create_owner(context):
    entity = context.row
    body = context.body
    full_name = body.string("full_name", required=True)
    date_of_birth = body.date("date_of_birth", required=True)
    residential_address = body.string("residential_address", required=True)
    id_document_number = body.string("id_document_number", required=True)
    ownership_pct = body.number("ownership_pct", required=True, gt=0, maximum=100)
    is_company_applicant = body.boolean("is_company_applicant", default=False)

    row = new_row(
        DB.beneficial_owners,
        {
            "legal_entity_id": entity["id"],
            "full_name": full_name,
            "date_of_birth": date_of_birth,
            "residential_address": residential_address,
            "id_document_number": id_document_number,
            "ownership_pct": ownership_pct,
            "is_company_applicant": is_company_applicant,
            "owner_status": "ACTIVE",
        },
    )
    # Adding a beneficial owner is itself a reportable change.
    if boi.arm_update_clock(entity, timeutil.today()):
        touch(entity)
    return envelope.object_response(serializers.beneficial_owner(row), 201)


@endpoint(
    "GET",
    "/legal-entities/{id}/beneficial-owners",
    roles=["PlatformAdmin", "ComplianceOfficer", "FilingAgent", "ClientContact"],
    success_code=200,
)
def list_owners(context):
    rows = [
        o for o in DB.beneficial_owners.values() if o["legal_entity_id"] == context.row["id"]
    ]
    rows = listing.apply_filters(rows, [("owner_status", "owner_status")])
    return listing.respond(rows, serializers.beneficial_owner)


@endpoint("PATCH", "/beneficial-owners/{id}", roles=["ComplianceOfficer"], success_code=200)
def patch_owner(context):
    owner = context.row
    body = context.body
    full_name = body.string("full_name")
    date_of_birth = body.date("date_of_birth")
    residential_address = body.string("residential_address")
    id_document_number = body.string("id_document_number")
    ownership_pct = body.number("ownership_pct", gt=0, maximum=100)
    owner_status = body.enum("owner_status", OWNER_STATUSES)
    body.check_enums()

    updates = {
        "full_name": full_name,
        "date_of_birth": date_of_birth,
        "residential_address": residential_address,
        "id_document_number": id_document_number,
        "ownership_pct": ownership_pct,
        "owner_status": owner_status,
    }
    reportable_change = False
    for field, value in updates.items():
        if value is None:
            continue
        if owner[field] != value:
            if field in REPORTABLE_OWNER_FIELDS:
                reportable_change = True
            owner[field] = value
    touch(owner)
    if reportable_change:
        entity = DB.legal_entities.get(owner["legal_entity_id"])
        if entity is not None and boi.arm_update_clock(entity, timeutil.today()):
            touch(entity)
    return envelope.object_response(serializers.beneficial_owner(owner))


@endpoint(
    "POST", "/legal-entities/{id}/name-clearances", roles=["ComplianceOfficer"], success_code=201
)
def create_name_clearance(context):
    body = context.body
    state_code = body.state_code("state_code", required=True)
    requested_name = body.string("requested_name", required=True)
    fallback_assumed_name = body.string("fallback_assumed_name", default=None, non_empty=False)
    row = new_row(
        DB.name_clearances,
        {
            "legal_entity_id": context.row["id"],
            "state_code": state_code,
            "requested_name": requested_name,
            "fallback_assumed_name": fallback_assumed_name,
            "result": "PENDING",
            "conflicting_name": None,
            "resolved_name": None,
        },
    )
    return envelope.object_response(serializers.name_clearance(row), 201)


@endpoint(
    "GET",
    "/legal-entities/{id}/name-clearances",
    roles=["PlatformAdmin", "ComplianceOfficer", "FilingAgent"],
    success_code=200,
)
def list_name_clearances(context):
    rows = [c for c in DB.name_clearances.values() if c["legal_entity_id"] == context.row["id"]]
    rows = listing.apply_filters(rows, [("state_code", "state_code"), ("result", "result")])
    return listing.respond(rows, serializers.name_clearance)


@endpoint(
    "POST", "/name-clearances/{id}/record-result", roles=["FilingAgent"], success_code=200
)
def record_name_result(context):
    clearance = context.row
    body = context.body
    result = body.enum("result", NAME_CLEARANCE_RESULTS, required=True)
    conflicting_name = body.string("conflicting_name", default=None, non_empty=False)
    body.check_enums()

    clearance["result"] = result
    if conflicting_name is not None:
        clearance["conflicting_name"] = conflicting_name
    if result == "AVAILABLE":
        clearance["resolved_name"] = clearance["requested_name"]
    elif result == "CONFLICT" and clearance["fallback_assumed_name"] is not None:
        clearance["resolved_name"] = clearance["fallback_assumed_name"]
    else:
        clearance["resolved_name"] = None
    touch(clearance)
    return envelope.object_response(serializers.name_clearance(clearance))
