"""Classroom compliance recomputation and waitlist promotion selection.

Recomputing placed_count / assigned_staff_count / compliance_status is a
genuine mutation of the classroom (PRD §2.4): it refreshes updated_at and
increments version.
"""
from db import db, touch
from services import calc


def recompute_counts(classroom):
    """Recompute placed_count and assigned_staff_count from live records."""
    cid = classroom["id"]
    placed = sum(
        1 for e in db.enrollments.values()
        if e["classroom_id"] == cid and e["placement_status"] == "PLACED"
    )
    staff = sum(
        1 for s in db.staff_assignments.values()
        if s["classroom_id"] == cid and s["status"] == "ACTIVE"
    )
    classroom["placed_count"] = placed
    classroom["assigned_staff_count"] = staff
    classroom["compliance_status"] = calc.compute_compliance_status(
        classroom["level"], placed, staff, classroom["capacity"]
    )


def recompute_and_touch(classroom):
    """Recompute the derived fields and record the mutation (version bump)."""
    recompute_counts(classroom)
    touch(classroom)


def select_top_waitlisted(classroom_id):
    """Promotion selector (PRD §3.3 / SCAFFOLD waitlist_priority.promotion_selector).

    Candidate set: Applications with status WAITLISTED and matching classroom_id.
    Recompute priority_score for each (tenure accrues to now), then rank by
    priority_score DESC, tie-break waitlisted_at ASC, then created_at ASC.
    Returns the single top-ranked application, or None if the set is empty.
    """
    candidates = [
        a for a in db.applications.values()
        if a["status"] == "WAITLISTED" and a["classroom_id"] == classroom_id
    ]
    if not candidates:
        return None
    for app in candidates:
        student = db.students.get(app["student_id"])
        if student is not None:
            app["priority_score"] = calc.compute_priority_score(app, student)

    def sort_key(a):
        return (
            -a["priority_score"],
            a.get("waitlisted_at") or "",
            a["created_at"],
            a.get("_seq", 0),
        )

    candidates.sort(key=sort_key)
    return candidates[0]
