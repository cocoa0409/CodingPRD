"""Shared business logic: serializers, derived counters, standing thresholds,
cascades, and the logical-clock sweeps."""

import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from db import STORE, new_id, next_seq, now, fmt_ts, bump
from errors import err

# ---------------------------------------------------------------------------
# Constants from the calculation rules
# ---------------------------------------------------------------------------

BASE_BY_GRADE = {9: 4, 10: 4, 11: 6, 12: 8}
STANDING_MULT = {"GOOD": 1.0, "PROBATION": 0.5, "SUSPENDED": 0.0}
ALLOWANCE_CAP = 10

PROBATION_AT = 10
SUSPENDED_AT = 20

LATE_LADDER = ((1, 15, 1), (16, 60, 2))  # 0 -> 0; 1-15 -> 1; 16-60 -> 2; >60 -> 3

NIGHT_CHECK_POINTS = {
    "BED_CHECK": {"PRESENT": 0, "LATE_ARRIVAL": 1, "ABSENT_EXCUSED": 0, "ABSENT_UNEXCUSED": 3},
    "STUDY_HALL": {"PRESENT": 0, "LATE_ARRIVAL": 1, "ABSENT_EXCUSED": 0, "ABSENT_UNEXCUSED": 2},
}

ROOM_CHARGE_FLAT_CENTS = 20000
DEPOSIT_CAP_CENTS = 5000
DEPOSIT_RATE = Decimal("0.10")

RATE_CENTS_PER_CUFT_WEEK = 250
EARLY_BIRD_DISCOUNT = Decimal("0.15")
EARLY_BIRD_DAYS = 30

APPEAL_WINDOW = timedelta(hours=168)
SIGN_OUT_BEFORE = timedelta(hours=2)
SIGN_OUT_AFTER = timedelta(hours=6)

LEAVE_PENDING_STATUSES = {"REQUESTED", "PARENT_APPROVED", "APPROVED"}
LEAVE_COUNTED_STATUSES = {"APPROVED", "SIGNED_OUT", "OVERDUE", "RETURNED"}


def new_common():
    ts = now()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1,
            "_seq": next_seq()}


def new_event():
    ts = now()
    return {"id": new_id(), "created_at": ts, "_seq": next_seq()}


# ---------------------------------------------------------------------------
# Derived lookups
# ---------------------------------------------------------------------------

def active_term():
    for t in STORE["terms"].values():
        if t["status"] == "ACTIVE":
            return t
    return None


def room_beds_assigned(room_id):
    n = 0
    for a in STORE["dorm_assignments"].values():
        if a["room_id"] == room_id and a["status"] == "CONFIRMED":
            n += 1
    return n


def dorm_counters(dorm_id):
    rooms = [r for r in STORE["rooms"].values() if r["dorm_id"] == dorm_id]
    room_ids = {r["id"] for r in rooms}
    beds_total = sum(r["beds"] for r in rooms)
    physical = projected_extra = 0
    for a in STORE["dorm_assignments"].values():
        if a["room_id"] in room_ids:
            if a["status"] == "CONFIRMED":
                physical += 1
            elif a["status"] == "PROPOSED":
                projected_extra += 1
    return beds_total, physical, physical + projected_extra, beds_total - physical


def guardian_wards_assigned(guardian_id):
    n = 0
    for s in STORE["students"].values():
        if s.get("guardian_id") == guardian_id and s["enrollment_status"] in ("ENROLLED", "ON_LEAVE"):
            n += 1
    return n


def student_provisional_points(student_id, official):
    extra = 0
    for c in STORE["discipline_cases"].values():
        if c["student_id"] == student_id and c["status"] in (
                "REPORTED", "UNDER_REVIEW", "HEARING_SCHEDULED", "APPEALED"):
            extra += c.get("points_proposed") or 0
    return official + extra


