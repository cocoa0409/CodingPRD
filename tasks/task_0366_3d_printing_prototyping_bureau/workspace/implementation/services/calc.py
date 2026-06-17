"""Calculation rules (SCAFFOLD §1.3, PRD §3, §2.9).

All monetary / gram / percentage results are integers in their base unit,
rounded half-up. We use Decimal with ROUND_HALF_UP — never float — for any
value that crosses a rounding boundary.
"""

import math
from decimal import Decimal, ROUND_HALF_UP

# Calculation constants (SCAFFOLD §1.3).
SECONDS_PER_LAYER = 7
W_MANIFOLD = 40
W_FITS = 30
W_WALL = 20
W_OVERHANG = 10
PRINTABLE_MIN = 70
FLAGGED_MIN = 50
RUSH_TIER = {"STANDARD": 0, "EXPEDITE": 30, "RUSH": 75}


def _d(value):
    """Coerce an arbitrary numeric (possibly float) to Decimal exactly enough.

    Inputs like material rates / volumes may arrive as JSON numbers (Python
    float). str() of the float gives the shortest round-trip representation,
    which matches the literal the author typed (e.g. 8.40 -> '8.4', 1.10 ->
    '1.1'), so Decimal(str(x)) reproduces the intended decimal value.
    """
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value):
    """Round a Decimal/number to the nearest integer, halves rounding up."""
    return int(_d(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------- #
# printability_score
# --------------------------------------------------------------------------- #
def printability_score(print_file, material, online_same_process_machines):
    """Compute the 0..100 integer printability score (no rounding) and resulting
    status, scored against the target material.

    fits: largest bbox dim <= largest single build dim across ONLINE machines of
    the same process as the target material; if no such machine, fits = 0.
    """
    manifold_pts = W_MANIFOLD if print_file["is_manifold"] else 0

    bbox_max = max(
        _d(print_file["bbox_x_mm"]),
        _d(print_file["bbox_y_mm"]),
        _d(print_file["bbox_z_mm"]),
    )
    build_dims = []
    for m in online_same_process_machines:
        build_dims.extend([_d(m["build_x_mm"]), _d(m["build_y_mm"]), _d(m["build_z_mm"])])
    if build_dims and bbox_max <= max(build_dims):
        fits_pts = W_FITS
    else:
        fits_pts = 0

    wall_pts = W_WALL if _d(print_file["min_wall_mm"]) >= _d(material["min_wall_thickness_mm"]) else 0
    overhang_pts = W_OVERHANG if _d(print_file["max_overhang_deg"]) <= _d(material["max_overhang_deg"]) else 0

    score = manifold_pts + fits_pts + wall_pts + overhang_pts

    # Hard gate: non-manifold forces REJECTED regardless of numeric score.
    if not print_file["is_manifold"]:
        status = "REJECTED"
    elif score >= PRINTABLE_MIN:
        status = "PRINTABLE"
    elif score >= FLAGGED_MIN:
        status = "FLAGGED"
    else:
        status = "REJECTED"
    return score, status


# --------------------------------------------------------------------------- #
# order_line_pricing
# --------------------------------------------------------------------------- #
def print_minutes_per_part(bbox_z_mm, layer_height_mm):
    layer_count = math.ceil(_d(bbox_z_mm) / _d(layer_height_mm))
    print_seconds = layer_count * SECONDS_PER_LAYER
    return math.ceil(_d(print_seconds) / _d(60))


def line_pricing(print_file, material, layer_height_mm, quantity):
    """Returns (print_minutes, per_part_cents, line_total_cents).

    Mode (b): round per-part FIRST, then multiply by quantity, then add the
    one-time setup fee.
    """
    pm = print_minutes_per_part(print_file["bbox_z_mm"], layer_height_mm)
    material_cost = _d(print_file["volume_cm3"]) * _d(material["material_rate_cents_per_cm3"])
    machine_cost = _d(pm) * _d(material["machine_rate_cents_per_min"])
    per_part = round_half_up(material_cost + machine_cost)
    line_total = per_part * int(quantity) + int(material["setup_fee_cents"])
    return pm, per_part, line_total


# --------------------------------------------------------------------------- #
# order_totals
# --------------------------------------------------------------------------- #
def order_totals(active_lines, lead_tier):
    """Returns (parts_subtotal, finishing_subtotal, rush_surcharge, grand_total)
    over ACTIVE lines only.
    """
    parts = sum(int(l["line_total_cents"]) for l in active_lines)
    finishing = sum(int(l.get("finishing_total_cents", 0)) for l in active_lines)
    base = parts + finishing
    rush_pct = RUSH_TIER.get(lead_tier, 0)
    rush = round_half_up(_d(base) * _d(rush_pct) / _d(100))
    grand = base + rush
    return parts, finishing, rush, grand


# --------------------------------------------------------------------------- #
# reprint_attribution
# --------------------------------------------------------------------------- #
def reprint_charge_forward(failed_line):
    """FORWARD (provisional, at /fail): full original line_total re-billed."""
    return int(failed_line["line_total_cents"])


def reprint_charge_chronological(failed_line, print_file, material, reprint_cause):
    """CHRONOLOGICAL (final, at /adjudicate): cause-based attribution.

    Bureau-fault (MACHINE_FAULT, OPERATOR_ERROR) -> 0.
    Customer-fault (FILE_DEFECT, CUSTOMER_CHANGE) ->
        material_portion + round_half_up(machine_portion * 0.5)
      where material_portion = round_half_up(volume * material_rate) * quantity
            machine_portion   = print_minutes * machine_rate * quantity
    """
    if reprint_cause in ("MACHINE_FAULT", "OPERATOR_ERROR"):
        return 0
    qty = int(failed_line["quantity"])
    material_portion = round_half_up(
        _d(print_file["volume_cm3"]) * _d(material["material_rate_cents_per_cm3"])
    ) * qty
    machine_portion = int(failed_line["print_minutes"]) * int(material["machine_rate_cents_per_min"]) * qty
    return material_portion + round_half_up(_d(machine_portion) * _d("0.5"))


# --------------------------------------------------------------------------- #
# machine_utilization
# --------------------------------------------------------------------------- #
def machine_utilization(scheduled_minutes, active_minutes, shift_capacity_minutes):
    """Returns (utilization_pct, active_utilization_pct), each rounded half-up
    to a whole percent."""
    cap = _d(shift_capacity_minutes)
    if cap == 0:
        return 0, 0
    util = round_half_up(_d(scheduled_minutes) / cap * _d(100))
    active_util = round_half_up(_d(active_minutes) / cap * _d(100))
    return util, active_util


# --------------------------------------------------------------------------- #
# spool_conservation
# --------------------------------------------------------------------------- #
def run_grams(print_file, material, quantity):
    return round_half_up(
        _d(print_file["volume_cm3"]) * _d(material["density_g_per_cm3"]) * _d(int(quantity))
    )
