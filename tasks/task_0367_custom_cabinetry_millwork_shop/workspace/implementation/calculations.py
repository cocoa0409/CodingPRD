"""Calculation rules (PRD §3.4, §3.6, §3.7, §3.8 / scaffold Table 3).

All monetary rounding is round_half_up at each pinned step, never float.
"""
import math

from db import store
from helpers import round_half_up_div
from models import project_specs, project_active_finish

# Margin multipliers in bps, indexed [margin_policy][qty_tier]
MARGIN_TABLE = {
    "STANDARD": {"SMALL": 13500, "MED": 13000, "BULK": 12500},
    "PREMIUM": {"SMALL": 16000, "MED": 15500, "BULK": 15000},
}

# Finish upcharge in bps of the margined line
FINISH_BPS = {"RAW": 0, "STAIN": 800, "PAINT": 1200, "LACQUER": 2000}

MIN_LINE_CENTS = 5000
MAX_LINE_CENTS = 5000000

KERF_WASTE_BPS = 1200  # 12% saw-kerf + offcut uplift

LATE_TIER1_BPS = 150   # 1..30 days
LATE_TIER2_BPS = 400   # >30 days


def qty_tier(quantity):
    if quantity <= 2:
        return "SMALL"
    if quantity <= 6:
        return "MED"
    return "BULK"


def panel_area_mm2(width_mm, height_mm, depth_mm):
    # 2*(w*h) + 2*(h*d) + 1*(w*d)
    return 2 * (width_mm * height_mm) + 2 * (height_mm * depth_mm) + 1 * (width_mm * depth_mm)


# --------------------------------------------------------------------------
# cut_list_sheets (PRD §3.3): ceil per spec, then sum within material.
# --------------------------------------------------------------------------
def per_spec_sheets(spec, material):
    total_panel_area = spec["panel_area_mm2"] * spec["quantity"]
    inflated = total_panel_area * (10000 + KERF_WASTE_BPS)  # multiply then divide
    # inflated_area = total_panel_area * 11200 / 10000 (exact rational); divide by sheet area; ceil
    # sheets = ceil( (total_panel_area * 11200 / 10000) / sheet_area_mm2 )
    numerator = inflated  # = total_panel_area * 11200
    denominator = 10000 * material["sheet_area_mm2"]
    if denominator <= 0:
        return 0
    return math.ceil(numerator / denominator)


def cut_list(project_id):
    """Returns (list of {material_id, total_sheets}, total_sheets)."""
    specs = project_specs(project_id)
    per_material = {}
    for spec in specs:
        material = store.materials.get(spec["material_id"])
        if material is None:
            continue
        sheets = per_spec_sheets(spec, material)
        per_material[spec["material_id"]] = per_material.get(spec["material_id"], 0) + sheets
    materials = [{"material_id": mid, "total_sheets": s} for mid, s in per_material.items()]
    total = sum(per_material.values())
    return materials, total


# --------------------------------------------------------------------------
# contract_total (PRD §3.4): estimate + final variants.
# --------------------------------------------------------------------------
def _per_spec_priced(spec, margin_policy, finish_code):
    line_base = spec["base_unit_price_cents"] * spec["quantity"]
    margin_mult_bps = MARGIN_TABLE[margin_policy][qty_tier(spec["quantity"])]
    margined = round_half_up_div(line_base * margin_mult_bps, 10000)
    finish_upcharge = round_half_up_div(margined * FINISH_BPS[finish_code], 10000)
    line_total = margined + finish_upcharge
    line_total = min(MAX_LINE_CENTS, max(MIN_LINE_CENTS, line_total))
    return line_total


def contract_total(project, variant):
    """variant: 'estimate' or 'final'. Returns total cents."""
    shop = store.shops[project["shop_id"]]
    specs = project_specs(project["id"])
    active = project_active_finish(project["id"])
    if variant == "estimate":
        finish_code = active["finish_code"] if active else "RAW"
    else:
        # final variant requires an active finish (enforced upstream)
        finish_code = active["finish_code"] if active else "RAW"

    subtotal = 0
    for spec in specs:
        subtotal += _per_spec_priced(spec, project["margin_policy"], finish_code)

    if variant == "final" and project["is_rush"]:
        subtotal += round_half_up_div(subtotal * shop["rush_surcharge_bps"], 10000)

    tax = round_half_up_div(subtotal * shop["tax_rate_bps"], 10000)
    return subtotal + tax


# --------------------------------------------------------------------------
# change_order_delta (PRD §3.7): BULK margin tier, sign preserved.
# --------------------------------------------------------------------------
def change_order_delta(project, spec_price_delta_cents):
    shop = store.shops[project["shop_id"]]
    active = project_active_finish(project["id"])
    finish_code = active["finish_code"] if active else "RAW"
    margin_mult_bps = MARGIN_TABLE[project["margin_policy"]]["BULK"]
    margined = round_half_up_div(spec_price_delta_cents * margin_mult_bps, 10000)
    finish_upcharge = round_half_up_div(margined * FINISH_BPS[finish_code], 10000)
    line_delta = margined + finish_upcharge
    tax = round_half_up_div(line_delta * shop["tax_rate_bps"], 10000)
    return line_delta + tax


# --------------------------------------------------------------------------
# draw_amount (PRD §3.8): waterfall capped at remaining billable.
# --------------------------------------------------------------------------
def draw_amount(project, draw_type, requested_pct_bps, billed_to_date):
    shop = store.shops[project["shop_id"]]
    contract = project["contract_total_cents"]
    remaining_billable = contract - billed_to_date
    if draw_type == "DEPOSIT":
        raw = round_half_up_div(contract * shop["deposit_pct_bps"], 10000)
    elif draw_type == "PROGRESS":
        raw = round_half_up_div(contract * (requested_pct_bps or 0), 10000)
    elif draw_type == "RETAINAGE":
        raw = round_half_up_div(contract * shop["retainage_pct_bps"], 10000)
    else:
        raw = 0
    amount = min(raw, remaining_billable)
    if amount < 0:
        amount = 0
    return amount


# --------------------------------------------------------------------------
# draw_settlement (PRD §3.8): late fee tiering.
# --------------------------------------------------------------------------
def draw_settlement(draw, shop):
    """Returns late_fee_cents for an issued draw being paid."""
    due = draw.get("due_utc")
    current = shop.get("current_utc")
    from helpers import parse_stored_dt
    due_dt = parse_stored_dt(due)
    current_dt = parse_stored_dt(current)

    if due_dt is None or current_dt is None or current_dt <= due_dt:
        days_late = 0
    else:
        elapsed = (current_dt - due_dt).total_seconds()
        days_late = math.floor(elapsed / 86400)

    if days_late <= 0:
        rate_bps = 0
    elif days_late <= 30:
        rate_bps = LATE_TIER1_BPS
    else:
        rate_bps = LATE_TIER2_BPS

    late_fee = round_half_up_div(draw["amount_cents"] * rate_bps, 10000)
    return late_fee
