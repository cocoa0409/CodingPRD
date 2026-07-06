"""Derived-field computation and entity serialization.

Computed fields (PRD §3) are recomputed at read time from current state and the
logical clock, so advancing the clock changes reads with no other mutation.
"""
from datetime import timezone

import db
from clock import clock
from services import calc
from util import parse_dt

# Booking statuses that occupy a seat (count toward enrolled_count).
SEAT_STATUSES = {"BOOKED", "CHECKED_IN", "ATTENDED"}
# Session statuses counted toward a school's open_session_count.
OPEN_SESSION_STATUSES = {"SCHEDULED", "WEATHER_HOLD", "IN_PROGRESS"}


# ----------------------------- School -----------------------------
def school_operating_status(school):
    return "STORM_CLOSED" if school["storm_advisory_active"] else "OPEN"


def school_open_session_count(school_id):
    return sum(
        1 for s in db.sessions.values()
        if s["school_id"] == school_id and s["status"] in OPEN_SESSION_STATUSES
    )


def serialize_school(school):
    return {
        "id": school["id"],
        "name": school["name"],
        "timezone": school["timezone"],
        "storm_advisory_active": school["storm_advisory_active"],
        "operating_status": school_operating_status(school),
        "open_session_count": school_open_session_count(school["id"]),
        "created_at": school["created_at"],
        "updated_at": school["updated_at"],
        "version": school["version"],
    }


