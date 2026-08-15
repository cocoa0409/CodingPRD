"""IssueTicket routes."""

from flask import Blueprint, request

import db
from errors import fail
from helpers import (get_json_body, require_str, require_enum, paginate,
                     sort_by_created, get_or_404)
from middleware import require_roles
from response import success_object, success_list
from services import calc, workflow

bp = Blueprint("issues", __name__)

CATEGORIES = ("ENCROACHMENT", "NOISE", "PROHIBITED_ITEM", "COPYRIGHT", "CONDUCT")
SEVERITIES = ("MINOR", "MAJOR", "CRITICAL")


def issue_view(t):
    return {k: t[k] for k in (
        "id", "convention_id", "exhibitor_id", "reporter_user_id", "category",
        "severity", "description", "status", "outcome", "strike_points_applied",
        "created_at", "updated_at", "version")}


@bp.route("/issue-tickets", methods=["POST"])
def create_issue_ticket():
    user_id, _ = require_roles("OperationsStaff", "ShowDirector")
    body = get_json_body()
    convention_id = require_str(body, "convention_id")
    exhibitor_id = require_str(body, "exhibitor_id")
    category = require_enum(body, "category", CATEGORIES)
    severity = require_enum(body, "severity", SEVERITIES)
    description = require_str(body, "description")
    if db.conventions.get(convention_id) is None:
        fail("ERR_NOT_FOUND", "convention_id does not exist")
    if db.exhibitors.get(exhibitor_id) is None:
        fail("ERR_NOT_FOUND", "exhibitor_id does not exist")
    t = {
        "id": db.new_id(),
        "convention_id": convention_id,
        "exhibitor_id": exhibitor_id,
        "reporter_user_id": user_id,
        "category": category,
        "severity": severity,
        "description": description,
        "status": "OPEN",
        "outcome": None,
        "strike_points_applied": 0,
    }
    db.stamp_created(t)
    db.issue_tickets[t["id"]] = t
    return success_object(issue_view(t), 201)


@bp.route("/issue-tickets", methods=["GET"])
def list_issue_tickets():
    require_roles("ShowDirector", "OperationsStaff")
    items = list(db.issue_tickets.values())
    for f in ("convention_id", "exhibitor_id", "status", "severity"):
        v = request.args.get(f)
        if v is not None:
            items = [t for t in items if t[f] == v]
    items = sort_by_created(items)
    limit, offset, total, page = paginate(items)
    return success_list([issue_view(t) for t in page], limit, offset, total)


@bp.route("/issue-tickets/<issueTicketId>", methods=["GET"])
def get_issue_ticket(issueTicketId):
    require_roles("ShowDirector", "OperationsStaff")
    t = get_or_404(db.issue_tickets, issueTicketId)
    return success_object(issue_view(t), 200)


@bp.route("/issue-tickets/<issueTicketId>/triage", methods=["POST"])
def triage_issue(issueTicketId):
    require_roles("ShowDirector")
    t = get_or_404(db.issue_tickets, issueTicketId)
    if t["status"] != "OPEN":
        fail("ERR_INVALID_TRANSITION", "triage requires OPEN")
    t["status"] = "TRIAGED"
    db.touch(t)
    return success_object(issue_view(t), 200)


@bp.route("/issue-tickets/<issueTicketId>/escalate", methods=["POST"])
def escalate_issue(issueTicketId):
    require_roles("ShowDirector")
    t = get_or_404(db.issue_tickets, issueTicketId)
    if t["status"] not in ("OPEN", "TRIAGED"):
        fail("ERR_INVALID_TRANSITION", "escalate requires OPEN or TRIAGED")
    t["status"] = "ESCALATED"
    db.touch(t)
    return success_object(issue_view(t), 200)


@bp.route("/issue-tickets/<issueTicketId>/resolve", methods=["POST"])
def resolve_issue(issueTicketId):
    user_id, _ = require_roles("ShowDirector")
    t = get_or_404(db.issue_tickets, issueTicketId)
    body = get_json_body()
    outcome = require_enum(body, "outcome", ("GUILTY", "UNFOUNDED"))
    if t["status"] not in ("OPEN", "TRIAGED", "ESCALATED"):
        fail("ERR_INVALID_TRANSITION",
             "resolve requires OPEN, TRIAGED, or ESCALATED")
    if user_id == t["reporter_user_id"]:
        fail("ERR_DUTY_SEGREGATION",
             "The resolver must differ from the reporter")
    t["status"] = "RESOLVED"
    t["outcome"] = outcome
    if outcome == "GUILTY":
        pts = calc.POINTS_BY_SEVERITY[t["severity"]]
        t["strike_points_applied"] = pts
        db.touch(t)
        exhibitor = db.exhibitors[t["exhibitor_id"]]
        workflow.apply_strikes(exhibitor, pts)
    else:
        t["strike_points_applied"] = 0
        db.touch(t)
    return success_object(issue_view(t), 200)
