"""The range of alternatives (PRD 3.4)."""

from flask import Blueprint

import db
import response
import validation as v
from errors import fail, invalid
from middleware import endpoint
from routes.helpers import body_ref, list_response, of_action, office_of, path_row
from routes.scoping import adopted_statement
from services import calc, rollups

bp = Blueprint("alternatives", __name__)

ALTERNATIVE_SPEC = {
    "action_id": {"required": True, "check": v.c_str(1)},
    "label": {"required": True, "check": v.c_str(1)},
    "alternative_kind": {
        "required": True,
        "check": v.c_enum(("NO_ACTION", "PROPOSED_ACTION", "REASONABLE_RANGE")),
    },
    "goal_alignment_codes": {"check": v.c_code_array(), "default": []},
    "estimated_cost_cents": {"required": True, "check": v.c_int(lo=0)},
}

READ_ROLES = ["NepaCoordinator", "ReviewingOfficial", "DecidingOfficial"]


@endpoint(bp, "/alternatives", ["POST"], ["NepaCoordinator"])
def create_alternative():
    body = v.parse_body(ALTERNATIVE_SPEC)
    action = body_ref("actions", body["action_id"], "action_id")

    statement = adopted_statement(action["id"])
    if statement is None:
        fail(
            "ERR_NO_ADOPTED_PURPOSE_NEED",
            "the action has no ADOPTED purpose and need statement to pin",
        )

    goal_codes = set(statement["goal_codes"])
    for code in body["goal_alignment_codes"]:
        if code not in goal_codes:
            raise invalid(
                "goal_alignment_codes element %s is not a goal of the pinned statement" % code
            )

    for other in of_action("alternatives", action["id"]):
        if other["label"] == body["label"]:
            fail("ERR_CONSTRAINT_VIOLATION", "label is already used by another alternative")

    score = calc.feasibility_score(
        body["goal_alignment_codes"],
        statement,
        body["estimated_cost_cents"],
        action["reference_cost_cents"],
    )
    row = db.new_row(
        "alternatives",
        {
            "action_id": action["id"],
            "pinned_pn_statement_id": statement["id"],
            "label": body["label"],
            "alternative_kind": body["alternative_kind"],
            "goal_alignment_codes": body["goal_alignment_codes"],
            "estimated_cost_cents": body["estimated_cost_cents"],
            "feasibility_score": float(score),
            "screening_status": "PROPOSED",
        },
    )
    return response.created(db.public(row))


@endpoint(bp, "/alternatives/<alternative_id>", ["GET"], READ_ROLES)
def get_alternative(alternative_id):
    alternative = path_row("alternatives", alternative_id, "alternative")
    return response.ok(db.public(alternative))


@endpoint(bp, "/alternatives", ["GET"], READ_ROLES)
def list_alternatives():
    return list_response(
        db.rows("alternatives"), "action_id", "pinned_pn_statement_id", "screening_status"
    )


@endpoint(bp, "/alternatives/<alternative_id>/screen", ["POST"], ["ReviewingOfficial"])
def screen_alternative(alternative_id):
    body = v.parse_body(
        {"decision": {"required": True, "check": v.c_enum(("SCREENED_IN", "SCREENED_OUT"))}}
    )
    alternative = path_row("alternatives", alternative_id, "alternative")
    action = db.find("actions", alternative["action_id"])
    office = office_of(action)

    if alternative["screening_status"] != "PROPOSED":
        fail("ERR_INVALID_STATE", "only a PROPOSED alternative may be screened")

    statement = db.find("statements", alternative["pinned_pn_statement_id"])
    if statement is None or statement["status"] != "ADOPTED":
        fail("ERR_ALTERNATIVE_STALE", "the alternative's pinned statement is no longer ADOPTED")

    if body["decision"] == "SCREENED_IN" and alternative["alternative_kind"] != "NO_ACTION":
        if calc.D(alternative["feasibility_score"]) < calc.D(office["min_alternative_feasibility"]):
            fail(
                "ERR_ALTERNATIVE_NOT_FEASIBLE",
                "feasibility_score is below the office minimum of %s"
                % office["min_alternative_feasibility"],
            )

    alternative["screening_status"] = body["decision"]
    db.touch(alternative)
    rollups.refresh_action(action)
    return response.ok(db.public(alternative))
