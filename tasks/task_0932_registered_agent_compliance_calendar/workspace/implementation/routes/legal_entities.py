"""Legal entities and their two independent state axes (PRD 3.1, 3.12)."""

import envelope
import lookup
import serializers
import timeutil
from constants import BOI_EXEMPT_CLASSES, ENTITY_TYPES
from dispatch import endpoint
from errors import ApiError
from services import boi, rollups
from store import DB, new_row, touch


@endpoint(
    "POST",
    "/clients/{id}/legal-entities",
    roles=["PlatformAdmin", "ComplianceOfficer"],
    success_code=201,
)
def create_legal_entity(context):
    body = context.body
    legal_name = body.string("legal_name", required=True, max_len=200)
    entity_type = body.enum("entity_type", ENTITY_TYPES, required=True)
    home_state_code = body.state_code("home_state_code", required=True)
    formation_date = body.date("formation_date", required=True)
    fiscal_year_end_month = body.integer("fiscal_year_end_month", default=12, minimum=1, maximum=12)
    fiscal_year_end_day = body.integer("fiscal_year_end_day", default=31, minimum=1, maximum=31)
    authorized_shares = body.integer("authorized_shares", default=0, minimum=0)
    issued_shares = body.integer("issued_shares", default=0, minimum=0)
    if issued_shares > authorized_shares:
        raise ApiError("ERR_INVALID_REQUEST", "issued_shares may not exceed authorized_shares.")
    total_gross_assets_cents = body.integer("total_gross_assets_cents", default=0, minimum=0)
    annual_gross_receipts_cents = body.integer("annual_gross_receipts_cents", default=0, minimum=0)
    boi_exempt_class = body.enum("boi_exempt_class", BOI_EXEMPT_CLASSES, default="NONE")
    body.check_enums()

    row = new_row(
        DB.legal_entities,
        {
            "client_id": context.row["id"],
            "legal_name": legal_name,
            "entity_type": entity_type,
            "home_state_code": home_state_code,
            "formation_date": formation_date,
            "fiscal_year_end_month": fiscal_year_end_month,
            "fiscal_year_end_day": fiscal_year_end_day,
            "authorized_shares": authorized_shares,
            "issued_shares": issued_shares,
            "total_gross_assets_cents": total_gross_assets_cents,
            "annual_gross_receipts_cents": annual_gross_receipts_cents,
            "boi_exempt_class": boi_exempt_class,
            "lifecycle_status": "DRAFT",
            "boi_status": "PENDING_INITIAL",
            "boi_initial_deadline": boi.initial_deadline(formation_date, boi_exempt_class),
            "boi_update_deadline": None,
            "company_applicant_required": boi.company_applicant_required(formation_date),
            "compliance_posture": "CURRENT",
            "final_report_required": False,
            "_boi_last_change_date": None,
        },
    )
    rollups.recompute_client(context.row)
    return envelope.object_response(serializers.legal_entity(row), 201)


@endpoint(
    "GET",
    "/legal-entities/{id}",
    roles=["PlatformAdmin", "ComplianceOfficer", "FilingAgent", "ClientContact"],
    success_code=200,
)
def read_legal_entity(context):
    return envelope.object_response(serializers.legal_entity(context.row))


@endpoint(
    "PATCH",
    "/legal-entities/{id}",
    roles=["PlatformAdmin", "ComplianceOfficer"],
    success_code=200,
)
def patch_legal_entity(context):
    entity = context.row
    body = context.body
    legal_name = body.string("legal_name", max_len=200) if body.has("legal_name") else None
    fiscal_year_end_month = body.integer("fiscal_year_end_month", minimum=1, maximum=12)
    fiscal_year_end_day = body.integer("fiscal_year_end_day", minimum=1, maximum=31)
    authorized_shares = body.integer("authorized_shares", minimum=0)
    issued_shares = body.integer("issued_shares", minimum=0)
    total_gross_assets_cents = body.integer("total_gross_assets_cents", minimum=0)
    annual_gross_receipts_cents = body.integer("annual_gross_receipts_cents", minimum=0)
    boi_exempt_class = body.enum("boi_exempt_class", BOI_EXEMPT_CLASSES)

    effective_authorized = (
        authorized_shares if authorized_shares is not None else entity["authorized_shares"]
    )
    effective_issued = issued_shares if issued_shares is not None else entity["issued_shares"]
    if effective_issued > effective_authorized:
        raise ApiError("ERR_INVALID_REQUEST", "issued_shares may not exceed authorized_shares.")
    body.check_enums()

    name_changed = legal_name is not None and legal_name != entity["legal_name"]
    if legal_name is not None:
        entity["legal_name"] = legal_name
    if fiscal_year_end_month is not None:
        entity["fiscal_year_end_month"] = fiscal_year_end_month
    if fiscal_year_end_day is not None:
        entity["fiscal_year_end_day"] = fiscal_year_end_day
    if authorized_shares is not None:
        entity["authorized_shares"] = authorized_shares
    if issued_shares is not None:
        entity["issued_shares"] = issued_shares
    if total_gross_assets_cents is not None:
        entity["total_gross_assets_cents"] = total_gross_assets_cents
    if annual_gross_receipts_cents is not None:
        entity["annual_gross_receipts_cents"] = annual_gross_receipts_cents
    if boi_exempt_class is not None and boi_exempt_class != entity["boi_exempt_class"]:
        boi.apply_exempt_class_change(entity, boi_exempt_class)
    if name_changed:
        boi.arm_update_clock(entity, timeutil.today())
    # PRD 2.4: version increases by exactly 1 on every mutation of the row, and
    # PRD 3.1: "Any accepted update increases the entity's version by 1" -- one
    # request is one mutation, so axis movement inside it does not add a second.
    touch(entity)
    rollups.cascade_from_entity(entity)
    return envelope.object_response(serializers.legal_entity(entity))


