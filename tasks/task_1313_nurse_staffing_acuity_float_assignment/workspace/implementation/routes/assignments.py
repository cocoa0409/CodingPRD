"""ShiftAssignment endpoints: list/get plus the response/confirmation/
cancellation/completion lifecycle."""

from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_ASSIGNMENT_NOT_FOUND,
    ERR_NOT_RESOURCE_OWNER,
    ERR_ASSIGNMENT_NOT_PROPOSED,
    ERR_ASSIGNMENT_NOT_ACCEPTED,
    ERR_ASSIGNMENT_NOT_CONFIRMED,
    ERR_ASSIGNMENT_TERMINAL,
    ERR_SHIFT_NOT_OPEN,
    ERR_CHARGE_SLOT_TAKEN,
    ERR_SKILL_MIX_VIOLATION,
    ERR_COVERS_ACTIVE_SITTER,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services.core import (
    COUNTED_ASSIGNMENT_STATUSES,
    TERMINAL_ASSIGNMENT_STATUSES,
    assignments_of_shift,
    assignment_covers_filled_sitter,
    float_request_for_assignment,
    final_economics,
    maybe_auto_incentive_offer,
    refresh_shift_and_touch,
    shift_of,
    pub,
)
from util import get_json_body, req_num, req_int, parse_pagination, paginate, apply_filters

bp = Blueprint("assignments", __name__)


def _get_assignment_or_404(assignment_id: str) -> dict:
    a = db.assignments.get(assignment_id)
    if a is None:
        raise_err(ERR_ASSIGNMENT_NOT_FOUND, "Assignment not found")
    return a


