"""Clock-driven sweeps (PRD 2.4). Evaluated when the logical clock advances.

Sweep set:
  - AvailabilityHold ACTIVE -> EXPIRED once clock >= expires_at
  - Offer EXTENDED/COUNTERED -> EXPIRED once clock >= expires_at
    (live-offer expiry returns submission OFFER_PENDING -> CALLBACK_COMPLETED)
  - AuditionSession SCHEDULED -> IN_PROGRESS once clock >= session_start
  - MinorWorkPermit VERIFIED -> EXPIRED once clock >= valid_until
    (dependent PENDING/CONFIRMED bookings whose memo engagement_end falls
     after valid_until cancel with PERMIT_REVOKED, no penalty)
  - TaftHartleyReport PENDING -> LATE once clock > filing_deadline
"""
import db
from services.domain import find, cancel_booking_record
from util import logical_now, touch

S = db.STORE


def _sweep_holds(now):
    for h in S["holds"].values():
        if h["status"] == "ACTIVE" and now >= h["expires_at"]:
            h["status"] = "EXPIRED"
            touch(h)


def _sweep_offers(now):
    for o in S["offers"].values():
        if o["status"] in ("EXTENDED", "COUNTERED") and now >= o["expires_at"]:
            was_live = o["status"] == "EXTENDED"
            o["status"] = "EXPIRED"
            touch(o)
            if was_live:
                sub = find("submissions", o["submission_id"])
                if sub is not None and sub["status"] == "OFFER_PENDING":
                    sub["status"] = "CALLBACK_COMPLETED"
                    touch(sub)


def _sweep_sessions(now):
    for s in S["sessions"].values():
        if s["status"] == "SCHEDULED" and now >= s["session_start"]:
            s["status"] = "IN_PROGRESS"
            touch(s)


def _sweep_permits(now):
    for p in S["permits"].values():
        if p["status"] == "VERIFIED" and now >= p["valid_until"]:
            p["status"] = "EXPIRED"
            touch(p)
            for b in S["bookings"].values():
                if b.get("work_permit_id") != p["id"]:
                    continue
                if b["status"] not in ("PENDING", "CONFIRMED"):
                    continue
                memo = find("deal_memos", b["deal_memo_id"])
                if memo is not None and memo["engagement_end"] > p["valid_until"]:
                    cancel_booking_record(b, "PERMIT_REVOKED", compute_penalty=False)


def _sweep_reports(now):
    for rep in S["taft_hartley_reports"].values():
        if rep["status"] == "PENDING" and now > rep["filing_deadline"]:
            rep["status"] = "LATE"
            touch(rep)


def run_sweeps():
    now = logical_now()
    _sweep_holds(now)
    _sweep_offers(now)
    _sweep_sessions(now)
    _sweep_permits(now)
    _sweep_reports(now)