@endpoint("POST", "/legal-entities/{id}/activate", roles=["ComplianceOfficer"], success_code=200)
def activate_entity(context):
    entity = context.row
    has_home = any(
        r["registration_kind"] == "HOME" for r in lookup.registrations_of_entity(entity["id"])
    )
    if entity["lifecycle_status"] != "DRAFT" or not has_home:  # rung 16
        raise ApiError("ERR_INVALID_STATE")
    entity["lifecycle_status"] = "ACTIVE"
    touch(entity)
    rollups.cascade_from_entity(entity)
    return envelope.object_response(serializers.legal_entity(entity))


@endpoint(
    "POST", "/legal-entities/{id}/begin-wind-down", roles=["ComplianceOfficer"], success_code=200
)
def begin_wind_down(context):
    entity = context.row
    if entity["lifecycle_status"] != "ACTIVE":  # rung 16
        raise ApiError("ERR_INVALID_STATE")
    entity["lifecycle_status"] = "WINDING_DOWN"
    entity["final_report_required"] = True
    touch(entity)
    rollups.cascade_from_entity(entity)
    return envelope.object_response(serializers.legal_entity(entity))


@endpoint(
    "POST", "/legal-entities/{id}/abort-wind-down", roles=["ComplianceOfficer"], success_code=200
)
def abort_wind_down(context):
    entity = context.row
    registration_ids = {r["id"] for r in lookup.registrations_of_entity(entity["id"])}
    lodged = any(
        f["filing_kind"] == "DISSOLUTION"
        and f["status"] in ("SUBMITTED", "ACCEPTED")
        and f["registration_id"] in registration_ids
        for f in DB.filings.values()
    )
    if entity["lifecycle_status"] != "WINDING_DOWN" or lodged:  # rung 16
        raise ApiError("ERR_INVALID_STATE")
    entity["lifecycle_status"] = "ACTIVE"
    # final_report_required is deliberately NOT cleared
    touch(entity)
    rollups.cascade_from_entity(entity)
    return envelope.object_response(serializers.legal_entity(entity))


@endpoint("POST", "/legal-entities/{id}/dissolve", roles=["ComplianceOfficer"], success_code=200)
def dissolve_entity(context):
    entity = context.row
    # gate order of PRD 2.9.1: 16, then 28, then 29 -- the referential sweep
    # genuinely precedes the final-report safety gate here.
    if entity["lifecycle_status"] != "WINDING_DOWN":  # rung 16
        raise ApiError("ERR_INVALID_STATE")
    registrations = lookup.registrations_of_entity(entity["id"])
    if any(
        r["status"] not in ("WITHDRAWN", "TERMINATED", "CLOSED_PERMANENT") for r in registrations
    ):  # rung 28
        raise ApiError("ERR_ACTIVE_REGISTRATIONS_EXIST")
    if entity["final_report_required"]:  # rung 29
        for registration in registrations:
            for obligation in lookup.obligations_of_registration(registration["id"]):
                if obligation["obligation_type"] == "FINAL_REPORT" and obligation["status"] not in (
                    "SATISFIED",
                    "WAIVED",
                ):
                    raise ApiError("ERR_FINAL_REPORT_OUTSTANDING")
    entity["lifecycle_status"] = "DISSOLVED"
    entity["boi_status"] = "NOT_REQUIRED"
    touch(entity)
    rollups.cascade_from_entity(entity)
    return envelope.object_response(serializers.legal_entity(entity))
