"""Declination sufficiency (PRD 3.4).

The anchor date is the calendar date of the application's submitted_at.  The
window opens sixty days before the anchor and closes on the anchor itself, and
BOTH bounds are inclusive.  Only verified rows count, and qualifying rows are
collapsed so at most one row per carrier counts.
"""

from datetime import timedelta

from db import db
from util import date_of, parse_date
from services.constants import DECLINATION_LOOKBACK_DAYS, MIN_DECLINATIONS


def declinations_for(application_id):
    return [d for d in db.declinations.values()
            if d["application_id"] == application_id]


def qualifying(application, anchor_date):
    if anchor_date is None:
        return []
    window_start = anchor_date - timedelta(days=DECLINATION_LOOKBACK_DAYS)
    rows = []
    for record in declinations_for(application["id"]):
        if not record["verified"]:
            continue
        declined = parse_date(record["declined_on"])
        if declined is None:
            continue
        if window_start <= declined <= anchor_date:
            rows.append(record)
    return rows


def declination_count(application, anchor_instant=None):
    """Distinct carriers surviving the collapse inside the inclusive window."""
    anchor_date = date_of(anchor_instant if anchor_instant is not None
                          else application.get("submitted_at"))
    rows = qualifying(application, anchor_date)
    return len({row["member_insurer_id"] for row in rows})


def sufficient(count):
    return count >= MIN_DECLINATIONS
