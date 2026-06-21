"""Domain constants, serialization, and derived-state recomputation."""
from decimal import Decimal, ROUND_HALF_UP

import db
import clock
from helpers import round_half_up_int, round_half_up_dp

# ---------------------------------------------------------------------------
# Constants (from scaffold §1.3 calculations)
# ---------------------------------------------------------------------------
MIN_ROAD_HOURS = 6
MIN_CLASSROOM_HOURS = 30
MIN_ONLINE_HOURS = 8
W_ROAD = Decimal("0.5")
W_CLASS = Decimal("0.3")
W_ONLINE = Decimal("0.2")

TEEN_DISCOUNT_PCT = Decimal("0.10")
PROMO_FLAT10_PCT = Decimal("0.10")

TIER1_DAYS = 3
TIER2_DAYS = 14
TIER3_DAYS = 30

FORGIVE_STRIKES = 1
BASE_NO_SHOW_FEE_CENTS = 4000
ESCALATION_MULTIPLIER = 2

CANCEL_CUTOFF_HOURS = 24


# ---------------------------------------------------------------------------
# Common system fields
# ---------------------------------------------------------------------------
def stamp_create_full(rec):
    ts = clock.iso_now()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    return rec


def stamp_create_ledger(rec):
    rec["created_at"] = clock.iso_now()
    return rec


def touch(rec):
    """Mutation of a full resource: bump updated_at and version."""
    rec["updated_at"] = clock.iso_now()
    rec["version"] = rec["version"] + 1


# ---------------------------------------------------------------------------
# Student derived-state recomputation
# ---------------------------------------------------------------------------
def compute_is_minor(date_of_birth_iso):
    from helpers import parse_dt

    dob = parse_dt(date_of_birth_iso)
    now = clock.now()
    age = now.year - dob.year - ((now.month, now.day) < (dob.month, dob.day))
    return age < 18


def recompute_readiness(student):
    road = student["completed_road_hours"]
    cls = student["completed_classroom_hours"]
    onl = student["completed_online_hours"]
    road_pct = min(Decimal(str(road)) / Decimal(MIN_ROAD_HOURS), Decimal(1))
    class_pct = min(Decimal(str(cls)) / Decimal(MIN_CLASSROOM_HOURS), Decimal(1))
    online_pct = min(Decimal(str(onl)) / Decimal(MIN_ONLINE_HOURS), Decimal(1))
    score = W_ROAD * road_pct + W_CLASS * class_pct + W_ONLINE * online_pct
    score = score.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    student["readiness_score"] = float(score)


def recompute_wallet(student):
    sid = student["id"]
    total = 0
    for w in db.wallet_entries.values():
        if w["student_id"] == sid:
            total += w["amount_cents"]
    student["wallet_balance_cents"] = total


def recompute_no_show_count(student):
    sid = student["id"]
    student["no_show_count"] = sum(
        1 for s in db.no_show_strikes.values() if s["student_id"] == sid
    )


def maybe_regress_or_advance_milestone(student):
    """Apply road-hours-driven milestone moves (does NOT bump version itself;
    caller wraps the whole op in a single version bump)."""
    if student["status"] == "PERMITTED" and student["completed_road_hours"] >= MIN_ROAD_HOURS:
        student["status"] = "ROAD_READY"
    elif student["status"] == "ROAD_READY" and student["completed_road_hours"] < MIN_ROAD_HOURS:
        student["status"] = "PERMITTED"


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def ser_course_package(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "code": p["code"],
        "name": p["name"],
        "price_cents": p["price_cents"],
        "enrollment_fee_cents": p["enrollment_fee_cents"],
        "included_classroom_hours": p["included_classroom_hours"],
        "included_online_hours": p["included_online_hours"],
        "included_road_hours": p["included_road_hours"],
        "bundle_discount_cents": p["bundle_discount_cents"],
        "active": p["active"],
    }


def ser_student(s):
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
        "full_name": s["full_name"],
        "email": s["email"],
        "date_of_birth": s["date_of_birth"],
        "is_minor": s["is_minor"],
        "permit_number": s["permit_number"],
        "status": s["status"],
        "completed_classroom_hours": s["completed_classroom_hours"],
        "completed_online_hours": s["completed_online_hours"],
        "completed_road_hours": s["completed_road_hours"],
        "scheduled_road_hours": s["scheduled_road_hours"],
        "readiness_score": s["readiness_score"],
        "no_show_count": s["no_show_count"],
        "wallet_balance_cents": s["wallet_balance_cents"],
    }


def ser_guardian_consent(g):
    return {
        "id": g["id"],
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
        "student_id": g["student_id"],
        "guardian_name": g["guardian_name"],
        "guardian_email": g["guardian_email"],
        "relationship": g["relationship"],
        "status": g["status"],
    }


def ser_enrollment(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
        "student_id": e["student_id"],
        "package_id": e["package_id"],
        "promo_code": e["promo_code"],
        "status": e["status"],
        "final_price_cents": e["final_price_cents"],
        "amount_paid_cents": e["amount_paid_cents"],
        "refund_method": e["refund_method"],
        "refunded_cents": e["refunded_cents"],
        "activated_at": e["activated_at"],
    }


def ser_instructor(i):
    return {
        "id": i["id"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
        "full_name": i["full_name"],
        "email": i["email"],
        "certified_road": i["certified_road"],
        "hourly_rate_cents": i["hourly_rate_cents"],
        "active": i["active"],
    }


def ser_vehicle(v):
    return {
        "id": v["id"],
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
        "plate": v["plate"],
        "dual_control": v["dual_control"],
        "prep_buffer_minutes": v["prep_buffer_minutes"],
        "out_of_service": v["out_of_service"],
    }


def ser_lesson(l):
    return {
        "id": l["id"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
        "student_id": l["student_id"],
        "enrollment_id": l["enrollment_id"],
        "instructor_id": l["instructor_id"],
        "vehicle_id": l["vehicle_id"],
        "lesson_type": l["lesson_type"],
        "start_at": l["start_at"],
        "end_at": l["end_at"],
        "duration_hours": l["duration_hours"],
        "status": l["status"],
        "instructor_payout_cents": l["instructor_payout_cents"],
    }


def ser_no_show_strike(n):
    return {
        "id": n["id"],
        "created_at": n["created_at"],
        "student_id": n["student_id"],
        "lesson_id": n["lesson_id"],
        "strike_index": n["strike_index"],
        "fee_charged_cents": n["fee_charged_cents"],
    }


def ser_wallet_entry(w):
    return {
        "id": w["id"],
        "created_at": w["created_at"],
        "student_id": w["student_id"],
        "amount_cents": w["amount_cents"],
        "reason": w["reason"],
        "enrollment_id": w["enrollment_id"],
    }


def ser_certificate(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "student_id": c["student_id"],
        "enrollment_id": c["enrollment_id"],
        "dmv_reference": c["dmv_reference"],
        "readiness_score_at_issue": c["readiness_score_at_issue"],
        "status": c["status"],
    }
