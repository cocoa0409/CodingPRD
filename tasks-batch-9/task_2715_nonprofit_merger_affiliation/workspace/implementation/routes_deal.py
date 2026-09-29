"""The deal lifecycle — PRD sections 3.2, 3.5 (selection), 3.8 (close), 3.9 (abandon)."""

from decimal import Decimal

from flask import Blueprint

import calc
import enums
import services
from auth import authenticate
from db import ORGANIZATIONS, PROGRAMS, create_row, touch
from errors import fail
from response import ok_row
from validate import body_object, req_enum, req_id, req_int, req_str, opt_enum

bp = Blueprint("deal", __name__)

AG_REVIEW_STATES = calc.AG_REVIEW_STATES


@bp.post("/restructurings")
def open_restructuring():
    authenticate(["StrategyOfficer"])
    body = body_object()
    initiator_org_id = req_id(body, "initiator_org_id")
    target_org_id = req_id(body, "target_org_id")
    tier = opt_enum(body, "confidentiality_tier", enums.CONFIDENTIALITY_TIERS,
                    default="STANDARD")

    initiator = services.find_org(initiator_org_id)
    target = services.find_org(target_org_id)

    # Ladder rule 23.
    if initiator["id"] == target["id"]:
        fail("ERR_SELF_RESTRUCTURING",
             "An organization cannot restructure with itself.")
    # Ladder rule 24.
    for org in (initiator, target):
        if org["affiliation_role"] in ("DISSOLVED", "DIVESTED", "SUBSIDIARY"):
            fail("ERR_ORGANIZATION_NOT_ELIGIBLE",
                 "An organization that is %s cannot restructure again."
                 % org["affiliation_role"])

    ag_required = (initiator["state_code"] in AG_REVIEW_STATES
                   or target["state_code"] in AG_REVIEW_STATES)

    row = create_row("Restructuring", {
        "initiator_org_id": initiator["id"],
        "target_org_id": target["id"],
        "confidentiality_tier": tier,
        "status": "EXPLORATORY",
        "structure_type": None,
        "round_no": 1,
        "combined_board_seats": 0,
        "reserved_seat_pool": 0,
        "unrestricted_transfer_value_cents": 0,
        "unresolved_restricted_fund_count": 0,
        "restricted_asset_posture": "NOT_ASSESSED",
        "ag_review_required": ag_required,
        "abandonment_reason": None,
    })
    return ok_row(row, 201)


@bp.post("/alignment-assessments")
def create_assessment():
    authenticate(["StrategyOfficer"])
    body = body_object()
    restructuring_id = req_id(body, "restructuring_id")
    variant = req_enum(body, "variant", enums.ASSESSMENT_VARIANTS)

    deal = services.find_deal(restructuring_id)

    # Ladder rule 16.
    if deal["status"] not in ("EXPLORATORY", "RATIONALE_BUILT", "LOI_NEGOTIATION",
                              "DILIGENCE", "DILIGENCE_CLOSED"):
        fail("ERR_INVALID_DEAL_STATE",
             "An alignment assessment cannot be taken while the deal is %s."
             % deal["status"])

    prior = [a for a in services.deal_assessments(deal["id"])
             if a["variant"] == variant]
    fields = {
        "restructuring_id": deal["id"],
        "variant": variant,
        "sequence_no": len(prior) + 1,
    }
    fields.update(services.build_assessment_fields(deal, variant))
    row = create_row("AlignmentAssessment", fields, versioned=False)

    # The first SCREENING snapshot advances the deal; the transition fires only
    # from EXPLORATORY.
    if variant == "SCREENING" and deal["status"] == "EXPLORATORY":
        deal["status"] = "RATIONALE_BUILT"
        touch(deal)
    return ok_row(row, 201)


@bp.post("/restructurings/<deal_id>/select-structure")
def select_structure(deal_id):
    actor = authenticate(["StrategyOfficer"])
    body = body_object()
    structure_type = req_enum(body, "structure_type", enums.STRUCTURE_TYPES)
    value_cents = req_int(body, "unrestricted_transfer_value_cents", minimum=0)

    deal = services.find_deal(deal_id)
    # Ladder rule 13: the initiator commits the structure.
    services.require_specific_party(actor, deal["initiator_org_id"])
    # Ladder rule 16.
    if deal["status"] != "DILIGENCE_CLOSED":
        fail("ERR_INVALID_DEAL_STATE",
             "The structure may only be selected while the deal is DILIGENCE_CLOSED.")

    # Ladder rule 44.
    letter = services.executed_letter_highest_round(deal["id"])
    if letter is None or letter["proposed_structure_type"] != structure_type:
        fail("ERR_STRUCTURE_TYPE_MISMATCH",
             "The structure must equal the executed letter's proposed structure.")
    # Ladder rule 48.
    assessment = services.latest_assessment(deal["id"], "DILIGENCE_ADJUSTED")
    if assessment is None or assessment["composite_rating"] not in ("STRONG", "MODERATE"):
        fail("ERR_ALIGNMENT_RATING_INSUFFICIENT",
             "The latest diligence-adjusted assessment must be rated STRONG or MODERATE.")
    # Ladder rule 49.
    if Decimal(str(assessment["reserve_months"])) < calc.RESERVE_FLOOR_MONTHS:
        fail("ERR_RESERVE_BELOW_FLOOR",
             "The latest diligence-adjusted assessment is below the reserve floor.")

    deal["structure_type"] = structure_type
    deal["unrestricted_transfer_value_cents"] = value_cents
    deal["status"] = "STRUCTURE_SELECTED"
    touch(deal)
    return ok_row(deal)


