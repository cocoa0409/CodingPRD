"""Logical-clock sweeps (PRD 2.5): run in a fixed order on every clock advance.

(1) waiver expiry, (2) event no-show marking, (3) agreement auto-suspension on
rolling non-compliance, (4) agreement auto-expiry past term end.
"""
from db import db
from services.compliance import GRACE_DAYS, REQUIRED_CLEANUPS, recompute_standing, rolling_count
from services.core import (
    noshow_event_cascade,
    suspend_cascade,
    expire_cascade,
    touch,
)
from util import CLOCK, parse_date


def run_sweeps():
    today = CLOCK.today()

    # (1) Waiver expiry: ACTIVE -> EXPIRED once today > expiry_date.
    for w in list(db["waivers"].values()):
        if w["status"] == "ACTIVE" and today > parse_date(w["expiry_date"]):
            w["status"] = "EXPIRED"
            touch(w)

    # (2) Event NO_SHOW: SCHEDULED/POSTPONED whose scheduled_date has passed.
    for ev in list(db["events"].values()):
        if ev["status"] in ("SCHEDULED", "POSTPONED") and today > parse_date(ev["scheduled_date"]):
            noshow_event_cascade(ev)

    # (3) Agreement auto-suspension: recompute rolling standing on every sweep;
    # suspend ACTIVE agreements at least 180 days old with count < 3.
    for ag in list(db["agreements"].values()):
        if ag["status"] in ("ACTIVE", "SUSPENDED", "RENEWAL_REVIEW"):
            recompute_standing(ag, today)
    for ag in list(db["agreements"].values()):
        if ag["status"] != "ACTIVE":
            continue
        term_start = ag.get("term_start_date")
        if term_start is None:
            continue
        age_days = (today - parse_date(term_start)).days
        n = rolling_count(ag["id"], today)
        if age_days >= GRACE_DAYS and n < REQUIRED_CLEANUPS:
            ag["status"] = "SUSPENDED"
            ag["suspension_reason"] = "COMPLIANCE_DEFICIENCY"
            touch(ag)
            suspend_cascade(ag)

    # (4) Agreement auto-expiry: ACTIVE with today > term_end_date.
    for ag in list(db["agreements"].values()):
        if ag["status"] == "ACTIVE" and ag.get("term_end_date") is not None:
            if today > parse_date(ag["term_end_date"]):
                ag["status"] = "EXPIRED"
                touch(ag)
                expire_cascade(ag)
