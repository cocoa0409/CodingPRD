"""Cross-entity business rules: the resource battery shared by assignment and
confirmation, the withdrawal cascades of PRD 2.10, the rain-plan selector and
the funder outcome rollup."""

from datetime import timedelta
from decimal import Decimal

import calc
import derive
import logical_clock
from errors import ApiError
from store import db, get_dt, touch


# --------------------------------------------------------------------------
# lazy training expiry (PRD 3.3)
# --------------------------------------------------------------------------
def lazy_expire_training(educator):
    if educator is None:
        return
    now = logical_clock.now()
    for record in derive.training_for(educator["id"]):
        if record["status"] != "ASSESSED_PASS":
            continue
        expires_on = get_dt(record, "expires_on")
        if expires_on is not None and expires_on <= now:
            record["status"] = "EXPIRED"
            touch(record)
    bands, tier = derive.educator_credentials(educator)
    derive._apply(educator, {
        "curriculum_certified_grade_bands": bands,
        "animal_handling_tier": tier,
    })


# --------------------------------------------------------------------------
# the shared resource battery — PRD 2.9 checks 19 through 25
# --------------------------------------------------------------------------
def resource_battery(offering, educator, animal, trail, party_persons):
    if animal is not None:
        permit = db.permits.get(animal["permit_id"])
        if permit is None or permit["status"] != "ACTIVE":
            raise ApiError("ERR_PERMIT_NOT_ACTIVE")
        if animal["status"] != "AVAILABLE":
            raise ApiError("ERR_ANIMAL_NOT_AVAILABLE")
    if trail is not None and trail["status"] != "OPEN":
        raise ApiError("ERR_TRAIL_NOT_OPEN")
    if educator is not None:
        if educator["status"] != "CLEARED":
            raise ApiError("ERR_EDUCATOR_NOT_CLEARED")
        if offering["grade_band"] not in (educator.get("curriculum_certified_grade_bands") or []):
            raise ApiError("ERR_EDUCATOR_NOT_CERTIFIED_FOR_GRADE_BAND")
    if educator is not None and animal is not None:
        have = calc.HANDLING_TIER_RANK.get(educator.get("animal_handling_tier") or "NONE", 0)
        need = calc.HANDLING_TIER_RANK.get(animal["handling_tier_required"], 0)
        if have < need:
            raise ApiError("ERR_HANDLING_TIER_INSUFFICIENT")
    if trail is not None and trail["habitat_sensitivity"] == "HIGH":
        if party_persons > calc.HIGH_SENSITIVITY_MAX_PERSONS:
            raise ApiError("ERR_HABITAT_SENSITIVITY_LIMIT")


# --------------------------------------------------------------------------
# assignment-only checks — PRD 2.9 checks 30, 31, 32 and 48
# --------------------------------------------------------------------------
def check_season(booking, educator):
    if educator is None or educator["employment_type"] != "SEASONAL_EDUCATOR":
        return
    season_end = get_dt(educator, "season_end_date")
    end_utc = get_dt(booking, "end_utc")
    if season_end is None or end_utc > season_end:
        raise ApiError("ERR_EDUCATOR_SEASON_ENDED")


def _blocked_interval(booking):
    offering = derive.offering_of(booking)
    minutes = calc.educator_buffer_minutes(offering["delivery_mode"]) if offering else 0
    buffer = timedelta(minutes=minutes)
    return get_dt(booking, "start_utc") - buffer, get_dt(booking, "end_utc") + buffer


def check_educator_conflict(booking, educator):
    if educator is None:
        return
    low, high = _blocked_interval(booking)
    for other in derive.bookings_where("lead_educator_id", educator["id"]):
        if other["id"] == booking["id"]:
            continue
        if other["delivery_status"] not in derive.LOAD_BEARING:
            continue
        other_low, other_high = _blocked_interval(other)
        # closed intervals: touching endpoints DO collide
        if low <= other_high and other_low <= high:
            raise ApiError("ERR_EDUCATOR_TIME_CONFLICT")


