"""Calculation rules per SCAFFOLD Table 3. Money is integer cents; Decimal used
for fractional intermediate steps with ROUND_HALF_UP."""

from decimal import Decimal, ROUND_HALF_UP

import db
from services.core import touch

# Constants
LABOR_RATE_CENTS = 8500
COMMITTED_RENTAL_MONTHS_DEFAULT = 6
RAIL_COST_PER_M_CENTS = 22000
CURVED_MULTIPLIER = Decimal("1.35")
OUTDOOR_SEALING_CENTS = 45000

CONDITION_FACTOR = {
    "REFURB_A": Decimal("0.85"),
    "REFURB_B": Decimal("0.65"),
    "REFURB_C": Decimal("0.35"),
    "RETIRED": Decimal("0.0"),
}
REGION_DEMAND_FACTOR = {
    "NORTH": Decimal("1.10"),
    "SOUTH": Decimal("0.95"),
    "EAST": Decimal("1.00"),
    "WEST": Decimal("1.05"),
}
USEFUL_LIFE_MONTHS = 120
MARKET_YEARLY_RETENTION = Decimal("0.85")

TIER_BASE_CENTS = {"BASIC": 2900, "STANDARD": 4900, "PREMIUM": 7900}
TIER_CAP_CENTS = {"BASIC": 50000, "STANDARD": 150000, "PREMIUM": 400000}

TIER_COVERAGE = {
    "BASIC": {"MECHANICAL", "ELECTRICAL"},
    "STANDARD": {"MECHANICAL", "ELECTRICAL", "WEAR_AND_TEAR"},
    "PREMIUM": {"MECHANICAL", "ELECTRICAL", "STRUCTURAL", "WEAR_AND_TEAR"},
}


def _round_cents(dec_value):
    return int(dec_value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def valid_rail_length_m(stair_rise_mm, stair_run_mm):
    """Pythagorean rail length; metres; round_half_up to 2dp."""
    rise = Decimal(stair_rise_mm) / Decimal(1000)
    run = Decimal(stair_run_mm) / Decimal(1000)
    sq = rise * rise + run * run
    # Decimal sqrt
    length = sq.sqrt()
    return float(length.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def provisional_quote_total(product_model, acquisition_mode):
    labor = product_model["install_labor_hours"] * LABOR_RATE_CENTS
    if acquisition_mode == "PURCHASE":
        return product_model["base_purchase_price_cents"] + labor
    else:  # RENTAL
        return (product_model["monthly_rental_rate_cents"]
                * COMMITTED_RENTAL_MONTHS_DEFAULT) + labor


def issued_quote_total(quote, assessment, product_model,
                       rail_length_m=None, labor_hours=None):
    """Actuals-based issued price. Optionally override rail length / labor for
    the reconciliation variant after install completion."""
    rail_m = rail_length_m if rail_length_m is not None else quote["valid_rail_length_m"]
    hours = labor_hours if labor_hours is not None else product_model["install_labor_hours"]

    rail_cost = Decimal(str(rail_m)) * Decimal(RAIL_COST_PER_M_CENTS)
    rail_cost_cents = _round_cents(rail_cost)
    if assessment["staircase_kind"] == "CURVED":
        rail_cost_cents = _round_cents(Decimal(rail_cost_cents) * CURVED_MULTIPLIER)
    if assessment.get("has_outdoor_exposure"):
        rail_cost_cents = rail_cost_cents + OUTDOOR_SEALING_CENTS

    if quote["acquisition_mode"] == "PURCHASE":
        base = product_model["base_purchase_price_cents"]
    else:
        base = (product_model["monthly_rental_rate_cents"]
                * COMMITTED_RENTAL_MONTHS_DEFAULT)
    return base + rail_cost_cents + hours * LABOR_RATE_CENTS


def funding_waterfall(agreement):
    """Recompute funding_applied_cents; auto-transition PENDING_FUNDING->FUNDED
    when threshold reached. Returns True if a transition to FUNDED occurred."""
    quote_id = agreement["quote_id"]
    eligible = [
        fa for fa in db.funding_applications.values()
        if fa["quote_id"] == quote_id and fa["status"] in ("APPROVED", "PARTIALLY_APPROVED")
    ]
    eligible.sort(key=lambda fa: (fa["priority_rank"], fa["created_at"]))
    remaining = agreement["list_price_cents"]
    applied = 0
    for fa in eligible:
        allocation = min(fa["approved_cents"], remaining)
        applied += allocation
        remaining -= allocation
        if remaining == 0:
            break
    transitioned = False
    if agreement.get("funding_applied_cents") != applied:
        agreement["funding_applied_cents"] = applied
        touch(agreement)
    if applied >= agreement["list_price_cents"] and agreement["status"] == "PENDING_FUNDING":
        agreement["status"] = "FUNDED"
        touch(agreement)
        transitioned = True
    return transitioned


def buyback_offer(agreement, customer, product_model, months_installed,
                  condition_grade):
    base = Decimal(product_model["base_purchase_price_cents"])
    cond = CONDITION_FACTOR[condition_grade]
    if agreement["mode"] == "RENTAL":
        frac = Decimal(months_installed) / Decimal(USEFUL_LIFE_MONTHS)
        keep = Decimal(1) - frac
        if keep < 0:
            keep = Decimal(0)
        value = base * keep * cond
    else:  # PURCHASE -> market_adjusted
        years = Decimal(months_installed) / Decimal(12)
        retention = MARKET_YEARLY_RETENTION ** years
        region = REGION_DEMAND_FACTOR.get(customer["home_region_code"], Decimal("1.00"))
        value = base * retention * cond * region
    return _round_cents(value)


def service_plan_fee(tier, has_outdoor_exposure, staircase_kind,
                     condition_grade, waiver_signed):
    base_fee = TIER_BASE_CENTS[tier]
    adders = Decimal("0")
    if has_outdoor_exposure:
        adders += Decimal("0.15")
    if staircase_kind == "CURVED":
        adders += Decimal("0.20")
    if condition_grade in ("REFURB_B", "REFURB_C"):
        adders += Decimal("0.10")
    if waiver_signed:
        fee = Decimal(base_fee) * (Decimal(1) + adders) * Decimal("0.85")
    else:
        fee = Decimal(base_fee) * (Decimal(1) + adders)
    return _round_cents(fee)


def whole_months_between(start_iso, end_iso):
    """Whole calendar months between two ISO timestamps (floor by day)."""
    from services.core import parse_iso8601
    start = parse_iso8601(start_iso)
    end = parse_iso8601(end_iso)
    if start is None or end is None:
        return 0
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    if months < 0:
        months = 0
    return months
