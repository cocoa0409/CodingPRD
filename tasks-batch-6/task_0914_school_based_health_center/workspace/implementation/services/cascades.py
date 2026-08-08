"""The multi-entity cascades of PRD 2.10, 3.3, 3.4, 3.7, 3.8 and 3.9."""

import store
from services import calc
from services.notifications import raise_notification


# --------------------------------------------------------------------------
# Student dose counters and the compliance posture
# --------------------------------------------------------------------------
def recompute_dose_counters(student):
    doses = [d for d in store.DB["doses"].values() if d["student_id"] == student["id"]]
    student["valid_dose_count"] = len([d for d in doses if d["status"] == "VALID"])
    student["invalid_dose_count"] = len([d for d in doses if d["status"] == "INVALID_TOO_EARLY"])
    student["voided_dose_count"] = len([d for d in doses if d["status"] == "VOIDED"])
    student["total_dose_count"] = len(doses)


def recompute_compliance(student, raise_events=True):
    """Recompute the grace-counting posture; fire the compliance cascade when
    the posture *falls to* NON_COMPLIANT.  Returns True when it changed."""
    previous = student["immunization_compliance_status"]
    current = calc.compliance_status(student)
    student["immunization_compliance_status"] = current
    if raise_events and previous != "NON_COMPLIANT" and current == "NON_COMPLIANT":
        # Ordering is pinned: IMMUNIZATION_NON_COMPLIANT is created BEFORE the
        # CLEARANCE_VOIDED notification the clearance void raises (PRD 3.7).
        raise_notification("IMMUNIZATION_NON_COMPLIANT", student["id"], None)
        void_clearances(student, "IMMUNIZATION_COMPLIANCE_LOST")
    return previous != current


def live_clearances(student_id):
    rows = [
        c
        for c in store.DB["clearances"].values()
        if c["student_id"] == student_id and c["status"] in ("ACTIVE", "PENDING_REEVALUATION")
    ]
    rows.sort(key=store.order_key)
    return rows


def void_clearances(student, void_reason):
    for clearance in live_clearances(student["id"]):
        clearance["status"] = "VOIDED"
        clearance["void_reason"] = void_reason
        store.touch(clearance)
        visit = store.get("visits", clearance["visit_id"])
        raise_notification("CLEARANCE_VOIDED", student["id"], visit)


def supersede_clearances(student_id, school_year):
    for clearance in live_clearances(student_id):
        if clearance["school_year"] == school_year:
            clearance["status"] = "SUPERSEDED"
            store.touch(clearance)


# --------------------------------------------------------------------------
# Telehealth booking conservation
# --------------------------------------------------------------------------
def resync_school_minutes(school):
    """PRD 2.10: the total is always recomputed from the session rows."""
    school["telehealth_booked_minutes_total"] = calc.booked_minutes(school["id"])
    store.touch(school, force=True)


def move_session(session, new_status):
    """Move a session and keep the hosting site's conserved total in step."""
    was_booked = session["status"] in ("SCHEDULED", "COMPLETED")
    session["status"] = new_status
    store.touch(session)
    now_booked = new_status in ("SCHEDULED", "COMPLETED")
    if was_booked != now_booked:
        school = store.get("schools", session["school_id"])
        if school is not None:
            resync_school_minutes(school)


def sessions_of_visit(visit_id, statuses=None):
    rows = [s for s in store.DB["sessions"].values() if s["visit_id"] == visit_id]
    if statuses is not None:
        rows = [s for s in rows if s["status"] in statuses]
    rows.sort(key=store.order_key)
    return rows


def cancel_sessions_for_visit(visit, new_status):
    for session in sessions_of_visit(visit["id"], ("SCHEDULED",)):
        move_session(session, new_status)