def check_animal_conflict(booking, animal):
    if animal is None:
        return
    start = get_dt(booking, "start_utc")
    end = get_dt(booking, "end_utc")
    for other in derive.bookings_where("animal_id", animal["id"]):
        if other["id"] == booking["id"]:
            continue
        if other["delivery_status"] not in derive.OCCUPYING:
            continue
        other_start = get_dt(other, "start_utc")
        other_end = get_dt(other, "end_utc")
        # half-open windows
        if start < other_end and other_start < end:
            raise ApiError("ERR_ANIMAL_TIME_CONFLICT")


def check_weekly_load(booking, educator, offering):
    if educator is None:
        return
    load = derive.educator_load(educator, exclude_booking_id=booking["id"])
    if load + offering["duration_minutes"] > derive.educator_weekly_cap(educator):
        raise ApiError("ERR_EDUCATOR_WEEKLY_LOAD_EXCEEDED")


# --------------------------------------------------------------------------
# confirmation-only checks
# --------------------------------------------------------------------------
def check_welfare_gate(animal, offering):
    if animal is None:
        return
    projected = derive.animal_projected(animal)
    if projected + offering["duration_minutes"] >= animal["weekly_exposure_cap_minutes"]:
        raise ApiError("ERR_ANIMAL_WELFARE_CAP_REACHED")


def check_public_contact(animal, offering):
    if not offering["public_contact_required"] or animal is None:
        return
    posture, rule = derive.animal_posture(animal, derive.animal_projected(animal))
    if rule != "SUPERVISED_TOUCH":
        raise ApiError("ERR_PUBLIC_CONTACT_NOT_PERMITTED")


def _occupancy(booking, buffer_minutes):
    return (
        get_dt(booking, "start_utc"),
        get_dt(booking, "end_utc") + timedelta(minutes=buffer_minutes),
    )


def check_trail_capacity(booking, trail):
    if trail is None:
        return
    buffer_minutes = trail["recovery_buffer_minutes"]
    low, high = _occupancy(booking, buffer_minutes)
    total = derive.persons(booking)
    for other in derive.bookings_where("trail_segment_id", trail["id"]):
        if other["id"] == booking["id"]:
            continue
        if other["delivery_status"] not in derive.OCCUPYING:
            continue
        other_low, other_high = _occupancy(other, buffer_minutes)
        # half-open windows: touching endpoints do NOT collide
        if low < other_high and other_low < high:
            total += derive.persons(other)
    if total > trail["capacity_persons"]:
        raise ApiError("ERR_TRAIL_CAPACITY_EXCEEDED")


def check_trail_weekly_budget(booking, trail):
    if trail is None:
        return
    visitors = derive.trail_visitors_this_week(trail, exclude_booking_id=booking["id"])
    if visitors + derive.persons(booking) > trail["weekly_visitor_budget_persons"]:
        raise ApiError("ERR_TRAIL_WEEKLY_BUDGET_EXCEEDED")


# --------------------------------------------------------------------------
# withdrawal cascades (PRD 2.10)
# --------------------------------------------------------------------------
def revert_booking(booking, reason, clear_animal=False, clear_trail=False, clear_educator=False):
    booking["delivery_status"] = "REQUESTED"
    if clear_animal:
        booking["animal_id"] = None
    if clear_trail:
        booking["trail_segment_id"] = None
    if clear_educator:
        booking["lead_educator_id"] = None
    booking["resource_release_reason"] = reason
    touch(booking)


def release_bookings_for_animal(animal, reason="PERMIT_LAPSE"):
    for booking in derive.bookings_where("animal_id", animal["id"]):
        if booking["delivery_status"] == "CONFIRMED":
            revert_booking(booking, reason, clear_animal=True, clear_trail=True)


def release_bookings_for_trail(trail, reason="PERMIT_LAPSE"):
    for booking in derive.bookings_where("trail_segment_id", trail["id"]):
        if booking["delivery_status"] == "CONFIRMED":
            revert_booking(booking, reason, clear_trail=True)


