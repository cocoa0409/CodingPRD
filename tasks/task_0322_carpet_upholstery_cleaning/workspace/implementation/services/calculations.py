"""Pricing & wallet calculations (PRD §3.2, §3.4, §3.5; scaffold §1.3).

All money in integer cents; round half up at each PINNED step (PRD §2.7).
Decimal is used for every multiply-by-fraction step; never float.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Dict, List, Optional

from services.common import round_half_up

# Soiling multipliers (PRD §3.2): LIGHT 1.0, MODERATE 1.25, HEAVY 1.6
SOIL_MULT = {
    "LIGHT": Decimal("1.0"),
    "MODERATE": Decimal("1.25"),
    "HEAVY": Decimal("1.6"),
}

# Recurring discount percentages keyed on cadence (PRD §3.1):
# MONTHLY 15%, QUARTERLY 10%, SEMIANNUAL 5%.
RECUR_DISCOUNT_PCT = {
    "MONTHLY": Decimal("0.15"),
    "QUARTERLY": Decimal("0.10"),
    "SEMIANNUAL": Decimal("0.05"),
}

# settled_price escalation (PRD §3.4): >= 3 HEAVY rooms -> +4000 cents.
HEAVY_ESCALATION_COUNT = 3
HEAVY_ESCALATION_CENTS = 4000

# Guarantee constants (PRD §3.5):
GUARANTEE_WINDOW_FACTOR = 2
GUARANTEE_GOODWILL_CENTS = 2000


def _room_base_cents(catalog: Dict, room: Dict) -> int:
    """Per-room base line, rounded half up to whole cents BEFORE summing.

    base_rate_cents_per_sqft * area_sqft * SOIL_MULT[soiling_level].
    """
    base = Decimal(catalog["base_rate_cents_per_sqft"]) * Decimal(room["area_sqft"]) * SOIL_MULT[room["soiling_level"]]
    return round_half_up(base)


def _discount_amount(pre_discount_cents: int, recurring_plan_id, plan: Optional[Dict]) -> int:
    """Recurring discount on the pre-discount total, rounded half up ONCE.

    disc_pct selected from the plan's cadence when a recurring_plan_id is set,
    else 0 (a one-off job earns no discount). The plan need not be ACTIVE — the
    discount is keyed purely on cadence per PRD §3.2/§3.4.
    """
    if not recurring_plan_id or plan is None:
        return 0
    pct = RECUR_DISCOUNT_PCT.get(plan["cadence"], Decimal("0"))
    if pct == 0:
        return 0
    return round_half_up(Decimal(pre_discount_cents) * pct)


def compute_quoted_price(catalog: Dict, job: Dict, rooms: List[Dict], addons: List[Dict],
                         plan: Optional[Dict]) -> int:
    """Forward-looking quote (PRD §3.2). Prices every room and add-on currently
    attached, in a pinned order. Frozen on quote; never recomputed.

    step 1  rooms_subtotal = sum of per-room base (each rounded first)
    step 2  addons_subtotal = sum of each add-on's frozen line_price_cents
    step 3  furn = catalog.move_furniture_flat_cents if job.move_furniture else 0
    step 4  pre_discount = rooms_subtotal + addons_subtotal + furn
    step 5  discount on pre_discount (cadence pct, else 0), rounded once
    step 6  quoted_price_cents = pre_discount - discount
    """
    rooms_subtotal = sum(_room_base_cents(catalog, r) for r in rooms)
    addons_subtotal = sum(a["line_price_cents"] for a in addons)
    furn = catalog["move_furniture_flat_cents"] if job.get("move_furniture") else 0
    pre_discount = rooms_subtotal + addons_subtotal + furn
    discount = _discount_amount(pre_discount, job.get("recurring_plan_id"), plan)
    return pre_discount - discount


def compute_settled_price(catalog: Dict, job: Dict, rooms_chrono: List[Dict],
                          addons_chrono: List[Dict], plan: Optional[Dict]) -> int:
    """Chronological settled price (PRD §3.4). Replays rooms and add-ons in
    created_at ASC order at invoice time; differs from the quote in exactly one
    respect — the heavy-soiling escalation surcharge.

    step 1  rooms_subtotal exactly as quote (round-then-sum), iterating in
            created_at ASC, counting HEAVY rooms as it goes.
    step 2  addons_subtotal in created_at ASC.
    step 3  furn = catalog.move_furniture_flat_cents if move_furniture else 0
    step 4  escalation = 4000 if heavy_rooms >= 3 else 0
    step 5  pre_discount = rooms + addons + furn + escalation
    step 6  same recurring discount as quote (rounded once)
    step 7  settled_price_cents = pre_discount - discount
    """
    rooms_subtotal = 0
    heavy_rooms = 0
    for r in rooms_chrono:
        rooms_subtotal += _room_base_cents(catalog, r)
        if r["soiling_level"] == "HEAVY":
            heavy_rooms += 1
    addons_subtotal = sum(a["line_price_cents"] for a in addons_chrono)
    furn = catalog["move_furniture_flat_cents"] if job.get("move_furniture") else 0
    escalation = HEAVY_ESCALATION_CENTS if heavy_rooms >= HEAVY_ESCALATION_COUNT else 0
    pre_discount = rooms_subtotal + addons_subtotal + furn + escalation
    discount = _discount_amount(pre_discount, job.get("recurring_plan_id"), plan)
    return pre_discount - discount


def compute_addon_line_price(addon_type: str, catalog: Dict, job_total_sqft: int) -> int:
    """AddOn line price (PRD §3.2 / scaffold addon_line_price).

    STAIN      -> catalog.stain_addon_cents
    PET        -> catalog.pet_addon_cents
    PROTECTANT -> round_half_up(catalog.protectant_cents_per_sqft * job.total_sqft)

    A PROTECTANT created before any room (total_sqft == 0) freezes 0 — not
    retroactively fixed.
    """
    if addon_type == "STAIN":
        return catalog["stain_addon_cents"]
    if addon_type == "PET":
        return catalog["pet_addon_cents"]
    # PROTECTANT
    return round_half_up(Decimal(catalog["protectant_cents_per_sqft"]) * Decimal(job_total_sqft))


def guarantee_window_minutes(origin_catalog: Dict) -> int:
    """window = origin_catalog.dry_time_minutes * GUARANTEE_WINDOW_FACTOR (PRD §3.5)."""
    return origin_catalog["dry_time_minutes"] * GUARANTEE_WINDOW_FACTOR


def guarantee_eligible(filed_at_minute: int, origin_completed_at_minute: int,
                       origin_catalog: Dict) -> bool:
    """Eligible iff (filed - completed) <= window, boundary inclusive (PRD §3.5)."""
    window = guarantee_window_minutes(origin_catalog)
    return (filed_at_minute - origin_completed_at_minute) <= window
