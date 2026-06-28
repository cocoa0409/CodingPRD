"""Session effective-capacity and posture derivation (PRD §2.6; SCAFFOLD §1.3
session_effective_capacity + Session state machine)."""
import math

from db import db

RESTRICTED_FRACTION = 0.8


def effective_capacity(session):
    """effective_capacity = min(floor(device_count / device_seats_requested),
                                 assigned_instructor_count * min_student_instructor_ratio)."""
    center = db.centers[session["center_id"]]
    device_seat_cap = center["device_count"] // session["device_seats_requested"]
    instructor_cap = session["assigned_instructor_count"] * center["min_student_instructor_ratio"]
    return min(device_seat_cap, instructor_cap)


def restricted_threshold(cap):
    # ceil(effective_capacity * 0.8)
    return math.ceil(cap * RESTRICTED_FRACTION)


def derive_posture(session):
    """Re-derive OPEN/RESTRICTED/FULL from confirmed_seat_count.

    Only applies while the session is in one of the auto-derived postures;
    terminal/draft states are left untouched.
    """
    if session["status"] not in ("OPEN", "RESTRICTED", "FULL"):
        return
    cap = effective_capacity(session)
    count = session["confirmed_seat_count"]
    threshold = restricted_threshold(cap)
    if count >= cap:
        session["status"] = "FULL"
    elif count >= threshold:
        session["status"] = "RESTRICTED"
    else:
        session["status"] = "OPEN"
