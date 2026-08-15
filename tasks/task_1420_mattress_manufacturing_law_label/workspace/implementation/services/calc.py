"""Calculation rules (SCAFFOLD Table 3 / PRD section 3)."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import clock
import db

# cure_eligibility_time constants
BASE_CURE_HOURS = {"STANDARD": 24, "HIGH_DENSITY": 48, "MEMORY": 72}
COOL_TIER_MAX_C = 18
WARM_TIER_MIN_C = 27
COOL_ADJUST_HOURS = 12
WARM_ADJUST_HOURS = -6
RECURE_PENALTY_HOURS = 12
CHAMBER_CAPACITY = 3

# order_compliance_fee constants
TIER1_MAX_CENTS = 100000
TIER2_MAX_CENTS = 500000
FEE_TIER1_CENTS = 500
FEE_TIER2_CENTS = 1500
FEE_TIER3_CENTS = 3000

# warranty_credit_amount constants
FULL_REPLACEMENT_MONTHS = 12
TERM_MONTHS = 120
MIN_CREDIT_PCT = Decimal("0.10")

# recycling_credit constants
PROVISIONAL_RATE_CENTS_PER_KG = 20
RATE_STEEL = 25
RATE_FOAM = 40
RATE_FIBER = 15
RATE_WOOD = 5

# returns
COMFORT_WINDOW_DAYS = 100


def round_half_up_cents(x):
    """Round a Decimal/exact value to integer cents, half up."""
    return int(Decimal(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dec(v):
    return Decimal(str(v))


def cure_adjust_hours(ambient_temp_c):
    t = dec(ambient_temp_c)
    if t < COOL_TIER_MAX_C:
        return COOL_ADJUST_HOURS
    if t <= WARM_TIER_MIN_C:
        return 0
    return WARM_ADJUST_HOURS


def compute_cure_eligible_at(cure_started_at, foam_density_class, ambient_temp_c):
    total_hours = BASE_CURE_HOURS[foam_density_class] + cure_adjust_hours(ambient_temp_c)
    return cure_started_at + timedelta(hours=total_hours)


def bom_line_cost(quantity_per_unit, unit_cost_cents):
    return round_half_up_cents(dec(quantity_per_unit) * dec(unit_cost_cents))


def recompute_bom_cost(model):
    total = 0
    for line in db.bom_lines.values():
        if line["model_id"] == model["id"]:
            total += line["line_cost_cents"]
    model["bom_cost_cents"] = total


def order_pricing(quantity, unit_price_cents):
    subtotal = quantity * unit_price_cents
    if subtotal < TIER1_MAX_CENTS:
        fee = FEE_TIER1_CENTS
    elif subtotal < TIER2_MAX_CENTS:
        fee = FEE_TIER2_CENTS
    else:
        fee = FEE_TIER3_CENTS
    return subtotal, fee, subtotal + fee


def warranty_credit(delivered_at, purchase_price_cents, approved_at):
    age_seconds = (approved_at - delivered_at).total_seconds()
    age_months = int(age_seconds // (30 * 86400))
    price = purchase_price_cents
    if age_months <= FULL_REPLACEMENT_MONTHS:
        return age_months, "FULL_REPLACEMENT", price
    linear = round_half_up_cents(dec(price) * dec(TERM_MONTHS - age_months) / dec(TERM_MONTHS))
    floor_amt = round_half_up_cents(dec(price) * MIN_CREDIT_PCT)
    credit = max(floor_amt, min(price, linear))
    return age_months, "PRORATED", credit


def recycling_provisional(declared_weight_kg):
    return round_half_up_cents(dec(declared_weight_kg) * dec(PROVISIONAL_RATE_CENTS_PER_KG))


def recycling_final(steel_kg, foam_kg, fiber_kg, wood_kg):
    return (
        round_half_up_cents(dec(steel_kg) * dec(RATE_STEEL))
        + round_half_up_cents(dec(foam_kg) * dec(RATE_FOAM))
        + round_half_up_cents(dec(fiber_kg) * dec(RATE_FIBER))
        + round_half_up_cents(dec(wood_kg) * dec(RATE_WOOD))
    )


def fulfillment_recompute(order):
    """Recompute the parallel fulfillment dimension. Returns True when the
    status actually changed (a real mutation of the order)."""
    units = [u for u in db.units.values() if u["order_id"] == order["id"]]
    shipped = sum(1 for u in units if u["status"] in ("SHIPPED", "DELIVERED"))
    delivered = sum(1 for u in units if u["status"] == "DELIVERED")
    qty = order["quantity"]
    if delivered == qty:
        status = "DELIVERED"
    elif shipped == qty:
        status = "FULLY_SHIPPED"
    elif shipped > 0:
        status = "PARTIALLY_SHIPPED"
    else:
        status = "UNFULFILLED"
    changed = order["fulfillment_status"] != status
    order["fulfillment_status"] = status
    return changed


def chamber_over_capacity(batch, new_start, new_end, now):
    """Reject iff 3+ OTHER CURING batches on the same chamber overlap the new window
    (the new batch may become the 3rd concurrent occupant, never the 4th).
    Touching endpoints do NOT overlap."""
    occupants = 0
    for other in db.foam_batches.values():
        if other["id"] == batch["id"]:
            continue
        if other["chamber_id"] != batch["chamber_id"]:
            continue
        if other["status"] != "CURING":
            continue
        a_start = clock.iso_parse(other["cure_started_at"])
        a_end = clock.iso_parse(other["cure_eligible_at"])
        if a_start < new_end and new_start < a_end:
            occupants += 1
    return occupants >= CHAMBER_CAPACITY


def quilt_machine_conflict(machine_id, new_start, new_end, exclude_id=None):
    for run in db.quilt_runs.values():
        if exclude_id is not None and run["id"] == exclude_id:
            continue
        if run["machine_id"] != machine_id:
            continue
        if run["status"] not in ("SCHEDULED", "RUNNING"):
            continue
        e_start = clock.iso_parse(run["start_at"])
        e_end = clock.iso_parse(run["end_at"])
        if e_start < new_end and new_start < e_end:
            return True
    return False
