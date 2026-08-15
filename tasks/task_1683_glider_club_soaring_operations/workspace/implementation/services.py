"""Business logic: calculations, currency checks, cascades, serializers."""

from datetime import timedelta
from decimal import Decimal
from fractions import Fraction

from db import STORE, now, today_start
from util import (
    add_12_months,
    ceil_distance_km,
    days_in_month,
    round_half_up_cents,
    to_decimal,
)

# Domain constants (scaffold "constants" + calculation constants).
ARREARS_THRESHOLD_CENTS = 20000
LATE_CANCEL_WINDOW_HOURS = 24
LATE_CANCEL_FEE_CENTS = 1500
NO_SHOW_FEE_CENTS = 2500
DUTY_NO_SHOW_FEE_CENTS = 5000
CREDIT_CAP_CENTS = -50000
TOW_SORTIE_MINUTES = 12
INSTRUCTOR_BUFFER_MIN = 30
CHECKOUT_EARLY_GRACE_MIN = 15

TIER1_CEILING_FT = 2000
TIER2_CEILING_FT = 3000
TIER3_CEILING_FT = 5000
TIER1_CENTS = 3000
TIER2_CENTS = 3800
TIER3_CENTS = 4600
TIER4_CENTS = 5500
SOAR_SURCHARGE_CENTS = 400
SOAR_SURCHARGE_BLOCK_MIN = 30
SOAR_FREE_MINUTES = 60

INSPECTION_INTERVAL_HOURS = 100.0
INSPECTION_LIMIT = Fraction(100, 1)

MIN_DUAL_HOURS = 10.0
SOLO_RECENCY_DAYS = 90

RETRIEVE_BASE_CENTS = 5000
RETRIEVE_PER_KM_CENTS = 120
BAND1_KM = 50
BAND2_KM = 100

BADGE_RANK = ["BADGE_A", "BADGE_B", "BADGE_C", "BADGE_BRONZE", "BADGE_SILVER"]
BADGE_LEVEL = {
    "BADGE_A": "A",
    "BADGE_B": "B",
    "BADGE_C": "C",
    "BADGE_BRONZE": "BRONZE",
    "BADGE_SILVER": "SILVER",
}

TOW_SORTIE_HOURS = Fraction(TOW_SORTIE_MINUTES, 60)


# ---------------------------------------------------------------------------
# Generic mutation helper: every mutation refreshes updated_at and bumps version.
# ---------------------------------------------------------------------------

def touch(record):
    record["updated_at"] = now()
    record["version"] += 1


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------

def tow_base_cents(release_altitude_ft):
    if release_altitude_ft < TIER1_CEILING_FT:
        return TIER1_CENTS
    if release_altitude_ft < TIER2_CEILING_FT:
        return TIER2_CENTS
    if release_altitude_ft < TIER3_CEILING_FT:
        return TIER3_CENTS
    return TIER4_CENTS


def _discounted(gross_cents, tier):
    discount = to_decimal(tier["tow_fee_discount_pct"])
    return round_half_up_cents(Decimal(gross_cents) * (Decimal(1) - discount))


def provisional_tow_fee_cents(tier, release_altitude_ft):
    """Provisional variant: altitude base * (1 - discount), half-up; nothing else."""
    return _discounted(tow_base_cents(release_altitude_ft), tier)


def reconciled_month_tow_count(member_id, takeoff_at):
    """Count of the member's RECONCILED flights in takeoff_at's UTC month."""
    year, month = takeoff_at.year, takeoff_at.month
    count = 0
    for flight in STORE["flights"].values():
        if flight["status"] != "RECONCILED":
            continue
        reservation = STORE["reservations"].get(flight["reservation_id"])
        if reservation is None or reservation["member_id"] != member_id:
            continue
        t = flight["takeoff_at"]
        if t.year == year and t.month == month:
            count += 1
    return count


