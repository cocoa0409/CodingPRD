"""Scheduled sweeps run on clock advance / standalone (PRD 2.10, 3.8).

Four housekeeping passes: no-show sweep, strike expiry, freeze auto-expiry, due
renewals. The standalone sweep capability is idempotent.
"""
from db import db
from clock import clock
from mutate import touch
from util import add_days, add_minutes
from strikes import STRIKE_TTL_DAYS

import reservation_service
import membership_service


def run_sweeps():
    _no_show_sweep()
    _strike_expiry_sweep()
    _freeze_expiry_sweep()
    _due_renewals_sweep()


def _no_show_sweep():
    # Every reservation still BOOKED whose start_utc is at least 15 minutes in
    # the past relative to the clock -> NO_SHOW with the full cascade.
    now = clock.get()
    for res in list(db.reservations.values()):
        if res["booking_status"] != "BOOKED":
            continue
        if now >= add_minutes(res["start_utc"], 15):
            reservation_service._do_no_show(res)


def _strike_expiry_sweep():
    # Every ACTIVE strike whose created_at + 90 days has been reached -> EXPIRED.
    now = clock.get()
    affected_members = set()
    for s in list(db.no_show_strikes.values()):
        if s["status"] != "ACTIVE":
            continue
        if now >= add_days(s["created_at"], STRIKE_TTL_DAYS):
            s["status"] = "EXPIRED"
            affected_members.add(s["member_id"])
    for mid in affected_members:
        member = db.members.get(mid)
        if member is not None:
            touch(member)  # no_show_strike_count is computed; refresh updated_at


def _freeze_expiry_sweep():
    # Every FROZEN membership whose freeze_until_utc has been reached -> ACTIVE
    # with the unfreeze restore cascade.
    now = clock.get()
    for mb in list(db.memberships.values()):
        if mb["status"] != "FROZEN":
            continue
        if mb["freeze_until_utc"] is not None and now >= mb["freeze_until_utc"]:
            membership_service._do_unfreeze(mb)
            touch(mb)


def _due_renewals_sweep():
    # Memberships whose cycle_anchor_utc + 30 days has arrived are renewed
    # (treated as a successful on-cycle renewal). Loop while still due so a large
    # advance processes multiple cycles; idempotent at a fixed clock.
    now = clock.get()
    for mb in list(db.memberships.values()):
        if mb["status"] != "ACTIVE":
            continue
        # Guard against unbounded loops; advance one cycle at a time.
        safety = 0
        while (mb["status"] == "ACTIVE"
               and mb["cycle_anchor_utc"] is not None
               and now >= add_days(mb["cycle_anchor_utc"], 30)
               and safety < 10000):
            membership_service.renew(mb, "SUCCEEDED")
            safety += 1
