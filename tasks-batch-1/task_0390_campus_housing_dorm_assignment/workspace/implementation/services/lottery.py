"""Lottery offer selection, waitlist promotion, and gender compatibility."""

import db
from services import core


def room_occupant_genders(room_id, exclude_student_id=None):
    """Genders of students actually residing in the room: those with an
    Assignment on it in {ACTIVE, SWAP_PENDING}. Pre-accept OFFER reservations
    are NOT counted here — during the lottery sweep two not-yet-resident
    candidates may both be offered the same room; the gender conflict only
    materialises once one becomes a live (ACTIVE) resident.
    """
    genders = set()
    for a in db.assignments.values():
        if a["room_id"] == room_id and a["status"] in ("ACTIVE", "SWAP_PENDING"):
            if exclude_student_id is not None and a["student_id"] == exclude_student_id:
                continue
            stu = db.students.get(a["student_id"])
            if stu:
                genders.add(stu["gender_identity"])
    return genders


def gender_compatible(room, student, exclude_student_id=None):
    """True if `student` may be placed in `room` given its live occupants.

    ALL_GENDER rooms accept anyone. SINGLE_GENDER rooms require the student's
    gender to match the gender of any current residents (an empty room accepts
    the first resident of any gender).
    """
    if room["gender_inclusivity"] == "ALL_GENDER":
        return True
    existing = room_occupant_genders(room["id"], exclude_student_id=exclude_student_id)
    if not existing:
        return True
    return all(g == student["gender_identity"] for g in existing)


def application_matches_room(application, student, room):
    """Lottery matching predicate (PRD §3.3)."""
    if room["status"] != "OPEN":
        return False
    if room["occupied_bed_count"] >= room["bed_capacity"]:
        return False
    building = db.buildings.get(room["building_id"])
    if building is None:
        return False
    pref_bt = application["preferred_building_type"]
    if pref_bt != "NO_PREFERENCE" and building["building_type"] != pref_bt:
        return False
    pref_rt = application["preferred_room_type"]
    if pref_rt != "NO_PREFERENCE" and room["room_type"] != pref_rt:
        return False
    if not gender_compatible(room, student):
        return False
    return True


def _candidate_sort_key(application):
    student = db.students[application["student_id"]]
    return (
        application["priority_rank"],
        student["lottery_number"],
        application["created_at"],
        application["_seq"],
    )


def _room_pick_key(room):
    """Tightest fit first: fewest free beds, then earliest created_at."""
    free = room["bed_capacity"] - room["occupied_bed_count"]
    return (free, room["created_at"], room["_seq"])


def find_offer_room(application):
    """Return the best matching OPEN room for the application, or None."""
    student = db.students[application["student_id"]]
    matching = [
        r for r in db.rooms.values()
        if application_matches_room(application, student, r)
    ]
    if not matching:
        return None
    matching.sort(key=_room_pick_key)
    return matching[0]


def mint_offer(application, room, lottery_run_index):
    """Move an application to OFFERED on the given room and reconcile."""
    application["status"] = "OFFERED"
    application["offered_room_id"] = room["id"]
    application["offer_lottery_index"] = lottery_run_index
    core.touch(application)
    # Reservation bumps the room's occupied count.
    core.reconcile_room(room)


def run_lottery(cycle):
    """Execute lottery_offer_selection over SUBMITTED applications in the cycle."""
    candidates = [
        a for a in db.applications.values()
        if a["cycle_id"] == cycle["id"] and a["status"] == "SUBMITTED"
    ]
    candidates.sort(key=_candidate_sort_key)

    for app in candidates:
        room = find_offer_room(app)
        if room is not None:
            mint_offer(app, room, cycle["lottery_run_index"])
        else:
            # Waitlist the candidate.
            student = db.students[app["student_id"]]
            app["status"] = "WAITLISTED"
            core.touch(app)
            entry = core.init_record({
                "cycle_id": cycle["id"],
                "application_id": app["id"],
                "priority_rank_snapshot": app["priority_rank"],
                "lottery_number_snapshot": student["lottery_number"],
                "status": "QUEUED",
            })
            db.waitlist_entries[entry["id"]] = entry


def promote_waitlist(cycle, freed_room):
    """After an offer is released, promote the best queued entry whose
    application can match the freed room (PRD §3.6)."""
    entries = [
        e for e in db.waitlist_entries.values()
        if e["cycle_id"] == cycle["id"] and e["status"] == "QUEUED"
    ]
    entries.sort(key=lambda e: (
        e["priority_rank_snapshot"],
        e["lottery_number_snapshot"],
        e["created_at"],
        e["_seq"],
    ))
    for entry in entries:
        app = db.applications.get(entry["application_id"])
        if app is None or app["status"] != "WAITLISTED":
            continue
        student = db.students.get(app["student_id"])
        if student is None:
            continue
        if application_matches_room(app, student, freed_room):
            mint_offer(app, freed_room, cycle["lottery_run_index"])
            entry["status"] = "PROMOTED"
            core.touch(entry)
            return True
    return False
