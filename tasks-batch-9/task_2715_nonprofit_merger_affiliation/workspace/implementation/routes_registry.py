"""Registry writes — PRD section 3.1 (organizations and programs)."""

from flask import Blueprint

import calc
import enums
import services
from auth import authenticate
from db import ORGANIZATIONS, create_row, touch
from errors import fail
from response import ok_row
from validate import (CODE_PATTERN, EIN_PATTERN, STATE_PATTERN, body_object,
                      req_enum, req_id, req_int, req_str)

bp = Blueprint("registry", __name__)


@bp.post("/organizations")
def register_organization():
    authenticate(["PlatformAdmin"])
    body = body_object()
    legal_name = req_str(body, "legal_name", min_len=1, max_len=160)
    ein = req_str(body, "ein", pattern=EIN_PATTERN)
    state_code = req_str(body, "state_code", pattern=STATE_PATTERN)
    mission_code = req_str(body, "mission_code", pattern=CODE_PATTERN)
    annual_expense_cents = req_int(body, "annual_expense_cents", minimum=0)
    unrestricted_net_assets_cents = req_int(body, "unrestricted_net_assets_cents",
                                            minimum=0)

    # Ladder rule 25.
    for org in ORGANIZATIONS.values():
        if org["ein"] == ein:
            fail("ERR_EIN_ALREADY_REGISTERED",
                 "This EIN is already registered to another organization.")

    row = create_row("Organization", {
        "legal_name": legal_name,
        "ein": ein,
        "state_code": state_code,
        "mission_code": mission_code,
        "annual_expense_cents": annual_expense_cents,
        "unrestricted_net_assets_cents": unrestricted_net_assets_cents,
        "monthly_expense_cents": calc.monthly_expense_cents(annual_expense_cents),
        "restricted_corpus_cents": 0,
        "governance_seats": 0,
        "affiliation_role": "INDEPENDENT",
        "parent_org_id": None,
    })
    return ok_row(row, 201)


@bp.post("/organizations/<org_id>/financial-restatement")
def restate_financials(org_id):
    actor = authenticate(["PlatformAdmin", "StrategyOfficer"])
    body = body_object()
    annual_expense_cents = req_int(body, "annual_expense_cents", minimum=0)
    unrestricted_net_assets_cents = req_int(body, "unrestricted_net_assets_cents",
                                            minimum=0)
    req_str(body, "restatement_reason", min_len=1)

    org = services.find_org(org_id)
    # Ladder rule 13: for a restatement the acting organization is the path org.
    services.require_specific_party(actor, org["id"])

    org["annual_expense_cents"] = annual_expense_cents
    org["unrestricted_net_assets_cents"] = unrestricted_net_assets_cents
    org["monthly_expense_cents"] = calc.monthly_expense_cents(annual_expense_cents)
    touch(org)
    return ok_row(org)


@bp.post("/programs")
def register_program():
    authenticate(["PlatformAdmin", "StrategyOfficer", "IntegrationManager"])
    body = body_object()
    org_id = req_id(body, "org_id")
    name = req_str(body, "name", min_len=1, max_len=160)
    service_category = req_enum(body, "service_category", enums.SERVICE_CATEGORIES)
    county_code = req_str(body, "county_code", pattern=CODE_PATTERN)
    annual_expense_cents = req_int(body, "annual_expense_cents", minimum=0)
    clients_served = req_int(body, "clients_served", minimum=0)

    org = services.find_org(org_id)

    row = create_row("Program", {
        "org_id": org["id"],
        "name": name,
        "service_category": service_category,
        "county_code": county_code,
        "annual_expense_cents": annual_expense_cents,
        "clients_served": clients_served,
        "continuity_status": "ACTIVE",
        "transferred_to_org_id": None,
    })
    return ok_row(row, 201)


@bp.post("/programs/<program_id>/continuity-decision")
def continuity_decision(program_id):
    authenticate(["IntegrationManager"])
    body = body_object()
    restructuring_id = req_id(body, "restructuring_id")
    disposition = req_enum(body, "disposition", enums.DISPOSITIONS)

    deal = services.find_deal(restructuring_id)
    program = services.find_program(program_id)

    # Ladder rule 16.
    if deal["status"] not in ("DILIGENCE", "DILIGENCE_CLOSED", "STRUCTURE_SELECTED",
                              "BOARD_APPROVAL", "REGULATORY_REVIEW", "INTEGRATION"):
        fail("ERR_INVALID_DEAL_STATE",
             "A continuity decision is not permitted while the deal is %s."
             % deal["status"])

    # Ladder rule 27.
    init, tgt = services.parties(deal)
    if program["org_id"] not in (init, tgt):
        fail("ERR_PROGRAM_NOT_DEAL_PARTY_ASSET",
             "This program is not an asset of either deal party.")
    recipient = program["transferred_to_org_id"]
    if recipient is not None:
        other = tgt if program["org_id"] == init else init
        if recipient != other:
            fail("ERR_PROGRAM_NOT_DEAL_PARTY_ASSET",
                 "The program recipient is not the counterparty of this deal.")
    if program["continuity_status"] != "ACTIVE":
        fail("ERR_PROGRAM_NOT_DEAL_PARTY_ASSET",
             "Only an ACTIVE program can receive a continuity decision.")

    program["continuity_status"] = ("PLANNED_TRANSFER" if disposition == "TRANSFER"
                                   else "PLANNED_SUNSET")
    touch(program)
    return ok_row(program)
