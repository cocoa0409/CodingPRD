"""Business-logic services: calculations, state helpers, and cascades."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from db import CLOCK, DB, _parse_iso, fmt_ts, stamp_new, touch
from errors import (
    ERR_ASSET_WINDOW_OVERLAP,
    ERR_CREDIT_LIMIT_EXCEEDED,
    ERR_PART_OBSOLETE,
    ERR_POOL_UNIT_UNAVAILABLE,
    ERR_QUOTE_EXPIRED,
    ERR_SUBSTITUTION_NOT_ALLOWED,
    ERR_SUBSTITUTION_TARGET_NOT_OBSOLETE,
    ERR_WARRANTY_NOT_ELIGIBLE,
    ERR_WINDOW_CAPACITY_EXCEEDED,
    ERR_WINDOW_FULL,
    ERR_WINDOW_OVERLAP,
    not_found,
    raise_err,
)

QUOTE_VALIDITY_DAYS = 14
WARRANTY_PART_DISCOUNT_PCT = Decimal("0.5")
SURGE_BASE = Decimal("1.25")
SURGE_PRIORITY_ADD = Decimal("0.15")
POOL_PROGRAM_CREDIT = Decimal("0.10")
MULTIPLIER_FLOOR = Decimal("1.0")
MULTIPLIER_CAP = Decimal("1.50")
TOLERANCE_PCT = Decimal("5.00")
SURGE_THRESHOLD_PCT = Decimal("0.8")


def round_half_up_cents(value: Decimal) -> int:
    """Round a Decimal to integer cents, half-up."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Capacity window posture
# ---------------------------------------------------------------------------


def compute_window_posture(window: dict) -> str:
    reserved = window["bay_hours_reserved"]
    capacity = window["bay_hours_capacity"]
    if reserved >= capacity:
        return "FULL"
    surge_threshold = math.ceil(Decimal("0.8") * capacity)
    if reserved >= surge_threshold:
        return "SURGE"
    return "NORMAL"


def recompute_window(window: dict, bump_version: bool = True):
    """Recompute posture after a reserved-hours change."""
    window["window_posture"] = compute_window_posture(window)
    if bump_version:
        touch(window)


# ---------------------------------------------------------------------------
# Customer pool count
# ---------------------------------------------------------------------------


def recompute_pool_available_count(customer_id: str):
    customer = DB.customers.get(customer_id)
    if customer is None:
        return
    count = sum(
        1
        for u in DB.pool_units.values()
        if u["customer_id"] == customer_id and u["pool_status"] in ("IN_POOL", "RESERVED")
    )
    if customer.get("pool_available_count") != count:
        customer["pool_available_count"] = count
        touch(customer)


# ---------------------------------------------------------------------------
# Overlap checks
# ---------------------------------------------------------------------------


def check_window_overlap(window_start: datetime, window_end: datetime):
    """Half-open interval [start, end) overlap; adjacency allowed."""
    for w in DB.capacity_windows.values():
        ws = _parse_iso(w["window_start"])
        we = _parse_iso(w["window_end"])
        if window_start < we and ws < window_end:
            raise_err(ERR_WINDOW_OVERLAP, "Capacity window overlaps an existing window")


def check_asset_window_overlap(asset_id: str, start_date: str, end_date: str, exclude_ro_id: str | None = None):
    """Closed-interval [start, end] overlap among non-terminal ROs of the asset.

    Touching endpoints conflict (closed interval at both ends).
    """
    for ro in DB.repair_orders.values():
        if ro["asset_id"] != asset_id:
            continue
        if ro["id"] == exclude_ro_id:
            continue
        if ro["status"] in ("CLOSED", "CANCELLED"):
            continue
        # closed-interval overlap: start <= other_end AND other_start <= end
        if start_date <= ro["planned_end_date"] and ro["planned_start_date"] <= end_date:
            raise_err(
                ERR_ASSET_WINDOW_OVERLAP,
                "Planned service window overlaps another non-terminal repair order of the same asset",
            )


# ---------------------------------------------------------------------------
# Warranty eligibility
# ---------------------------------------------------------------------------


def evaluate_warranty(parent_id: str, asset_id: str, customer_id: str) -> tuple[bool, dict | None]:
    """Returns (eligible, parent_ro). Raises nothing; caller decides."""
    parent = DB.repair_orders.get(parent_id)
    if parent is None:
        return False, None
    if parent["status"] != "CLOSED":
        return False, parent
    if parent["asset_id"] != asset_id:
        return False, parent
    if parent["customer_id"] != customer_id:
        return False, parent
    customer = DB.customers.get(customer_id)
    terms_days = int(customer["warranty_terms_days"]) if customer else 0
    now = CLOCK.now()
    closed_at = _parse_iso(parent["closed_at"])
    elapsed_seconds = (now - closed_at).total_seconds()
    days = math.floor(elapsed_seconds / 86400)
    if days > terms_days:
        return False, parent
    return True, parent