ROLE_MAP = {
    "MERGER": ("SURVIVOR", "DISSOLVED"),
    "ASSET_ACQUISITION": ("SURVIVOR", "DIVESTED"),
    "PARENT_SUBSIDIARY": ("PARENT", "SUBSIDIARY"),
    "MANAGEMENT_SERVICES_AGREEMENT": ("MSA_PROVIDER", "MSA_CLIENT"),
}


@bp.post("/restructurings/<deal_id>/consummate")
def consummate(deal_id):
    actor = authenticate(["StrategyOfficer"])
    body = body_object()
    req_str(body, "closing_memo_ref", min_len=1)

    deal = services.find_deal(deal_id)
    # Ladder rule 13.
    services.require_specific_party(actor, deal["initiator_org_id"])
    # Ladder rule 16.
    if deal["status"] != "INTEGRATION":
        fail("ERR_INVALID_DEAL_STATE",
             "Consummation requires the deal to be in INTEGRATION.")
    # Ladder rule 35.
    if deal["ag_review_required"]:
        if (not services.has_ag_clearance(deal["id"])
                or services.has_ag_objection(deal["id"])):
            fail("ERR_AG_APPROVAL_MISSING",
                 "An approved attorney-general filing with no objection on record is "
                 "required before closing.")
    # Ladder rule 46.
    if deal["restricted_asset_posture"] not in ("NOT_ASSESSED", "CLEARED"):
        fail("ERR_RESTRICTED_ASSETS_UNRESOLVED",
             "Restricted assets of this deal are not resolved.")
    # Ladder rule 47.
    for task in services.deal_tasks(deal["id"]):
        if task["status"] not in ("COMPLETE", "CANCELLED"):
            fail("ERR_INTEGRATION_INCOMPLETE",
                 "Every integration task must be COMPLETE or CANCELLED before closing.")

    initiator = ORGANIZATIONS[deal["initiator_org_id"]]
    target = ORGANIZATIONS[deal["target_org_id"]]
    init_role, target_role = ROLE_MAP[deal["structure_type"]]

    deal["status"] = "CONSUMMATED"
    touch(deal)

    initiator["affiliation_role"] = init_role
    touch(initiator)
    target["affiliation_role"] = target_role
    if deal["structure_type"] == "PARENT_SUBSIDIARY":
        target["parent_org_id"] = initiator["id"]
    touch(target)

    # The surviving, parent or provider party receives the transferred programs.
    surviving = initiator if init_role in ("SURVIVOR", "PARENT", "MSA_PROVIDER") else target
    for program in PROGRAMS.values():
        if program["org_id"] not in (initiator["id"], target["id"]):
            continue
        if program["continuity_status"] == "PLANNED_TRANSFER":
            program["continuity_status"] = "TRANSFERRED"
            program["transferred_to_org_id"] = surviving["id"]
            touch(program)
        elif program["continuity_status"] == "PLANNED_SUNSET":
            program["continuity_status"] = "SUNSET"
            touch(program)

    return ok_row(deal)


@bp.post("/restructurings/<deal_id>/abandon")
def abandon(deal_id):
    actor = authenticate(["StrategyOfficer"])
    body = body_object()
    reason = req_str(body, "abandonment_reason", min_len=1)

    deal = services.find_deal(deal_id)
    # Ladder rule 13: abandonment accepts either party.
    services.require_party(actor, deal)
    # Ladder rule 16.
    if deal["status"] in ("CONSUMMATED", "ABANDONED"):
        fail("ERR_INVALID_DEAL_STATE",
             "A deal that is %s can no longer be abandoned." % deal["status"])

    deal["status"] = "ABANDONED"
    deal["abandonment_reason"] = reason
    touch(deal)

    # Fan-out across four child collections (PRD 3.9).
    for letter in services.deal_letters(deal["id"]):
        if letter["status"] in ("ISSUED", "COUNTERED", "EXECUTED"):
            letter["status"] = "WITHDRAWN"
            letter["exclusivity_status"] = "RELEASED"
            touch(letter)

    for approval in services.deal_approvals(deal["id"]):
        if approval["status"] in ("RECORDED", "CERTIFIED"):
            approval["status"] = "SUPERSEDED"
            services.return_seats(deal, approval)
            touch(approval)

    for task in services.deal_tasks(deal["id"]):
        if task["status"] in ("PLANNED", "HELD", "IN_PROGRESS"):
            task["status"] = "CANCELLED"
            touch(task)

    for fund in services.party_funds(deal):
        if (fund["transfer_status"] == "TRANSFERRED"
                and fund["transfer_restructuring_id"] == deal["id"]):
            services.unwind_fund(fund, deal)

    return ok_row(deal)