def weekend_leaves_used(student_id):
    term = active_term()
    if term is None:
        return 0
    start = datetime.combine(term["_starts_on"], datetime.min.time(), tzinfo=timezone.utc)
    end = datetime.combine(term["_ends_on"], datetime.max.time(), tzinfo=timezone.utc)
    n = 0
    for lv in STORE["leave_requests"].values():
        if (lv["student_id"] == student_id
                and lv["leave_type"] == "WEEKEND_OVERNIGHT"
                and lv["status"] in LEAVE_COUNTED_STATUSES
                and start <= lv["_departs_at"] <= end):
            n += 1
    return n


def weekend_leave_allowance(student):
    base = BASE_BY_GRADE.get(student["grade"], 0)
    mult = STANDING_MULT.get(student["discipline_standing"], 1.0)
    bonus = 0
    if student.get("is_international") and student.get("guardian_id"):
        g = STORE["guardians"].get(student["guardian_id"])
        if g is not None and g["status"] == "APPROVED":
            bonus = 1
    return min(ALLOWANCE_CAP, math.floor(base * mult) + bonus)


def med_doses_remaining(order):
    used = 0
    for adm in STORE["medication_administrations"].values():
        if adm["order_id"] == order["id"] and adm["outcome"] == "ADMINISTERED":
            used += 1
    return order["doses_total"] - used


def storage_unit_used_cuft(unit_id):
    total = 0
    for r in STORE["storage_reservations"].values():
        if r["storage_unit_id"] == unit_id and r["status"] in ("RESERVED", "CHECKED_IN"):
            total += r["volume_cuft"]
    return total


def confirmed_assignment_in_term(student_id, term):
    """The student's CONFIRMED DormAssignment in the ACTIVE term, or None."""
    if term is None:
        return None
    for a in STORE["dorm_assignments"].values():
        if (a["student_id"] == student_id and a["term_id"] == term["id"]
                and a["status"] == "CONFIRMED"):
            return a
    return None


def compatibility_score(sa, sb):
    score = 100 - (
        12 * abs(sa["sleep_schedule"] - sb["sleep_schedule"])
        + 8 * abs(sa["cleanliness"] - sb["cleanliness"])
        + 8 * abs(sa["noise_tolerance"] - sb["noise_tolerance"])
        + 4 * abs(sa["guests_comfort"] - sb["guests_comfort"])
    )
    return max(0, score)


def late_points_ladder(minutes_late):
    if minutes_late <= 0:
        return 0
    if minutes_late <= 15:
        return 1
    if minutes_late <= 60:
        return 2
    return 3


