"""Core shared services: record lifecycle and cross-aggregate recomputes.

Every recompute helper maintains stored counters equal to a full recount
(PRD 2.9) and bumps the owning resource's version/updated_at only when a
value actually changes.
"""
from db import db, next_seq
from util import new_id, now_ts, parse_dt, fmt_dt, add_days, CLOCK


def new_record(collection, fields, with_version=True):
    rec = dict(fields)
    rec["id"] = new_id()
    ts = now_ts()
    rec["created_at"] = ts
    if with_version:
        rec["updated_at"] = ts
        rec["version"] = 1
    rec["_seq"] = next_seq()
    db[collection][rec["id"]] = rec
    return rec


def touch(rec):
    rec["updated_at"] = now_ts()
    rec["version"] = rec.get("version", 1) + 1


# ---------------------------------------------------------------------------
# District census + posture (PRD 2.9)
# ---------------------------------------------------------------------------

def recompute_district_census(district_id):
    """total_inventory_count / contributing_count / preservation_posture, always
    equal to a full recount of the district's non-DEMOLISHED properties."""
    if district_id is None:
        return
    district = db["districts"].get(district_id)
    if district is None:
        return
    props = [
        p for p in db["properties"].values()
        if p.get("district_id") == district_id and p.get("listing_status") != "DEMOLISHED"
    ]
    total = len(props)
    contributing = sum(1 for p in props if p.get("contributing_status") == "CONTRIBUTING")
    posture = "AT_RISK" if (total > 0 and contributing * 2 < total) else "STABLE"
    changed = (
        district["total_inventory_count"] != total
        or district["contributing_count"] != contributing
        or district["preservation_posture"] != posture
    )
    if changed:
        district["total_inventory_count"] = total
        district["contributing_count"] = contributing
        district["preservation_posture"] = posture
        touch(district)


# ---------------------------------------------------------------------------
# Property enforcement counters (PRD 3.8)
# ---------------------------------------------------------------------------

OPEN_VIOLATION_STATUSES = {"OPEN", "NOTICE_ISSUED", "AFTER_THE_FACT_PENDING", "COURT_REFERRAL"}


def recompute_property_enforcement(property_id):
    prop = db["properties"].get(property_id)
    if prop is None:
        return
    count = sum(
        1 for v in db["violations"].values()
        if v.get("property_id") == property_id and v.get("status") in OPEN_VIOLATION_STATUSES
    )
    posture = "UNDER_ENFORCEMENT" if count > 0 else "CLEAR"
    if prop["open_violation_count"] != count or prop["compliance_posture"] != posture:
        prop["open_violation_count"] = count
        prop["compliance_posture"] = posture
        touch(prop)


# ---------------------------------------------------------------------------
# Meeting agenda occupancy (entities.CommissionMeeting.scheduled_hearing_count)
# ---------------------------------------------------------------------------

OCCUPYING_HEARING_STATUSES = {"SCHEDULED", "OPENED"}


def refresh_meeting_count(meeting_id):
    meeting = db["meetings"].get(meeting_id)
    if meeting is None:
        return
    count = sum(
        1 for h in db["hearings"].values()
        if h.get("meeting_id") == meeting_id and h.get("status") in OCCUPYING_HEARING_STATUSES
    )
    if meeting["scheduled_hearing_count"] != count:
        meeting["scheduled_hearing_count"] = count
        touch(meeting)


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def adopted_guideline_set_for(district_id):
    """The district's currently ADOPTED guideline set, or None."""
    if district_id is None:
        return None
    for gs in db["guideline_sets"].values():
        if gs.get("district_id") == district_id and gs.get("status") == "ADOPTED":
            return gs
    return None


def hearing_for_application(application_id, statuses=None):
    for h in db["hearings"].values():
        if h.get("application_id") != application_id:
            continue
        if statuses is None or h.get("status") in statuses:
            return h
    return None


def linked_after_fact_application(violation_id):
    """The after-the-fact application legalizing this violation, if any."""
    for a in db["applications"].values():
        if a.get("after_the_fact") and a.get("violation_id") == violation_id:
            return a
    return None


def delay_for_application(application_id):
    for d in db["demolition_delays"].values():
        if d.get("application_id") == application_id:
            return d
    return None
