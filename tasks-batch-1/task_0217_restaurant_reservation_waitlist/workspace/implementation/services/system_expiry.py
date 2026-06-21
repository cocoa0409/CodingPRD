"""Lazy system transitions fired by clock advance (PRD §3.8, §3.9).

When the test clock advances, two system transitions become due and are
applied when the affected entities are next touched/read:
  * WaitlistEntry WAITING -> EXPIRED once now > requested_start + 120 min
  * DepositHold  HELD     -> EXPIRED once now > reservation_start + 7 days
"""
from datetime import timedelta

import clock
import db
from services import calc


def sweep_waitlist():
    now = clock.now()
    for w in db.waitlist_entries.values():
        if w["status"] != "WAITING":
            continue
        if w["requested_start"] is None:
            continue
        if now > w["requested_start"] + timedelta(minutes=calc.WAITLIST_EXPIRY_MINUTES):
            w["status"] = "EXPIRED"
            db.touch(w)


def sweep_holds():
    now = clock.now()
    for h in db.deposit_holds.values():
        if h["status"] != "HELD":
            continue
        res = db.reservations.get(h["reservation_id"])
        if res is None or res["reservation_start"] is None:
            continue
        if now > res["reservation_start"] + timedelta(days=calc.HOLD_EXPIRY_DAYS):
            h["status"] = "EXPIRED"
            db.touch(h)


def sweep_all():
    sweep_waitlist()
    sweep_holds()
