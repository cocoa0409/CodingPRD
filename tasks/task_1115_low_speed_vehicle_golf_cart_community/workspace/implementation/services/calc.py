"""Calculation rules per SCAFFOLD §1.3 / PRD §2.8, §3.5, §3.6, §3.9.

Money: integer cents; each multiplication rounded half-up to 0 decimals
before the next step. Scores: inspection per-component round to 2dp then
sum; renewal score rounded half-up to 2dp on the final value, floored at 0.
"""
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db


# --- annual_registration_fee constants ---
BASE_FEE = {"GOLF_CART": 7500, "LSV": 15000}
EQUIP_RATE = {"provisional": Decimal("0.02"), "finalized": Decimal("0.025")}
MULT_CAP = Decimal("1.20")
SEAT_FREE = 4
SEAT_SURCHARGE = 500
FLEET_DISCOUNT_PCT = Decimal("0.10")

# --- late_renewal_fee constants ---
TIER_BOUNDARY_CENTS = 10000
TIER_A_LATE = [1500, 3000, 6000]
TIER_B_LATE = [2500, 5000, 10000]
BAND_1_MAX_DAYS = 30
BAND_2_MAX_DAYS = 60
TOTAL_CAP_MULTIPLE = 2

# --- inspection_total_score constants ---
WEIGHT_PCT = {
    "headlights": Decimal("16.67"),
    "brake_lights": Decimal("16.67"),
    "turn_signals": Decimal("13.33"),
    "horn": Decimal("6.67"),
    "mirrors": Decimal("10.00"),
    "windshield": Decimal("10.00"),
    "seatbelts": Decimal("16.66"),
    "reflectors": Decimal("10.00"),
}
PASS_THRESHOLD = Decimal("70.00")

# --- renewal_compliance_score constants ---
RENEWAL_PASS_THRESHOLD = Decimal("70")
RECENCY_FULL_DAYS = 180
WINDOW_DAYS = 365
AGED_FILED_DAYS = 30

# --- holder_points_standing constants ---
POINTS_WINDOW_DAYS = 730
PROBATION_THRESHOLD = 4
BAR_THRESHOLD = 12

# --- charging_fee constants ---
MIN_CHARGE_CENTS = 200

# --- fleet late fine ---
LATE_FINE_PER_DAY_CENTS = 500


