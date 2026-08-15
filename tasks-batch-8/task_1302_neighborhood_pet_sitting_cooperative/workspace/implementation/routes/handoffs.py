"""AccessHandoff endpoints: per-assignment lookup, update (PUT),
confirm-handoff, confirm-return, report-lost."""

from datetime import timedelta

from flask import Blueprint

import clock
import db
from errors import (
    ApiError,
    ERR_FORBIDDEN,
    ERR_HANDOFF_TOO_EARLY,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
)
from middleware import body, require_roles
from response import ok, ok_array
from routes.assignments import get_assignment_or_404
from serializers import handoff_view
from services.calc import SCORE_ACCESS_LOST, adjust_reliability, handoff_for_assignment
from util import new_id, touch

bp = Blueprint("handoffs", __name__)

HANDOFF_METHODS = {"IN_PERSON", "LOCKBOX", "CONCIERGE", "SMART_LOCK"}
RETURNABLE_ASSIGNMENT_STATES = {
    "COMPLETED_PENDING_REVIEW",
    "SETTLED",
    "CANCELLED_BY_OWNER",
    "CANCELLED_BY_SITTER",
}


def get_handoff_or_404(handoff_id):
    handoff = db.store["handoffs"].get(handoff_id)
    if handoff is None:
        raise ApiError(
            ERR_NOT_FOUND, 404, f"AccessHandoff {handoff_id} does not exist"
        )
    return handoff


def _may_see_code(handoff, assignment, user_id, role):
    """The access ciphertext is revealed to the owner (and admins) freely, but
    to the sitter only once the assignment is confirmed and the current time
    is within the two hours preceding scheduled_start_at."""
    if role == "CoopAdmin" or user_id == assignment["owner_member_id"]:
        return True
    if user_id == assignment["sitter_member_id"]:
        return clock.now() >= assignment["scheduled_start_at"] - timedelta(hours=2)
    return False


@bp.get("/coop/sitting-assignments/<assignment_id>/access-handoff")
def get_handoff_for_assignment(assignment_id):
    user_id, role = require_roles("CoopAdmin", "Member")
    assignment = get_assignment_or_404(assignment_id)
    handoff = handoff_for_assignment(assignment["id"])
    if handoff is None:
        return ok_array([])
    reveal = _may_see_code(handoff, assignment, user_id, role)
    return ok_array([handoff_view(handoff, reveal_code=reveal)])


@bp.put("/coop/access-handoffs/<handoff_id>")
def update_handoff(handoff_id):
    user_id, _ = require_roles("Member")
    handoff = get_handoff_or_404(handoff_id)
    assignment = db.store["assignments"].get(handoff["sitting_assignment_id"])
    if handoff["status"] != "PENDING":
        raise ApiError(
            ERR_INVALID_STATE, 409, "Access details may only be set while PENDING"
        )
    if assignment is None or user_id != assignment["owner_member_id"]:
        raise ApiError(
            ERR_FORBIDDEN, 403, "Only the owner may set access details"
        )
    data = body()
    handoff_method = data.get("handoff_method")
    if handoff_method not in HANDOFF_METHODS:
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            "handoff_method must be one of IN_PERSON, LOCKBOX, CONCIERGE, SMART_LOCK",
        )
    access_code_ciphertext = data.get("access_code_ciphertext")
    if not isinstance(access_code_ciphertext, str) or not access_code_ciphertext:
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "access_code_ciphertext is required"
        )
    handoff["handoff_method"] = handoff_method
    handoff["access_code_ciphertext"] = access_code_ciphertext
    touch(handoff)
    return ok(handoff_view(handoff))


@bp.post("/coop/access-handoffs/<handoff_id>/confirm-handoff")
def confirm_handoff(handoff_id):
    user_id, _ = require_roles("Member")
    handoff = get_handoff_or_404(handoff_id)
    assignment = db.store["assignments"].get(handoff["sitting_assignment_id"])
    if handoff["status"] != "PENDING":
        raise ApiError(
            ERR_INVALID_STATE, 409, "Handoff must be PENDING to confirm"
        )
    if assignment is None or user_id != assignment["owner_member_id"]:
        raise ApiError(ERR_FORBIDDEN, 403, "Only the owner may confirm the handoff")
    if clock.now() < assignment["scheduled_start_at"] - timedelta(hours=2):
        raise ApiError(
            ERR_HANDOFF_TOO_EARLY,
            409,
            "Handoff cannot be confirmed earlier than 2h before the scheduled start",
        )
    handoff["status"] = "HANDED_OFF"
    handoff["handed_off_at"] = clock.now()
    touch(handoff)
    return ok(handoff_view(handoff))


@bp.post("/coop/access-handoffs/<handoff_id>/confirm-return")
def confirm_return(handoff_id):
    user_id, _ = require_roles("Member")
    handoff = get_handoff_or_404(handoff_id)
    assignment = db.store["assignments"].get(handoff["sitting_assignment_id"])
    if handoff["status"] != "HANDED_OFF":
        raise ApiError(
            ERR_INVALID_STATE, 409, "Handoff must be HANDED_OFF to confirm return"
        )
    if assignment is None or user_id != assignment["owner_member_id"]:
        raise ApiError(
            ERR_FORBIDDEN, 403, "Only the owner may confirm the return"
        )
    if assignment["status"] not in RETURNABLE_ASSIGNMENT_STATES:
        raise ApiError(
            ERR_INVALID_STATE,
            409,
            "Assignment must be completed, settled, or cancelled before access return",
        )
    handoff["status"] = "RETURNED"
    handoff["returned_at"] = clock.now()
    touch(handoff)
    return ok(handoff_view(handoff))


@bp.post("/coop/access-handoffs/<handoff_id>/report-lost")
def report_lost(handoff_id):
    user_id, _ = require_roles("Member")
    handoff = get_handoff_or_404(handoff_id)
    assignment = db.store["assignments"].get(handoff["sitting_assignment_id"])
    if handoff["status"] != "HANDED_OFF":
        raise ApiError(
            ERR_INVALID_STATE, 409, "Handoff must be HANDED_OFF to report lost"
        )
    if assignment is None or user_id not in (
        assignment["owner_member_id"],
        assignment["sitter_member_id"],
    ):
        raise ApiError(
            ERR_FORBIDDEN, 403, "Only the owner or the sitter may report access lost"
        )
    handoff["status"] = "LOST"
    touch(handoff)
    # Auto-file a MAJOR incident and dock the sitter's reliability.
    now = clock.now()
    incident = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
        "sitting_assignment_id": assignment["id"],
        "reporter_member_id": user_id,
        "severity": "MAJOR",
        "description": "Access credentials lost",
        "vet_involved": False,
        "at_fault_member_id": None,
        "status": "FILED",
        "_decided_at": None,
    }
    db.store["incidents"][incident["id"]] = incident
    sitter = db.store["members"].get(assignment["sitter_member_id"])
    if sitter is not None:
        adjust_reliability(sitter, SCORE_ACCESS_LOST)
    return ok(handoff_view(handoff))
