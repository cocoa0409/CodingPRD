"""testing_requirement / exam_pass_evaluation calculations."""

import db
from services import core

PASSING_PERCENTILE = 23


def recompute_testing_satisfied(enrollment):
    satisfied = False
    for reg in db.test_registrations.values():
        if reg["enrollment_id"] != enrollment["id"]:
            continue
        if reg["status"] == "EXCUSED":
            satisfied = True
            break
        if reg["status"] == "SCORED" and reg["passed"] is True:
            satisfied = True
            break
    if enrollment["testing_satisfied"] != satisfied:
        enrollment["testing_satisfied"] = satisfied
        core.touch(enrollment)
