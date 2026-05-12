"""Case posture computation per PRD §2.8 / SCAFFOLD calc case_posture.

Priority order:
  1) Case has any Evidence with status=REBUTTED -> RESTRICTED
  2) Case has any SCHEDULED Hearing whose scheduled_start in [now, now+24h) -> RESTRICTED
  3) Case.status == ON_HOLD -> FROZEN
  4) Otherwise -> OPEN

Recompute mutates the Case row's posture (and bumps version/updated_at IF the
posture actually changed) so cascaded mutations carry their own version bump.
"""

from datetime import timedelta

import clock
import db
import helpers


RESTRICTED_HEARING_WINDOW_HOURS = 24


def derive(case):
    case_id = case["id"]
    # Rule 1: any REBUTTED evidence
    for ev in db.evidence_rows.values():
        if ev["case_id"] == case_id and ev["status"] == "REBUTTED":
            return "RESTRICTED"

    # Rule 2: any SCHEDULED hearing within next 24h
    now = clock.now()
    horizon = now + timedelta(hours=RESTRICTED_HEARING_WINDOW_HOURS)
    for h in db.hearings.values():
        if h["case_id"] != case_id:
            continue
        if h["status"] != "SCHEDULED":
            continue
        if h["scheduled_start"] >= now and h["scheduled_start"] < horizon:
            return "RESTRICTED"

    # Rule 3: ON_HOLD
    if case["status"] == "ON_HOLD":
        return "FROZEN"

    return "OPEN"


def recompute(case):
    new_posture = derive(case)
    if case.get("posture") != new_posture:
        case["posture"] = new_posture
        helpers.bump(case)
    return new_posture


def recompute_by_id(case_id):
    case = db.cases.get(case_id)
    if case is None:
        return None
    return recompute(case)
