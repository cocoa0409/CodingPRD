"""Calculation rules (scaffold §1.3 / PRD §3.2–3.4, §3.8–3.9).

All money is integer cents. round_half_up applied exactly at each calc's named
rounding point, using Decimal so half-up means "away from zero to next cent".
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

# ---- service line constants (PRD §3.2 — "fixed service rate for that line type")
# Per-unit service rates snapshotted onto non-TIRE lines at creation.
SERVICE_RATE_CENTS = {
    "MOUNT_BALANCE": 2500,
    "ROTATION": 1500,
    "TPMS_SERVICE": 1000,
    "ALIGNMENT": 8000,
}

# ---- pricing constants ------------------------------------------------------
TAX_RATE = Decimal("0.0825")

DISPOSAL_FEE_T1_CENTS = 350
DISPOSAL_FEE_T2_CENTS = 250
DISPOSAL_FEE_T3_CENTS = 150

ROAD_HAZARD_PCT = Decimal("0.12")
ROAD_HAZARD_FLOOR_PER_TIRE_CENTS = 1200

SPECIAL_ORDER_DEPOSIT_PCT = Decimal("0.25")
SPECIAL_ORDER_MIN_DEPOSIT_CENTS = 2000

WEAR_BAR_THRESHOLD_32NDS = 2


def round_half_up(value: Decimal) -> int:
    """Round a Decimal to the nearest integer cent, half away from zero."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---- disposal_fee_total (scaffold calc; PRD §3.3) ---------------------------


def disposal_fee_total(n: int) -> int:
    """Marginal-by-bracket per-tire disposal fee over n total TIRE units."""
    if n <= 0:
        return 0
    t1 = min(n, 4)
    t2 = max(0, min(n - 4, 4))
    t3 = max(n - 8, 0)
    return (
        t1 * DISPOSAL_FEE_T1_CENTS
        + t2 * DISPOSAL_FEE_T2_CENTS
        + t3 * DISPOSAL_FEE_T3_CENTS
    )


# ---- road_hazard_premium (scaffold calc; PRD §3.4) --------------------------


def road_hazard_premium(extended_cents: int, quantity: int) -> int:
    """max(round_half_up(extended * 12%), quantity * 1200)."""
    pct_premium = round_half_up(Decimal(extended_cents) * ROAD_HAZARD_PCT)
    floor_premium = quantity * ROAD_HAZARD_FLOOR_PER_TIRE_CENTS
    return max(pct_premium, floor_premium)


# ---- special_order_deposit (scaffold calc; PRD §3.8) ------------------------


def special_order_deposit(unit_price_cents: int, requested_quantity: int) -> int:
    """max(round_half_up(goods_value * 25%), 2000)."""
    goods_value = unit_price_cents * requested_quantity
    pct_deposit = round_half_up(Decimal(goods_value) * SPECIAL_ORDER_DEPOSIT_PCT)
    return max(pct_deposit, SPECIAL_ORDER_MIN_DEPOSIT_CENTS)


# ---- mileage_proration (scaffold calc; PRD §3.9 — mileage-based VARIANT A) ---


def mileage_proration(
    orig_price_cents: int, warranty_miles: int, miles_driven: int, claim_quantity: int
) -> int:
    """SYSTEM-SELECTED mileage-based variant.

    remaining_frac = 1 - miles_driven/warranty_miles
    per_tire       = round_half_up(orig_price * remaining_frac)
    prorated       = per_tire * claim_quantity   (round per-tire THEN multiply)
    """
    used_fraction = Decimal(miles_driven) / Decimal(warranty_miles)
    remaining_frac = Decimal(1) - used_fraction
    per_tire = round_half_up(Decimal(orig_price_cents) * remaining_frac)
    return per_tire * claim_quantity


# ---- work_order_pricing (scaffold calc; PRD §3.2) ---------------------------


def work_order_pricing(lines, tire_models, requested_credit, customer_balance):
    """Compute every money field for a work order at approval.

    `lines` is the list of non-VOID WorkOrderLine dicts of the order.
    Returns a dict of computed fields plus the clamped applied_credit.
    Mutates each line's extended_cents (Step 1).
    """
    # Step 1 — per-line extension (exact integer cents).
    for line in lines:
        line["extended_cents"] = (
            line["unit_price_cents_snapshot"] * line["quantity"]
        )

    # Step 2 — subtotals by line_type bucket.
    parts_subtotal_cents = sum(
        l["extended_cents"] for l in lines if l["line_type"] == "TIRE"
    )
    service_types = {"MOUNT_BALANCE", "ROTATION", "TPMS_SERVICE", "ALIGNMENT"}
    service_subtotal_cents = sum(
        l["extended_cents"] for l in lines if l["line_type"] in service_types
    )

    # Step 3 — disposal fee (depends on total TIRE quantity).
    total_tire_qty = sum(
        l["quantity"] for l in lines if l["line_type"] == "TIRE"
    )
    disposal_fee_cents = disposal_fee_total(total_tire_qty)

    # Step 4 — road-hazard premium (sum over opted TIRE lines).
    road_hazard_premium_cents = 0
    for l in lines:
        if l["line_type"] == "TIRE" and l.get("road_hazard_opted"):
            road_hazard_premium_cents += road_hazard_premium(
                l["extended_cents"], l["quantity"]
            )

    # Step 5 — tax on parts + service only (single rounding).
    taxable_base = parts_subtotal_cents + service_subtotal_cents
    tax_cents = round_half_up(Decimal(taxable_base) * TAX_RATE)

    # Step 6 — pre-credit grand total, then store-credit clamp.
    pre_credit_total = (
        parts_subtotal_cents
        + service_subtotal_cents
        + disposal_fee_cents
        + road_hazard_premium_cents
        + tax_cents
    )
    applied_credit = min(requested_credit, customer_balance, pre_credit_total)
    total_due_cents = pre_credit_total - applied_credit

    return {
        "parts_subtotal_cents": parts_subtotal_cents,
        "service_subtotal_cents": service_subtotal_cents,
        "disposal_fee_cents": disposal_fee_cents,
        "road_hazard_premium_cents": road_hazard_premium_cents,
        "tax_cents": tax_cents,
        "total_due_cents": total_due_cents,
        "applied_credit": applied_credit,
    }
