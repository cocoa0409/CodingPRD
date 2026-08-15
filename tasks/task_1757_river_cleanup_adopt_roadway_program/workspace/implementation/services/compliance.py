"""Compliance standing calculation (PRD 2.6; calculations.compliance_standing).

ROLLING variant (drives `standing` / `cleanups_completed_in_window`, the
suspension sweep, and auto-reinstatement): count COMPLETED events whose
scheduled_date falls in [today - 365 days, today], both bounds inclusive.

ANNIVERSARY variant (renewal-decision APPROVE eligibility only): two fixed
12-month windows anchored at term_start_date, lower bound inclusive, upper
exclusive; EVERY window must hold >= 3 completions.
"""
from datetime import timedelta

from db import db
from services.core import touch
from util import add_months, parse_date

REQUIRED_CLEANUPS = 3
ROLLING_WINDOW_DAYS = 365
GRACE_DAYS = 180
TERM_MONTHS = 24


def completed_event_dates(agreement_id):
    out = []
    for ev in db["events"].values():
        if ev["agreement_id"] == agreement_id and ev["status"] == "COMPLETED":
            out.append(parse_date(ev["scheduled_date"]))
    return out


def rolling_count(agreement_id, today):
    lo = today - timedelta(days=ROLLING_WINDOW_DAYS)
    return sum(1 for d in completed_event_dates(agreement_id) if lo <= d <= today)


def standing_for(agreement, today, n):
    if n >= REQUIRED_CLEANUPS:
        return "COMPLIANT"
    term_start = agreement.get("term_start_date")
    if term_start is None:
        return "NOT_EVALUATED"
    age_days = (today - parse_date(term_start)).days
    if age_days < GRACE_DAYS:
        return "NOT_EVALUATED"
    return "NON_COMPLIANT"


def recompute_standing(agreement, today):
    """Recompute the rolling counter and standing; a changed value is a
    mutation (version bump + updated_at refresh per PRD 2.4)."""
    if agreement.get("term_start_date") is None:
        return agreement["standing"]
    n = rolling_count(agreement["id"], today)
    new_standing = standing_for(agreement, today, n)
    if n != agreement["cleanups_completed_in_window"] or new_standing != agreement["standing"]:
        agreement["cleanups_completed_in_window"] = n
        agreement["standing"] = new_standing
        touch(agreement)
    return new_standing


def anniversary_eligible(agreement):
    """True when every fixed 12-month term window holds >= 3 COMPLETED cleanups
    (membership by scheduled_date; lower bound inclusive, upper exclusive)."""
    ts = parse_date(agreement["term_start_date"])
    dates = completed_event_dates(agreement["id"])
    for k in (1, 2):
        lo = add_months(ts, 12 * (k - 1))
        hi = add_months(ts, 12 * k)
        if sum(1 for d in dates if lo <= d < hi) < REQUIRED_CLEANUPS:
            return False
    return True
