"""RepairOutcome reads, verification (segregation of duties), and rejection."""

from flask import Blueprint, g

import db
import serializers as ser
from errors import (
    ERR_INVALID_OUTCOME_STATE,
    ERR_OUTCOME_NOT_FOUND,
    ERR_SAFETY_HOLD,
    ERR_SELF_VERIFICATION_FORBIDDEN,
    raise_err,
)
from middleware import require_roles
from response import success
from util import list_response

bp = Blueprint("outcomes", __name__)

ALL_ROLES = ("Coordinator", "IntakeVolunteer", "Fixer", "SafetyOfficer")


def get_outcome_or_404(outcome_id):
    rec = db.outcomes.get(outcome_id)
    if rec is None:
        raise_err(ERR_OUTCOME_NOT_FOUND, "RepairOutcome %s does not exist" % outcome_id)
    return rec


@bp.get("/api/repair-outcomes")
@require_roles(*ALL_ROLES)
def list_outcomes():
    return list_response(
        db.outcomes.values(),
        ser.outcome,
        [
            ("item_id", "item_id"),
            ("fixer_id", "fixer_id"),
            ("verification_status", "verification_status"),
        ],
    )


@bp.get("/api/repair-outcomes/<outcome_id>")
@require_roles(*ALL_ROLES)
def get_outcome(outcome_id):
    return success(ser.outcome(get_outcome_or_404(outcome_id)), 200)


@bp.post("/api/repair-outcomes/<outcome_id>/verify")
@require_roles("Coordinator", "Fixer")
def verify_outcome(outcome_id):
    outcome = get_outcome_or_404(outcome_id)
    # State (priority 4).
    if outcome["verification_status"] != "RECORDED":
        raise_err(ERR_INVALID_OUTCOME_STATE, "Only a RECORDED outcome can be verified")
    # Safety gate (priority 5): no REPORTED incident of any severity on the item.
    for inc in db.incidents.values():
        if inc["item_id"] == outcome["item_id"] and inc["status"] == "REPORTED":
            raise_err(ERR_SAFETY_HOLD, "An open safety incident exists for this item")
    # Segregation of duties (priority 10): a Fixer never verifies their own work.
    if g.role == "Fixer" and g.user_id == outcome["fixer_id"]:
        raise_err(ERR_SELF_VERIFICATION_FORBIDDEN, "A fixer cannot verify their own outcome")
    outcome["verification_status"] = "VERIFIED"
    outcome["verified_by_user_id"] = g.user_id
    db.touch(outcome)
    item = db.items[outcome["item_id"]]
    item["status"] = "VERIFIED"
    db.touch(item)
    return success(ser.outcome(outcome), 200)


@bp.post("/api/repair-outcomes/<outcome_id>/reject")
@require_roles("Coordinator")
def reject_outcome(outcome_id):
    outcome = get_outcome_or_404(outcome_id)
    if outcome["verification_status"] != "RECORDED":
        raise_err(ERR_INVALID_OUTCOME_STATE, "Only a RECORDED outcome can be rejected")
    outcome["verification_status"] = "REJECTED"
    db.touch(outcome)
    item = db.items[outcome["item_id"]]
    item["assigned_fixer_id"] = None
    item["assigned_station_id"] = None
    item["status"] = "QUEUED"
    db.touch(item)
    return success(ser.outcome(outcome), 200)
