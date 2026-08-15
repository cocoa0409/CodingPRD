"""VolunteerProject routes + ticket queueing / claim-next (PRD §3.5)."""

from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_ITEM_NOT_AVAILABLE,
    ERR_NO_CLAIMABLE_TICKETS, ERR_ACTIVE_TICKETS_REMAIN,
)
from middleware import require_roles, ANY_ROLE
from response import success_object, success_list
from services.calc import digitization_priority
from services.rollup import recompute_project_active_count
from util import get_json_body, as_str, as_int, paginate, public_view

bp = Blueprint("projects", __name__)

DEFAULT_MAX_HOURS = 40


def serialize_project(p: dict) -> dict:
    return public_view(p)


def serialize_ticket(t: dict) -> dict:
    return public_view(t)


def get_project(pid: str) -> dict:
    p = db.projects.get(pid)
    if p is None:
        raise_err(ERR_NOT_FOUND, f"VolunteerProject not found: {pid}")
    return p


@bp.route("/volunteer-projects", methods=["POST"])
@require_roles("VolunteerCoordinator")
def create_project(_user_id: str, _role: str):
    body = get_json_body()
    name = as_str(body, "name", required=True)
    description = as_str(body, "description", required=False, default=None)
    max_hours = as_int(body, "max_hours_per_volunteer", required=False,
                       default=DEFAULT_MAX_HOURS, minimum=0)

    proj = {
        **db.make_common_fields(),
        "name": name,
        "description": description,
        "max_hours_per_volunteer": max_hours,
        "status": "PLANNED",
        "hours_logged_total": 0,
        "volunteer_hours": {},
        "active_ticket_count": 0,
    }
    db.projects[proj["id"]] = proj
    return success_object(serialize_project(proj), 201)


@bp.route("/volunteer-projects", methods=["GET"])
@require_roles(*ANY_ROLE)
def list_projects(_user_id: str, _role: str):
    status = request.args.get("status")
    rows = list(db.projects.values())
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    page, limit, offset, total = paginate(rows)
    return success_list([serialize_project(p) for p in page], limit, offset, total)


@bp.route("/volunteer-projects/<pid>", methods=["GET"])
@require_roles(*ANY_ROLE)
def get_one_project(pid: str, _user_id: str, _role: str):
    return success_object(serialize_project(get_project(pid)))


@bp.route("/volunteer-projects/<pid>/activate", methods=["POST"])
@require_roles("VolunteerCoordinator")
def activate_project(pid: str, _user_id: str, _role: str):
    proj = get_project(pid)
    if proj["status"] != "PLANNED":
        raise_err(ERR_INVALID_STATE, "Only a PLANNED project may be activated")
    proj["status"] = "ACTIVE"
    db.touch(proj)
    return success_object(serialize_project(proj))


@bp.route("/volunteer-projects/<pid>/close", methods=["POST"])
@require_roles("VolunteerCoordinator")
def close_project(pid: str, _user_id: str, _role: str):
    proj = get_project(pid)
    if proj["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Only an ACTIVE project may be closed")
    recompute_project_active_count(proj, touch_it=False)
    if proj["active_ticket_count"] != 0:
        raise_err(ERR_ACTIVE_TICKETS_REMAIN, "Project still has active tickets")
    proj["status"] = "CLOSED"
    db.touch(proj)
    return success_object(serialize_project(proj))


# ---------------------------------------------------------------------------
# Ticket queueing + claim-next (nested under the project)
# ---------------------------------------------------------------------------

@bp.route("/volunteer-projects/<pid>/tickets", methods=["POST"])
@require_roles("VolunteerCoordinator")
def create_ticket(pid: str, _user_id: str, _role: str):
    body = get_json_body()
    raw_item_id = body.get("item_id")
    # Tolerate a nested {"id": ...} reference object for the FK field.
    if isinstance(raw_item_id, dict) and isinstance(raw_item_id.get("id"), str):
        body = {**body, "item_id": raw_item_id["id"]}
    item_id = as_str(body, "item_id", required=True)

    proj = get_project(pid)  # path id first
    item = db.items.get(item_id)
    if item is None:
        raise_err(ERR_NOT_FOUND, f"Item not found: {item_id}")

    if proj["status"] not in ("PLANNED", "ACTIVE"):
        raise_err(ERR_INVALID_STATE, "Tickets may be queued only under PLANNED or ACTIVE projects")
    if item["status"] != "AVAILABLE":
        raise_err(ERR_ITEM_NOT_AVAILABLE, "Ticket creation requires an AVAILABLE item")

    approved_count = sum(
        1 for r in db.requests.values()
        if r["status"] == "APPROVED" and item_id in r["item_ids"]
    )
    score = digitization_priority(item["conservation_priority_score"], approved_count)

    ticket = {
        **db.make_common_fields(),
        "project_id": pid,
        "item_id": item_id,
        "priority_score": score,
        "status": "QUEUED",
        "claimed_by_user_id": None,
        "qc_fail_count": 0,
        "hours_logged": 0,
    }
    db.tickets[ticket["id"]] = ticket
    return success_object(serialize_ticket(ticket), 201)


@bp.route("/volunteer-projects/<pid>/tickets/claim-next", methods=["POST"])
@require_roles("Volunteer")
def claim_next(pid: str, _user_id: str, _role: str):
    proj = get_project(pid)
    if proj["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Tickets may be claimed only under an ACTIVE project")

    # selector policy: QUEUED tickets whose item is AVAILABLE;
    # rank priority_score DESC, tie-break created_at ASC (then insertion seq)
    pool = [
        t for t in db.tickets.values()
        if t["project_id"] == pid and t["status"] == "QUEUED"
        and (db.items.get(t["item_id"]) or {}).get("status") == "AVAILABLE"
    ]
    if not pool:
        raise_err(ERR_NO_CLAIMABLE_TICKETS, "No claimable tickets in this project")
    pool.sort(key=lambda t: (t.get("created_at", ""), t.get("_seq", 0)))
    best = max(pool, key=lambda t: t["priority_score"])
    # max() returns the first max in iteration order; iteration order above is
    # created_at-ascending, so ties resolve to the earliest-created ticket.
    best["status"] = "CLAIMED"
    best["claimed_by_user_id"] = _user_id
    db.touch(best)
    recompute_project_active_count(proj)
    return success_object(serialize_ticket(best))