# ----------------------------- Course -----------------------------
def serialize_course(c):
    return {
        "id": c["id"],
        "school_id": c["school_id"],
        "discipline": c["discipline"],
        "title": c["title"],
        "kind": c["kind"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


# --------------------------- CourseLevel --------------------------
def serialize_level(l):
    return {
        "id": l["id"],
        "course_id": l["course_id"],
        "school_id": l["school_id"],
        "rank": l["rank"],
        "name": l["name"],
        "max_students_per_instructor": l["max_students_per_instructor"],
        "base_price_cents": l["base_price_cents"],
        "min_age": l["min_age"],
        "requires_swim_test": l["requires_swim_test"],
        "required_equipment_type": l["required_equipment_type"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


# ---------------------------- Instructor --------------------------
def serialize_instructor(i):
    return {
        "id": i["id"],
        "school_id": i["school_id"],
        "full_name": i["full_name"],
        "certified_disciplines": list(i["certified_disciplines"]),
        "status": i["status"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


# --------------------------- EquipmentItem ------------------------
def equipment_status(item):
    """AVAILABLE | RENTED | MAINTENANCE (PRD §3.2).

    MAINTENANCE while toggled out of service; RENTED while a rental on it is
    ACTIVE; else AVAILABLE.
    """
    if item.get("maintenance"):
        return "MAINTENANCE"
    for r in db.rentals.values():
        if r["equipment_item_id"] == item["id"] and r["status"] == "ACTIVE":
            return "RENTED"
    return "AVAILABLE"


def serialize_equipment(e):
    return {
        "id": e["id"],
        "school_id": e["school_id"],
        "equipment_type": e["equipment_type"],
        "asset_tag": e["asset_tag"],
        "hourly_rate_cents": e["hourly_rate_cents"],
        "deposit_cents": e["deposit_cents"],
        "status": equipment_status(e),
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


# ----------------------------- Student ----------------------------
def student_age_years(student):
    """Whole years from birthdate to current logical-clock date (PRD §3.3)."""
    bd = parse_dt(student["birthdate"], "birthdate").astimezone(timezone.utc)
    now = clock.get()
    years = now.year - bd.year
    # subtract a year if the birthday has not yet occurred this clock-year
    if (now.month, now.day) < (bd.month, bd.day):
        years -= 1
    return years


def _waiver_effective_status(w):
    """REVOKED stays REVOKED; SIGNED becomes EXPIRED once clock >= expires_at."""
    if w["status"] == "REVOKED":
        return "REVOKED"
    if w["status"] == "EXPIRED":
        return "EXPIRED"
    # SIGNED -> EXPIRED when clock has reached/passed expiry
    expires = parse_dt(w["expires_at"], "expires_at")
    if clock.get() >= expires:
        return "EXPIRED"
    return "SIGNED"


def student_waiver_status(student_id):
    """Derived from the student's latest applicable waiver (PRD §3.3).

    NONE | SIGNED | EXPIRED | REVOKED. The latest waiver by created_at drives the
    status; SIGNED becomes EXPIRED against the logical clock.
    """
    ws = [w for w in db.waivers.values() if w["student_id"] == student_id]
    if not ws:
        return "NONE"
    latest = max(ws, key=lambda w: (w["created_at"], w["_seq"]))
    return _waiver_effective_status(latest)


def serialize_student(s):
    return {
        "id": s["id"],
        "school_id": s["school_id"],
        "full_name": s["full_name"],
        "birthdate": s["birthdate"],
        "age_years": student_age_years(s),
        "swim_test_status": s["swim_test_status"],
        "waiver_status": student_waiver_status(s["id"]),
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


# ------------------------------ Waiver ----------------------------
def serialize_waiver(w):
    return {
        "id": w["id"],
        "student_id": w["student_id"],
        "signed_by": w["signed_by"],
        "is_guardian": w["is_guardian"],
        "expires_at": w["expires_at"],
        "status": _waiver_effective_status(w),
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


# ---------------------------- Membership --------------------------
def serialize_membership(m):
    return {
        "id": m["id"],
        "student_id": m["student_id"],
        "tier": m["tier"],
        "status": m["status"],
        "makeup_credit_balance": m["makeup_credit_balance"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


# ---------------------------- Enrollment --------------------------
def enrollment_attended_count(enrollment_id):
    return sum(
        1 for b in db.bookings.values()
        if b["enrollment_id"] == enrollment_id and b["status"] == "ATTENDED"
    )


def serialize_enrollment(e):
    return {
        "id": e["id"],
        "school_id": e["school_id"],
        "student_id": e["student_id"],
        "course_level_id": e["course_level_id"],
        "membership_id": e["membership_id"],
        "planned_sessions": e["planned_sessions"],
        "party_size": e["party_size"],
        "progress_status": e["progress_status"],
        "payment_status": e["payment_status"],
        "estimated_price_cents": e["estimated_price_cents"],
        "final_price_cents": e["final_price_cents"],
        "refund_cents": e["refund_cents"],
        "attended_count": enrollment_attended_count(e["id"]),
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


# ------------------------------ Session ---------------------------
def session_enrolled_count(session_id):
    return sum(
        1 for b in db.bookings.values()
        if b["session_id"] == session_id and b["status"] in SEAT_STATUSES
    )


def session_required_instructors(session):
    level = db.levels.get(session["course_level_id"])
    cap = level["max_students_per_instructor"] if level else 1
    return calc.required_instructors(session_enrolled_count(session["id"]), cap)


def serialize_session(s):
    return {
        "id": s["id"],
        "school_id": s["school_id"],
        "course_level_id": s["course_level_id"],
        "instructor_id": s["instructor_id"],
        "starts_at": s["starts_at"],
        "ends_at": s["ends_at"],
        "tide_window_start": s["tide_window_start"],
        "tide_window_end": s["tide_window_end"],
        "capacity": s["capacity"],
        "enrolled_count": session_enrolled_count(s["id"]),
        "required_instructors": session_required_instructors(s),
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


# --------------------------- SessionBooking -----------------------
def serialize_booking(b):
    return {
        "id": b["id"],
        "session_id": b["session_id"],
        "enrollment_id": b["enrollment_id"],
        "is_makeup": b["is_makeup"],
        "status": b["status"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


# -------------------------- RentalAgreement -----------------------
def serialize_rental(r):
    return {
        "id": r["id"],
        "school_id": r["school_id"],
        "student_id": r["student_id"],
        "equipment_item_id": r["equipment_item_id"],
        "session_id": r["session_id"],
        "starts_at": r["starts_at"],
        "ends_at": r["ends_at"],
        "rental_fee_cents": r["rental_fee_cents"],
        "deposit_held_cents": r["deposit_held_cents"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


# ------------------------- CertificationCard ----------------------
def serialize_card(c):
    return {
        "id": c["id"],
        "student_id": c["student_id"],
        "enrollment_id": c["enrollment_id"],
        "course_level_id": c["course_level_id"],
        "discipline": c["discipline"],
        "card_number": c["card_number"],
        "issued_at": c["issued_at"],
        "created_at": c["created_at"],
    }
