"""Computed fields, serializers, and calculation rules."""
from decimal import Decimal

from helpers import fmt_dt, round_half_up
from store import store

# Booking status groups
ACTIVE_BOOKING = {"CONFIRMED", "CHECKED_IN", "BRIEFED"}
MEMBER_BOOKING = {"CONFIRMED", "CHECKED_IN", "BRIEFED", "COMPLETED"}

# Constants (from PRD / scaffold)
WAIVER_VALID_DAYS = 365
CLEANING_BUFFER_MINUTES = 30
INSURANCE_RATE = Decimal("0.0745")
VOLUNTARY_FULL_REFUND_HOURS = 24
VOLUNTARY_LATE_REFUND_PCT = Decimal("0.5")


# ---------------------------------------------------------------------------
# Participant computed fields
# ---------------------------------------------------------------------------
def participant_age_years(p):
    birth = p["birthdate"]
    now = store.clock
    years = now.year - birth.year
    if (now.month, now.day) < (birth.month, birth.day):
        years -= 1
    return years


def participant_waiver_status(p):
    signed = p.get("waiver_signed_at")
    if signed is None:
        return "NONE"
    if store.clock <= p["waiver_expires_at"]:
        return "SIGNED"
    return "EXPIRED"


# ---------------------------------------------------------------------------
# TimeSlot computed fields
# ---------------------------------------------------------------------------
def slot_booked_count(slot_id):
    return sum(
        1 for b in store.bookings.values()
        if b["time_slot_id"] == slot_id and b["status"] in ACTIVE_BOOKING
    )


def slot_remaining_capacity(slot):
    return max(0, slot["capacity"] - slot_booked_count(slot["id"]))


def slot_assigned_guide_count(slot_id):
    return sum(
        1 for a in store.guide_assignments.values()
        if a["time_slot_id"] == slot_id and a["status"] == "ASSIGNED"
    )


def slot_assigned_capacity(slot):
    course = store.courses[slot["course_id"]]
    return slot_assigned_guide_count(slot["id"]) * course["max_participants_per_guide"]


# ---------------------------------------------------------------------------
# SeasonPass computed fields
# ---------------------------------------------------------------------------
def pass_uses_committed(pass_id):
    return sum(
        1 for b in store.bookings.values()
        if b.get("season_pass_id") == pass_id and b["status"] in ACTIVE_BOOKING
    )


def pass_uses_settled(pass_id):
    return sum(
        1 for b in store.bookings.values()
        if b.get("season_pass_id") == pass_id and b["status"] == "COMPLETED"
    )


def pass_uses_remaining(sp):
    return max(0, sp["total_uses"] - pass_uses_committed(sp["id"]) - pass_uses_settled(sp["id"]))


def find_active_pass(participant_id):
    for sp in store.season_passes.values():
        if sp["participant_id"] == participant_id and sp["status"] == "ACTIVE":
            return sp
    return None


# ---------------------------------------------------------------------------
# Group computed fields
# ---------------------------------------------------------------------------
def group_member_bookings(group_id):
    return [
        b for b in store.bookings.values()
        if b.get("group_id") == group_id and b["status"] in MEMBER_BOOKING
    ]


def group_member_count(group_id):
    return len(group_member_bookings(group_id))


def group_insurance_total(group_id):
    total = 0
    for b in group_member_bookings(group_id):
        slot = store.time_slots[b["time_slot_id"]]
        course = store.courses[slot["course_id"]]
        per_member = round_half_up(Decimal(course["base_price_cents"]) * INSURANCE_RATE)
        total += per_member
    return total


# ---------------------------------------------------------------------------
# GearItem computed status
# ---------------------------------------------------------------------------
def gear_item_status(gear_item_id):
    for c in store.gear_checkouts.values():
        if c["gear_item_id"] == gear_item_id and c["status"] == "OUT":
            return "CHECKED_OUT"
    return "AVAILABLE"


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def group_discount_pct(expected_size):
    if expected_size >= 8:
        return Decimal("0.20")
    if expected_size >= 4:
        return Decimal("0.10")
    return Decimal("0.00")


def compute_booking_price(course, slot, group):
    """Return the discounted price rounded to whole cents (int). No pass logic."""
    base = Decimal(course["base_price_cents"])
    weekday = slot["start_at"].weekday()  # Mon=0 .. Sun=6
    is_weekend = weekday in (5, 6)
    if is_weekend:
        subtotal = base + base * Decimal(str(course["weekend_surcharge_pct"]))
    else:
        subtotal = base
    gpct = group_discount_pct(group["expected_size"]) if group else Decimal("0.00")
    discounted = subtotal * (Decimal("1") - gpct)
    return round_half_up(discounted)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def _base(rec, versioned=True):
    out = {"id": rec["id"], "created_at": fmt_dt(rec["created_at"])}
    if versioned:
        out["updated_at"] = fmt_dt(rec["updated_at"])
        out["version"] = rec["version"]
    return out


