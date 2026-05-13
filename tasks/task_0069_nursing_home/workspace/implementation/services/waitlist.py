"""Waitlist priority + promotion logic."""
from clock import now, iso_now, parse_dt, parse_date
from db import get_db
from helpers import touch


CARE_LEVEL_WEIGHT = {"L1": 1, "L2": 2, "L3": 3, "L4": 4, "INTENSIVE": 5}


def compute_priority(elder):
    """priority_score = base*100 + floor(age/5).

    If elder.current_care_level is None we treat its weight as 0
    (priority still computed; the entry is rarely promoted before the
    first care-level assignment, but the formula must always yield an
    integer).
    """
    level = elder.get("current_care_level")
    base = CARE_LEVEL_WEIGHT.get(level, 0)
    today = now().date()
    dob = parse_date(elder.get("date_of_birth")) if elder.get("date_of_birth") else None
    age_years = 0
    if dob is not None:
        age_years = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    bonus = age_years // 5
    return base * 100 + bonus


def _sorted_queued_for_type(bed_type):
    """Return QUEUED waitlist entries matching bed_type, ordered by
    priority_score desc, queued_at asc.
    """
    db = get_db()
    entries = [
        e for e in db.waitlist.values()
        if e["status"] == "QUEUED" and e["requested_bed_type"] == bed_type
    ]
    entries.sort(
        key=lambda e: (-e["priority_score"], parse_dt(e["queued_at"]))
    )
    return entries


def promote_for_bed(bed):
    """When `bed` enters AVAILABLE, offer it to the highest-priority QUEUED
    entry with matching requested_bed_type, if any.
    """
    db = get_db()
    queued = _sorted_queued_for_type(bed["bed_type"])
    # Skip entries whose elder is no longer PENDING_ADMISSION
    for entry in queued:
        elder = db.elders.get(entry["elder_id"])
        if elder is None or elder.get("status") != "PENDING_ADMISSION":
            continue
        # Don't double-offer the same bed
        if any(e for e in db.waitlist.values()
               if e["status"] == "OFFERED" and e.get("offered_bed_id") == bed["id"]):
            return
        entry["status"] = "OFFERED"
        entry["offered_bed_id"] = bed["id"]
        db.waitlist_offered_at[entry["id"]] = now()
        return
