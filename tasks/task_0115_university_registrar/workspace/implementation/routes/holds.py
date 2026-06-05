"""Hold routes: place a hold, clear a hold."""
from __future__ import annotations

from flask import Blueprint

import db
from errors import err
from middleware import authenticate, current_role, require_roles
from response import ok_object
from services import helpers as h
from services import serialize
from services.entities import new_common, touch

bp = Blueprint("holds", __name__)

HOLD_TYPES = {"FINANCIAL", "ADVISING"}


@bp.post("/holds")
def create_hold():
    authenticate()
    require_roles("Bursar", "Advisor")
    body = h.get_json_body()

    student_id = h.require_string(body, "student_id")
    hold_type = h.require_enum(body, "hold_type", HOLD_TYPES)
    reason = h.require_string(body, "reason")
    h.get_student(student_id)

    rec = new_common("Hold")
    rec.update({
        "student_id": student_id,
        "hold_type": hold_type,
        "reason": reason,
        "status": "ACTIVE",
    })
    db.holds[rec["id"]] = rec
    return ok_object(serialize.hold(rec), 201)


@bp.post("/holds/<hold_id>/clear")
def clear_hold(hold_id):
    authenticate()
    require_roles("Bursar", "Advisor")
    hold = h.get_hold(hold_id)

    # State validity (priority 5): only an ACTIVE hold may be cleared.
    if hold["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Only an ACTIVE hold can be cleared")

    # Wrong-clearer check (priority 20): FINANCIAL by Bursar, ADVISING by Advisor.
    role = current_role()
    if hold["hold_type"] == "FINANCIAL" and role != "Bursar":
        raise err("ERR_HOLD_WRONG_CLEARER", "FINANCIAL holds may be cleared only by a Bursar")
    if hold["hold_type"] == "ADVISING" and role != "Advisor":
        raise err("ERR_HOLD_WRONG_CLEARER", "ADVISING holds may be cleared only by an Advisor")

    hold["status"] = "CLEARED"
    touch(hold)
    return ok_object(serialize.hold(hold), 200)