@bp.get("/assignments")
@require_roles(*ALL_ROLES)
def list_assignments(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sorted(db.assignments.values(), key=lambda a: a["created_at"])
    items = apply_filters(items, {
        "shift_id": request.args.get("shift_id"),
        "nurse_id": request.args.get("nurse_id"),
        "status": request.args.get("status"),
        "source": request.args.get("source"),
    })
    page, total = paginate(items, limit, offset)
    return success_list([pub(a) for a in page], limit, offset, total)


@bp.get("/assignments/<assignmentId>")
@require_roles(*ALL_ROLES)
def get_assignment(assignmentId: str, _user_id: str, _role: str):
    return success_object(pub(_get_assignment_or_404(assignmentId)))


@bp.post("/assignments/<assignmentId>/accept")
@require_roles("StaffNurse")
def accept_assignment(assignmentId: str, _user_id: str, _role: str):
    a = _get_assignment_or_404(assignmentId)
    # Ownership (tier 4) before state (tier 6).
    if _user_id != a["nurse_id"]:
        raise_err(ERR_NOT_RESOURCE_OWNER, "Only the named nurse may accept this assignment")
    if a["status"] in TERMINAL_ASSIGNMENT_STATUSES:
        raise_err(ERR_ASSIGNMENT_TERMINAL, "Assignment is terminal")
    if a["status"] != "PROPOSED":
        raise_err(ERR_ASSIGNMENT_NOT_PROPOSED, "accept requires a PROPOSED assignment")
    a["status"] = "ACCEPTED"
    db.touch(a)
    refresh_shift_and_touch(shift_of(a))
    return success_object(pub(a), 200)


@bp.post("/assignments/<assignmentId>/decline")
@require_roles("StaffNurse")
def decline_assignment(assignmentId: str, _user_id: str, _role: str):
    a = _get_assignment_or_404(assignmentId)
    if _user_id != a["nurse_id"]:
        raise_err(ERR_NOT_RESOURCE_OWNER, "Only the named nurse may decline this assignment")
    if a["status"] in TERMINAL_ASSIGNMENT_STATUSES:
        raise_err(ERR_ASSIGNMENT_TERMINAL, "Assignment is terminal")
    if a["status"] != "PROPOSED":
        raise_err(ERR_ASSIGNMENT_NOT_PROPOSED, "decline requires a PROPOSED assignment")
    a["status"] = "DECLINED"
    db.touch(a)
    if a["source"] == "FLOAT":
        fr = float_request_for_assignment(a["id"])
        if fr is not None and fr["status"] == "DEPLOYED":
            fr["status"] = "UNFULFILLED"
            db.touch(fr)
    return success_object(pub(a), 200)


@bp.post("/assignments/<assignmentId>/confirm")
@require_roles("ChargeNurse")
def confirm_assignment(assignmentId: str, _user_id: str, _role: str):
    a = _get_assignment_or_404(assignmentId)
    if a["status"] != "ACCEPTED":
        raise_err(ERR_ASSIGNMENT_NOT_ACCEPTED, "confirm requires an ACCEPTED assignment")
    shift = shift_of(a)
    if shift["status"] == "LOCKED":
        raise_err(ERR_SHIFT_NOT_OPEN, "Shift is LOCKED")

    # Charge-slot gate: no other counted is_charge assignment on the shift.
    counted = [x for x in assignments_of_shift(shift["id"])
               if x["status"] in COUNTED_ASSIGNMENT_STATUSES]
    if a["is_charge"]:
        for other in counted:
            if other["id"] != a["id"] and other.get("is_charge"):
                raise_err(ERR_CHARGE_SLOT_TAKEN,
                          "Another accepted/confirmed assignment already holds the charge designation")

    # Skill-mix gate: FLOAT_POOL share of counted assignments must not exceed
    # floor(counted / 2) after this confirmation (the counted set is unchanged
    # by confirmation, so the current figures are the post-confirm figures).
    float_count = sum(
        1 for x in counted
        if db.nurses[x["nurse_id"]]["employment_type"] == "FLOAT_POOL"
    )
    if float_count > len(counted) // 2:
        raise_err(ERR_SKILL_MIX_VIOLATION,
                  "Confirming would push the float-pool share above floor(counted/2)")

    a["status"] = "CONFIRMED"
    db.touch(a)
    refresh_shift_and_touch(shift)
    return success_object(pub(a), 200)


@bp.post("/assignments/<assignmentId>/revoke-confirmation")
@require_roles("ChargeNurse")
def revoke_confirmation(assignmentId: str, _user_id: str, _role: str):
    a = _get_assignment_or_404(assignmentId)
    if a["status"] != "CONFIRMED":
        raise_err(ERR_ASSIGNMENT_NOT_CONFIRMED, "revoke-confirmation requires a CONFIRMED assignment")
    shift = shift_of(a)
    if shift["status"] == "LOCKED":
        raise_err(ERR_SHIFT_NOT_OPEN, "Shift is LOCKED")
    a["status"] = "ACCEPTED"
    db.touch(a)
    refresh_shift_and_touch(shift)
    return success_object(pub(a), 200)


@bp.post("/assignments/<assignmentId>/cancel")
@require_roles("ChargeNurse")
def cancel_assignment(assignmentId: str, _user_id: str, _role: str):
    a = _get_assignment_or_404(assignmentId)
    if a["status"] in TERMINAL_ASSIGNMENT_STATUSES:
        raise_err(ERR_ASSIGNMENT_TERMINAL, "Assignment is terminal")
    if assignment_covers_filled_sitter(a["id"]):
        raise_err(ERR_COVERS_ACTIVE_SITTER,
                  "Assignment currently covers a FILLED sitter request")

    shift = shift_of(a)
    was_counted = a["status"] in COUNTED_ASSIGNMENT_STATUSES
    posture_before = shift["staffing_posture"]

    a["status"] = "CANCELLED"
    db.touch(a)

    if a["source"] == "FLOAT":
        fr = float_request_for_assignment(a["id"])
        if fr is not None and fr["status"] == "DEPLOYED":
            fr["status"] = "RELEASED"
            db.touch(fr)

    if a["source"] == "INCENTIVE":
        for o in db.offers.values():
            if o.get("claimed_assignment_id") == a["id"] and o["status"] == "CLAIMED":
                o["status"] = "WITHDRAWN"  # reserve released
                db.touch(o)
                break

    refresh_shift_and_touch(shift)

    # Auto-incentive arm: only a confirmed-staff loss (counted cancellation on
    # an unlocked shift) that flips posture from ADEQUATE can fire it.
    if was_counted and shift["status"] != "LOCKED":
        maybe_auto_incentive_offer(shift, posture_before, shift["staffing_posture"])

    return success_object(pub(a), 200)


@bp.post("/assignments/<assignmentId>/complete")
@require_roles("ChargeNurse")
def complete_assignment(assignmentId: str, _user_id: str, _role: str):
    a = _get_assignment_or_404(assignmentId)
    body = get_json_body()
    actual_hours_worked = req_num(body, "actual_hours_worked")
    if not (actual_hours_worked > 0 and actual_hours_worked <= 16):
        raise_err(ERR_INVALID_REQUEST, "actual_hours_worked must be > 0 and <= 16")
    missed_breaks = req_int(body, "missed_breaks")
    if missed_breaks < 0:
        raise_err(ERR_INVALID_REQUEST, "missed_breaks must be >= 0")

    if a["status"] != "CONFIRMED":
        raise_err(ERR_ASSIGNMENT_NOT_CONFIRMED, "complete requires a CONFIRMED assignment")
    if assignment_covers_filled_sitter(a["id"]):
        raise_err(ERR_COVERS_ACTIVE_SITTER,
                  "Assignment currently covers a FILLED sitter request")

    nurse = db.nurses[a["nurse_id"]]
    final_cost, final_ot = final_economics(nurse, a, actual_hours_worked, missed_breaks)

    a["status"] = "COMPLETED"
    a["actual_hours_worked"] = actual_hours_worked
    a["missed_breaks"] = missed_breaks
    a["final_cost_cents"] = final_cost
    a["final_ot_hours"] = final_ot
    db.touch(a)

    if a["source"] == "INCENTIVE":
        for o in db.offers.values():
            if o.get("claimed_assignment_id") == a["id"] and o["status"] == "CLAIMED":
                o["status"] = "SETTLED"  # reserve moves to spent
                db.touch(o)
                break

    refresh_shift_and_touch(shift_of(a))
    return success_object(pub(a), 200)