def _rh0(x):
    """Round half-up to integer cents."""
    return int(Decimal(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _rh2(x):
    return Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def equipment_count(vehicle):
    """7 booleans true plus (mirror_count >= 1 ? 1 : 0)."""
    n = 0
    for f in ("has_headlights", "has_brake_lights", "has_turn_signals", "has_horn",
              "has_windshield", "has_seatbelts", "has_reflectors"):
        if vehicle.get(f):
            n += 1
    if vehicle.get("mirror_count", 0) >= 1:
        n += 1
    return n


def _fleet_discount_applies(variant, community, holder_id, as_of):
    if variant == "provisional":
        return bool(community.get("fleet_program_enabled"))
    # finalized: holder has >=1 RETURNED FleetDispatch with returned_at within
    # trailing 365 days of the calculation instant
    if as_of is None:
        as_of = db.now()
    cutoff = as_of - timedelta(days=365)
    for d in db.fleet_dispatches.values():
        if d["holder_id"] != holder_id:
            continue
        if d["status"] != "RETURNED":
            continue
        ra = d.get("returned_at")
        if ra is None:
            continue
        if cutoff <= ra <= as_of:
            return True
    return False


def annual_registration_fee(vehicle, community, holder_id, variant, as_of=None):
    """Returns integer fee in cents. variant in {'provisional','finalized'}."""
    base = BASE_FEE[vehicle["vehicle_type"]]
    equip = equipment_count(vehicle)
    rate = EQUIP_RATE[variant]
    mult = Decimal(1) + rate * equip
    if mult > MULT_CAP:
        mult = MULT_CAP
    seat_surcharge = max(0, vehicle["seat_count"] - SEAT_FREE) * SEAT_SURCHARGE
    subtotal = _rh0(Decimal(base) * mult) + seat_surcharge
    if _fleet_discount_applies(variant, community, holder_id, as_of):
        subtotal = _rh0(Decimal(subtotal) * (Decimal(1) - FLEET_DISCOUNT_PCT))
    fee = max(subtotal, base)
    return fee


def late_renewal_fee(finalized_fee_cents, expiry_date, now_dt, late_grace_days):
    """Pinned order: base -> tier -> days -> band -> raw; total capped at 2x base.

    Returns (late_fee_cents, total_due_cents).
    """
    base = finalized_fee_cents
    tier = "A" if base < TIER_BOUNDARY_CENTS else "B"
    days_overdue = int(math.floor((now_dt - expiry_date).total_seconds() / 86400.0))
    if days_overdue <= BAND_1_MAX_DAYS:
        band = 0
    elif days_overdue <= BAND_2_MAX_DAYS:
        band = 1
    else:
        band = 2  # 61..late_grace_days guaranteed by the renewal gate
    raw_late = (TIER_A_LATE if tier == "A" else TIER_B_LATE)[band]
    total_due = min(base + raw_late, TOTAL_CAP_MULTIPLE * base)
    return raw_late, total_due


def inspection_total_score(scores):
    """Per-component round half-up to 2dp FIRST, then sum. Returns Decimal."""
    total = Decimal("0")
    for name, weight in WEIGHT_PCT.items():
        contribution = _rh2(Decimal(scores[name + "_score"]) * weight / Decimal(100))
        total += contribution
    return total


def inspection_passed(total_score):
    return total_score >= PASS_THRESHOLD


def renewal_compliance_score(holder_id, variant, as_of):
    """100 - sum(points * recency * status_weight), floored at 0, 2dp half-up.

    provisional: UPHELD only (weight 1.0); FILED excluded.
    audited: UPHELD at 1.0 + FILED older than 30 days at 0.5.
    recency: 1.0 within trailing 180d; 0.5 within trailing 365d; else excluded.
    """
    penalty = Decimal("0")
    full_cutoff = as_of - timedelta(days=RECENCY_FULL_DAYS)
    window_cutoff = as_of - timedelta(days=WINDOW_DAYS)
    aged_cutoff = as_of - timedelta(days=AGED_FILED_DAYS)
    for v in db.violations.values():
        if v["holder_id"] != holder_id:
            continue
        status = v["status"]
        if variant == "provisional":
            if status != "UPHELD":
                continue
            status_weight = Decimal("1.0")
        else:  # audited
            if status == "UPHELD":
                status_weight = Decimal("1.0")
            elif status == "FILED":
                # occurred_at strictly more than AGED_FILED_DAYS before as_of
                if not (v["occurred_at"] < aged_cutoff):
                    continue
                status_weight = Decimal("0.5")
            else:
                continue
        occurred = v["occurred_at"]
        if occurred >= full_cutoff:
            recency = Decimal("1.0")
        elif occurred >= window_cutoff:
            recency = Decimal("0.5")
        else:
            continue
        penalty += Decimal(v["points_assessed"]) * recency * status_weight
    score = Decimal(100) - penalty
    if score < 0:
        score = Decimal(0)
    return _rh2(score)


def holder_points_standing(holder_id, now_dt):
    """Sum of points over UPHELD violations within trailing 730 days (inclusive)."""
    cutoff = now_dt - timedelta(days=POINTS_WINDOW_DAYS)
    total = 0
    for v in db.violations.values():
        if v["holder_id"] != holder_id:
            continue
        if v["status"] != "UPHELD":
            continue
        if v["occurred_at"] >= cutoff:
            total += v["points_assessed"]
    return total


def compliance_status_for_points(points):
    if points >= BAR_THRESHOLD:
        return "BARRED"
    if points >= PROBATION_THRESHOLD:
        return "PROBATION"
    return "GOOD_STANDING"


def charging_fee(start_at, end_at, rate_cents_per_min):
    """max(200, ceil(duration_minutes) * rate). Fractional minutes round up."""
    minutes = (end_at - start_at).total_seconds() / 60.0
    whole = int(math.ceil(minutes - 1e-12))
    fee = whole * rate_cents_per_min
    return max(MIN_CHARGE_CENTS, fee)


def fleet_late_fine(shift_end, returned_at):
    """ceil(days late) * 500. Returns 0 when returned_at <= shift_end."""
    if returned_at <= shift_end:
        return 0
    days = (returned_at - shift_end).total_seconds() / 86400.0
    return int(math.ceil(days - 1e-12)) * LATE_FINE_PER_DAY_CENTS


def age_years(birth_date, today_date):
    """Floor of whole years between birth_date and today (logical clock)."""
    years = today_date.year - birth_date.year
    if (today_date.month, today_date.day) < (birth_date.month, birth_date.day):
        years -= 1
    return years
