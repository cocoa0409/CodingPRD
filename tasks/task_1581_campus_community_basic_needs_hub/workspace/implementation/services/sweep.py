"""Sweep checkpoint (PRD 2.4): evaluates clock-driven transitions in pinned order.

Order: (1) IntakeAssessment VERIFIED->EXPIRED, (2) Referral SENT->EXPIRED,
(3) ShelterStay RESERVED->NO_SHOW, (4) EmergencyGrantApplication APPROVED->EXPIRED,
(5) OutreachEvent OPEN/FULL->COMPLETED. Each fired transition runs its §1.2 side
effects, including fund reopens and queued-grant promotion.
"""
from datetime import timedelta

from db import db
from services.core import (
    touch, recompute_fund, recompute_agency, maybe_reopen_fund, promote_queued_application,
)
from util import CLOCK, parse_datetime, parse_date


def run_sweeps():
    now = CLOCK.now()
    today = now.date()
    tallies = {
        "assessments_expired": 0,
        "referrals_expired": 0,
        "stays_marked_no_show": 0,
        "grants_expired": 0,
        "events_completed": 0,
        "queued_grants_promoted": 0,
    }

    # (1) VERIFIED assessments whose validity lapsed (boundary inclusive: now >= expires_at)
    for a in sorted(db["assessments"].values(), key=lambda r: r["_seq"]):
        if a["status"] == "VERIFIED" and a.get("expires_at") and now >= parse_datetime(a["expires_at"]):
            a["status"] = "EXPIRED"
            touch(a)
            tallies["assessments_expired"] += 1
            # Client derived fields unwind (household null, allotment 0, tier null)
            client = db["clients"].get(a["client_id"])
            if client is not None:
                touch(client)

    # (2) SENT referrals strictly past their acknowledgement deadline
    for r in sorted(db["referrals"].values(), key=lambda r: r["_seq"]):
        if r["status"] == "SENT" and r.get("ack_due_at") and now > parse_datetime(r["ack_due_at"]):
            r["status"] = "EXPIRED"
            touch(r)
            agency = db["partner_agencies"].get(r["agency_id"])
            if agency is not None:
                recompute_agency(agency)  # decrement frees capacity
            tallies["referrals_expired"] += 1

    # (3) RESERVED stays past the arrival grace (today > check_in_date + 1 day)
    for s in sorted(db["shelter_stays"].values(), key=lambda r: r["_seq"]):
        if s["status"] == "RESERVED" and today > parse_date(s["check_in_date"]) + timedelta(days=1):
            s["status"] = "NO_SHOW"
            s["no_show_marked_at"] = CLOCK.now_iso()
            touch(s)
            client = db["clients"].get(s["client_id"])
            if client is not None:
                touch(client)  # shelter_no_show_count_90d / shelter_restricted recompute
            tallies["stays_marked_no_show"] += 1

    # (4) APPROVED grants strictly past the 72h disbursement window
    for g in sorted(db["grant_applications"].values(), key=lambda r: r["_seq"]):
        if g["status"] == "APPROVED" and g.get("approved_at") and \
                now > parse_datetime(g["approved_at"]) + timedelta(hours=72):
            g["status"] = "EXPIRED"
            touch(g)
            tallies["grants_expired"] += 1
            fund = db["grant_funds"].get(g["fund_id"])
            if fund is not None:
                recompute_fund(fund, bump=False)   # counters release
                reopened = maybe_reopen_fund(fund)  # EXHAUSTED -> OPEN flip
                touch(fund)                         # one version advance per expiry event
                if reopened and promote_queued_application(fund):
                    tallies["queued_grants_promoted"] += 1

    # (5) OPEN/FULL events a full day past their start
    for e in sorted(db["outreach_events"].values(), key=lambda r: r["_seq"]):
        if e["status"] in ("OPEN", "FULL") and now >= parse_datetime(e["event_date"]) + timedelta(hours=24):
            e["status"] = "COMPLETED"
            touch(e)
            tallies["events_completed"] += 1

    return tallies
