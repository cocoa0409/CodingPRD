"""Calculation rules (PRD §3.2, §3.3, §3.5, §3.6, §3.9 / SCAFFOLD §1.3).

All money in integer cents. Use Decimal for the non-integer intermediates so we
control the rounding direction exactly per the PRD.
"""
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

# Global constants (SCAFFOLD global_constants / §1.3)
DEPOSIT_RATE = Decimal("0.50")
RUSH_RATE = Decimal("0.30")
RUSH_DEPOSIT_FLOOR_CENTS = 20000
MAX_REMAKES = 2
GROUP_MIN_MEMBERS = 3

UPCHARGE_TABLE = {
    "MONOGRAM": 1500,
    "CONTRAST_LINING": 4000,
    "WORKING_CUFFS": 6000,
    "PICK_STITCH": 3500,
    "EXTRA_TROUSER": 9000,
}

# yardage tier multipliers
TIER1_MULT = Decimal("1.00")
TIER2_MULT = Decimal("0.90")
TIER3_MULT = Decimal("0.80")

# group discount tiers
GROUP_TIER1_MIN = 4
GROUP_TIER1_DISC = Decimal("0.05")
GROUP_TIER2_MIN = 8
GROUP_TIER2_DISC = Decimal("0.10")

# remake compensation
REMAKE_BASE_CENTS = 5000
REMAKE_STEP_CENTS = 3000

# customer remake risk thresholds
WATCH_THRESHOLD = Decimal("0.34")
HIGH_THRESHOLD = Decimal("0.50")

GROUP_MEMBER_STATES = {"CONFIRMED", "IN_FITTING", "REMAKE", "READY", "PICKED_UP"}


def _round_half_up(value):
    """value is a Decimal -> nearest whole cent, halves up."""
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _ceil(value):
    """value is a Decimal -> next whole cent (ceiling)."""
    return int(value.quantize(Decimal(1), rounding=ROUND_CEILING))


def option_upcharge(option_code):
    return UPCHARGE_TABLE[option_code]


def yardage_cost(meters, price_per_meter_cents):
    """Marginal tiered rate; round EACH TIER to whole cents independently, then sum."""
    m = Decimal(str(meters))
    price = Decimal(str(price_per_meter_cents))

    m1 = min(m, Decimal("3.0"))
    m2 = max(Decimal("0"), min(m, Decimal("6.0")) - Decimal("3.0"))
    m3 = max(Decimal("0"), m - Decimal("6.0"))

    c1 = _round_half_up(m1 * price * TIER1_MULT)
    c2 = _round_half_up(m2 * price * TIER2_MULT)
    c3 = _round_half_up(m3 * price * TIER3_MULT)
    return c1 + c2 + c3


def rush_surcharge(pre_rush_cents, is_rush):
    if not is_rush:
        return 0
    return _ceil(Decimal(pre_rush_cents) * RUSH_RATE)


def order_quote_total(base_labor_cents, fabric_meters_required,
                      live_price_per_meter_cents, option_lines, is_rush):
    """PROVISIONAL quote — uses the LIVE fabric catalog price."""
    yardage = yardage_cost(fabric_meters_required, live_price_per_meter_cents)
    options = sum(line["upcharge_cents"] for line in option_lines)
    pre_rush = base_labor_cents + yardage + options
    return pre_rush + rush_surcharge(pre_rush, is_rush)


def order_final_invoice(base_labor_cents, fabric_meters_required,
                        snapshot_price_per_meter_cents, option_lines, is_rush):
    """FINAL invoice — uses the FIRST option line's snapshot fabric price."""
    yardage = yardage_cost(fabric_meters_required, snapshot_price_per_meter_cents)
    options = sum(line["upcharge_cents"] for line in option_lines)
    pre_rush = base_labor_cents + yardage + options
    return pre_rush + rush_surcharge(pre_rush, is_rush)


def deposit_due(locked_total_cents, is_rush):
    dep = _ceil(Decimal(locked_total_cents) * DEPOSIT_RATE)
    if is_rush:
        dep = max(dep, RUSH_DEPOSIT_FLOOR_CENTS)
    return dep


def balance_due(locked_total_cents, amount_paid_cents, store_credit_applied_cents):
    return max(0, locked_total_cents - amount_paid_cents - store_credit_applied_cents)


def group_order_total(member_locked_totals):
    """member_locked_totals: list of locked_total_cents for qualifying members.
    Sum first, then apply the member-count discount tier, ceiling the discount."""
    raw_sum = sum(member_locked_totals)
    n = len(member_locked_totals)
    if n >= GROUP_TIER2_MIN:
        disc = GROUP_TIER2_DISC
    elif n >= GROUP_TIER1_MIN:
        disc = GROUP_TIER1_DISC
    else:
        disc = Decimal("0")
    discount = _ceil(Decimal(raw_sum) * disc) if disc > 0 else 0
    return raw_sum - discount


def remake_compensation(remake_round, locked_total_cents):
    """remake_round has ALREADY been incremented (round 1 -> raw = base)."""
    raw = REMAKE_BASE_CENTS + (remake_round - 1) * REMAKE_STEP_CENTS
    return min(raw, locked_total_cents)


def customer_remake_risk(remake_count, completed_order_count):
    denom = max(1, completed_order_count + remake_count)
    rate = Decimal(remake_count) / Decimal(denom)
    if rate >= HIGH_THRESHOLD:
        return "HIGH_RISK"
    if rate >= WATCH_THRESHOLD:
        return "WATCH"
    return "STANDARD"
