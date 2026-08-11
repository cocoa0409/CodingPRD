"""Beneficial-ownership reports (PRD 3.10)."""

import envelope
import listing
import serializers
import timeutil
from constants import OUTCOMES, REPORT_KINDS
from dispatch import endpoint
from errors import ApiError
from services import boi
from store import DB, new_row, touch


@endpoint(
    "POST", "/legal-entities/{id}/boi-reports", roles=["ComplianceOfficer"], success_code=201
)
def draft_report(context):
    entity = context.row
    body = context.body
    report_kind = body.enum("report_kind", REPORT_KINDS, required=True)
    includes_company_applicant = body.boolean("includes_company_applicant", default=False)
    expected = body.integer("expected_legal_entity_version", required=True)
    body.check_enums()  # rung 14
    if expected != entity["version"]:  # rung 15
        raise ApiError("ERR_STALE_VERSION")
    if report_kind == "UPDATED" and entity["boi_status"] != "UPDATE_DUE":  # rung 16
        raise ApiError("ERR_INVALID_STATE")
    if entity["boi_exempt_class"] != "NONE":  # rung 40
        raise ApiError("ERR_BOI_EXEMPT_ENTITY")

    if report_kind == "INITIAL":
        deadline_date = entity["boi_initial_deadline"]
        triggering_change_date = None
    else:
        deadline_date = entity["boi_update_deadline"]
        triggering_change_date = entity.get("_boi_last_change_date")
    owner_snapshot_count = sum(
        1
        for o in DB.beneficial_owners.values()
        if o["legal_entity_id"] == entity["id"] and o["owner_status"] == "ACTIVE"
    )
    row = new_row(
        DB.boi_reports,
        {
            "legal_entity_id": entity["id"],
            "report_kind": report_kind,
            "includes_company_applicant": includes_company_applicant,
            "deadline_date": deadline_date,
            "triggering_change_date": triggering_change_date,
            "owner_snapshot_count": owner_snapshot_count,
            "submitted_on": None,
            "accepted_on": None,
            "status": "DRAFT",
        },
    )
    touch(entity)
    return envelope.object_response(serializers.boi_report(row), 201)


@endpoint(
    "GET",
    "/legal-entities/{id}/boi-reports",
    roles=["PlatformAdmin", "ComplianceOfficer", "FilingAgent", "ClientContact"],
    success_code=200,
)
def list_reports(context):
    rows = [r for r in DB.boi_reports.values() if r["legal_entity_id"] == context.row["id"]]
    rows = listing.apply_filters(rows, [("status", "status"), ("report_kind", "report_kind")])
    return listing.respond(rows, serializers.boi_report)


@endpoint("POST", "/boi-reports/{id}/submit", roles=["FilingAgent"], success_code=200)
def submit_report(context):
    report = context.row
    entity = DB.legal_entities.get(report["legal_entity_id"])
    # declared gate order (PRD 2.9.1): 16, then 40, then 41
    if report["status"] != "DRAFT":  # rung 16
        raise ApiError("ERR_INVALID_STATE")
    if entity is None or entity["boi_exempt_class"] != "NONE":  # rung 40
        raise ApiError("ERR_BOI_EXEMPT_ENTITY")
    if entity["company_applicant_required"] and not report["includes_company_applicant"]:
        raise ApiError("ERR_COMPANY_APPLICANT_REQUIRED")  # rung 41
    report["status"] = "SUBMITTED"
    report["submitted_on"] = timeutil.today()
    touch(report)
    return envelope.object_response(serializers.boi_report(report))


@endpoint("POST", "/boi-reports/{id}/record-outcome", roles=["FilingAgent"], success_code=200)
def record_report_outcome(context):
    report = context.row
    outcome = context.body.enum("outcome", OUTCOMES, required=True)
    context.body.check_enums()  # rung 14
    if report["status"] != "SUBMITTED":  # rung 16
        raise ApiError("ERR_INVALID_STATE")
    entity = DB.legal_entities.get(report["legal_entity_id"])
    if outcome == "ACCEPTED":
        report["status"] = "ACCEPTED"
        report["accepted_on"] = timeutil.today()
        touch(report)
        if entity is not None and boi.record_accepted_report(entity):
            touch(entity)
    else:
        # A rejection deliberately leaves the entity's BOI axis exactly where
        # it stood, including boi_update_deadline.
        report["status"] = "REJECTED"
        touch(report)
    return envelope.object_response(serializers.boi_report(report))
