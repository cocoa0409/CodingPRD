"""Business calculations: pricing engine, trim optimization, capacity/balance/exposure rollups.

All monetary values use Decimal with ROUND_HALF_UP at each pinned precision step.
"""
from decimal import Decimal

from db import db
from util import D, round2, round4, utcnow_iso


# =============================================================================
# Common fields
# =============================================================================

def bump(entity):
    """Refresh updated_at and increment version on every mutation."""
    entity["updated_at"] = utcnow_iso()
    entity["version"] = entity.get("version", 1) + 1


# =============================================================================
# Pricing engine (PROVISIONAL and FINAL variants)
# =============================================================================

COLOR_SURCHARGE_PER_MSF = Decimal("1.50")
DIE_CUT_ROUTING_MULT = Decimal("1.12")
SLOTTED_ROUTING_MULT = Decimal("1.00")

LOCAL_MAX_MILES = Decimal("150.00")
REGIONAL_MAX_MILES = Decimal("400.00")
TIER_RATE_LOCAL = Decimal("18.00")
TIER_RATE_REGIONAL = Decimal("32.00")
TIER_RATE_NATIONAL = Decimal("47.00")

TIER1_MIN = Decimal("5000.00")
TIER2_MIN = Decimal("20000.00")
TIER1_PCT = Decimal("0.02")
TIER2_PCT = Decimal("0.04")
ZERO_PCT = Decimal("0.00")

FREIGHT_REIMB_CAP = Decimal("500.00")


def compute_area_sqft_per_box(blank_width_in, blank_length_in):
    """round(blank_width_in * blank_length_in / 144, 4) half-up"""
    return round4(D(blank_width_in) * D(blank_length_in) / Decimal(144))


def freight_tier_for(distance_miles):
    d = D(distance_miles)
    if d <= LOCAL_MAX_MILES:
        return "LOCAL"
    if d <= REGIONAL_MAX_MILES:
        return "REGIONAL"
    return "NATIONAL"


TIER_RATE = {
    "LOCAL": TIER_RATE_LOCAL,
    "REGIONAL": TIER_RATE_REGIONAL,
    "NATIONAL": TIER_RATE_NATIONAL,
}


def compute_pricing(order, customer, qty, unit_price_per_msf):
    """Compute the full pricing chain (PROVISIONAL or FINAL) for an order.

    Returns a dict with keys:
      billable_msf (4dp), freight_tier (str), merchandise_total_dollars (2dp),
      discount_pct (as Decimal 0/0.02/0.04), discount_dollars (2dp),
      freight_charge_dollars (2dp), grand_total_dollars (2dp)
    """
    area = order["area_sqft_per_box"]  # already 4dp Decimal
    billable_msf = round4(D(qty) * area / Decimal(1000))

    color_count = int(order.get("color_count", 0))
    rate_per_msf = D(unit_price_per_msf) + COLOR_SURCHARGE_PER_MSF * color_count

    routing_mult = DIE_CUT_ROUTING_MULT if order["routing_type"] == "DIE_CUT" else SLOTTED_ROUTING_MULT

    merchandise_total = round2(billable_msf * rate_per_msf * routing_mult)

    tier = freight_tier_for(customer["distance_miles_from_plant"])
    freight_charge = round2(billable_msf * TIER_RATE[tier])

    # Volume discount keyed on merchandise_total only
    if merchandise_total < TIER1_MIN:
        discount_pct = ZERO_PCT
    elif merchandise_total < TIER2_MIN:
        discount_pct = TIER1_PCT
    else:
        discount_pct = TIER2_PCT
    discount_dollars = round2(merchandise_total * discount_pct)

    grand_total = merchandise_total - discount_dollars + freight_charge

    return {
        "billable_msf": billable_msf,
        "freight_tier": tier,
        "merchandise_total_dollars": merchandise_total,
        "discount_pct": discount_pct,
        "discount_dollars": discount_dollars,
        "freight_charge_dollars": freight_charge,
        "grand_total_dollars": grand_total,
    }


# =============================================================================
# Trim optimization
# =============================================================================

