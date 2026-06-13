"""Pricing and quantity calculations (PRD §3.4–§3.6, SCAFFOLD §1.3).

All money is integer cents; percentages are scaled with Decimal and rounded UP
(ceiling) to the next whole cent / whole unit (PRD §2.6). Only the rush-window
day count is floored.
"""
import math
from decimal import Decimal


# Quantity-tier rate table (PRD §3.5; SCAFFOLD calculations.decoration_run_cost).
TIER1_MAX = 23
TIER2_MAX = 71
TIER3_MAX = 143
TIER1_RATE_CENTS = 800
TIER2_RATE_CENTS = 550
TIER3_RATE_CENTS = 400
TIER4_RATE_CENTS = 300

DEPOSIT_PCT = Decimal("0.5")


def _ceil_pct(amount_cents, pct):
    """ceil(amount_cents * pct) using exact Decimal arithmetic (PRD §2.6)."""
    product = Decimal(int(amount_cents)) * Decimal(str(pct))
    return int(math.ceil(product))


def tier_rate(line_qty):
    """Flat per-unit-per-location tier rate chosen by the whole line_qty."""
    if line_qty <= TIER1_MAX:
        return TIER1_RATE_CENTS
    if line_qty <= TIER2_MAX:
        return TIER2_RATE_CENTS
    if line_qty <= TIER3_MAX:
        return TIER3_RATE_CENTS
    return TIER4_RATE_CENTS


def line_qty_of(size_run):
    """Sum of all size_run quantities (SCAFFOLD calculations.line_qty)."""
    return sum(int(q) for q in size_run.values())


def per_unit_line_cost(method, line):
    """Per-unit (one garment) decoration run cost = per-unit-per-location * num_locations.

    SCREEN_PRINT: tier_rate(line_qty) + (num_colors - 1) * extra_color_run_cents.
    EMBROIDERY:   ceil(stitch_count / 1000) * stitch_run_per_1k_cents.
    """
    num_locations = line["num_locations"]
    if method["method_type"] == "SCREEN_PRINT":
        per_loc = tier_rate(line["line_qty"]) \
            + (line["num_colors"] - 1) * method["extra_color_run_cents"]
    else:  # EMBROIDERY
        thousands = math.ceil(line["stitch_count"] / 1000) if line["stitch_count"] > 0 else 0
        per_loc = thousands * method["stitch_run_per_1k_cents"]
    return per_loc * num_locations


def line_decoration_cost(method, line):
    """Per-line integer-cent decoration cost: per_unit_line * line_qty.

    Per-line rounding is pinned to happen here before summation (PRD §3.4):
    "round per line, then sum." Both factors are integers, so the product is
    already an integer.
    """
    return per_unit_line_cost(method, line) * line["line_qty"]


def line_setup_cost(method, line):
    """Per-line setup charge before any reorder waiver (PRD §3.6).

    SCREEN_PRINT: num_colors * num_locations * screen_fee_cents.
    EMBROIDERY:   num_locations * digitizing_fee_cents.
    """
    if method["method_type"] == "SCREEN_PRINT":
        return line["num_colors"] * line["num_locations"] * method["screen_fee_cents"]
    return line["num_locations"] * method["digitizing_fee_cents"]


def spoilage_allowance(ordered_qty, spoilage_pct):
    """ceil(ordered_qty * spoilage_pct) whole units (PRD §2.6, §3.4)."""
    return _ceil_pct(ordered_qty, spoilage_pct)


def rush_whole_days(requested_ship_dt, current_utc_dt):
    """floor((requested - current_utc) / 86400 seconds) -> whole days (PRD §3.4)."""
    delta_seconds = (requested_ship_dt - current_utc_dt).total_seconds()
    return math.floor(delta_seconds / 86400)


def is_rush(requested_ship_dt, current_utc_dt, rush_threshold_days):
    """is_rush iff whole_days < rush_threshold_days (strict '<')."""
    return rush_whole_days(requested_ship_dt, current_utc_dt) < rush_threshold_days


def rush_surcharge(decoration_subtotal_cents, rush_surcharge_pct, rush):
    """ceil(decoration_subtotal * rush_surcharge_pct) when rush, else 0."""
    if not rush:
        return 0
    return _ceil_pct(decoration_subtotal_cents, rush_surcharge_pct)


def deposit_cents(grand_total_cents):
    """ceil(grand_total * 0.5) (PRD §3.4, deposit)."""
    return _ceil_pct(grand_total_cents, DEPOSIT_PCT)
