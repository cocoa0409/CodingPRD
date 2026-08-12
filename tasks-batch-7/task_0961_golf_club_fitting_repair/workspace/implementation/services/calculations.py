"""Calculation rules from the scaffold — implemented exactly as specified.

All money is integer cents; round-half-up applied at exactly the pinned points.
"""
from decimal import Decimal, ROUND_HALF_UP

from db import db

# --- build pricing constants ---
TIER1_MIN = 200000
TIER2_MIN = 500000
LOYALTY_RATE = Decimal("0.05")
LOYALTY_MIN_BUILDS = 2
RATE_CAP = Decimal("0.15")
TIER1_RATE = Decimal("0.05")
TIER2_RATE = Decimal("0.10")
FITTING_FEE_REBATE = 7500

# --- repair quote constants ---
SERVICE_BASE = {"REGRIP": 1800, "RESHAFT": 6500, "LOFT_LIE_ADJUST": 2500}
RUSH_RATE = Decimal("0.35")
RUSH_MIN_FEE = 1500
RUSH_HOURS = 24
STANDARD_HOURS = 72
DEPOSIT_RATE = Decimal("0.5")

# --- trade-in constants ---
BOOK_VALUE = {
    "DRIVER": 29999,
    "FAIRWAY": 21999,
    "HYBRID": 17999,
    "IRON_SET": 44999,
    "WEDGE": 8999,
    "PUTTER": 14999,
}
GRADE_MULT = {
    "A": Decimal("0.60"),
    "B": Decimal("0.45"),
    "C": Decimal("0.30"),
    "D": Decimal("0.15"),
}
COMP_FACTOR = Decimal("0.8")

# --- warranty constants ---
SPEC_FULL_DAYS = 90
SPEC_PARTIAL_DAYS = 365
TICKET_FULL_DAYS = 30


def round_half_up_cents(value):
    """Round a Decimal to integer cents, half-up."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _tier_rate(amount_cents):
    if amount_cents >= TIER2_MIN:
        return TIER2_RATE
    if amount_cents >= TIER1_MIN:
        return TIER1_RATE
    return Decimal("0")


def _discount_rate(base_cents, completed_builds_count):
    tier_rate = _tier_rate(base_cents)
    loyalty_rate = LOYALTY_RATE if completed_builds_count >= LOYALTY_MIN_BUILDS else Decimal("0")
    return min(tier_rate + loyalty_rate, RATE_CAP)


def build_provisional_quote(spec):
    """MSRP-based provisional quote. Returns integer cents."""
    head = db.component_items[spec["head_item_id"]]
    shaft = db.component_items[spec["shaft_item_id"]]
    grip = db.component_items[spec["grip_item_id"]]
    component_msrp_sum = head["msrp_cents"] + shaft["msrp_cents"] + grip["msrp_cents"]
    customer = db.customers[spec["customer_id"]]
    rate = _discount_rate(component_msrp_sum, customer["completed_builds_count"])
    discount_cents = round_half_up_cents(Decimal(component_msrp_sum) * rate)
    return component_msrp_sum - discount_cents + spec["labor_cents"]


def build_final_price(spec):
    """Unit-cost-based final price with fitting-fee rebate. Returns integer cents."""
    head = db.component_items[spec["head_item_id"]]
    shaft = db.component_items[spec["shaft_item_id"]]
    grip = db.component_items[spec["grip_item_id"]]
    component_cost_sum = head["unit_cost_cents"] + shaft["unit_cost_cents"] + grip["unit_cost_cents"]
    customer = db.customers[spec["customer_id"]]
    # Tier selected on cost sum BEFORE any rebate
    rate = _discount_rate(component_cost_sum, customer["completed_builds_count"])
    discount_cents = round_half_up_cents(Decimal(component_cost_sum) * rate)
    session = db.fitting_sessions.get(spec["fitting_session_id"])
    rebate_cents = FITTING_FEE_REBATE if (session and session["status"] == "COMPLETED") else 0
    final = component_cost_sum - discount_cents + spec["labor_cents"] - rebate_cents
    return max(0, final)


def repair_quote(service_type, rush, created_at):
    """Returns (quoted_total_cents, promised_at, deposit_cents)."""
    from datetime import timedelta

    base_cents = SERVICE_BASE[service_type]
    if rush:
        rush_fee_cents = max(RUSH_MIN_FEE, round_half_up_cents(Decimal(base_cents) * RUSH_RATE))
    else:
        rush_fee_cents = 0
    quoted_total_cents = base_cents + rush_fee_cents
    hours = RUSH_HOURS if rush else STANDARD_HOURS
    promised_at = created_at + timedelta(hours=hours)
    deposit_cents = round_half_up_cents(Decimal(quoted_total_cents) * DEPOSIT_RATE)
    return quoted_total_cents, promised_at, deposit_cents


def tradein_offer_value(clubs, basis, market_comps_cents=None):
    """Per-line round-then-sum, pinned order. Returns integer cents."""
    total = 0
    if basis == "GRADE_MATRIX":
        for club in clubs:
            line = Decimal(BOOK_VALUE[club["club_type"]]) * GRADE_MULT[club["condition_grade"]]
            total += round_half_up_cents(line)
    else:  # MARKET_COMP
        for comp in market_comps_cents:
            line = Decimal(comp) * COMP_FACTOR
            total += round_half_up_cents(line)
    return total


def warranty_coverage(subject_type, anchor, now, subject_price):
    """Returns (coverage_pct, covered_estimate_cents).

    subject_type: "spec" or "ticket". Raises nothing — caller handles window
    expiry check via return value of None.
    """
    age_days = int((now - anchor).total_seconds() // 86400)
    if subject_type == "spec":
        if age_days <= SPEC_FULL_DAYS:
            coverage_pct = 100
        elif age_days <= SPEC_PARTIAL_DAYS:
            coverage_pct = 50
        else:
            return None
    else:  # ticket
        if age_days <= TICKET_FULL_DAYS:
            coverage_pct = 100
        else:
            return None
    covered = round_half_up_cents(Decimal(subject_price) * Decimal(coverage_pct) / Decimal(100))
    return coverage_pct, covered


def recompute_credit_balance(customer_id):
    """customer.credit_balance_cents = SUM(amount_cents) over the ledger."""
    total = 0
    for entry in db.credit_ledger_entries:
        if entry["customer_id"] == customer_id:
            total += entry["amount_cents"]
    db.customers[customer_id]["credit_balance_cents"] = total
