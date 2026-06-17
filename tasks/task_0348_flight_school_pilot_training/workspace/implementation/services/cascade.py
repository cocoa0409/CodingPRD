"""Cross-entity cascade effects (PRD §2.6, §3.2, §3.3, §3.5).

These functions implement the automatic, immediate, atomic cascades:
  - grounding / un-grounding an aircraft
  - cancelling a booking (with hold release for CONFIRMED ones)
  - cancelling open bookings on an aircraft / enrollment
  - suspending an active enrollment
Each entity touched independently records its own mutation (updated_at +
version bump where versioned).
"""

from db import db, touch
from services import ledger
from services.calc import NO_SHOW_SUSPEND_THRESHOLD


def cancel_booking(booking):
    """Cancel a single booking (system cascade variant).

    REQUESTED -> CANCELLED: no ledger effect (no hold was placed).
    CONFIRMED -> CANCELLED: release the held estimate.
    """
    was_confirmed = booking["status"] == "CONFIRMED"
    booking["status"] = "CANCELLED"
    touch(booking)
    if was_confirmed:
        student = _student_for_booking(booking)
        if student is not None:
            ledger.release(student, booking["estimated_cost_cents"], booking["id"])


def _student_for_booking(booking):
    enrollment = db.enrollments.get(booking["enrollment_id"])
    if enrollment is None:
        return None
    return db.students.get(enrollment["student_id"])


def cancel_open_bookings_for_aircraft(aircraft_id):
    """Cascade: cancel every REQUESTED/CONFIRMED booking on this aircraft."""
    from db import sorted_by_created
    targets = [b for b in db.bookings.values()
               if b["aircraft_id"] == aircraft_id
               and b["status"] in ("REQUESTED", "CONFIRMED")]
    for b in sorted_by_created(targets):
        cancel_booking(b)


def cancel_open_bookings_for_enrollment(enrollment_id):
    """Cascade: cancel every REQUESTED/CONFIRMED booking on this enrollment."""
    from db import sorted_by_created
    targets = [b for b in db.bookings.values()
               if b["enrollment_id"] == enrollment_id
               and b["status"] in ("REQUESTED", "CONFIRMED")]
    for b in sorted_by_created(targets):
        cancel_booking(b)


def ground_aircraft(aircraft):
    """AVAILABLE -> GROUNDED (automatic). Bump version, cancel open bookings."""
    if aircraft["status"] != "AVAILABLE":
        return
    aircraft["status"] = "GROUNDED"
    touch(aircraft)
    cancel_open_bookings_for_aircraft(aircraft["id"])


def unground_aircraft(aircraft):
    """GROUNDED -> AVAILABLE (automatic) when open grounding squawks hit 0."""
    if aircraft["status"] != "GROUNDED":
        return
    aircraft["status"] = "AVAILABLE"
    touch(aircraft)


def suspend_enrollment(enrollment):
    """ACTIVE -> SUSPENDED (system cascade). Cancels its open bookings."""
    if enrollment["status"] != "ACTIVE":
        return
    enrollment["status"] = "SUSPENDED"
    touch(enrollment)
    cancel_open_bookings_for_enrollment(enrollment["id"])


def apply_no_show_strike_cascade(student, enrollment):
    """After a no-show increments strikes, suspend the active enrollment if the
    student has reached the threshold."""
    if (student["no_show_strikes"] >= NO_SHOW_SUSPEND_THRESHOLD
            and enrollment is not None and enrollment["status"] == "ACTIVE"):
        suspend_enrollment(enrollment)


def refresh_student_status(student):
    """Student.status is ACTIVE unless no_show_strikes >= threshold (then
    SUSPENDED). Treated as a derived field; bump on change."""
    desired = "SUSPENDED" if student["no_show_strikes"] >= NO_SHOW_SUSPEND_THRESHOLD else "ACTIVE"
    if student.get("status") != desired:
        student["status"] = desired
        touch(student)
