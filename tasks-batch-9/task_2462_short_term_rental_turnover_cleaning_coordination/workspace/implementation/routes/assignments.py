"""Offer reads, acceptance and the deliberately asymmetric decline."""

from flask import Blueprint

import errors
import validation as v
from db import db, now, touch
from errors import fail
from middleware import authenticate
from response import ok, ok_list
from services import lookup
from services.listing import sort_assignments
from services.matching import daily_cap_reached, has_schedule_conflict
from services.pay import create_pay_line, sync_cleaner
from services.serialize import assignment_view

bp = Blueprint("assignments", __name__)

ASSIGNMENT_STATUSES = ("OFFERED", "ACCEPTED", "ACTIVE", "COMPLETED", "DECLINED", "REVOKED")


@bp.get("/assignments")
def list_assignments():
    authenticate(("PlatformAdmin", "Coordinator", "Cleaner"))
    limit, offset = v.pagination()
    turnover_id = v.query_string("turnover_id")
    cleaner_id = v.query_string("cleaner_id")
    status = v.query_enum("status", ASSIGNMENT_STATUSES)

    rows = list(db.assignments.values())
    if turnover_id is not None:
        rows = [a for a in rows if a["turnover_id"] == turnover_id]
    if cleaner_id is not None:
        rows = [a for a in rows if a["cleaner_id"] == cleaner_id]
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    rows = sort_assignments(rows)
    page, total = v.paginate(rows, limit, offset)
    return ok_list([assignment_view(r) for r in page], limit, offset, total)


@bp.get("/assignments/<assignment_id>")
def read_assignment(assignment_id):
    authenticate(("PlatformAdmin", "Coordinator", "Cleaner"))
    return ok(assignment_view(lookup.get_assignment(assignment_id)))


def _own_assignment(actor, assignment):
    if actor.is_cleaner and assignment["cleaner_id"] != actor.user_id:
        fail(errors.ERR_NOT_ASSIGNMENT_OWNER,
             "A Cleaner may only act on its own offers.")


@bp.post("/assignments/<assignment_id>/accept")
def accept_assignment(assignment_id):
    actor = authenticate(("Cleaner",))
    assignment = lookup.get_assignment(assignment_id)
    _own_assignment(actor, assignment)

    if assignment["status"] != "OFFERED":
        fail(errors.ERR_INVALID_ASSIGNMENT_STATE, "Only an OFFERED offer may be accepted.")

    turnover = db.turnovers[assignment["turnover_id"]]
    if turnover["status"] != "PENDING_ASSIGNMENT":
        fail(errors.ERR_INVALID_TURNOVER_STATE,
             "The turnover is no longer awaiting an assignment.")

    cleaner = db.cleaners[assignment["cleaner_id"]]
    if cleaner["status"] != "ACTIVE":
        fail(errors.ERR_CLEANER_NOT_ACTIVE, "Only an ACTIVE cleaner may accept work.")
    if has_schedule_conflict(cleaner, turnover):
        fail(errors.ERR_CLEANER_SCHEDULE_CONFLICT,
             "This turnover's window overlaps another of the cleaner's assignments.")
    if daily_cap_reached(cleaner, turnover):
        fail(errors.ERR_CLEANER_DAILY_CAP_REACHED,
             "The cleaner is already at its daily turnover ceiling.")

    assignment["status"] = "ACCEPTED"
    assignment["accepted_at"] = now()
    touch(assignment)

    turnover["status"] = "SCHEDULED"
    touch(turnover)

    prop = db.properties[turnover["property_id"]]
    create_pay_line(assignment, turnover, prop, cleaner)
    sync_cleaner(cleaner)

    return ok(assignment_view(assignment))


@bp.post("/assignments/<assignment_id>/decline")
def decline_assignment(assignment_id):
    actor = authenticate(("Cleaner",))
    body = v.json_body()
    v.opt_string(body, "decline_reason")

    assignment = lookup.get_assignment(assignment_id)
    _own_assignment(actor, assignment)

    if assignment["status"] != "OFFERED":
        fail(errors.ERR_INVALID_ASSIGNMENT_STATE, "Only an OFFERED offer may be declined.")

    assignment["status"] = "DECLINED"
    assignment["declined_at"] = now()
    touch(assignment)

    # The turnover is left entirely alone: status and version are untouched.
    sync_cleaner(db.cleaners.get(assignment["cleaner_id"]))

    return ok(assignment_view(assignment))
