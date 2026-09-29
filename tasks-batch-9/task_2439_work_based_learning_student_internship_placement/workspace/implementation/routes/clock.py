"""The logical clock and its three deferred-expiry sweeps (PRD 2.4)."""

from flask import Blueprint

import derive
from auth import require
from db import by_created, days_between, db, fmt_ts, set_and_touch
from response import ok
from validation import f_str, get_body, parse_iso_dt

bp = Blueprint("clock", __name__)

OUTCOME_WINDOW_DAYS = 180


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require("WblCoordinator")
    body = get_body()
    raw = f_str(body, "to_iso8601")
    moment = parse_iso_dt(raw, "to_iso8601")
    db.clock = moment
    new_date = moment.date().isoformat()

    # sweep 1: work permits
    permits_expired = 0
    for permit in by_created(list(db.work_permits.values())):
        if permit["status"] != "ISSUED":
            continue
        if permit["expires_on"] is None or permit["expires_on"] >= new_date:
            continue
        set_and_touch(permit, status="EXPIRED")
        permits_expired += 1
        derive.flag_placements_of_student(permit["student_id"])

    # sweep 2: partnership agreements
    agreements_expired = 0
    for agreement in by_created(list(db.agreements.values())):
        if agreement["status"] != "EXECUTED":
            continue
        if agreement["expires_on"] is None or agreement["expires_on"] >= new_date:
            continue
        set_and_touch(agreement, status="EXPIRED")
        agreements_expired += 1
        for placement in derive.placements_of_agreement(agreement["id"]):
            if placement["lifecycle_status"] == "ACTIVE":
                set_and_touch(placement, compliance_status="FLAGGED")

    # sweep 3: placement outcomes
    outcomes_late = 0
    for outcome in by_created(list(db.placement_outcomes.values())):
        if outcome["status"] != "RECORDED":
            continue
        placement = db.placements.get(outcome["placement_id"])
        if placement is None or not placement.get("completed_on"):
            continue
        if days_between(placement["completed_on"], new_date) <= OUTCOME_WINDOW_DAYS:
            continue
        set_and_touch(outcome, status="LATE_UNVERIFIABLE")
        outcomes_late += 1

    return ok({
        "current_utc": fmt_ts(moment),
        "permits_expired_count": permits_expired,
        "agreements_expired_count": agreements_expired,
        "outcomes_late_unverifiable_count": outcomes_late,
    })
