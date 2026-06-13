"""Calculation rules (§1.3 / PRD §3.5, §3.9, §3.10, §3.11, §3.13).

All money is integer cents. Rate steps use round-half-up; capacity uses floor.
"""
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR


def round_half_up(value):
    """Round a numeric value to the nearest whole cent, half rounds up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --- pricing -------------------------------------------------------------

PEAK_FLAT_CENTS = 2500
PEAK_MID_RATE = Decimal("0.10")
PEAK_HIGH_RATE = Decimal("0.15")
PEAK_MID_TIER_FLOOR_CENTS = 20000
PEAK_HIGH_TIER_FLOOR_CENTS = 50000


def compute_pricing(lines, product, production_day):
    """Run the pinned estimate/final pipeline. Returns (total_cents, peak_surcharge_cents).

    lines: list of OrderLineCustomization dicts.
    product: ProductCatalogItem dict.
    production_day: ProductionDay dict.
    """
    base_price = product["base_price_cents"]
    lines_subtotal = 0
    for line in lines:
        lines_subtotal += line["units"] * base_price + line["line_surcharge_cents"]

    if production_day.get("is_peak"):
        if lines_subtotal < PEAK_MID_TIER_FLOOR_CENTS:
            peak_surcharge = PEAK_FLAT_CENTS
        elif lines_subtotal < PEAK_HIGH_TIER_FLOOR_CENTS:
            peak_surcharge = round_half_up(Decimal(lines_subtotal) * PEAK_MID_RATE)
        else:
            peak_surcharge = round_half_up(Decimal(lines_subtotal) * PEAK_HIGH_RATE)
    else:
        peak_surcharge = 0

    total = lines_subtotal + peak_surcharge
    return total, peak_surcharge


# --- deposit -------------------------------------------------------------

DEPOSIT_FLOOR_CENTS = 5000
STANDARD_RATIO = Decimal("0.30")
PEAK_RATIO = Decimal("0.50")
COMPLEX_RATIO = Decimal("0.60")


def compute_deposit(estimate_total_cents, production_day, product):
    base_ratio = STANDARD_RATIO
    if production_day.get("is_peak"):
        base_ratio = PEAK_RATIO
    if product["tier_levels"] >= 3:
        base_ratio = max(base_ratio, COMPLEX_RATIO)

    raw = Decimal(estimate_total_cents) * base_ratio
    deposit = round_half_up(raw)
    # floor at DEPOSIT_FLOOR_CENTS but never above the total
    deposit = min(max(deposit, DEPOSIT_FLOOR_CENTS), estimate_total_cents)
    return deposit


# --- line surcharge ------------------------------------------------------

def compute_line_surcharge(units, selected_option_codes, option_by_code):
    """sum(surcharge_cents over selected options) * units."""
    per_unit = sum(option_by_code[c]["surcharge_cents"] for c in selected_option_codes)
    return per_unit * units


def compute_effective_allergens(product, selected_option_codes, option_by_code):
    """union of product declared allergens and every selected option's introduced allergens."""
    allergens = list(product.get("declared_allergen_codes") or [])
    for c in selected_option_codes:
        for a in (option_by_code[c].get("introduces_allergen_codes") or []):
            if a not in allergens:
                allergens.append(a)
    # add product allergens (already in list) — ensure de-dup while preserving order
    out = []
    for a in allergens:
        if a not in out:
            out.append(a)
    return out


# --- balance capture (waterfall) ----------------------------------------

def compute_balance_capture(balance_due_cents, applied_credit_cents, store_credit_cents):
    """Returns (credit_applied_cents, fresh_tender). Caller validates bounds first."""
    gross_balance = balance_due_cents
    credit_applied = min(applied_credit_cents, store_credit_cents, gross_balance)
    fresh_tender = gross_balance - credit_applied
    return credit_applied, fresh_tender


# --- refund settlement ---------------------------------------------------

def compute_refund(captured_cents, production_status_at_cancel, deposit_due_cents):
    """How much captured tender returns to store credit, by cancel state."""
    if production_status_at_cancel == "QUOTED":
        return captured_cents
    if production_status_at_cancel in ("PROOF_PENDING", "CHANGES_REQUESTED"):
        return captured_cents
    if production_status_at_cancel == "PROOF_APPROVED":
        return max(0, captured_cents - deposit_due_cents)
    return 0


# --- capacity ------------------------------------------------------------

PEAK_CAPACITY_RATIO = Decimal("0.80")


def effective_capacity(production_day):
    cap = production_day["unit_capacity"]
    if production_day.get("is_peak"):
        cap = int((Decimal(cap) * PEAK_CAPACITY_RATIO).to_integral_value(rounding=ROUND_FLOOR))
    return cap


def capacity_admissible(production_day, order_units):
    eff = effective_capacity(production_day)
    return (production_day["units_committed"] + order_units) <= eff


# --- loyalty -------------------------------------------------------------

def loyalty_tier(lifetime_spend_cents):
    if lifetime_spend_cents >= 150000:
        return "GOLD"
    if lifetime_spend_cents >= 50000:
        return "SILVER"
    return "STANDARD"
