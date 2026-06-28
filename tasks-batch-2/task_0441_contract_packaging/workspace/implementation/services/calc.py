"""Calculation rules (SCAFFOLD §1.3, PRD §2.8, §3.4-§3.6).

All money/quantity precision uses Decimal round-half-up via util.round_half_up.
"""
import re
from datetime import timedelta

import util

OVERRUN_ALLOWANCE_PCT = 10
MAX_REJECT_RATE = 0.05
SEQ_PAD = 3


def required_qty_for_line(bom_line, planned_units):
    """material_consumption: gross_per_unit = qty_per_unit*(1+scrap/100);
    required_qty = round_half_up(gross_per_unit * planned_units, 3)."""
    qpu = bom_line["qty_per_unit"]
    scrap = bom_line.get("scrap_factor_pct", 0)
    gross_per_unit = qpu * (1 + scrap / 100.0)
    return util.round_half_up(gross_per_unit * planned_units, 3)


def planned_waste_line(bom_line, planned_units):
    """planned_waste_qty_line = required_qty - (qty_per_unit * planned_units).

    Not pre-rounded here; the waste_totals caller rounds per line then sums.
    Returns the raw value (required_qty itself is already rounded to 3)."""
    required = required_qty_for_line(bom_line, planned_units)
    return required - (bom_line["qty_per_unit"] * planned_units)


def actual_waste_line(consumed_qty_line, qty_per_unit, actual_units_good):
    """actual_waste_qty_line = round_half_up(consumed - qpu*actual_good, 3)."""
    return util.round_half_up(consumed_qty_line - (qty_per_unit * actual_units_good), 3)


def project_run_window(scheduled_start, line, recipe, planned_units):
    """project_run_window. Changeover added only when line residue set !=
    recipe allergen_profile set. scheduled_end rounded to whole seconds
    (round_half_up on minutes->seconds)."""
    residue = set(line.get("current_allergen_residue", []))
    profile = set(recipe.get("allergen_profile", []))
    needs_changeover = residue != profile
    changeover_min = line["changeover_minutes"] if needs_changeover else 0
    run_hours = planned_units / float(line["rated_units_per_hour"])
    run_minutes = run_hours * 60.0
    total_minutes = changeover_min + run_minutes
    total_seconds = util.round_half_up(total_minutes * 60.0, 0)
    return scheduled_start + timedelta(seconds=int(total_seconds))


def recipe_short_token(name):
    """First 4 alphanumeric chars of recipe.name uppercased, padded with X."""
    alnum = re.sub(r"[^A-Za-z0-9]", "", name or "").upper()
    token = alnum[:4]
    if len(token) < 4:
        token = token + ("X" * (4 - len(token)))
    return token


def assign_lot_code(customer_code, pack_date, recipe_name, seq):
    """lot_code = f"{code}-{YYYYMMDD}-{recipe_short}-{seq:03d}"."""
    pack_yyyymmdd = "{:04d}{:02d}{:02d}".format(pack_date.year, pack_date.month, pack_date.day)
    short = recipe_short_token(recipe_name)
    return "{}-{}-{}-{:0{pad}d}".format(customer_code, pack_yyyymmdd, short, seq, pad=SEQ_PAD)


def checkweigh_verdict(measured_weight_g, target_fill_weight_g, fill_tolerance_pct):
    """Band endpoints round_half_up to 3 decimals; comparison in grams to 3
    decimals. Boundary inclusive (lower/upper PASS)."""
    lower = util.round_half_up(target_fill_weight_g * (1 - fill_tolerance_pct / 100.0), 3)
    upper = util.round_half_up(target_fill_weight_g * (1 + fill_tolerance_pct / 100.0), 3)
    measured = util.round_half_up(measured_weight_g, 3)
    if measured < lower:
        return "UNDER"
    if measured > upper:
        return "OVER"
    return "PASS"


def checkweigh_reject_rate(samples):
    """reject_rate = round_half_up(rejects/total, 4). total assumed > 0."""
    total = len(samples)
    if total == 0:
        return 0.0
    rejects = sum(1 for s in samples if s["verdict"] in ("UNDER", "OVER"))
    return util.round_half_up(rejects / float(total), 4)


def run_rate(total_units, elapsed_hours):
    """0 if elapsed_hours == 0 else round_half_up(total/elapsed, 2)."""
    if elapsed_hours == 0:
        return 0.0
    return util.round_half_up(total_units / elapsed_hours, 2)
