"""Application enrollment-axis routing and the session intake cascade.

PRD §3.4: submit auto-routes to OFFERED (seat available) or WAITLISTED;
run-intake first expires lapsed offers back to WAITLISTED (freeing seats) then
promotes earliest-submitted waitlisted applicants into freed seats.
"""
from datetime import timedelta

import db
from services import recompute
from services.store import touch


def make_offer(application, camp):
    """SUBMITTED|WAITLISTED -> OFFERED side effects (PRD §3.4)."""
    application["enroll_status"] = "OFFERED"
    application["offer_expires_at_dt"] = db.now() + timedelta(days=camp["deposit_grace_days"])
    application["payment_status"] = "DEPOSIT_DUE"
    recompute.recompute_application_money(application)
    touch(application)


def make_waitlist(application):
    """SUBMITTED -> WAITLISTED side effects (PRD §3.4). payment stays UNBILLED."""
    application["enroll_status"] = "WAITLISTED"
    application["payment_status"] = "UNBILLED"
    application["offer_expires_at_dt"] = None
    recompute.recompute_application_money(application)
    touch(application)


def run_intake(session, camp):
    """Two-phase intake cascade (PRD §3.4).

    Phase 1: every OFFERED app whose offer_expires_at is strictly before the
    clock is recycled to WAITLISTED (payment -> UNBILLED, offer cleared,
    committed_count freed).
    Phase 2: while committed_count < capacity, promote the earliest-submitted
    WAITLISTED app (submitted_at ASC, tie-break created_at ASC) to OFFERED.
    """
    clock = db.now()

    # Phase 1 — expire lapsed offers.
    for app in db.applications.values():
        if app["session_id"] != session["id"]:
            continue
        if app["enroll_status"] != "OFFERED":
            continue
        exp = app.get("offer_expires_at_dt")
        if exp is not None and clock > exp:
            app["enroll_status"] = "WAITLISTED"
            app["payment_status"] = "UNBILLED"
            app["offer_expires_at_dt"] = None
            recompute.recompute_application_money(app)
            touch(app)

    # Phase 2 — promote earliest waitlisted while seats remain.
    while True:
        committed = recompute.session_committed_count(session["id"])
        if committed >= session["capacity"]:
            break
        waitlisted = [
            a for a in db.applications.values()
            if a["session_id"] == session["id"] and a["enroll_status"] == "WAITLISTED"
        ]
        if not waitlisted:
            break
        # earliest submitted_at, tie-break earliest created_at (then seq)
        waitlisted.sort(key=lambda a: (a["submitted_at_dt"], a["created_at_dt"], a["_seq"]))
        make_offer(waitlisted[0], camp)
