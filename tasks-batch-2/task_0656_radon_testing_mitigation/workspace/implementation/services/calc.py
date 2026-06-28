"""Calculation rules (SCAFFOLD §1.3, PRD §3.3, §3.4, §3.5, §3.6, §3.7).

All money is integer cents; percentage steps round half up to a whole cent.
Radon concentrations are carried to one decimal place, round half up.
Never use float for money — use Decimal with ROUND_HALF_UP.
"""

from decimal import Decimal, ROUND_HALF_UP

ACTION_LEVEL_PCI_L = Decimal("4.0")

# --- mitigation_quote constants (SCAFFOLD §1.3 / PRD §3.4) ---
BASE_BY_FOUNDATION = {
    "SLAB": 150000,
    "BASEMENT": 185000,
    "CRAWLSPACE": 240000,
}
PER_SUCTION_POINT_CENTS = 45000
SUMP_SEAL_FEE_CENTS = 32000
AREA_TIER1_SQFT = 1500
AREA_TIER2_SQFT = 3000
AREA_TIER2_SURCHARGE_CENTS = 50000
AREA_TIER3_SURCHARGE_CENTS = 120000
RUSH_RATE = Decimal("0.15")
DEPOSIT_RATE = Decimal("0.30")

# --- warranty_refund step-tier constants ---
STEP_T1 = Decimal("0.25")
STEP_T2 = Decimal("0.50")
STEP_T3 = Decimal("0.75")
STEP_PCT1 = Decimal("0.90")
STEP_PCT2 = Decimal("0.60")
STEP_PCT3 = Decimal("0.30")


def round_half_up_cents(value):
    """Round a Decimal to a whole cent, half up. Returns int."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_1dp(value):
    """Round a numeric value to one decimal place, half up. Returns float."""
    d = Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return float(d)


def radon_result_average(test_kind, hourly_readings, lab_integrated_pci_l, warmup_hours_dropped):
    """Compute result_pci_l (SCAFFOLD radon_result_average, PRD §3.3).

    CONTINUOUS_MONITOR: drop the first warmup_hours_dropped readings, mean the rest,
                        round half up to 1 decimal.
    SHORT_TERM_48HR:    round half up the supplied lab_integrated_pci_l to 1 decimal.
    """
    if test_kind == "CONTINUOUS_MONITOR":
        valid = hourly_readings[warmup_hours_dropped:]
        total = sum(Decimal(str(r)) for r in valid)
        mean = total / Decimal(len(valid))
        return round_half_up_1dp(mean)
    else:  # SHORT_TERM_48HR
        return round_half_up_1dp(lab_integrated_pci_l)


def action_level_classification(result_pci_l):
    """ACTION_RECOMMENDED iff result_pci_l >= 4.0 (inclusive boundary); else NO_ACTION.
    Compares on the one-decimal value (PRD §3.3, §2.8)."""
    if Decimal(str(result_pci_l)) >= ACTION_LEVEL_PCI_L:
        return "ACTION_RECOMMENDED"
    return "NO_ACTION"


def mitigation_quote(foundation_type, floor_area_sqft, num_suction_points, has_sump_pump, is_rush):
    """Compute (subtotal, rush_surcharge, total, deposit_required) in cents.

    Evaluation order is pinned: subtotal must be fully resolved before the rush
    surcharge keys off it (SCAFFOLD §1.3 / PRD §3.4).
    """
    base = BASE_BY_FOUNDATION[foundation_type]
    extra_points = max(num_suction_points - 1, 0) * PER_SUCTION_POINT_CENTS
    sump_fee = SUMP_SEAL_FEE_CENTS if has_sump_pump else 0

    if floor_area_sqft <= AREA_TIER1_SQFT:
        area = 0
    elif floor_area_sqft <= AREA_TIER2_SQFT:
        area = AREA_TIER2_SURCHARGE_CENTS
    else:
        area = AREA_TIER3_SURCHARGE_CENTS

    subtotal = base + extra_points + sump_fee + area
    if is_rush:
        rush = round_half_up_cents(Decimal(subtotal) * RUSH_RATE)
    else:
        rush = 0
    total = subtotal + rush
    deposit = round_half_up_cents(Decimal(total) * DEPOSIT_RATE)
    return subtotal, rush, total, deposit


def warranty_refund(refund_method, covered_system_price_cents, term_days, elapsed_days):
    """Compute prorated refund_paid_cents (SCAFFOLD warranty_refund, PRD §3.6).

    elapsed_days is the floored whole-day count since started_at_utc.
    """
    remaining_days = max(term_days - elapsed_days, 0)
    price = Decimal(covered_system_price_cents)
    if refund_method == "STRAIGHT_LINE":
        amount = price * Decimal(remaining_days) / Decimal(term_days)
        return round_half_up_cents(amount)
    else:  # STEP_TIER
        frac = Decimal(elapsed_days) / Decimal(term_days)
        if frac < STEP_T1:
            pct = STEP_PCT1
        elif frac < STEP_T2:
            pct = STEP_PCT2
        elif frac < STEP_T3:
            pct = STEP_PCT3
        else:
            pct = Decimal("0.00")
        return round_half_up_cents(price * pct)
