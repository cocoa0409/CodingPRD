"""Control items: global reads, implement, verify (PRD 3.3)."""

from flask import Blueprint, request

import db
from clock import CLOCK
from errors import ApiError
from middleware import auth, paginate, NON_CONTRACTOR_ROLES
from response import ok, ok_list
from services import core, ops

bp = Blueprint("controls", __name__)


@bp.route("/safety/controls", methods=["GET"])
def list_controls():
    auth(NON_CONTRACTOR_ROLES)
    hazard_id = request.args.get("hazard_id")
    implementer_id = request.args.get("implementer_id")
    status = request.args.get("status")
    items = list(db.DB["controls"].values())
    if hazard_id is not None:
        items = [c for c in items if c["hazard_id"] == hazard_id]
    if implementer_id is not None:
        items = [c for c in items if c["implementer_id"] == implementer_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items = core.sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([core.control_view(c) for c in page], total, limit, offset)


@bp.route("/safety/controls/<cid>", methods=["GET"])
def get_control(cid):
    auth(NON_CONTRACTOR_ROLES)
    c = core.get_or_404("controls", cid, "ControlItem")
    return ok(core.control_view(c))


@bp.route("/safety/controls/<cid>/implement", methods=["POST"])
def implement_control(cid):
    auth(["Supervisor", "SafetyManager"])
    c = core.get_or_404("controls", cid, "ControlItem")
    body = core.body_json()
    implemented_at = core.opt_datetime(body, "implemented_at", default=None)
    if implemented_at is None:
        implemented_at = CLOCK.now()
    h = db.DB["hazards"].get(c["hazard_id"])
    if h is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Hazard not found")
    if c["status"] not in ("PLANNED", "OVERDUE"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a PLANNED or OVERDUE control can be implemented")
    if c["status"] == "PLANNED" and h["status"] not in (
            "CONTROLS_PLANNED", "IN_PROGRESS", "PENDING_VERIFICATION"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Parent hazard does not permit implementation")
    if implemented_at > CLOCK.now():
        raise ApiError("ERR_FUTURE_DATE_NOT_ALLOWED", 422,
                       "implemented_at must not be in the future")
    was_overdue = c["status"] == "OVERDUE"
    c["status"] = "IMPLEMENTED"
    c["implemented_at"] = implemented_at
    core.touch(c)
    if was_overdue:
        ops.recompute_overdue_counts(h)
    ops.advance_hazard(h)
    return ok(core.control_view(c))


@bp.route("/safety/controls/<cid>/verify", methods=["POST"])
def verify_control(cid):
    user_id, _ = auth(["SafetyManager"])
    c = core.get_or_404("controls", cid, "ControlItem")
    body = core.body_json()
    outcome = core.req_enum(body, "outcome", ("PASS", "FAIL"))
    outcome_note = core.opt_str(body, "outcome_note", default=None)
    new_due = core.opt_datetime(body, "due_date", default=None)
    if outcome == "FAIL" and (outcome_note is None or new_due is None):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "A FAIL outcome requires outcome_note and a new due_date")
    h = db.DB["hazards"].get(c["hazard_id"])
    if h is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Hazard not found")
    if h["status"] != "PENDING_VERIFICATION":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Control verification requires the hazard to be "
                       "PENDING_VERIFICATION")
    if c["status"] != "IMPLEMENTED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an IMPLEMENTED control can be verified")
    if user_id == c["implementer_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 422,
                       "The verifier must differ from the implementer")

    if outcome == "PASS":
        now = CLOCK.now()
        c["status"] = "VERIFIED"
        c["verified_by"] = user_id
        c["verified_at"] = now
        if outcome_note is not None:
            c["outcome_note"] = outcome_note
        core.touch(c)
        # CONTROL_VERIFIED event for the implementer; timeliness 1.25 when
        # verified on or before the control's due date.
        on_time = now <= c["due_date"]
        ops.create_event(h["program_id"], c["implementer_id"],
                         "CONTROL_VERIFIED", c["id"], timeliness=on_time)
        # Closing the last non-verified control closes the hazard, cascading to
        # LINKED observations and their reporter events.
        ops.advance_hazard(h)
    else:
        c["status"] = "PLANNED"
        c["due_date"] = new_due
        c["implemented_at"] = None
        c["outcome_note"] = outcome_note
        core.touch(c)
        # Revision loop: failed verification reopens implementation.
        if h["status"] == "PENDING_VERIFICATION":
            h["status"] = "IN_PROGRESS"
            core.touch(h)
    return ok(core.control_view(c))