def whole_minutes_between(later, earlier):
    secs = (later - earlier).total_seconds()
    if secs <= 0:
        return 0
    return int(secs // 60)


# ---------------------------------------------------------------------------
# Standing reevaluation and cascades
# ---------------------------------------------------------------------------

def reevaluate_standing(student):
    """Recompute standing from demerit_points; flip stored value, bump version,
    and cascade-cancel pending leaves on transition into SUSPENDED."""
    pts = student["demerit_points"]
    new = "SUSPENDED" if pts >= SUSPENDED_AT else ("PROBATION" if pts >= PROBATION_AT else "GOOD")
    old = student["discipline_standing"]
    if new == old:
        return
    student["discipline_standing"] = new
    bump(student)
    if new == "SUSPENDED":
        for lv in STORE["leave_requests"].values():
            if lv["student_id"] == student["id"] and lv["status"] in LEAVE_PENDING_STATUSES:
                lv["status"] = "CANCELLED"
                lv["denial_reason"] = "STANDING_SUSPENDED"
                bump(lv)


def clear_roommate_link(assignment):
    """Dissolve the mutual roommate link on both sides (version bumps for the
    partner; caller bumps the assignment itself)."""
    partner_id = assignment.get("roommate_assignment_id")
    if partner_id:
        partner = STORE["dorm_assignments"].get(partner_id)
        if partner is not None and partner.get("roommate_assignment_id") == assignment["id"]:
            partner["roommate_assignment_id"] = None
            partner["compatibility_score"] = None
            bump(partner)
    assignment["roommate_assignment_id"] = None
    assignment["compatibility_score"] = None


def recompute_room_status(room):
    """Auto-flip AVAILABLE<->FULL based on confirmed occupancy; bumps version
    only on an actual status change."""
    assigned = room_beds_assigned(room["id"])
    if room["status"] in ("AVAILABLE", "FULL"):
        if assigned >= room["beds"] and room["status"] != "FULL":
            room["status"] = "FULL"
            bump(room)
        elif assigned < room["beds"] and room["status"] == "FULL":
            room["status"] = "AVAILABLE"
            bump(room)


def end_assignment(assignment):
    """CONFIRMED -> ENDED with room and roommate side effects."""
    ts = now()
    assignment["status"] = "ENDED"
    assignment["check_out_at"] = ts
    clear_roommate_link(assignment)
    bump(assignment)
    room = STORE["rooms"].get(assignment["room_id"])
    if room is not None:
        recompute_room_status(room)


def supersede_assignment(assignment):
    """PROPOSED -> SUPERSEDED with roommate link cleanup."""
    assignment["status"] = "SUPERSEDED"
    clear_roommate_link(assignment)
    bump(assignment)
    room = STORE["rooms"].get(assignment["room_id"])
    if room is not None:
        recompute_room_status(room)


def cancel_leave(leave, reason):
    leave["status"] = "CANCELLED"
    leave["denial_reason"] = reason
    bump(leave)


def withdraw_cascade(student):
    """Student withdrawal: end/supersede active-term assignments, cancel pending
    leaves, discontinue active/held medication orders, cancel break-housing
    requests and reserved storage."""
    sid = student["id"]
    term = active_term()
    if term is not None:
        for a in list(STORE["dorm_assignments"].values()):
            if a["student_id"] == sid and a["term_id"] == term["id"]:
                if a["status"] == "CONFIRMED":
                    end_assignment(a)
                elif a["status"] == "PROPOSED":
                    supersede_assignment(a)
    for lv in list(STORE["leave_requests"].values()):
        if lv["student_id"] == sid and lv["status"] in LEAVE_PENDING_STATUSES:
            cancel_leave(lv, "STUDENT_WITHDRAWN")
    for o in list(STORE["medication_orders"].values()):
        if o["student_id"] == sid and o["status"] in ("ACTIVE", "HOLD"):
            o["status"] = "DISCONTINUED"
            bump(o)
    for r in list(STORE["break_housing_requests"].values()):
        if r["student_id"] == sid and r["status"] in ("REQUESTED", "APPROVED"):
            r["status"] = "CANCELLED"
            bump(r)
    for r in list(STORE["storage_reservations"].values()):
        if r["student_id"] == sid and r["status"] == "RESERVED":
            r["status"] = "CANCELLED"
            bump(r)


def term_close_cascade(term):
    """Close the active term: end/supersede its assignments, clear roommate
    links, recompute rooms, cancel in-flight leaves."""
    for a in list(STORE["dorm_assignments"].values()):
        if a["term_id"] == term["id"]:
            if a["status"] == "CONFIRMED":
                end_assignment(a)
            elif a["status"] == "PROPOSED":
                supersede_assignment(a)
    for lv in list(STORE["leave_requests"].values()):
        if lv["status"] in LEAVE_PENDING_STATUSES:
            cancel_leave(lv, "TERM_CLOSED")


def break_close_cascade(bp):
    for r in list(STORE["break_housing_requests"].values()):
        if r["break_period_id"] == bp["id"] and r["status"] == "CHECKED_IN":
            r["status"] = "CHECKED_OUT"
            bump(r)
    for r in list(STORE["storage_reservations"].values()):
        if r["break_period_id"] == bp["id"] and r["status"] == "RESERVED":
            r["status"] = "EXPIRED"
            bump(r)


def run_sweeps():
    """All time-based sweeps, run after every logical-clock advance."""
    now_dt = now()
    today = now_dt.date()

    # BreakPeriod lifecycle
    for bp in list(STORE["break_periods"].values()):
        if bp["status"] == "UPCOMING" and today >= bp["_starts_on"]:
            bp["status"] = "ACTIVE"
            bump(bp)
        if bp["status"] == "ACTIVE" and today > bp["_ends_on"]:
            bp["status"] = "CLOSED"
            bump(bp)
            break_close_cascade(bp)

    # Leave expiry / overdue
    for lv in list(STORE["leave_requests"].values()):
        if lv["status"] == "APPROVED" and now_dt > lv["_departs_at"] + SIGN_OUT_AFTER:
            lv["status"] = "EXPIRED"
            bump(lv)
        elif lv["status"] == "SIGNED_OUT" and now_dt > lv["_returns_at"]:
            lv["status"] = "OVERDUE"
            bump(lv)

    # Duty shifts missed
    for sh in list(STORE["duty_shifts"].values()):
        if sh["status"] == "SCHEDULED" and today > sh["_duty_date"]:
            if not shift_bed_checks_complete(sh):
                sh["status"] = "MISSED"
                bump(sh)


def dorm_enrolled_residents(dorm_id):
    """ENROLLED students with a CONFIRMED assignment in this dorm (ACTIVE term)."""
    term = active_term()
    if term is None:
        return []
    room_ids = {r["id"] for r in STORE["rooms"].values() if r["dorm_id"] == dorm_id}
    out = []
    for a in STORE["dorm_assignments"].values():
        if (a["room_id"] in room_ids and a["term_id"] == term["id"]
                and a["status"] == "CONFIRMED"):
            stu = STORE["students"].get(a["student_id"])
            if stu is not None and stu["enrollment_status"] == "ENROLLED":
                out.append(stu)
    return out


def shift_bed_checks_complete(shift):
    residents = dorm_enrolled_residents(shift["dorm_id"])
    checked = {nc["student_id"] for nc in STORE["night_checks"].values()
               if nc["duty_shift_id"] == shift["id"] and nc["check_kind"] == "BED_CHECK"}
    return all(s["id"] in checked for s in residents)


def shift_slot_conflict(staff_id, duty_date, slot, exclude_ids=()):
    """Conflict iff another non-CANCELLED shift for the same staff on the same
    date carries the same slot (WEEKEND_DAY/WEEKEND_NIGHT never conflict with
    each other; WEEKDAY_NIGHT conflicts only with WEEKDAY_NIGHT)."""
    for sh in STORE["duty_shifts"].values():
        if sh["id"] in exclude_ids:
            continue
        if (sh["staff_id"] == staff_id and sh["_duty_date"] == duty_date
                and sh["status"] != "CANCELLED" and sh["shift_slot"] == slot):
            return True
    return False


def storage_fee(volume_cuft, weeks, early_bird):
    rate = Decimal(RATE_CENTS_PER_CUFT_WEEK)
    if early_bird:
        rate = rate * (Decimal(1) - EARLY_BIRD_DISCOUNT)
    raw = Decimal(volume_cuft) * Decimal(weeks) * rate
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def break_housing_fee_breakdown(student_id, break_period_id):
    """Pinned evaluation order: room charge, storage total, deposit credit, fee."""
    room_charge = ROOM_CHARGE_FLAT_CENTS
    storage_total = 0
    for r in STORE["storage_reservations"].values():
        if (r["student_id"] == student_id and r["break_period_id"] == break_period_id
                and r["status"] in ("RESERVED", "CHECKED_IN", "EXPIRED")):
            storage_total += r["fee_cents"]
    deposit = int((DEPOSIT_RATE * Decimal(room_charge + storage_total)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))
    deposit = min(DEPOSIT_CAP_CENTS, deposit)
    return room_charge, storage_total, deposit, room_charge + storage_total - deposit


# ---------------------------------------------------------------------------
# Serializers (public views)
# ---------------------------------------------------------------------------

def _base(e):
    return {
        "id": e["id"],
        "created_at": fmt_ts(e["created_at"]),
        "updated_at": fmt_ts(e["updated_at"]),
        "version": e["version"],
    }


def ser_term(t):
    d = _base(t)
    d.update({"name": t["name"], "starts_on": t["starts_on"],
              "ends_on": t["ends_on"], "status": t["status"]})
    return d


def ser_dorm(x):
    d = _base(x)
    beds_total, physical, projected, beds_available = dorm_counters(x["id"])
    d.update({
        "name": x["name"], "gender_policy": x["gender_policy"],
        "curfew_weekday": x["curfew_weekday"], "curfew_weekend": x["curfew_weekend"],
        "posture": x["posture"], "beds_total": beds_total,
        "occupancy_physical": physical, "occupancy_projected": projected,
        "beds_available": beds_available,
    })
    return d


def ser_room(r):
    d = _base(r)
    assigned = room_beds_assigned(r["id"])
    d.update({
        "dorm_id": r["dorm_id"], "room_number": r["room_number"], "beds": r["beds"],
        "status": r["status"], "beds_assigned": assigned,
        "beds_available": r["beds"] - assigned,
    })
    return d


def ser_parent(p):
    d = _base(p)
    d.update({"full_name": p["full_name"], "email": p["email"]})
    return d


def ser_guardian(g):
    d = _base(g)
    d.update({
        "full_name": g["full_name"], "email": g["email"], "city": g["city"],
        "max_wards": g["max_wards"], "wards_assigned": guardian_wards_assigned(g["id"]),
        "status": g["status"],
    })
    return d


def ser_staff(s):
    d = _base(s)
    d.update({
        "full_name": s["full_name"], "staff_role": s["staff_role"],
        "dorm_id": s["dorm_id"], "is_active": s["is_active"],
    })
    return d


def ser_student(s):
    d = _base(s)
    official = s["demerit_points"]
    d.update({
        "legal_name": s["legal_name"], "grade": s["grade"], "gender": s["gender"],
        "is_international": s["is_international"], "parent_id": s["parent_id"],
        "guardian_id": s["guardian_id"],
        "sleep_schedule": s["sleep_schedule"], "cleanliness": s["cleanliness"],
        "noise_tolerance": s["noise_tolerance"], "guests_comfort": s["guests_comfort"],
        "enrollment_status": s["enrollment_status"],
        "discipline_standing": s["discipline_standing"],
        "demerit_points": official,
        "demerit_points_provisional": student_provisional_points(s["id"], official),
        "weekend_leaves_used": weekend_leaves_used(s["id"]),
        "weekend_leave_allowance": weekend_leave_allowance(s),
    })
    return d


def ser_assignment(a):
    d = _base(a)
    d.update({
        "student_id": a["student_id"], "room_id": a["room_id"], "term_id": a["term_id"],
        "roommate_assignment_id": a["roommate_assignment_id"], "status": a["status"],
        "compatibility_score": a["compatibility_score"],
        "check_in_at": fmt_ts(a["check_in_at"]) if a["check_in_at"] else None,
        "check_out_at": fmt_ts(a["check_out_at"]) if a["check_out_at"] else None,
    })
    return d


def ser_leave(lv):
    d = _base(lv)
    d.update({
        "student_id": lv["student_id"], "leave_type": lv["leave_type"],
        "destination": lv["destination"],
        "departs_at": lv["departs_at"], "returns_at": lv["returns_at"],
        "status": lv["status"],
        "decided_by_parent_id": lv["decided_by_parent_id"],
        "decided_by_staff_id": lv["decided_by_staff_id"],
        "denial_reason": lv["denial_reason"],
        "signed_out_at": fmt_ts(lv["signed_out_at"]) if lv["signed_out_at"] else None,
        "returned_at": fmt_ts(lv["returned_at"]) if lv["returned_at"] else None,
        "late_return_minutes": lv["late_return_minutes"],
    })
    return d


def ser_sign_event(ev):
    return {
        "id": ev["id"],
        "created_at": fmt_ts(ev["created_at"]),
        "student_id": ev["student_id"],
        "event_type": ev["event_type"],
        "occurred_at": ev["occurred_at"],
        "leave_request_id": ev["leave_request_id"],
        "recorded_by_staff_id": ev["recorded_by_staff_id"],
        "minutes_late": ev["minutes_late"],
    }


def ser_shift(sh):
    d = _base(sh)
    d.update({
        "dorm_id": sh["dorm_id"], "staff_id": sh["staff_id"],
        "duty_date": sh["duty_date"], "shift_slot": sh["shift_slot"],
        "status": sh["status"], "swap_requested_to_id": sh["swap_requested_to_id"],
        "cancel_reason": sh["cancel_reason"],
    })
    return d


def ser_night_check(nc):
    return {
        "id": nc["id"],
        "created_at": fmt_ts(nc["created_at"]),
        "duty_shift_id": nc["duty_shift_id"], "student_id": nc["student_id"],
        "check_kind": nc["check_kind"], "result": nc["result"],
        "checked_at": fmt_ts(nc["checked_at"]),
        "points_assessed": nc["points_assessed"],
    }


def ser_med_order(o):
    d = _base(o)
    remaining = med_doses_remaining(o)
    d.update({
        "student_id": o["student_id"], "medication_name": o["medication_name"],
        "dose_mg": o["dose_mg"], "slot": o["slot"], "doses_total": o["doses_total"],
        "doses_remaining": remaining, "refill_threshold": o["refill_threshold"],
        "low_stock": remaining <= o["refill_threshold"],
        "is_controlled": o["is_controlled"], "prescriber_name": o["prescriber_name"],
        "status": o["status"], "hold_reason": o["hold_reason"],
    })
    return d


def ser_med_admin(a):
    return {
        "id": a["id"],
        "created_at": fmt_ts(a["created_at"]),
        "order_id": a["order_id"], "scheduled_date": a["scheduled_date"],
        "outcome": a["outcome"],
        "administered_by_staff_id": a["administered_by_staff_id"],
        "witness_staff_id": a["witness_staff_id"], "notes": a["notes"],
    }


def ser_case(c):
    d = _base(c)
    d.update({
        "student_id": c["student_id"], "reported_by_staff_id": c["reported_by_staff_id"],
        "category": c["category"], "description": c["description"],
        "points_proposed": c["points_proposed"], "status": c["status"],
        "hearing_officer_id": c["hearing_officer_id"],
        "hearing_at": c["hearing_at"],
        "sanction_type": c["sanction_type"], "points_assessed": c["points_assessed"],
        "decided_at": fmt_ts(c["decided_at"]) if c["decided_at"] else None,
        "appeal_count": c["appeal_count"],
    })
    return d


def ser_break_period(bp):
    d = _base(bp)
    d.update({
        "name": bp["name"], "kind": bp["kind"], "starts_on": bp["starts_on"],
        "ends_on": bp["ends_on"], "housing_available": bp["housing_available"],
        "status": bp["status"],
    })
    return d


def ser_break_housing(r):
    d = _base(r)
    d.update({
        "student_id": r["student_id"], "break_period_id": r["break_period_id"],
        "reason": r["reason"], "status": r["status"], "room_id": r["room_id"],
        "room_charge_cents": r["room_charge_cents"],
        "storage_total_cents": r["storage_total_cents"],
        "deposit_credit_cents": r["deposit_credit_cents"],
        "fee_cents": r["fee_cents"],
    })
    return d


def ser_storage_unit(u):
    d = _base(u)
    d.update({
        "label": u["label"], "capacity_cuft": u["capacity_cuft"],
        "status": u["status"], "used_cuft": storage_unit_used_cuft(u["id"]),
    })
    return d


def ser_storage_reservation(r):
    d = _base(r)
    d.update({
        "storage_unit_id": r["storage_unit_id"], "student_id": r["student_id"],
        "break_period_id": r["break_period_id"], "volume_cuft": r["volume_cuft"],
        "weeks": r["weeks"], "items_description": r["items_description"],
        "early_bird": r["early_bird"], "fee_cents": r["fee_cents"],
        "status": r["status"],
    })
    return d