def recompute_run_trim(run):
    """Recompute consumed_width_in, trim_waste_in, trim_waste_pct from attached orders.

    Attached = orders with corrugator_run_id == run.id AND status == SCHEDULED.
    """
    consumed = Decimal("0")
    outs_map = db.run_outs.get(run["id"], {})
    for order_id, outs in outs_map.items():
        order = db.box_orders.get(order_id)
        if order is None:
            continue
        if order.get("corrugator_run_id") != run["id"]:
            continue
        if order.get("status") != "SCHEDULED":
            continue
        consumed += D(outs) * D(order["blank_width_in"])
    run["consumed_width_in"] = consumed
    web = D(run["web_width_in"])
    trim_waste = web - consumed
    run["trim_waste_in"] = trim_waste
    if web != 0:
        run["trim_waste_pct"] = round2(Decimal(100) * trim_waste / web)
    else:
        run["trim_waste_pct"] = Decimal("0")


# =============================================================================
# Shift capacity rollup
# =============================================================================

def recompute_shift_rollup(shift):
    """Recompute scheduled_minutes / available_minutes on a WorkShift."""
    total = 0
    for r in db.corrugator_runs.values():
        if r["work_shift_id"] != shift["id"]:
            continue
        if r["status"] in ("SCHEDULED", "COMPLETED"):
            total += (r["end_minute"] - r["start_minute"])
    for b in db.converting_bookings.values():
        if b["work_shift_id"] != shift["id"]:
            continue
        if b["status"] in ("QUEUED", "RUNNING", "COMPLETED"):
            total += (b["end_minute"] - b["start_minute"])
    shift["scheduled_minutes"] = total
    shift["available_minutes"] = shift["capacity_minutes"] - total


# =============================================================================
# Inventory program balance rollup
# =============================================================================

def recompute_program_balance(program):
    """committed_qty = sum of qty over PENDING or APPROVED releases."""
    committed = 0
    for r in db.release_orders.values():
        if r["program_id"] != program["id"]:
            continue
        if r["status"] in ("PENDING", "APPROVED"):
            committed += r["qty"]
    program["committed_qty"] = committed
    program["available_qty"] = program["on_hand_qty"] - committed


# =============================================================================
# Credit exposure rollup
# =============================================================================

EXPOSURE_STATUSES = {
    "ACCEPTED", "SCHEDULED", "AWAITING_CONVERTING",
    "DIE_CUT_QUEUED", "SLOTTED_QUEUED", "CONVERTING", "PRODUCED",
}


def recompute_credit_exposure(customer):
    """Sum committed_value_dollars over the customer's pipeline-state orders."""
    total = Decimal("0.00")
    for o in db.box_orders.values():
        if o["customer_id"] != customer["id"]:
            continue
        if o["status"] in EXPOSURE_STATUSES:
            cv = o.get("committed_value_dollars")
            if cv is not None:
                total += D(cv)
    customer["credit_exposure_dollars"] = round2(total)


# =============================================================================
# Reorder threshold check (boundary-sensitive)
# =============================================================================

def reorder_threshold_check(program):
    """Apply the reorder_threshold_check after on_hand_qty changes.

    If status == ACTIVE and on_hand_qty <= reorder_point:
        -> REPLENISHMENT_NEEDED + auto-create replenishment DRAFT BoxOrder.
    If status == REPLENISHMENT_NEEDED and on_hand_qty > reorder_point (strictly):
        -> ACTIVE.
    Boundary: == reorder_point flips into REPLENISHMENT_NEEDED but not back.
    Returns True if a replenishment order was auto-created (caller may need to know).
    """
    from services.cascade import create_replenishment_order  # deferred to avoid circular import
    flipped = False
    if program["status"] == "ACTIVE" and program["on_hand_qty"] <= program["reorder_point"]:
        program["status"] = "REPLENISHMENT_NEEDED"
        create_replenishment_order(program)
        flipped = True
    elif program["status"] == "REPLENISHMENT_NEEDED" and program["on_hand_qty"] > program["reorder_point"]:
        program["status"] = "ACTIVE"
    return flipped
