"""No-show strike aggregation (calc active_strike_count).

PRD 3.5: no_show_strike_count is the number of that member's NoShowStrike rows
whose status is ACTIVE and whose created_at plus 90 days is still strictly after
the current clock instant — a strike sitting exactly at its 90-day mark counts as
expired, not active, so the boundary is strict.
"""
from db import db
from clock import clock
from util import add_days

STRIKE_TTL_DAYS = 90


def member_active_strike_count(member_id):
    now = clock.get()
    count = 0
    for s in db.no_show_strikes.values():
        if s["member_id"] != member_id:
            continue
        if s["status"] != "ACTIVE":
            continue
        if add_days(s["created_at"], STRIKE_TTL_DAYS) > now:
            count += 1
    return count
