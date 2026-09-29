"""Calculations program_capacity_seats and utilization_and_portable_need."""

import constants as C
from db import db
from services.numbers import D, ceil_div, floor_div, floor_of, pct1, round_half_up


def rooms_of(school_id, in_service_only=True):
    rows = [r for r in db.rooms.values() if r["school_id"] == school_id]
    if in_service_only:
        rows = [r for r in rows if r["status"] == "IN_SERVICE"]
    return rows


def _standard_seats(room, policy):
    return min(
        policy["max_class_size"],
        floor_div(room["area_sqft"], policy["min_area_sqft_per_seat"]),
    )


def district_seats(room, policy):
    room_type = room["room_type"]
    if room_type == "STANDARD_CLASSROOM":
        return _standard_seats(room, policy)
    if room_type == "SCIENCE_LAB":
        divisor = D(policy["min_area_sqft_per_seat"]) + D(policy["lab_area_premium_sqft"])
        if divisor <= 0:
            return 0
        return min(policy["max_class_size"], floor_div(room["area_sqft"], divisor))
    if room_type == "SPED_RESOURCE":
        return C.SPED_FIXED_SEATS
    if room_type == "ART_MUSIC":
        return floor_of(D(_standard_seats(room, policy)) * C.ART_MUSIC_LOADING_FACTOR)
    return 0


def state_seats(room):
    return C.STATE_LOADING.get(room["room_type"], 0)


def program_capacity(school_id, policy, method):
    """Returns (gross_room_seats, set_aside_deduction_seats, program_capacity_seats)."""
    rooms = rooms_of(school_id)
    if method == "DISTRICT_POLICY":
        gross = sum(district_seats(r, policy) for r in rooms)
    else:
        gross = sum(state_seats(r) for r in rooms)

    set_asides = [s for s in db.set_asides.values() if s["school_id"] == school_id]
    if method == "STATE_LOADING_STANDARD":
        set_asides = [s for s in set_asides if s["program_type"] == "SPED_SELF_CONTAINED"]

    deduction = 0
    for sa in set_asides:
        available = len([r for r in rooms if r["room_type"] == sa["reserved_room_type"]])
        deduction += min(sa["reserved_room_count"], available) * sa["seats_excluded_per_room"]

    net = max(0, gross - deduction)
    return gross, deduction, net


def selected_projections(school_id, school_year, grade_configuration, method):
    """One projection row per grade: newest wins, value-deterministic tie-break.

    Returns (selected_rows_by_grade, missing_grades).
    """
    grades = C.GRADE_SET[grade_configuration]
    selected = {}
    missing = []
    for grade in grades:
        candidates = [
            p for p in db.projections.values()
            if p["school_id"] == school_id
            and p["school_year"] == school_year
            and p["grade_level"] == grade
            and (method == "DISTRICT_POLICY" or p["source"] == "COHORT_SURVIVAL")
        ]
        if not candidates:
            missing.append(grade)
            continue
        candidates.sort(key=lambda r: r["_seq"])
        candidates.sort(
            key=lambda r: (r["created_at"], r["projected_students"]), reverse=True
        )
        selected[grade] = candidates[0]
    return selected, missing


def projected_total(school_id, school_year, grade_configuration, method):
    selected, _missing = selected_projections(
        school_id, school_year, grade_configuration, method
    )
    return sum(row["projected_students"] for row in selected.values())


def utilization(program_capacity_seats, projected_enrollment_total):
    """utilization_pct / portable_trigger_met / seat_deficit / required count."""
    if program_capacity_seats > 0:
        util = round_half_up(
            D(projected_enrollment_total) * 100 / D(program_capacity_seats), 1
        )
    else:
        util = D("0.0")
    trigger = util >= C.PORTABLE_TRIGGER_PCT
    effective_capacity = floor_div(
        D(program_capacity_seats) * C.TARGET_UTILIZATION_PCT, 100
    )
    deficit = max(0, projected_enrollment_total - effective_capacity) if trigger else 0
    required = ceil_div(deficit, C.STANDARD_PORTABLE_SEATS)
    return {
        "utilization_pct": pct1(util),
        "portable_trigger_met": bool(trigger),
        "seat_deficit": deficit,
        "required_portable_count": required,
    }


def compute_all(school, policy, school_year, method):
    """Full live recomputation for one (school, policy, year, method) tuple."""
    gross, deduction, net = program_capacity(school["id"], policy, method)
    total = projected_total(school["id"], school_year, school["grade_configuration"], method)
    figures = utilization(net, total)
    figures.update({
        "gross_room_seats": gross,
        "set_aside_deduction_seats": deduction,
        "program_capacity_seats": net,
        "projected_enrollment_total": total,
    })
    return figures
