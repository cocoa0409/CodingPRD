"""Full re-derivation of every derived counter (PRD section 2.10)."""

import lookup
from db import db, reconcile
from services import calc


def recompute_committee_counts(committee):
    """Committee.member_count / external_member_count."""
    counts = calc.committee_composition_counts(committee["id"])
    reconcile(
        committee,
        member_count=counts["member_count"],
        external_member_count=counts["external_member_count"],
    )
    return counts


def recompute_all_chair_loads():
    """FacultyMember.active_chair_load, re-derived from scratch for everyone."""
    for faculty in db.faculty_members.values():
        reconcile(faculty, active_chair_load=calc.faculty_active_chair_load(faculty["id"]))


def recompute_room(room_id):
    room = db.defense_rooms.get(room_id)
    if room is None:
        return
    reconcile(room, booked_minutes_total=calc.room_booked_minutes_total(room_id))


def recompute_rooms(room_ids):
    for room_id in set(room_ids):
        recompute_room(room_id)


def thesis_counter_values(thesis):
    return {
        "format_cycle_count": len(lookup.reviews_of_thesis(thesis["id"])),
        "documented_permission_count": sum(
            1
            for row in lookup.permissions_of_thesis(thesis["id"])
            if row["status"] in ("ACCEPTED", "WAIVED")
        ),
        "analyst_turnaround_bdays_total": calc.analyst_turnaround_bdays_total(
            thesis["id"]
        ),
    }


def sync_thesis_counters(thesis):
    """Secondary-target refresh: bumps the version only when a counter moved."""
    reconcile(thesis, **thesis_counter_values(thesis))
