"""Voluntary correction proposals and decisions (PRD 3.8)."""
from flask import Blueprint, g

import db
from constants import (
    CORRECTION_DECISIONS,
    DISPOSITIONS,
    LEGAL_COUNSEL_AUTHORITY_CAP_CENTS,
)
from errors import fail
from middleware import body, endpoint
from response import success
from services import derive, lookup, serialize
from validation import opt_int, opt_str, req_enum, req_int, req_str

bp = Blueprint("voluntary_corrections", __name__)


@bp.post("/voluntary-corrections")
@endpoint(["CompensationManager", "LegalCounsel"])
def create_correction():
    payload = body()
    case_id = req_str(payload, "reclassification_case_id")
    decision = req_enum(payload, "decision", CORRECTION_DECISIONS)
    proposed_amount_cents = req_int(payload, "proposed_amount_cents", minimum=0)

    # rank 5: foreign key
    case = lookup.case(case_id)

    row = db.make_row(
        reclassification_case_id=case["id"],
        decision=decision,
        proposed_amount_cents=proposed_amount_cents,
        proposed_by_user_id=g.user_id,
        approved_amount_cents=None,
        approver_user_id=None,
        rejection_reason=None,
        status="PROPOSED",
    )
    db.voluntary_corrections[row["id"]] = row
    return success(serialize.voluntary_correction(row), 201)


@bp.post("/voluntary-corrections/<correction_id>/decision")
@endpoint(["LegalCounsel"])
def decide_correction(correction_id):
    correction = lookup.correction(correction_id)
    payload = body()
    disposition = req_enum(payload, "disposition", DISPOSITIONS)
    approved_amount_cents = opt_int(payload, "approved_amount_cents", minimum=0)
    rejection_reason = opt_str(payload, "rejection_reason", default=None)

    # rank 8: both decided states are terminal
    if correction["status"] != "PROPOSED":
        fail("ERR_INVALID_STATE_TRANSITION")

    # rank 10: four eyes
    if g.user_id == correction["proposed_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")

    case = lookup.case(correction["reclassification_case_id"])

    if disposition == "APPROVE":
        amount = approved_amount_cents if approved_amount_cents is not None else 0
        # rank 18: delegated authority cap
        if amount > LEGAL_COUNSEL_AUTHORITY_CAP_CENTS:
            fail("ERR_APPROVAL_AUTHORITY_EXCEEDED")
        # rank 19: a full self-correction must actually be funded
        if correction["decision"] == "SELF_CORRECT_FULL":
            if amount < derive.case_exposure_cents(case):
                fail("ERR_CORRECTION_AMOUNT_BELOW_EXPOSURE")

        correction["approved_amount_cents"] = amount
        correction["approver_user_id"] = g.user_id
        correction["status"] = "APPROVED"
        db.touch(correction)

        # the engagement's committed_correction_cents moves with the approval
        position = lookup.position(case["position_id"])
        project = derive.project_of_position(position)
        if project is not None:
            db.touch(project)
    else:
        correction["rejection_reason"] = rejection_reason
        correction["approver_user_id"] = g.user_id
        correction["status"] = "REJECTED"
        db.touch(correction)

    return success(serialize.voluntary_correction(correction), 200)
