"""Logical clock: set_current_utc + scheduled deferred actions on advance.

After each advance:
  1. SCHEDULED reviews past their grace window flip to OVERDUE (REVIEW_OVERDUE).
  2. TRAINED_CURRENT staff whose latest training expired flip to TRAINED_EXPIRED
     (TRAINING_LAPSED).
  3. Every school's posture is recomputed (POSTURE_CHANGED where it moved).
"""
from flask import Blueprint

from db import db, now, set_clock, touch
from middleware import body, req_str, require_roles
from response import success
from services import (annual_review_grace_delta, current_training_status, emit,
                      recompute_posture, school_of_plan)
from util import iso, parse_dt

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@require_roles("District504Director")
def set_current_utc():
    d = body()
    target = parse_dt(req_str(d, "to_iso8601"), "to_iso8601")
    set_clock(target)

    # 1. Reviews still SCHEDULED past scheduled_for + grace -> OVERDUE.
    flipped_schools = {}
    for rv in list(db.reviews.values()):
        if rv["review_status"] != "SCHEDULED":
            continue
        if now() > rv["scheduled_for"] + annual_review_grace_delta(rv["review_type"]):
            rv["review_status"] = "OVERDUE"
            touch(rv)
            school = school_of_plan(db.plans.get(rv["plan_id"], {})) if db.plans.get(rv["plan_id"]) else None
            emit("REVIEW_OVERDUE", school["id"] if school else None, rv["id"], None,
                 {"plan_id": rv["plan_id"], "review_type": rv["review_type"],
                  "scheduled_for": iso(rv["scheduled_for"])})
            if school is not None:
                flipped_schools[school["id"]] = school

    # 2. Training statuses that lapsed -> TRAINED_EXPIRED (TRAINING_LAPSED).
    for staff in db.staff.values():
        if staff.get("current_training_status") != "TRAINED_CURRENT":
            continue
        new_status = current_training_status(staff)
        if new_status == "TRAINED_EXPIRED":
            staff["current_training_status"] = new_status
            touch(staff)
            emit("TRAINING_LAPSED", staff["school_id"], staff["id"], None,
                 {"staff_id": staff["id"]})
            flipped_schools[staff["school_id"]] = db.schools.get(staff["school_id"])

    # 3. Recompute every school's posture (all inputs may have shifted).
    for school in list(db.schools.values()):
        recompute_posture(school)

    return success({"now": iso(now())}, 200)
