"""ShiftAssignment transitions: complete, cancel (PRD 3.3)."""
from flask import Blueprint

import db
from errors import forbidden, invalid_state
from helpers import (actor, as_num, body, get_or_404, req_field, require_roles)
from response import ok
from serialize import assignment_out

bp = Blueprint("assignments", __name__)

SUPERVISOR = ("ContractorSupervisor",)
CANCEL_ROLES = ("Planner", "ContractorSupervisor")


def _turnaround_of_assignment(a):
    shift = db.shifts.get(a["shift_id"])
    return db.turnarounds.get(shift["turnaround_id"]) if shift else None


@bp.post("/assignments/<aid>/complete")
def complete_assignment(aid):
    _uid, role = actor()
    require_roles(role, SUPERVISOR)
    a = get_or_404(db.assignments, aid, "ShiftAssignment")
    b = body()
    actual = as_num(req_field(b, "actual_hours"), "actual_hours", ge=0)
    t = _turnaround_of_assignment(a)
    if t is None or t["status"] != "EXECUTION":
        invalid_state("Completing an assignment requires the turnaround to be "
                      "EXECUTION")
    if a["status"] != "ASSIGNED":
        invalid_state("Only an ASSIGNED assignment can be completed")
    a["actual_hours"] = actual
    a["status"] = "COMPLETED"
    db.touch(a)
    return ok(assignment_out(a))


@bp.post("/assignments/<aid>/cancel")
def cancel_assignment(aid):
    uid, role = actor()
    require_roles(role, CANCEL_ROLES)
    a = get_or_404(db.assignments, aid, "ShiftAssignment")
    if role == "ContractorSupervisor":
        worker = db.workers.get(a["worker_id"])
        if worker is None or worker["contractor_id"] != uid:
            forbidden("A ContractorSupervisor can only cancel assignments of "
                      "their own contractor's workers")
    if a["status"] != "ASSIGNED":
        invalid_state("Only an ASSIGNED assignment can be cancelled")
    a["status"] = "CANCELLED"
    db.touch(a)
    return ok(assignment_out(a))
