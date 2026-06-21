"""Domain helpers: classroom status, age-band fit, waitlist priority."""
from __future__ import annotations

from datetime import date

from db import db, clock
from common import touch

AGE_BANDS = {"INFANT", "TODDLER", "PRESCHOOL"}

# Age-band bounds in years [lower_inclusive, upper_exclusive) at activation date.
# Standard daycare bands: INFANT 0-1, TODDLER 1-3, PRESCHOOL 3-5.
AGE_BAND_BOUNDS = {
    "INFANT": (0, 1),
    "TODDLER": (1, 3),
    "PRESCHOOL": (3, 5),
}


def recompute_classroom_status(classroom: dict) -> None:
    classroom["status"] = "OPEN" if classroom["active_enrollment_count"] < classroom["licensed_capacity"] else "FULL"


def age_in_years(birthdate: str, on: date) -> int:
    y, m, d = [int(x) for x in birthdate.split("-")]
    bd = date(y, m, d)
    years = on.year - bd.year - ((on.month, on.day) < (bd.month, bd.day))
    return years


def age_band_fits(birthdate: str, age_band: str) -> bool:
    on = clock.now().date()
    age = age_in_years(birthdate, on)
    lo, hi = AGE_BAND_BOUNDS[age_band]
    return lo <= age < hi


def child_has_active_enrollment_at_center(child: dict, center_id: str) -> bool:
    for enr in db.enrollments.values():
        if enr["status"] != "ACTIVE":
            continue
        c = db.children.get(enr["child_id"])
        if c is None:
            continue
        if c["id"] != child["id"]:
            continue
        cls = db.classrooms.get(enr["classroom_id"])
        if cls and cls["center_id"] == center_id:
            return True
    return False


def compute_has_active_sibling(child: dict, center_id: str) -> bool:
    """True if child shares sibling_group_id with a child holding an ACTIVE
    Enrollment at the same center."""
    group = child["sibling_group_id"]
    for enr in db.enrollments.values():
        if enr["status"] != "ACTIVE":
            continue
        c = db.children.get(enr["child_id"])
        if c is None:
            continue
        if c["family_id"] != child["family_id"]:
            continue
        if c["sibling_group_id"] != group:
            continue
        cls = db.classrooms.get(enr["classroom_id"])
        if cls and cls["center_id"] == center_id:
            return True
    return False


def recompute_waitlist_ranks(classroom_id: str) -> None:
    """Recompute priority_rank for all WAITING/OFFERED entries on a classroom.
    sibling class (has_active_sibling True) first, then created_at ASC."""
    classroom = db.classrooms.get(classroom_id)
    if classroom is None:
        return
    center_id = classroom["center_id"]
    entries = [w for w in db.waitlist_entries.values()
               if w["classroom_id"] == classroom_id and w["status"] in ("WAITING", "OFFERED")]
    # refresh has_active_sibling for each entry
    for w in entries:
        child = db.children.get(w["child_id"])
        if child is not None:
            w["has_active_sibling"] = compute_has_active_sibling(child, center_id)
    # rank: sibling class first (has_active_sibling True), then created_at ASC
    entries.sort(key=lambda w: (0 if w["has_active_sibling"] else 1, w["_seq"]))
    for idx, w in enumerate(entries):
        rank = idx + 1
        if w.get("priority_rank") != rank:
            w["priority_rank"] = rank


def select_promote_entry(classroom_id: str):
    """Pick the single WAITING entry with minimum priority_rank (deterministic).
    sibling class first, then created_at ASC; id never breaks ties."""
    recompute_waitlist_ranks(classroom_id)
    waiting = [w for w in db.waitlist_entries.values()
               if w["classroom_id"] == classroom_id and w["status"] == "WAITING"]
    if not waiting:
        return None
    waiting.sort(key=lambda w: (0 if w["has_active_sibling"] else 1, w["_seq"]))
    return waiting[0]
