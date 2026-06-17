"""Calculation rules (PRD §3, SCAFFOLD calculations table).

All money is integer cents, round-half-up at the points pinned per calculation.
"""
import math

from validators import round_half_up


# ---------------------------------------------------------------------------
# estimate_total / line cost  (PRD §3.2)
# ---------------------------------------------------------------------------
def line_cost_cents(squares, waste_factor_pct, unit_price_cents):
    """round_half_up( squares * (1 + waste_factor_pct) * unit_price_cents ).

    Rounding happens AT THE LINE.
    """
    raw = squares * (1 + waste_factor_pct) * unit_price_cents
    return round_half_up(raw)


def line_subtotal_cents(line_items):
    """Sum of each line item's already-rounded line_cost_cents (round-per-line
    then sum)."""
    return sum(li["line_cost_cents"] for li in line_items)


def final_total_cents(subtotal, source_kind, aerial_contingency_pct):
    """AERIAL: round_half_up(subtotal * (1 + pct)); FIELD: subtotal unchanged."""
    if source_kind == "AERIAL":
        return round_half_up(subtotal * (1 + aerial_contingency_pct))
    return subtotal


# ---------------------------------------------------------------------------
# draw_amounts  (PRD §3.7)
# ---------------------------------------------------------------------------
def draw_amounts(contract_value_cents, disbursed_gross_cents, cumulative_pct,
                 retainage_pct):
    """Returns (gross_eligible, retainage, net_disbursed, is_final)."""
    gross_to_date = round_half_up(contract_value_cents * cumulative_pct)
    gross_eligible = gross_to_date - disbursed_gross_cents
    is_final = (cumulative_pct == 1.0)
    if is_final:
        retainage = 0
    else:
        retainage = round_half_up(gross_eligible * retainage_pct)
    net_disbursed = gross_eligible - retainage
    return gross_eligible, retainage, net_disbursed, is_final


# ---------------------------------------------------------------------------
# material_order_sizing  (PRD §3.4)
# ---------------------------------------------------------------------------
MIN_BUNDLES = 12
BUNDLES_PER_SQUARE = 3
SHINGLE_WASTE = 0.15
WEIGHT_PER_BUNDLE_LBS = 80


def material_sizing(effective_squares):
    """Returns (bundles, total_weight_lbs, freight_cents)."""
    bundles = max(
        MIN_BUNDLES,
        math.ceil(effective_squares * (1 + SHINGLE_WASTE) * BUNDLES_PER_SQUARE),
    )
    total_weight = bundles * WEIGHT_PER_BUNDLE_LBS
    if total_weight <= 2000:
        freight = 7500
    elif total_weight <= 4000:
        freight = 12500
    else:
        freight = 12500 + math.ceil((total_weight - 4000) / 1000) * 3000
    return bundles, total_weight, freight


# ---------------------------------------------------------------------------
# warranty_refund  (PRD §3.10)
# ---------------------------------------------------------------------------
SHORT_RATE_FACTOR = 0.90


def elapsed_whole_months(start_at, current):
    """Whole months between two aware datetimes, floored, never below zero."""
    months = (current.year - start_at.year) * 12 + (current.month - start_at.month)
    # Subtract one if the day/time-of-month hasn't been reached yet.
    if (current.day, current.hour, current.minute, current.second, current.microsecond) < \
       (start_at.day, start_at.hour, start_at.minute, start_at.second, start_at.microsecond):
        months -= 1
    return max(0, months)


def warranty_refund_cents(premium_cents, term_months, start_at, current, cancel_basis):
    elapsed = elapsed_whole_months(start_at, current)
    remaining = max(0, term_months - elapsed)
    prorated = round_half_up(premium_cents * remaining / term_months)
    if cancel_basis == "PRORATED":
        return prorated
    # SHORT_RATE
    return round_half_up(prorated * SHORT_RATE_FACTOR)


# ---------------------------------------------------------------------------
# Date-add helper for warranty expiry: start_at + term_months
# ---------------------------------------------------------------------------
def add_months(dt, months):
    """Return dt advanced by `months` calendar months (clamping day overflow)."""
    total = dt.month - 1 + months
    year = dt.year + total // 12
    month = total % 12 + 1
    # clamp day to month length
    day = dt.day
    while True:
        try:
            return dt.replace(year=year, month=month, day=day)
        except ValueError:
            day -= 1
            if day < 1:
                raise
