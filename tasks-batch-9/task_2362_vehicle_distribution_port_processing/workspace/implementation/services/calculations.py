"""Calculation rules — PRD §2.7, §2.8, §3.2-§3.9 (scaffold §1.3).

All monetary arithmetic uses Decimal; rounding is always round-half-up and only
at the positions the PRD pins.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

# --- yard posture (PRD §2.7) ------------------------------------------------
GRIDLOCK_RATIO_PCT = 95
CONSTRAINED_RATIO_PCT = 80

# --- damage severity index (PRD §3.2) --------------------------------------
ZONE_WEIGHT = {
    "GLASS": Decimal("1.5"),
    "BODY_PANEL": Decimal("1.2"),
    "INTERIOR": Decimal("1.0"),
    "UNDERBODY": Decimal("1.8"),
}
SPREAD_POINTS_PER_EXTRA_LINE = 5
SEVERITY_CAP = 100
CLAIM_MANDATORY_THRESHOLD = 60
DAMAGE_OPEN_THRESHOLD = 25

# --- carrier claim recoverable amount (PRD §3.3) ---------------------------
PER_ITEM_CAP_CENTS = 80000
CLAIM_DEDUCTIBLE_CENTS = 25000
MAX_CLAIM_REVISIONS = 3

# --- repair authorization tier (PRD §3.4) ---------------------------------
REPAIR_ESCALATION_THRESHOLD_CENTS = 150000

# --- accessory program billing (PRD §3.5) --------------------------------
PARTS_MARKUP_PCT = Decimal("0.125")

# --- storage charge (PRD §3.9) -------------------------------------------
PROJECTED_DISPATCH_LAG_DAYS = 2
SECONDS_PER_DAY = 86400

# --- freight settlement (PRD §3.8) ---------------------------------------
ZONE_ACCESSORIAL_CENTS = {"A": 0, "B": 4500, "C": 9800}
DISCOUNT_TIER1_CENTS = 60000
DISCOUNT_TIER2_CENTS = 120000
TIER1_PCT = Decimal("0.03")
TIER2_PCT = Decimal("0.06")

MODEL_LINES = ["EV900", "LX500", "TX300"]  # ascending
ROUTE_ZONES = ["A", "B", "C"]


def round_half_up(value):
    """Round a Decimal to a whole integer, halves away from zero."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------- yard posture
def yard_posture(occupied, capacity):
    if capacity <= 0:
        return "GRIDLOCK"
    if occupied * 100 >= capacity * GRIDLOCK_RATIO_PCT:
        return "GRIDLOCK"
    if occupied * 100 >= capacity * CONSTRAINED_RATIO_PCT:
        return "CONSTRAINED"
    return "OPEN"


# ------------------------------------------------------- damage severity
def severity_index(line_items):
    """peak = round_half_up(max(points * zone_weight)); + 5 per extra line; cap 100."""
    weighted = [
        Decimal(line["severity_points"]) * ZONE_WEIGHT[line["damage_zone"]]
        for line in line_items
    ]
    peak = round_half_up(max(weighted))
    breadth = SPREAD_POINTS_PER_EXTRA_LINE * (len(line_items) - 1)
    return min(SEVERITY_CAP, peak + breadth)


def capped_line_total(line_items):
    """claimed_amount_cents: per-line estimate capped at 80,000 cents, summed."""
    return sum(min(line["repair_estimate_cents"], PER_ITEM_CAP_CENTS) for line in line_items)


def recoverable_from_basis(basis_amount_cents):
    return max(0, basis_amount_cents - CLAIM_DEDUCTIBLE_CENTS)


# ------------------------------------------------------------ repair tier
def repair_authorization_tier(estimate_cents):
    if estimate_cents >= REPAIR_ESCALATION_THRESHOLD_CENTS:
        return "ESCALATED"
    return "AUTO"


# ------------------------------------------------------ accessory billing
def accessory_billing(unit_cost_cents, install_minutes_per_unit, labor_rate_cents_per_hour, qty):
    parts_per_unit = round_half_up(Decimal(unit_cost_cents) * (Decimal(1) + PARTS_MARKUP_PCT))
    labor_per_unit = round_half_up(
        Decimal(install_minutes_per_unit) * Decimal(labor_rate_cents_per_hour) / Decimal(60)
    )
    return (parts_per_unit + labor_per_unit) * qty


# ------------------------------------------------------------ dwell / storage
def dwell_days(start_instant, end_instant):
    """Whole 86,400-second days rounded up, floored at 1."""
    seconds = int((end_instant - start_instant).total_seconds())
    days = -((-seconds) // SECONDS_PER_DAY)  # ceiling division
    return max(1, days)


def blocked_credit_days(damage_opened_at, damage_cleared_at):
    """Whole days between damage open and clearance, partial day discarded."""
    if damage_opened_at is None or damage_cleared_at is None:
        return 0
    seconds = int((damage_cleared_at - damage_opened_at).total_seconds())
    if seconds <= 0:
        return 0
    return seconds // SECONDS_PER_DAY


def storage_charge_cents(yard_in_at, end_instant, free_storage_days, credit_days, daily_rate_cents):
    days = dwell_days(yard_in_at, end_instant)
    chargeable = max(0, days - free_storage_days - credit_days)
    return chargeable * daily_rate_cents


def provisional_end_instant(allocation_instant):
    return allocation_instant + timedelta(days=PROJECTED_DISPATCH_LAG_DAYS)


# --------------------------------------------------------- freight settlement
def freight_settlement(distance_miles, linehaul_rate_cents_per_mile, fuel_surcharge_pct, route_zone):
    base = round_half_up(Decimal(distance_miles) * Decimal(linehaul_rate_cents_per_mile))
    fuel = round_half_up(Decimal(base) * Decimal(str(fuel_surcharge_pct)))
    accessorial = ZONE_ACCESSORIAL_CENTS[route_zone]
    gross = base + fuel + accessorial
    if gross >= DISCOUNT_TIER2_CENTS:
        pct = TIER2_PCT
    elif gross >= DISCOUNT_TIER1_CENTS:
        pct = TIER1_PCT
    else:
        pct = Decimal("0")
    discount = round_half_up(Decimal(gross) * pct)
    total = gross - discount
    return {
        "base_linehaul_cents": base,
        "fuel_surcharge_cents": fuel,
        "zone_accessorial_cents": accessorial,
        "gross_freight_cents": gross,
        "freight_discount_cents": discount,
        "freight_total_cents": total,
    }


def avg_dwell_days(total_days, unit_count):
    if unit_count == 0:
        return 0.0
    value = (Decimal(total_days) / Decimal(unit_count)).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP
    )
    return float(value)
