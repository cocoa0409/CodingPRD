"""Due diligence findings, clearance and the depth-five escalation cascade — PRD 3.4."""

from flask import Blueprint

import enums
import services
from auth import authenticate
from db import create_row, touch
from errors import fail
from response import ok_row
from validate import body_object, opt_int, req_enum, req_id, req_str

bp = Blueprint("diligence", __name__)

RAISE_DEAL_STATES = ("DILIGENCE", "DILIGENCE_CLOSED", "STRUCTURE_SELECTED",
                     "BOARD_APPROVAL", "REGULATORY_REVIEW")


@bp.post("/diligence-requests")
def raise_finding():
    actor = authenticate(["DiligenceLead"])
    body = body_object()
    restructuring_id = req_id(body, "restructuring_id")
    workstream = req_enum(body, "workstream", enums.WORKSTREAMS)
    severity = req_enum(body, "severity", enums.SEVERITIES)
    summary = req_str(body, "summary", min_len=1, max_len=400)
    exposure_cents = opt_int(body, "exposure_cents", minimum=0, default=0)

    deal = services.find_deal(restructuring_id)
    # Ladder rule 16: post-signing findings are admitted deliberately.
    if deal["status"] not in RAISE_DEAL_STATES:
        fail("ERR_INVALID_DEAL_STATE",
             "A diligence finding cannot be raised while the deal is %s."
             % deal["status"])

    row = create_row("DiligenceRequest", {
        "restructuring_id": deal["id"],
        "workstream": workstream,
        "severity": severity,
        "summary": summary,
        "exposure_cents": exposure_cents,
        "raised_by_user_id": actor.user_id,
        "cleared_by_user_id": None,
        "status": "OPEN",
        "response_ref": None,
        "escalation_reason": None,
        "waiver_justification": None,
    })

    # Raising a finding on a closed diligence phase cycles the deal straight back.
    if deal["status"] == "DILIGENCE_CLOSED":
        deal["status"] = "DILIGENCE"
        touch(deal)
    return ok_row(row, 201)


@bp.post("/diligence-requests/<finding_id>/respond")
def respond_finding(finding_id):
    actor = authenticate(["StrategyOfficer", "DiligenceLead"])
    body = body_object()
    response_ref = req_str(body, "response_ref", min_len=1)
    exposure_cents = opt_int(body, "exposure_cents", minimum=0)

    finding = services.find_finding(finding_id)
    deal = services.find_deal(finding["restructuring_id"])
    # Ladder rule 13: either party may answer, so only membership is checked.
    services.require_party(actor, deal)
    # Ladder rule 22.
    if finding["status"] not in ("OPEN", "ESCALATED"):
        fail("ERR_INVALID_DILIGENCE_STATE",
             "Only an OPEN or ESCALATED finding can be answered.")

    finding["status"] = "RESPONDED"
    finding["response_ref"] = response_ref
    if exposure_cents is not None:
        finding["exposure_cents"] = exposure_cents
    touch(finding)
    # A response alone never closes diligence: the deal row is not mutated.
    return ok_row(finding)


@bp.post("/diligence-requests/<finding_id>/clear")
def clear_finding(finding_id):
    actor = authenticate(["DiligenceLead"])
    body = body_object()
    req_str(body, "clearance_note", min_len=1)

    finding = services.find_finding(finding_id)
    # Ladder rule 14 speaks before the state guard of rule 22.
    if actor.user_id == finding["raised_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The lead who raised a finding may not clear it.")
    # Ladder rule 22.
    if finding["status"] != "RESPONDED":
        fail("ERR_INVALID_DILIGENCE_STATE",
             "Only a RESPONDED finding can be cleared.")

    finding["status"] = "CLEARED"
    finding["cleared_by_user_id"] = actor.user_id
    touch(finding)

    deal = services.find_deal(finding["restructuring_id"])
    services.reevaluate_diligence_closure(deal)
    return ok_row(finding)


@bp.post("/diligence-requests/<finding_id>/waive")
def waive_finding(finding_id):
    actor = authenticate(["DiligenceLead"])
    body = body_object()
    justification = req_str(body, "waiver_justification", min_len=1)

    finding = services.find_finding(finding_id)
    # Ladder rule 14 speaks before the state guard of rule 22.
    if actor.user_id == finding["raised_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The lead who raised a finding may not accept it unresolved.")
    # Ladder rule 22.
    if finding["status"] not in ("OPEN", "RESPONDED", "ESCALATED"):
        fail("ERR_INVALID_DILIGENCE_STATE",
             "A finding in %s can no longer be waived." % finding["status"])

    finding["status"] = "WAIVED"
    finding["waiver_justification"] = justification
    touch(finding)

    deal = services.find_deal(finding["restructuring_id"])
    services.reevaluate_diligence_closure(deal)
    return ok_row(finding)


@bp.post("/diligence-requests/<finding_id>/escalate")
def escalate_finding(finding_id):
    authenticate(["DiligenceLead"])
    body = body_object()
    reason = req_str(body, "escalation_reason", min_len=1)

    finding = services.find_finding(finding_id)
    deal = services.find_deal(finding["restructuring_id"])
    # Ladder rule 16.
    if deal["status"] not in RAISE_DEAL_STATES:
        fail("ERR_INVALID_DEAL_STATE",
             "A finding cannot be escalated while the deal is %s." % deal["status"])
    # Ladder rule 22.
    if finding["status"] not in ("OPEN", "RESPONDED"):
        fail("ERR_INVALID_DILIGENCE_STATE",
             "Only an OPEN or RESPONDED finding can be escalated.")

    # CASCADE HOP 1 always runs.
    finding["status"] = "ESCALATED"
    finding["escalation_reason"] = reason
    touch(finding)

    if finding["severity"] != "CRITICAL":
        # A non-critical escalation stops here and touches nothing else.
        return ok_row(finding)

    # CASCADE HOP 2: the deal reverts and opens a new negotiation round.
    deal["status"] = "LOI_NEGOTIATION"
    deal["round_no"] += 1
    # structure_type is deliberately retained across the revert.
    touch(deal)

    # CASCADE HOP 3: the executed letter is superseded and its window released.
    for letter in services.deal_letters(deal["id"]):
        if letter["status"] == "EXECUTED":
            letter["status"] = "SUPERSEDED"
            letter["exclusivity_status"] = "RELEASED"
            touch(letter)

    # CASCADE HOP 4 and 5: certified approvals are superseded and seats returned.
    for approval in services.deal_approvals(deal["id"]):
        if approval["status"] == "CERTIFIED":
            approval["status"] = "SUPERSEDED"
            services.return_seats(deal, approval)
            touch(approval)

    return ok_row(finding)