def release_bookings_for_educator(educator, reason="PERMIT_LAPSE"):
    for booking in derive.bookings_where("lead_educator_id", educator["id"]):
        status = booking["delivery_status"]
        if status not in ("REQUESTED", "CONFIRMED"):
            continue
        if status == "CONFIRMED":
            revert_booking(booking, reason, clear_educator=True)
        else:
            booking["lead_educator_id"] = None
            touch(booking)


def revoke_awarded_aid(booking):
    """Reverse every award on this booking; the fund ledger is rebuilt by sync()."""
    for application in derive.aid_for_booking(booking["id"]):
        if application["status"] in derive.AWARDED:
            application["status"] = "REVOKED"
            application["awarded_scholarship_cents"] = 0
            application["awarded_transport_cents"] = 0
            touch(application)


def cascade_school_suspension(school, origin_booking_id=None):
    """PRD 2.10: a suspended school loses every other REQUESTED booking."""
    if school["status"] != "SUSPENDED":
        return
    for booking in derive.bookings_where("school_id", school["id"]):
        if booking["id"] == origin_booking_id:
            continue
        if booking["delivery_status"] != "REQUESTED":
            continue
        booking["delivery_status"] = "CANCELLED"
        booking["resource_release_reason"] = "SCHOOL_SUSPENSION"
        revoke_awarded_aid(booking)
        if booking["funding_status"] == "AID_APPROVED":
            booking["funding_status"] = "UNFUNDED"
        touch(booking)


# --------------------------------------------------------------------------
# rain-plan alternate selector
# --------------------------------------------------------------------------
def rain_candidates(booking, offering):
    party = derive.persons(booking)
    pool = []
    for candidate in db.offerings.values():
        if candidate.get("rain_alternate_for_offering_id") != booking["offering_id"]:
            continue
        if candidate["status"] != "PUBLISHED":
            continue
        if candidate["grade_band"] != offering["grade_band"]:
            continue
        if candidate["requires_trail_segment"]:
            continue
        if candidate["max_group_size"] < party:
            continue
        pool.append(candidate)
    pool.sort(key=lambda o: (
        -o["standard_alignment_count"],
        o["base_fee_cents_per_student"],
        o["created_at"],
        o["_seq"],
    ))
    return pool


# --------------------------------------------------------------------------
# funder outcome rollup
# --------------------------------------------------------------------------
def outcome_report(fund):
    awarded_application_count = 0
    disbursed_booking_ids = set()
    for application in derive.aid_for_fund(fund["id"]):
        if application["status"] in derive.CREDITING:
            awarded_application_count += 1
        if application["status"] == "DISBURSED":
            disbursed_booking_ids.add(application["booking_id"])

    qualifying = []
    for report in db.evaluations.values():
        if report["status"] != "ACCEPTED":
            continue
        booking = db.bookings.get(report["booking_id"])
        if booking is None or booking["delivery_status"] != "DELIVERED":
            continue
        if booking["id"] not in disbursed_booking_ids:
            continue
        qualifying.append((report, booking))

    students = sum((b.get("actual_student_count") or 0) for _, b in qualifying)
    if students == 0:
        weighted = Decimal("0.000")
        tier_1_share = Decimal("0.000")
    else:
        numerator = sum(
            (calc.D(r["learning_gain_index"]) * calc.D(b.get("actual_student_count") or 0))
            for r, b in qualifying
        )
        weighted = calc.round_half_up(numerator / calc.D(students), 3)
        tier_1_students = 0
        for _, booking in qualifying:
            school = db.schools.get(booking["school_id"])
            if school and school.get("equity_tier") == "TIER_1":
                tier_1_students += booking.get("actual_student_count") or 0
        tier_1_share = calc.round_half_up(calc.D(tier_1_students) / calc.D(students), 3)

    return {
        "fund_id": fund["id"],
        "total_cents": fund["total_cents"],
        "committed_cents": fund["committed_cents"],
        "disbursed_cents": fund["disbursed_cents"],
        "available_cents": fund["available_cents"],
        "awarded_application_count": awarded_application_count,
        "students_served_count": students,
        "weighted_learning_gain_index": float(weighted),
        "tier_1_student_share_pct": float(tier_1_share),
    }
