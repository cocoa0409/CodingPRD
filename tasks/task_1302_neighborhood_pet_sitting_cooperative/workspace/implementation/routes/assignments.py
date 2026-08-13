"""SittingAssignment endpoints: get, per-request lookup, checkout, settle."""

from flask import Blueprint

import clock
import db
from errors import (
    ApiError,
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_NO_CHECKIN,
    ERR_UNRESOLVED_INCIDENT,
)
from middleware import require_roles
from response import ok, ok_array
from routes.requests import get_request_or_404
from serializers import assignment_view
from services.calc import assignment_for_request, settle_assignment
from util import new_id, touch

bp = Blueprint("assignments", __name__)


def get_assignment_or_404(assignment_id):
    assignment = db.store["assignments"].get(assignment_id)
    if assignment is None:
        raise ApiError(
            ERR_NOT_FOUND, 404, f"SittingAssignment {assignment_id} does not exist"
        )
    return assignment


@bp.get("/coop/sitting-assignments/<assignment_id>")
def get_assignment(assignment_id):
    require_roles("CoopAdmin", "Member")
    return ok(assignment_view(get_assignment_or_404(assignment_id)))


@bp.get("/coop/sitting-requests/<request_id>/assignment")
def get_assignment_for_request(request_id):
    require_roles("CoopAdmin", "Member")
    get_request_or_404(request_id)
    assignment = assignment_for_request(request_id)
    items = [assignment_view(assignment)] if assignment is not None else []
    return ok_array(items)


@bp.post("/coop/sitting-assignments/<assignment_id>/checkout")
def checkout(assignment_id):
    user_id, _ = require_roles("Member")
    assignment = get_assignment_or_404(assignment_id)
    if assignment["status"] != "IN_PROGRESS":
        raise ApiError(
            ERR_INVALID_STATE, 409, "Assignment must be IN_PROGRESS to check out"
        )
    if user_id != assignment["sitter_member_id"]:
        raise ApiError(ERR_FORBIDDEN, 403, "Only the sitter may check out")
    has_checkin = any(
        e["sitting_assignment_id"] == assignment["id"] and e["event_type"] == "CHECK_IN"
        for e in db.store["entries"].values()
    )
    if not has_checkin:
        raise ApiError(ERR_NO_CHECKIN, 409, "Checkout requires a prior CHECK_IN entry")
    now = clock.now()
    assignment["actual_end_at"] = now
    assignment["status"] = "COMPLETED_PENDING_REVIEW"
    touch(assignment)
    # System-appended final CHECK_OUT entry log.
    entry = {
        "id": new_id(),
        "created_at": now,
        "_seq": db.next_seq(),
        "sitting_assignment_id": assignment["id"],
        "actor_member_id": user_id,
        "event_type": "CHECK_OUT",
        "occurred_at": now,
        "notes": None,
    }
    db.store["entries"][entry["id"]] = entry
    req = db.store["requests"].get(assignment["sitting_request_id"])
    if req is not None:
        req["status"] = "COMPLETED"
        touch(req)
    return ok(assignment_view(assignment))


@bp.post("/coop/sitting-assignments/<assignment_id>/settle")
def settle(assignment_id):
    require_roles("CoopAdmin")
    assignment = get_assignment_or_404(assignment_id)
    if assignment["status"] != "COMPLETED_PENDING_REVIEW":
        raise ApiError(
            ERR_INVALID_STATE,
            409,
            "Assignment must be COMPLETED_PENDING_REVIEW to settle",
        )
    open_incident = any(
        i["sitting_assignment_id"] == assignment["id"]
        and i["status"] in ("FILED", "UNDER_REVIEW")
        for i in db.store["incidents"].values()
    )
    if open_incident:
        raise ApiError(
            ERR_UNRESOLVED_INCIDENT,
            409,
            "Settlement is blocked by a FILED or UNDER_REVIEW incident",
        )
    settle_assignment(assignment)
    return ok(assignment_view(assignment))
