"""Entity computation and serialization services.

Candidate accrual intervals (PRD §3.4) are tracked internally as a list of
[start_iso, end_iso|None] pairs. An interval is open (end None) while the
candidate is both LISTED and medical_status ACTIVE.
"""
import math

from store import db
from common import public_view
from timeutil import parse_iso, format_iso
from calc import SECONDS_PER_DAY

# DOB-based pediatric threshold: age in whole years < 12 at listing time.
DAYS_PER_YEAR = 365.25


# ----------------------------------------------------------------------------
# Candidate computed fields
# ----------------------------------------------------------------------------
def compute_is_pediatric(candidate, listed_at):
    """Age in whole years at listing time = floor(elapsed_days / 365.25);
    pediatric when strictly < 12 (PRD §3.2)."""
    dob = parse_iso(candidate["date_of_birth"])
    elapsed_days = (listed_at - dob).total_seconds() / SECONDS_PER_DAY
    age_years = math.floor(elapsed_days / DAYS_PER_YEAR)
    return age_years < 12


def waiting_time_days(candidate):
    """Sum whole days across all accrual intervals; the open interval ends at
    the current clock (PRD §3.4)."""
    now = db.clock
    total_seconds = 0.0
    for start_iso, end_iso in candidate.get("_accrual_intervals", []):
        start = parse_iso(start_iso)
        end = parse_iso(end_iso) if end_iso is not None else now
        if end > start:
            total_seconds += (end - start).total_seconds()
    return int(math.floor(total_seconds / SECONDS_PER_DAY))


def open_accrual_interval(candidate, at_iso):
    candidate.setdefault("_accrual_intervals", [])
    candidate["_accrual_intervals"].append([at_iso, None])


def close_accrual_interval(candidate, at_iso):
    for interval in candidate.get("_accrual_intervals", []):
        if interval[1] is None:
            interval[1] = at_iso
            break


# ----------------------------------------------------------------------------
# Serializers — produce the public JSON view of each entity.
# ----------------------------------------------------------------------------
def serialize_candidate(candidate):
    rec = public_view(candidate)
    rec["waiting_time_days"] = waiting_time_days(candidate)
    return rec


def serialize(rec):
    return public_view(rec)
