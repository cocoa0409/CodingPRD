"""Field distribution and adoption measurement (PRD 3.8)."""
from flask import Blueprint, g

from db import db, new_row, touch
from errors import fail
from middleware import ANY_ROLE, endpoint
from response import list_response, object_response
from validate import (ASSIGNMENT_STATUS, body, fk_from_body, fk_from_query,
                      paginate, pagination, query_enum, query_str, req_dt,
                      req_int, req_str, resolve)

from services import calc, serialize
from services.listing import by_created_at

bp = Blueprint("enablement", __name__)


def get_assignment(assignment_id):
    return resolve(db.enablement_assignments, assignment_id,
                   "ERR_ENABLEMENT_ASSIGNMENT_NOT_FOUND")


@bp.post("/enablement-assignments")
@endpoint(("EnablementManager",))
def distribute_battlecard():
    payload = body()
    card = fk_from_body(payload, "battlecard_id", db.battlecards,
                        "ERR_BATTLECARD_NOT_FOUND")
    req_str(payload, "battlecard_id")
    sales_rep_user_ref = req_str(payload, "sales_rep_user_ref")
    due_at = req_dt(payload, "due_at")

    assigned_at = db.clock
    # 9. the training deadline must be strictly later than assignment
    if not due_at > assigned_at:
        fail("ERR_INVALID_TIME_WINDOW",
             "due_at must be strictly later than assigned_at.")

    # 11. one assignment per rep per card
    for existing in calc.assignments_of_battlecard(card["id"]):
        if existing["sales_rep_user_ref"] == sales_rep_user_ref:
            fail("ERR_DUPLICATE_RESOURCE_KEY",
                 "That sales rep already holds an assignment on this card.")

    # 13. the card must be published
    if card["status"] != "PUBLISHED":
        fail("ERR_BATTLECARD_STATE_INVALID",
             "Only a PUBLISHED card can be distributed.")
    # 14. posture
    program = calc.program_of_battlecard(card)
    if program is not None and calc.posture(program) == "FROZEN":
        fail("ERR_PROGRAM_POSTURE_FROZEN", "The program's posture is FROZEN.")

    assignment = new_row({
        "battlecard_id": card["id"],
        "sales_rep_user_ref": sales_rep_user_ref,
        "assigned_at": assigned_at,
        "due_at": due_at,
        "status": "ASSIGNED",
        "quiz_score": None,
        "attempt_count": 0,
        "completed_at": None,
    })
    db.enablement_assignments[assignment["id"]] = assignment
    touch(card)
    return object_response(serialize.enablement_assignment(assignment), 201)


@bp.get("/enablement-assignments/<assignment_id>")
@endpoint(ANY_ROLE)
def read_assignment(assignment_id):
    return object_response(
        serialize.enablement_assignment(get_assignment(assignment_id)))


@bp.post("/enablement-assignments/<assignment_id>/complete")
@endpoint(("SalesRep",))
def complete_assignment(assignment_id):
    assignment = get_assignment(assignment_id)
    payload = body()
    quiz_score = req_int(payload, "quiz_score")
    if quiz_score < 0 or quiz_score > 100:
        fail("ERR_VALUE_OUT_OF_RANGE",
             "quiz_score must be an integer from 0 through 100.")

    if assignment["status"] not in ("ASSIGNED", "FAILED"):
        fail("ERR_ASSIGNMENT_STATE_INVALID",
             "A TRAINED or EXPIRED assignment refuses further attempts.")
    card = db.battlecards.get(assignment["battlecard_id"])
    if card is None or card["status"] != "PUBLISHED":
        fail("ERR_ASSIGNMENT_STATE_INVALID",
             "The battlecard must still be PUBLISHED.")

    # 15. the acting user must be the assignment's own rep
    if g.user_id != assignment["sales_rep_user_ref"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "Only the assigned sales rep can record the attempt.")

    # 35. the deadline boundary is inclusive
    if db.clock > assignment["due_at"]:
        fail("ERR_ASSIGNMENT_PAST_DUE", "The training deadline has passed.")

    assignment["quiz_score"] = quiz_score
    assignment["attempt_count"] = assignment["attempt_count"] + 1
    if quiz_score >= calc.QUIZ_PASS_SCORE:
        assignment["status"] = "TRAINED"
        assignment["completed_at"] = db.clock
    else:
        assignment["status"] = "FAILED"
        assignment["completed_at"] = None
    touch(assignment)
    touch(card)
    return object_response(serialize.enablement_assignment(assignment))


@bp.get("/enablement-assignments")
@endpoint(ANY_ROLE)
def list_assignments():
    battlecard_id = fk_from_query("battlecard_id", db.battlecards,
                                  "ERR_BATTLECARD_NOT_FOUND")
    sales_rep_user_ref = query_str("sales_rep_user_ref")
    status = query_enum("status", ASSIGNMENT_STATUS)
    limit, offset = pagination()
    rows = list(db.enablement_assignments.values())
    if battlecard_id:
        rows = [a for a in rows if a["battlecard_id"] == battlecard_id]
    if sales_rep_user_ref:
        rows = [a for a in rows if a["sales_rep_user_ref"] == sales_rep_user_ref]
    if status:
        rows = [a for a in rows if a["status"] == status]
    rows = sorted(by_created_at(rows), key=lambda a: a["due_at"].timestamp())
    page, total = paginate(rows, limit, offset)
    return list_response([serialize.enablement_assignment(r) for r in page],
                         limit, offset, total)
