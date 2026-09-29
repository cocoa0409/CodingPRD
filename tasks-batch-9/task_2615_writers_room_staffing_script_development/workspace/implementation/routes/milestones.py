"""Milestone delivery and lateness (PRD 3.6)."""
from flask import Blueprint

from db import db, day_floor, touch
from errors import ApiError
from middleware import (GUILD_ADMINISTRATOR, LEGAL_COUNSEL, SHOWRUNNER,
                        STUDIO_EXECUTIVE, WRITER, fetch, require)
from response import ok
from routes.common import list_out, match, out
from services import domain
from validation import filter_value

bp = Blueprint("milestones", __name__)

READ_ROLES = (STUDIO_EXECUTIVE, SHOWRUNNER, GUILD_ADMINISTRATOR, LEGAL_COUNSEL, WRITER)
DELIVERABLE = ("PENDING", "LATE", "NOTES_ISSUED")
CHAIN_DONE = ("DELIVERED", "NOTES_ISSUED", "ACCEPTED")


@bp.post("/milestones/<milestone_id>/deliver")
def deliver(milestone_id):
    actor = require(WRITER)
    milestone = fetch(db.milestones, milestone_id, "ERR_MILESTONE_NOT_FOUND")
    assignment = db.assignments[milestone["assignment_id"]]
    episode = domain.episode_of_assignment(assignment)
    # 11. ownership, then 14. state (milestone, assignment, episode)
    if assignment["writer_id"] != actor.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if milestone["status"] not in DELIVERABLE:
        raise ApiError("ERR_MILESTONE_NOT_DELIVERABLE")
    if assignment["status"] not in ("DRAFTING", "IN_NOTES"):
        raise ApiError("ERR_ASSIGNMENT_NOT_DRAFTING")
    if episode["script_readiness"] == "LOCKED":
        raise ApiError("ERR_EPISODE_ALREADY_LOCKED")
    was_in_notes = milestone["status"] == "NOTES_ISSUED"
    now = db.now()
    if milestone["status"] == "PENDING" and now > milestone["due_date"]:
        milestone["status"] = "LATE"
    milestone["delivered_at"] = now
    milestone["status"] = "DELIVERED"
    late_days = (day_floor(now) - day_floor(milestone["due_date"])).days
    milestone["days_late"] = late_days if late_days > 0 else 0
    touch(milestone)
    changed = False
    if was_in_notes and assignment["status"] == "IN_NOTES":
        assignment["status"] = "DRAFTING"
        changed = True
    rows = domain.milestones_of(assignment["id"])
    if (assignment["status"] == "DRAFTING"
            and all(m["status"] in CHAIN_DONE for m in rows)):
        assignment["status"] = "DELIVERED"
        changed = True
    if domain.recompute_late_milestone_count(assignment):
        changed = True
    if changed:
        touch(assignment)
    return ok(out(milestone))


@bp.get("/milestones/<milestone_id>")
def get_milestone(milestone_id):
    require(*READ_ROLES)
    return ok(out(fetch(db.milestones, milestone_id, "ERR_MILESTONE_NOT_FOUND")))


@bp.get("/milestones")
def list_milestones():
    require(*READ_ROLES)
    rows = list(db.milestones.values())
    rows = match(rows, "assignment_id", filter_value("assignment_id"))
    rows = match(rows, "milestone_type", filter_value("milestone_type"))
    rows = match(rows, "status", filter_value("status"))
    return list_out(rows, order="sequence")
