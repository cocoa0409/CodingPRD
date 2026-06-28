"""Calculation rules (PRD §3.5, §3.6, §3.8, §3.9; SCAFFOLD §1.3).

All monetary amounts are whole cents. Non-integer intermediates round half-up,
exactly once, at the pinned step.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

# --- Constants (SCAFFOLD §1.3) ---
TRAIL_TOUR_FEE_CENTS = {"TRAIL": 4000, "UTILITY": 6000, "MOUNTAIN": 9000}
MEMBER_DISCOUNT_PCT = {"NONE": Decimal("0.0"), "SEASON": Decimal("0.10"), "PREMIER": Decimal("0.20")}
GEAR_SURCHARGE_CENTS = 1525

FUEL_OK_FRACTION = Decimal("0.95")
FUEL_PRICE_CENTS_PER_LITER = Decimal("180")

LATE_GRACE_MINUTES = 30
LATE_BLOCK_MINUTES = 60
LATE_FEE_PER_BLOCK_CENTS = 2500

NO_SHOW_FEE_CENTS = 5000

GUIDE_RIDER_RATIO = 6

MIN_RIDER_AGE = 16
WAIVER_ADULT_AGE = 18
WAIVER_VALIDITY_DAYS = 365
GEAR_BUFFER_MINUTES = 60


def _round_half_up(value):
    """Round a Decimal to whole cents (integer) using round-half-up."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_to_days(start_dt, end_dt):
    """Departure-days = ceil((ends_at - starts_at) / 1 day), minimum 1 (PRD §3.5)."""
    seconds = (end_dt - start_dt).total_seconds()
    days = math.ceil(seconds / 86400.0)
    return max(1, days)


def membership_active(member, clock_now):
    """Benefits active iff tier in {SEASON, PREMIER} AND (expires null OR expires > now)."""
    tier = member["membership_tier"]
    if tier not in ("SEASON", "PREMIER"):
        return False
    expires = member.get("membership_expires_at")
    if expires is None:
        return True
    from common import parse_datetime
    return parse_datetime(expires) > clock_now


def estimate_reservation_quote(unit, trail, departure, member, gear_count, clock_now):
    """Forward-looking quote written to estimated_total_cents (PRD §3.5)."""
    start_dt = _dt(departure["starts_at"])
    end_dt = _dt(departure["ends_at"])
    days = ceil_to_days(start_dt, end_dt)
    rental_base = unit["daily_rate_cents"] * days
    tour_base = TRAIL_TOUR_FEE_CENTS[trail["required_class"]]
    gear_surcharge = GEAR_SURCHARGE_CENTS * gear_count
    gross = rental_base + tour_base + gear_surcharge

    if membership_active(member, clock_now):
        disc_pct = MEMBER_DISCOUNT_PCT[member["membership_tier"]]
    else:
        disc_pct = Decimal("0.0")

    # Pinned: round once on the COMBINED gross, then subtract.
    discount = _round_half_up(Decimal(gross) * disc_pct)
    est_fuel = 0
    return gross - discount + est_fuel


def deposit_hold(member, unit, clock_now):
    """Deposit equals unit.deposit_cents unless premier-waiver applies (PRD §3.8)."""
    if (
        member["membership_tier"] == "PREMIER"
        and membership_active(member, clock_now)
        and member["lifetime_damage_strikes"] == 0
    ):
        return 0
    return unit["deposit_cents"]


def fuel_charge(fuel_return_fraction, tank_capacity_liters):
    """Fuel shortfall charge (PRD §3.9). Billed only when fraction < 0.95."""
    frac = Decimal(str(fuel_return_fraction))
    if frac >= FUEL_OK_FRACTION:
        return 0
    shortfall_liters = (FUEL_OK_FRACTION - frac) * Decimal(str(tank_capacity_liters))
    return _round_half_up(shortfall_liters * FUEL_PRICE_CENTS_PER_LITER)


def late_charge(returned_at_dt, ends_at_dt):
    """Late-return fee from inclusive grace + per-started-block rule (PRD §3.9)."""
    delta_minutes = (returned_at_dt - ends_at_dt).total_seconds() / 60.0
    late_minutes = max(0.0, delta_minutes)
    if late_minutes <= LATE_GRACE_MINUTES:
        return 0
    billable = late_minutes - LATE_GRACE_MINUTES
    blocks = math.ceil(billable / LATE_BLOCK_MINUTES)
    return blocks * LATE_FEE_PER_BLOCK_CENTS


def guide_ratio_required(rider_count):
    """Minimum guides required for the current rider_count (PRD §3.3)."""
    if rider_count == 0:
        return 0
    return max(1, math.ceil(rider_count / GUIDE_RIDER_RATIO))


def final_settlement(rental_charge_cents, fuel_charge_cents, late_charge_cents,
                     damage_assessed_cents, gear_loss_cents, deposit_hold_cents):
    """Waterfall allocation against the held deposit (PRD §3.9)."""
    total_charges = (rental_charge_cents + fuel_charge_cents + late_charge_cents
                     + damage_assessed_cents + gear_loss_cents)
    deposit_applied = min(deposit_hold_cents, total_charges)
    refund = deposit_hold_cents - deposit_applied
    net_charge = max(0, total_charges - deposit_hold_cents)
    return {
        "total_charges": total_charges,
        "deposit_applied_cents": deposit_applied,
        "refund_cents": refund,
        "net_charge_cents": net_charge,
    }


def _dt(value):
    from common import parse_datetime
    return parse_datetime(value)
