"""Probate milestones: add, list, read, FILE / CLOSE (PRD 3.7)."""
from flask import Blueprint

import store
from domain import MILESTONE_KINDS, lookup, matches, paginate, sort_created, view
from envelope import success
from errors import ApiError
from security import ALL_ROLES, require_roles
from store import base_fields, iso, now, touch
from validate import get_body, validate_body

bp = Blueprint("milestones", __name__)

ACTIONS = ("FILE", "CLOSE")


@bp.post("/giving/probate-milestones")
@require_roles("EstateManager")
def create_milestone():
    body = get_body()
    validate_body(
        body,
        {
            "estate_id": ("str", True, None),
            "kind": ("str", True, MILESTONE_KINDS),
            "due_date": ("datetime", True, None),
        },
    )
    estate = lookup(store.estates, body["estate_id"], "Estate")
    milestone = base_fields()
    milestone.update(
        {
            "estate_id": estate["id"],
            "kind": body["kind"],
            "due_date": body["due_date"],
            "status": "PENDING",
            "filed_on": None,
        }
    )
    store.milestones[milestone["id"]] = milestone
    return success(view(milestone), 201)


@bp.get("/giving/probate-milestones")
@require_roles(*ALL_ROLES)
def list_milestones():
    items = [
        m
        for m in sort_created(store.milestones.values())
        if matches(m, {"estate_id": None, "kind": None, "status": None})
    ]
    page, meta = paginate(items)
    return success([view(m) for m in page], 200, meta)


@bp.get("/giving/probate-milestones/<milestone_id>")
@require_roles(*ALL_ROLES)
def get_milestone(milestone_id):
    return success(
        view(lookup(store.milestones, milestone_id, "ProbateMilestone")), 200
    )


@bp.post("/giving/probate-milestones/<milestone_id>/transition")
@require_roles("EstateManager")
def milestone_transition(milestone_id):
    milestone = lookup(store.milestones, milestone_id, "ProbateMilestone")
    body = get_body()
    validate_body(body, {"action": ("str", True, ACTIONS)})
    action = body["action"]
    status = milestone["status"]

    if action == "FILE":
        # FILE cures both PENDING and OVERDUE (late cure)
        if status not in ("PENDING", "OVERDUE"):
            raise ApiError("ERR_INVALID_STATE", 409, "Cannot FILE from %s" % status)
        milestone["status"] = "FILED"
        milestone["filed_on"] = iso(now())
    else:  # CLOSE
        if status != "FILED":
            raise ApiError("ERR_INVALID_STATE", 409, "Cannot CLOSE from %s" % status)
        milestone["status"] = "CLOSED"

    touch(milestone)
    return success(view(milestone), 200)
