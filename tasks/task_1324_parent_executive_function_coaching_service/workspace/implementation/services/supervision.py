"""Supervision requirement recompute (pinned non-circular order, PRD §2.9)."""
from datetime import timedelta

import db
import middleware as mw

SUPERVISION_DIVISOR = {"ASSOCIATE": 2, "CERTIFIED": 4, "SUPERVISOR": 6}
CASELOAD_CAP = {"ASSOCIATE": 12, "CERTIFIED": 20, "SUPERVISOR": 28}


def recompute_coach(coach):
    # (1) active caseload
    coach["active_caseload"] = sum(
        1 for p in db.plans.values()
        if p["coach_id"] == coach["id"] and p["status"] == "ACTIVE"
    )
    # (2) required hours: floor(caseload / divisor)
    coach["required_supervision_hours"] = coach["active_caseload"] // SUPERVISION_DIVISOR[coach["credential_level"]]
    # (3) verified hours in rolling 30-day window, inclusive both ends
    window_start = db.clock - timedelta(days=30)
    total = 0
    for r in db.supervision_records.values():
        if r["coach_id"] == coach["id"] and r["status"] == "VERIFIED" and r["verified_at_dt"] is not None:
            if window_start <= r["verified_at_dt"] <= db.clock:
                total += r["hours"]
    coach["verified_supervision_hours_30d"] = total
    # (4)+(5) deficit flip (INACTIVE untouched)
    deficit = total < coach["required_supervision_hours"]
    if deficit and coach["status"] == "AVAILABLE":
        coach["status"] = "SUPERVISION_DEFICIT"
    elif not deficit and coach["status"] == "SUPERVISION_DEFICIT":
        coach["status"] = "AVAILABLE"