def final_tow_fee_cents(member, tier, flight, flight_minutes):
    """Final variant: included-tow quota by monthly position, then discount
    (half-up) on gross, then integer surcharge added undiscounted."""
    position = reconciled_month_tow_count(member["id"], flight["takeoff_at"]) + 1
    if position <= tier["included_tows_per_month"]:
        gross = 0
    else:
        gross = tow_base_cents(flight["release_altitude_ft"])
    if flight_minutes > SOAR_FREE_MINUTES:
        blocks = -(-(flight_minutes - SOAR_FREE_MINUTES) // SOAR_SURCHARGE_BLOCK_MIN)
        surcharge = SOAR_SURCHARGE_CENTS * blocks
    else:
        surcharge = 0
    return _discounted(gross, tier) + surcharge


def prorated_dues_cents(old_dues, new_dues, at):
    """Mid-month tier change blend: old half floored, new half rounded half up;
    the change day itself bills to the new tier."""
    dim = days_in_month(at.year, at.month)
    days_on_old = at.day - 1
    days_on_new = dim - days_on_old
    old_half = (old_dues * days_on_old) // dim  # floor for non-negative ints
    new_half = round_half_up_cents(
        Decimal(new_dues * days_on_new) / Decimal(dim)
    )
    return old_half + new_half


def retrieve_cost_split(distance_km):
    """Total = base + ceil(km) * per-km. Band costs proportional to band widths
    over the raw distance, each half-up. Pilot pays band1 + half of band2;
    club share is the residual."""
    d = to_decimal(distance_km)
    total = RETRIEVE_BASE_CENTS + ceil_distance_km(distance_km) * RETRIEVE_PER_KM_CENTS
    w1 = min(d, Decimal(BAND1_KM))
    w2 = min(max(d - Decimal(BAND1_KM), Decimal(0)), Decimal(BAND2_KM))
    band1_cost = round_half_up_cents(Decimal(total) * w1 / d)
    band2_cost = round_half_up_cents(Decimal(total) * w2 / d)
    pilot_share = band1_cost + round_half_up_cents(
        Decimal(band2_cost) * Decimal("0.5")
    )
    club_share = total - pilot_share
    return pilot_share, club_share


def recompute_badge_level(student_id):
    """Highest-ranked badge among the student's VERIFIED records; else NONE."""
    best = None
    for rec in STORE["progress"].values():
        if rec["student_id"] != student_id or rec["status"] != "VERIFIED":
            continue
        if rec["kind"] in BADGE_RANK:
            if best is None or BADGE_RANK.index(rec["kind"]) > BADGE_RANK.index(best):
                best = rec["kind"]
    return BADGE_LEVEL[best] if best else "NONE"


def dual_flights(student_id):
    """RECONCILED flights piloted by the student that carried an instructor."""
    out = []
    for flight in STORE["flights"].values():
        if flight["status"] != "RECONCILED":
            continue
        reservation = STORE["reservations"].get(flight["reservation_id"])
        if reservation is None:
            continue
        if reservation["member_id"] == student_id and reservation.get("instructor_id"):
            out.append(flight)
    return out


def dual_hours_total(student_id):
    """Sum of flight_minutes/60 over the student's RECONCILED dual flights (exact)."""
    total = Fraction(0, 1)
    for flight in dual_flights(student_id):
        total += Fraction(flight["flight_minutes"], 60)
    return total


def solo_eligible(student, at):
    """Hours >= 10.0 over full history AND a dual flight within trailing 90 days."""
    if dual_hours_total(student["id"]) < Fraction(10, 1):
        return False
    cutoff = at - timedelta(days=SOLO_RECENCY_DAYS)
    for flight in dual_flights(student["id"]):
        if flight["takeoff_at"] >= cutoff:
            return True
    return False


# ---------------------------------------------------------------------------
# Airworthiness currency (PRD section 2.8)
# ---------------------------------------------------------------------------

def currency_ok(aircraft, at):
    """Strict: hours_since_inspection < 100.0 AND annual_due_date > now."""
    return (
        aircraft["hours_since_inspection"] < INSPECTION_LIMIT
        and aircraft["annual_due_date"] > at
    )


def currency_failure_reason(aircraft, at):
    """Returns 'INSPECTION_OVERDUE' | 'ANNUAL_OVERDUE' | None.
    INSPECTION_OVERDUE wins when both fail."""
    if aircraft["hours_since_inspection"] >= INSPECTION_LIMIT:
        return "INSPECTION_OVERDUE"
    if aircraft["annual_due_date"] <= at:
        return "ANNUAL_OVERDUE"
    return None


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def cancel_reservation(reservation):
    reservation["status"] = "CANCELLED"
    touch(reservation)


def ground_aircraft(aircraft, reason):
    """AIRWORTHY -> GROUNDED with cascade: future BOOKED reservations on the
    airframe cancel; for tow planes, future SCHEDULED tow slots cancel.
    Linked flights are unaffected."""
    aircraft["status"] = "GROUNDED"
    aircraft["grounded_reason"] = reason
    touch(aircraft)
    at = now()
    for reservation in STORE["reservations"].values():
        if (
            reservation["aircraft_id"] == aircraft["id"]
            and reservation["status"] == "BOOKED"
            and reservation["start_at"] > at
        ):
            cancel_reservation(reservation)
    if aircraft["kind"] == "TOW_PLANE":
        for slot in STORE["tow_slots"].values():
            if (
                slot["tow_plane_id"] == aircraft["id"]
                and slot["status"] == "SCHEDULED"
                and slot["start_at"] > at
            ):
                slot["status"] = "CANCELLED"
                touch(slot)


def suspend_member(member, reason):
    """ACTIVE -> SUSPENDED; future BOOKED reservations of the member cancel."""
    member["status"] = "SUSPENDED"
    member["suspension_reason"] = reason
    touch(member)
    at = now()
    for reservation in STORE["reservations"].values():
        if (
            reservation["member_id"] == member["id"]
            and reservation["status"] == "BOOKED"
            and reservation["start_at"] > at
        ):
            cancel_reservation(reservation)


def member_tier(member):
    return STORE["tiers"].get(member["tier_id"])


def set_badge_level(student):
    level = recompute_badge_level(student["id"])
    if student["badge_level"] != level:
        student["badge_level"] = level
        touch(student)


def apply_annual(aircraft, performed_at):
    aircraft["annual_due_date"] = add_12_months(performed_at)


# ---------------------------------------------------------------------------
# Serializers (internal records -> wire shape)
# ---------------------------------------------------------------------------

def _common(record):
    return {
        "id": record["id"],
        "created_at": _fmt(record["created_at"]),
        "updated_at": _fmt(record["updated_at"]),
        "version": record["version"],
    }


def _fmt(dt):
    from util import fmt_ts
    return fmt_ts(dt)


def _hours(frac):
    return float(frac)


def ser_tier(t):
    out = {
        "tier_code": t["tier_code"],
        "monthly_dues_cents": t["monthly_dues_cents"],
        "tow_fee_discount_pct": t["tow_fee_discount_pct"],
        "included_tows_per_month": t["included_tows_per_month"],
        "student_tier": t["student_tier"],
    }
    out.update(_common(t))
    return out


def ser_member(m):
    out = {
        "full_name": m["full_name"],
        "tier_id": m["tier_id"],
        "status": m["status"],
        "is_instructor": m["is_instructor"],
        "is_tow_pilot": m["is_tow_pilot"],
        "account_balance_cents": m["account_balance_cents"],
        "pending_dues_cents": m["pending_dues_cents"],
        "suspension_reason": m["suspension_reason"],
        "solo_endorsed": m["solo_endorsed"],
        "badge_level": m["badge_level"],
    }
    out.update(_common(m))
    return out


def ser_aircraft(a):
    out = {
        "registration": a["registration"],
        "kind": a["kind"],
        "status": a["status"],
        "total_time_hours": _hours(a["total_time_hours"]),
        "hours_since_inspection": _hours(a["hours_since_inspection"]),
        "annual_due_date": _fmt(a["annual_due_date"]),
        "grounded_reason": a["grounded_reason"],
    }
    out.update(_common(a))
    return out


def ser_duty_slot(s):
    out = {
        "duty_date": _fmt(s["duty_date"]),
        "member_id": s["member_id"],
        "status": s["status"],
        "swap_with_slot_id": s["swap_with_slot_id"],
    }
    out.update(_common(s))
    return out


def ser_availability(w):
    out = {
        "instructor_id": w["instructor_id"],
        "start_at": _fmt(w["start_at"]),
        "end_at": _fmt(w["end_at"]),
        "status": w["status"],
    }
    out.update(_common(w))
    return out


def ser_reservation(r):
    out = {
        "aircraft_id": r["aircraft_id"],
        "member_id": r["member_id"],
        "instructor_id": r["instructor_id"],
        "start_at": _fmt(r["start_at"]),
        "end_at": _fmt(r["end_at"]),
        "status": r["status"],
    }
    out.update(_common(r))
    return out


def ser_flight(f):
    out = {
        "reservation_id": f["reservation_id"],
        "tow_slot_id": f["tow_slot_id"],
        "release_altitude_ft": f["release_altitude_ft"],
        "takeoff_at": _fmt(f["takeoff_at"]),
        "landed_at": _fmt(f["landed_at"]) if f["landed_at"] else None,
        "status": f["status"],
        "flight_minutes": f["flight_minutes"],
        "provisional_fee_cents": f["provisional_fee_cents"],
        "final_fee_cents": f["final_fee_cents"],
        "retrieve_id": f["retrieve_id"],
    }
    out.update(_common(f))
    return out


def ser_tow_slot(s):
    out = {
        "tow_plane_id": s["tow_plane_id"],
        "tow_pilot_id": s["tow_pilot_id"],
        "start_at": _fmt(s["start_at"]),
        "end_at": _fmt(s["end_at"]),
        "capacity": s["capacity"],
        "confirmed_count": s["confirmed_count"],
        "status": s["status"],
    }
    out.update(_common(s))
    return out


def ser_maintenance(rec):
    # MaintenanceRecord carries only id and created_at (no updated_at/version).
    return {
        "id": rec["id"],
        "aircraft_id": rec["aircraft_id"],
        "kind": rec["kind"],
        "performed_at": _fmt(rec["performed_at"]),
        "hobbs_hours_at_service": rec["hobbs_hours_at_service"],
        "notes": rec["notes"],
        "created_at": _fmt(rec["created_at"]),
    }


def ser_progress(p):
    out = {
        "student_id": p["student_id"],
        "instructor_id": p["instructor_id"],
        "kind": p["kind"],
        "status": p["status"],
        "dual_hours_at_signoff": p["dual_hours_at_signoff"],
        "signed_off_at": _fmt(p["signed_off_at"]) if p["signed_off_at"] else None,
    }
    out.update(_common(p))
    return out


def ser_retrieve(r):
    out = {
        "flight_id": r["flight_id"],
        "distance_km": r["distance_km"],
        "status": r["status"],
        "pilot_share_cents": r["pilot_share_cents"],
        "club_share_cents": r["club_share_cents"],
        "crew_member_id": r["crew_member_id"],
    }
    out.update(_common(r))
    return out
