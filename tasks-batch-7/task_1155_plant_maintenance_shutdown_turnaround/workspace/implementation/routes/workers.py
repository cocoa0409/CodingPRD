"""Worker badging endpoints (PRD 3.2)."""
from flask import Blueprint

import db
from errors import conflict, invalid_state
from helpers import (actor, as_enum, body, get_or_404, paged,
                     pagination_params, req_field, require_roles,
                     sorted_by_created)
from response import ok
from serialize import assignment_out, worker_out
from services import computed

bp = Blueprint("workers", __name__)

PC = ("PermitCoordinator",)
BADGE_STATUSES = ("REGISTERED", "VETTED", "BADGED", "SUSPENDED", "DEBADGED")


def _turnaround_of_worker(w):
    c = db.contractors.get(w["contractor_id"])
    return db.turnarounds.get(c["turnaround_id"]) if c else None


@bp.get("/workers/<wid>")
def get_worker(wid):
    actor()
    w = get_or_404(db.workers, wid, "Worker")
    return ok(worker_out(w))


@bp.post("/workers/<wid>/vet")
def vet_worker(wid):
    _uid, role = actor()
    require_roles(role, PC)
    w = get_or_404(db.workers, wid, "Worker")
    if w["badge_status"] != "REGISTERED":
        invalid_state("Only a REGISTERED worker can be vetted")
    t = _turnaround_of_worker(w)
    if t is not None and t["status"] in ("CANCELLED", "HANDED_OVER"):
        invalid_state("Cannot vet workers of a terminal turnaround")
    w["badge_status"] = "VETTED"
    db.touch(w)
    return ok(worker_out(w))


@bp.post("/workers/<wid>/badge")
def badge_worker(wid):
    _uid, role = actor()
    require_roles(role, PC)
    w = get_or_404(db.workers, wid, "Worker")
    if w["badge_status"] != "VETTED":
        invalid_state("Only a VETTED worker can be badged")
    c = db.contractors.get(w["contractor_id"])
    if c is None or c["mobilization_status"] not in ("MOBILIZING", "MOBILIZED"):
        invalid_state("The contractor must be MOBILIZING or MOBILIZED to badge workers")
    t = db.turnarounds.get(c["turnaround_id"])
    if t is None or t["status"] not in ("MOBILIZATION", "EXECUTION"):
        invalid_state("Badging requires the turnaround to be MOBILIZATION or EXECUTION")
    if computed.badged_headcount(c["id"]) >= c["headcount_cap"]:
        conflict("ERR_CONTRACTOR_HEADCOUNT_CAP",
                 "The contractor's badge headcount cap has been reached")
    w["badge_status"] = "BADGED"
    db.touch(w)
    return ok(worker_out(w))


@bp.post("/workers/<wid>/badge-transition")
def badge_transition(wid):
    _uid, role = actor()
    require_roles(role, PC)
    w = get_or_404(db.workers, wid, "Worker")
    b = body()
    to = as_enum(req_field(b, "to"), "to", BADGE_STATUSES)
    current = w["badge_status"]
    c = db.contractors.get(w["contractor_id"])
    if current == "BADGED" and to == "SUSPENDED":
        w["badge_status"] = "SUSPENDED"
    elif current == "SUSPENDED" and to == "BADGED":
        if c is not None and computed.badged_headcount(c["id"]) >= c["headcount_cap"]:
            conflict("ERR_CONTRACTOR_HEADCOUNT_CAP",
                     "The contractor's badge headcount cap has been reached")
        w["badge_status"] = "BADGED"
    elif current in ("BADGED", "SUSPENDED") and to == "DEBADGED":
        w["badge_status"] = "DEBADGED"
        for a in sorted(db.assignments.values(), key=lambda a: a["_seq"]):
            if a["worker_id"] == wid and a["status"] == "ASSIGNED":
                a["status"] = "CANCELLED"
                db.touch(a)
    else:
        invalid_state("Illegal badge transition from %s to %s" % (current, to))
    db.touch(w)
    return ok(worker_out(w))


@bp.get("/workers/<wid>/assignments")
def list_worker_assignments(wid):
    actor()
    get_or_404(db.workers, wid, "Worker")
    items = [a for a in db.assignments.values() if a["worker_id"] == wid]
    limit, offset = pagination_params()
    page, meta = paged(sorted_by_created(items), limit, offset)
    return ok([assignment_out(a) for a in page], pagination=meta)
