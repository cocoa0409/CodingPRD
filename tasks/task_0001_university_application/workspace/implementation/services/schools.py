"""School posture and confirmed-enrollment bookkeeping."""

import db
import util


def recompute_posture(school_id: str) -> None:
    school = db.schools.get(school_id)
    if school is None:
        return
    target = school["target_class_size"]
    count = school["confirmed_enrollment_count"]
    if count < target:
        new_posture = "OPEN"
    elif count == target:
        new_posture = "AT_TARGET"
    else:
        new_posture = "OVER_TARGET"
    if school["posture"] != new_posture:
        school["posture"] = new_posture


def inc_enrollment(school_id: str) -> None:
    school = db.schools[school_id]
    school["confirmed_enrollment_count"] += 1
    util.stamp_update(school)
    recompute_posture(school_id)


def dec_enrollment(school_id: str) -> None:
    school = db.schools[school_id]
    school["confirmed_enrollment_count"] -= 1
    util.stamp_update(school)
    recompute_posture(school_id)