# ---------------------------------------------------------------------------
# Quote pricing calculations
# ---------------------------------------------------------------------------


def compute_surge_multiplier(ro: dict, window: dict, customer: dict, pricing_variant: str) -> Decimal:
    if pricing_variant == "WARRANTY":
        return Decimal("1.0")
    base = Decimal("1.0")
    posture = window["window_posture"]
    if posture == "FULL":
        raise_err(ERR_WINDOW_FULL, "Referenced capacity window posture is FULL")
    if posture == "SURGE":
        base = SURGE_BASE
    if ro["intake_priority"] == "SURGE":
        base += SURGE_PRIORITY_ADD
    if customer.get("pool_program"):
        base -= POOL_PROGRAM_CREDIT
    if base < MULTIPLIER_FLOOR:
        base = MULTIPLIER_FLOOR
    if base > MULTIPLIER_CAP:
        base = MULTIPLIER_CAP
    return base.quantize(Decimal("0.01"))


def price_quote(ro: dict, window: dict, customer: dict, labor_hours, labor_rate_cents: int, part_lines: list[dict]):
    """Compute pricing_variant, surge multiplier, parts/labor subtotals, total."""
    pricing_variant = "WARRANTY" if ro["warranty_case"] else "COMMERCIAL"
    multiplier = compute_surge_multiplier(ro, window, customer, pricing_variant)

    discount = WARRANTY_PART_DISCOUNT_PCT if pricing_variant == "WARRANTY" else Decimal("0")
    parts_subtotal = 0
    for line in part_lines:
        qty = Decimal(str(line["quantity"]))
        price = Decimal(int(line["unit_price_cents"]))
        line_total = round_half_up_cents(qty * price * (Decimal("1") - discount))
        parts_subtotal += line_total

    if pricing_variant == "WARRANTY":
        labor_cents = 0
    else:
        labor_cents = round_half_up_cents(Decimal(str(labor_hours)) * Decimal(int(labor_rate_cents)))

    pre_surge = parts_subtotal + labor_cents
    total = round_half_up_cents(Decimal(pre_surge) * multiplier)

    return {
        "pricing_variant": pricing_variant,
        "surge_multiplier_applied": float(multiplier),
        "parts_subtotal_cents": parts_subtotal,
        "labor_cents": labor_cents,
        "total_cents": total,
    }


# ---------------------------------------------------------------------------
# Quote lazy expiry
# ---------------------------------------------------------------------------


def apply_lazy_expiry(quote: dict) -> bool:
    """If the quote is ISSUED and clock >= expires_at, transition to EXPIRED.

    Returns True when the quote was (or is) expired by this call — callers then
    raise ERR_QUOTE_EXPIRED for actions. For plain reads, the quote just flips.
    """
    if quote["status"] == "ISSUED" and quote.get("expires_at"):
        now = CLOCK.now()
        expires_at = _parse_iso(quote["expires_at"])
        if now >= expires_at:
            quote["status"] = "EXPIRED"
            touch(quote)
            return True
    return False


# ---------------------------------------------------------------------------
# Repair order cascades
# ---------------------------------------------------------------------------

_RESERVING_STATUSES = {"AUTHORIZED", "IN_REPAIR", "IN_TEST", "READY_FOR_CERT", "COMPLETE"}


def cancel_repair_order(ro: dict):
    """Shared cancellation side effects (used by cancel endpoint + quote decline)."""
    # Release window hours if the order held any.
    if ro["status"] in _RESERVING_STATUSES and ro.get("capacity_window_id"):
        window = DB.capacity_windows.get(ro["capacity_window_id"])
        if window is not None:
            window["bay_hours_reserved"] = max(
                0, window["bay_hours_reserved"] - ro["estimated_bay_hours"]
            )
            recompute_window(window)
    # Release any pool reservation held for this order.
    for unit in DB.pool_units.values():
        if unit["pool_status"] == "RESERVED" and unit.get("reserved_for_ro_id") == ro["id"]:
            unit["pool_status"] = "IN_POOL"
            unit["reserved_for_ro_id"] = None
            touch(unit)
            recompute_pool_available_count(unit["customer_id"])
    # Cancel all non-terminal quotes on the order.
    for q in DB.quotes.values():
        if q["repair_order_id"] == ro["id"] and q["status"] in (
            "DRAFT",
            "ISSUED",
            "REVISION_REQUESTED",
        ):
            q["status"] = "CANCELLED"
            touch(q)
    ro["status"] = "CANCELLED"
    touch(ro)


def approved_quote_for_ro(ro_id: str) -> dict | None:
    for q in DB.quotes.values():
        if q["repair_order_id"] == ro_id and q["status"] == "APPROVED":
            return q
    return None


def find_part(part_id: str) -> dict | None:
    return DB.parts.get(part_id)


def quote_line_part_ids(lines: list[dict]) -> set[str]:
    return {line.get("part_id") for line in lines if isinstance(line, dict)}
