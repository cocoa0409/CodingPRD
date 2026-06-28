"""Enrollment placement/billing cascades + section capacity (PRD 3.3, 3.4)."""
from db import db, touch
from services.billing import remove_fee_or_credit
from services.tuition import recompute_family

OCCUPIED = {"CONFIRMED", "WAITLIST_PROMOTED"}


def effective_capacity(section):
    room = db.rooms.get(section["room_id"])
    room_cap = room["capacity"] if room else section["capacity_cap"]
    return min(section["capacity_cap"], room_cap)


def recompute_enrolled_count(section):
    count = sum(
        1 for e in db.enrollments.values()
        if e["section_id"] == section["id"] and e["placement_status"] in OCCUPIED
    )
    if section["enrolled_count"] != count:
        section["enrolled_count"] = count
        touch(section)


def _set_section_status(section, status):
    if section["status"] != status:
        section["status"] = status
        touch(section)


def maybe_full(section):
    """OPEN -> FULL when enrolled_count reaches effective capacity."""
    if section["status"] == "OPEN" and section["enrolled_count"] >= effective_capacity(section):
        _set_section_status(section, "FULL")


def maybe_open(section):
    """FULL -> OPEN when capacity is not refilled after a drop."""
    if section["status"] == "FULL" and section["enrolled_count"] < effective_capacity(section):
        _set_section_status(section, "OPEN")


def confirm_enrollment(enr, section):
    """Move PENDING -> CONFIRMED + billing active + tuition recompute + capacity."""
    enr["placement_status"] = "CONFIRMED"
    enr["billing_status"] = "BILLING_ACTIVE"
    enr["waitlist_rank"] = 0
    touch(enr)
    recompute_enrolled_count(section)
    recompute_family(enr["family_id"])
    maybe_full(section)


def waitlist_enrollment(enr, section):
    """Move PENDING -> WAITLISTED with rank assignment."""
    existing = [
        e for e in db.enrollments.values()
        if e["section_id"] == section["id"] and e["placement_status"] == "WAITLISTED"
    ]
    enr["placement_status"] = "WAITLISTED"
    enr["waitlist_rank"] = len(existing) + 1
    enr["billing_status"] = "UNBILLED"
    touch(enr)


def _waitlisted_for_section(section_id):
    items = [
        e for e in db.enrollments.values()
        if e["section_id"] == section_id and e["placement_status"] == "WAITLISTED"
    ]
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


def _resequence_waitlist(section_id):
    """Reassign waitlist_rank 1..N in created_at order."""
    for idx, e in enumerate(_waitlisted_for_section(section_id), start=1):
        if e["waitlist_rank"] != idx:
            e["waitlist_rank"] = idx
            touch(e)


def promote_next_waitlist(section):
    """Promote the lowest-rank WAITLISTED enrollment if capacity allows.
    Returns the promoted enrollment or None."""
    if section["enrolled_count"] >= effective_capacity(section):
        return None
    waitlisted = _waitlisted_for_section(section["id"])
    if not waitlisted:
        return None
    promoted = waitlisted[0]
    promoted["placement_status"] = "WAITLIST_PROMOTED"
    promoted["billing_status"] = "BILLING_ACTIVE"
    promoted["waitlist_rank"] = 0
    touch(promoted)
    recompute_enrolled_count(section)
    recompute_family(promoted["family_id"])
    # Remaining waitlisted ranks close the gap.
    _resequence_waitlist(section["id"])
    maybe_full(section)
    return promoted


def drop_enrollment(enr):
    """Drop a CONFIRMED / WAITLIST_PROMOTED / WAITLISTED enrollment with cascades."""
    section = db.sections.get(enr["section_id"])
    prev = enr["placement_status"]
    family_id = enr["family_id"]

    if prev in OCCUPIED:
        enr["placement_status"] = "DROPPED"
        enr["billing_status"] = "BILLING_ENDED"
        touch(enr)
        if section:
            recompute_enrolled_count(section)
        recompute_family(family_id)
        if section:
            promoted = promote_next_waitlist(section)
            if promoted is None:
                maybe_open(section)
    elif prev == "WAITLISTED":
        enr["placement_status"] = "DROPPED"
        enr["waitlist_rank"] = 0
        touch(enr)
        if section:
            _resequence_waitlist(section["id"])


def cancel_section_cascade(section):
    """Cancel a populated section: drop all enrollments; end billing on occupied
    ones; recompute family tuition (PRD 3.2)."""
    affected = [
        e for e in db.enrollments.values()
        if e["section_id"] == section["id"]
        and e["placement_status"] in {"CONFIRMED", "WAITLISTED", "WAITLIST_PROMOTED"}
    ]
    families = set()
    for e in affected:
        if e["placement_status"] in OCCUPIED:
            e["billing_status"] = "BILLING_ENDED"
        e["placement_status"] = "DROPPED"
        e["waitlist_rank"] = 0
        touch(e)
        families.add(e["family_id"])
    recompute_enrolled_count(section)
    for fid in families:
        recompute_family(fid)