def serialize_course(c):
    out = _base(c)
    out.update({
        "name": c["name"],
        "difficulty_level": c["difficulty_level"],
        "min_weight_kg": c["min_weight_kg"],
        "max_weight_kg": c["max_weight_kg"],
        "min_age_years": c["min_age_years"],
        "base_price_cents": c["base_price_cents"],
        "duration_minutes": c["duration_minutes"],
        "default_capacity": c["default_capacity"],
        "max_participants_per_guide": c["max_participants_per_guide"],
        "weekend_surcharge_pct": c["weekend_surcharge_pct"],
    })
    return out


def serialize_time_slot(s):
    out = _base(s)
    out.update({
        "course_id": s["course_id"],
        "start_at": fmt_dt(s["start_at"]),
        "end_at": fmt_dt(s["end_at"]),
        "capacity": s["capacity"],
        "booked_count": slot_booked_count(s["id"]),
        "remaining_capacity": slot_remaining_capacity(s),
        "status": s["status"],
        "closure_reason": s.get("closure_reason"),
    })
    return out


def serialize_guide(g):
    out = _base(g)
    out.update({"name": g["name"], "certification_level": g["certification_level"]})
    return out


def serialize_participant(p):
    out = _base(p)
    out.update({
        "full_name": p["full_name"],
        "weight_kg": p["weight_kg"],
        "birthdate": fmt_dt(p["birthdate"]),
        "age_years": participant_age_years(p),
        "waiver_status": participant_waiver_status(p),
        "waiver_signed_at": fmt_dt(p.get("waiver_signed_at")),
        "waiver_expires_at": fmt_dt(p.get("waiver_expires_at")),
    })
    return out


def serialize_season_pass(sp):
    out = _base(sp)
    out.update({
        "participant_id": sp["participant_id"],
        "tier": sp["tier"],
        "valid_from": fmt_dt(sp["valid_from"]),
        "valid_until": fmt_dt(sp["valid_until"]),
        "total_uses": sp["total_uses"],
        "uses_committed": pass_uses_committed(sp["id"]),
        "uses_settled": pass_uses_settled(sp["id"]),
        "uses_remaining": pass_uses_remaining(sp),
        "status": sp["status"],
    })
    return out


def serialize_group(g):
    out = _base(g)
    out.update({
        "name": g["name"],
        "time_slot_id": g["time_slot_id"],
        "expected_size": g["expected_size"],
        "organizer_name": g["organizer_name"],
        "organizer_participant_id": g.get("organizer_participant_id"),
        "member_count": group_member_count(g["id"]),
        "insurance_total_cents": group_insurance_total(g["id"]),
        "status": g["status"],
    })
    return out


def serialize_booking(b):
    out = _base(b)
    out.update({
        "time_slot_id": b["time_slot_id"],
        "participant_id": b["participant_id"],
        "group_id": b.get("group_id"),
        "season_pass_id": b.get("season_pass_id"),
        "use_season_pass": b["use_season_pass"],
        "status": b["status"],
        "price_cents": b["price_cents"],
        "raincheck_credit_cents": b["raincheck_credit_cents"],
        "redeemed_from_booking_id": b.get("redeemed_from_booking_id"),
    })
    return out


def serialize_guide_assignment(a):
    out = _base(a)
    out.update({
        "guide_id": a["guide_id"],
        "time_slot_id": a["time_slot_id"],
        "status": a["status"],
    })
    return out


def serialize_gear_item(g):
    out = _base(g)
    out.update({
        "gear_type": g["gear_type"],
        "size": g["size"],
        "status": gear_item_status(g["id"]),
    })
    return out


def serialize_gear_checkout(c):
    out = _base(c)
    out.update({
        "gear_item_id": c["gear_item_id"],
        "booking_id": c["booking_id"],
        "window_start": fmt_dt(c["window_start"]),
        "window_end": fmt_dt(c["window_end"]),
        "checked_out_at": fmt_dt(c.get("checked_out_at")),
        "returned_at": fmt_dt(c.get("returned_at")),
        "status": c["status"],
    })
    return out


def serialize_incident_report(r):
    out = _base(r, versioned=False)
    out.update({
        "booking_id": r["booking_id"],
        "severity": r["severity"],
        "description": r["description"],
        "reported_by_guide_id": r["reported_by_guide_id"],
        "occurred_at": fmt_dt(r["occurred_at"]),
    })
    return out
