"""Loyalty ledger, points math, tier evaluation."""
from decimal import Decimal, ROUND_FLOOR
from clock import iso_now
from db import DB, new_id

TIER_MULT = {
    "BRONZE": Decimal("1.0"),
    "SILVER": Decimal("1.5"),
    "GOLD": Decimal("2.0"),
    "PLATINUM": Decimal("3.0"),
}

TIER_THRESHOLDS = [
    ("PLATINUM", 10000),
    ("GOLD", 2000),
    ("SILVER", 500),
]


def compute_accrual_points(subtotal_cents: int, tier: str) -> int:
    """base_points = floor(subtotal_cents / 100)
    points = floor(base_points * tier_mult)"""
    base = subtotal_cents // 100
    mult = TIER_MULT[tier]
    prod = Decimal(base) * mult
    return int(prod.to_integral_value(rounding=ROUND_FLOOR))


def compute_reversal_for_line(line_subtotal_cents: int, tier: str) -> int:
    """Reversal magnitude for a warranty-approve on a delivered line:
    base_points = floor(line_subtotal_cents/100); result = floor(base * tier_mult)."""
    base = line_subtotal_cents // 100
    mult = TIER_MULT[tier]
    prod = Decimal(base) * mult
    return int(prod.to_integral_value(rounding=ROUND_FLOOR))


def append_ledger(customer_id: str, order_id, reason: str, delta_points: int) -> dict:
    """Append a LoyaltyLedger row. Reduced-fields (id + created_at)."""
    row = {
        "id": new_id(),
        "customer_id": customer_id,
        "order_id": order_id,
        "reason": reason,
        "delta_points": delta_points,
        "recorded_at": iso_now(),
        "created_at": iso_now(),
    }
    DB.loyalty_ledger[row["id"]] = row
    # Update customer balances.
    customer = DB.customers[customer_id]
    customer["points_balance"] = customer.get("points_balance", 0) + delta_points
    if reason in ("ACCRUAL_PROVISIONAL", "ACCRUAL_FINAL_DELTA"):
        customer["lifetime_points_earned"] = customer.get("lifetime_points_earned", 0) + delta_points
        # Re-evaluate tier only when lifetime_points_earned changes.
        _re_evaluate_tier(customer)
    return row


def _re_evaluate_tier(customer: dict):
    lifetime = customer.get("lifetime_points_earned", 0)
    tier = "BRONZE"
    for name, threshold in TIER_THRESHOLDS:
        if lifetime >= threshold:
            tier = name
            break
    customer["loyalty_tier"] = tier
