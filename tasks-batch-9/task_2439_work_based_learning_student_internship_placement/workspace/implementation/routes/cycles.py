"""Evaluation cycles: two independent dimensions and a compound status (PRD 3.8)."""

from flask import Blueprint

import calc
import derive
from auth import require
from db import db, touch
from errors import fail
from response import listing, ok
from validation import f_enum, f_int, f_str, get_body, pagination, paginate, q_enum

bp = Blueprint("cycles", __name__)

CYCLE_STATUSES = ("OPEN", "PARTIAL", "CLOSED", "SUSPENDED", "CANCELLED")
WRITABLE_CYCLE_STATUSES = ("OPEN", "PARTIAL")
REFLECTION_DECISIONS = ("ACCEPT", "RETURN")
MAX_REFLECTION_RETURNS = 2
RATING_FIELDS = ("rating_technical", "rating_communication", "rating_reliability",
                 "rating_safety", "rating_initiative")


@bp.post("/evaluation-cycles/<cycleId>/evaluation")
def submit_evaluation(cycleId):
    user_id, _role = require("EmployerSupervisor")
    cycle = derive.get_cycle(cycleId)
    placement = derive.get_placement(cycle["placement_id"])

    # step 3
    if user_id != placement["supervisor_id"]:
        fail("ERR_NOT_RESOURCE_OWNER",
             "Only the placement's own supervisor may submit this evaluation.")

    # step 8
    body = get_body()
    ratings = {}
    for name in RATING_FIELDS:
        ratings[name] = f_int(body, name, minimum=1, maximum=5)

    # step 18
    if placement["compliance_status"] == "BLOCKED":
        fail("ERR_PLACEMENT_COMPLIANCE_BLOCKED",
             "The placement's compliance dimension is blocked.")
    # step 19
    if (cycle["cycle_status"] not in WRITABLE_CYCLE_STATUSES
            or cycle["supervisor_eval_status"] != "PENDING"):
        fail("ERR_CYCLE_INVALID_STATE",
             "The cycle's supervisor dimension is not open for submission.")
    # step 31
    supervisor = derive.get_supervisor(placement["supervisor_id"])
    derive.require_supervisor_training(supervisor)

    cycle.update(ratings)
    cycle["supervisor_eval_status"] = "SUBMITTED"
    cycle["competency_score"] = calc.competency_score(ratings)

    if cycle["reflection_status"] == "ACCEPTED":
        derive.close_cycle(cycle, placement)
    else:
        cycle["cycle_status"] = derive.derive_cycle_status(cycle)
    touch(cycle)
    return ok(cycle)


@bp.post("/evaluation-cycles/<cycleId>/reflection")
def submit_reflection(cycleId):
    user_id, _role = require("Student")
    cycle = derive.get_cycle(cycleId)
    placement = derive.get_placement(cycle["placement_id"])

    # step 3
    if user_id != placement["student_id"]:
        fail("ERR_NOT_RESOURCE_OWNER",
             "Only the placed student may submit this reflection.")

    body = get_body()
    reflection_text = f_str(body, "reflection_text")

    # step 18
    if placement["compliance_status"] == "BLOCKED":
        fail("ERR_PLACEMENT_COMPLIANCE_BLOCKED",
             "The placement's compliance dimension is blocked.")
    # step 19
    if (cycle["cycle_status"] not in WRITABLE_CYCLE_STATUSES
            or cycle["reflection_status"] not in ("PENDING", "RETURNED")):
        fail("ERR_CYCLE_INVALID_STATE",
             "The cycle's reflection dimension is not open for submission.")

    cycle["reflection_status"] = "SUBMITTED"
    cycle["reflection_text"] = reflection_text
    cycle["cycle_status"] = derive.derive_cycle_status(cycle)
    touch(cycle)
    return ok(cycle)


@bp.post("/evaluation-cycles/<cycleId>/reflection-decision")
def decide_reflection(cycleId):
    require("WblCoordinator")
    cycle = derive.get_cycle(cycleId)
    placement = derive.get_placement(cycle["placement_id"])

    body = get_body()
    decision = f_enum(body, "decision", REFLECTION_DECISIONS)
    f_str(body, "feedback_note")

    # step 19
    if (cycle["cycle_status"] not in WRITABLE_CYCLE_STATUSES
            or cycle["reflection_status"] != "SUBMITTED"):
        fail("ERR_CYCLE_INVALID_STATE",
             "The cycle has no submitted reflection awaiting a decision.")

    if decision == "RETURN":
        # step 48
        if cycle["reflection_returned_count"] >= MAX_REFLECTION_RETURNS:
            fail("ERR_NEGOTIATION_ROUND_LIMIT",
                 "The reflection return loop has consumed its cap.")
        cycle["reflection_status"] = "RETURNED"
        cycle["reflection_returned_count"] += 1
        cycle["cycle_status"] = derive.derive_cycle_status(cycle)
        touch(cycle)
        return ok(cycle)

    cycle["reflection_status"] = "ACCEPTED"
    if cycle["supervisor_eval_status"] == "SUBMITTED":
        derive.close_cycle(cycle, placement)
    else:
        cycle["cycle_status"] = derive.derive_cycle_status(cycle)
    touch(cycle)
    return ok(cycle)


@bp.get("/placements/<id>/evaluation-cycles")
def list_placement_cycles(id):
    require("WblCoordinator", "ComplianceOfficer", "EmployerSupervisor", "Student")
    placement = derive.get_placement(id)
    limit, offset = pagination()
    status = q_enum("cycle_status", CYCLE_STATUSES)
    rows = [c for c in derive.cycles_of(placement["id"])
            if status is None or c["cycle_status"] == status]
    page, total = paginate(rows, limit, offset)
    return listing(page, total, limit, offset)
