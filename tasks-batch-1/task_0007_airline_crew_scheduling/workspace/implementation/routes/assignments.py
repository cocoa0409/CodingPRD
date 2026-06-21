"""Assignment routes (PRD §3.3)."""
from flask import Blueprint, request

import db
from errors import (
    not_found, forbidden, invalid_state, cross_entity_state,
    faa_duty_cap, faa_flight_cap, crew_rest_violation,
)
from middleware import require_roles, ROLE_PLANNER, ROLE_OPS, ROLE_CREW
from response import success, paginated
from routes.common import parse_pagination, sort_by_created_at, slice_page
from services.calc import faa_preview_violations, crew_rest_passes
from services.entity import touch


bp = Blueprint("assignments", __name__)


@bp.route("/assignments", methods=["GET"])
def list_assignments():
    user_id, role = require_roles({ROLE_PLANNER, ROLE_OPS, ROLE_CREW})
    limit, offset = parse_pagination()
    rows = list(db.assignments.values())
    pairing_id = request.args.get("pairing_id")
    crew_member_id = request.args.get("crew_member_id")
    state = request.args.get("state")
    if pairing_id:
        rows = [r for r in rows if r["pairing_id"] == pairing_id]
    if crew_member_id:
        rows = [r for r in rows if r["crew_member_id"] == crew_member_id]
    if state:
        rows = [r for r in rows if r["state"] == state]
    if role == ROLE_CREW:
        rows = [r for r in rows if r["crew_member_id"] == user_id]
    rows = sort_by_created_at(rows)
    page, total = slice_page(rows, limit, offset)
    return paginated(page, limit, offset, total)


@bp.route("/assignments/<assignment_id>", methods=["GET"])
def get_assignment(assignment_id):
    user_id, role = require_roles({ROLE_PLANNER, ROLE_OPS, ROLE_CREW})
    a = db.assignments.get(assignment_id)
    if a is None:
        raise not_found("Assignment not found")
    return success(a, status=200)


@bp.route("/assignments/<assignment_id>/confirm", methods=["POST"])
def confirm_assignment(assignment_id):
    user_id, role = require_roles({ROLE_CREW})
    a = db.assignments.get(assignment_id)
    if a is None:
        raise not_found("Assignment not found")
    # Ownership.
    if a["crew_member_id"] != user_id:
        raise forbidden("Assignment not owned by acting crew member")
    # State eligibility (priority 5).
    if a["state"] != "SCHEDULED":
        raise invalid_state(f"Cannot confirm Assignment in state {a['state']!r}")
    # Cross-entity state (priority 6): parent Pairing must be AWARDED.
    p = db.pairings.get(a["pairing_id"])
    if p is None:
        raise not_found("Parent Pairing not found")
    if p["state"] != "AWARDED":
        raise cross_entity_state(
            f"Parent Pairing must be AWARDED, got {p['state']!r}"
        )

    # Business-safety checks (priorities 7-9).
    cm = db.crew_members[a["crew_member_id"]]
    duty_exceeds, flight_exceeds = faa_preview_violations(cm, p)
    if duty_exceeds:
        raise faa_duty_cap()
    if flight_exceeds:
        raise faa_flight_cap()
    if not crew_rest_passes(cm, p):
        raise crew_rest_violation()

    a["state"] = "CONFIRMED"
    touch(a)
    return success(a, status=200)
