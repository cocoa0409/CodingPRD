"""Calculation rules (scaffold §1.3 / PRD §2.5, §3.1, §3.4, §3.7)."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

import db

# ---- constants (scaffold §1.3) ---------------------------------------------
DEVICE_SHARE_WEIGHT = 20
VELOCITY_WINDOW_SECONDS = 3600
VELOCITY_FREE = 2
VELOCITY_WEIGHT = 15
EMAIL_PLUS_PENALTY = 25
BOT_FLAG_THRESHOLD = 70

BAND1_RATIO = Decimal("0.50")
BAND2_RATIO = Decimal("0.80")
BAND1_BPS = 1500
BAND2_BPS = 3000

SERVICE_FEE_BPS = 1200

LOYALTY_THRESHOLD = 3
STANDARD_REFUND_BPS = 9000

OFFER_WINDOW_SECONDS = 120
MAX_PER_FAN = 6


def round_half_up(value: Decimal) -> int:
    """Round a Decimal to the nearest integer, half up."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def bot_risk_score(fan: dict) -> int:
    """Recompute the bot-detection risk score (scaffold §1.3.bot_risk_score).

    velocity counts this fan's queue entries created within the trailing
    VELOCITY_WINDOW_SECONDS window (by created_at), INCLUDING any entry being
    created by the current join — so callers must create the QueueEntry first,
    then recompute.
    """
    this_id = fan["id"]
    fingerprint = fan.get("device_fingerprint")

    shared_device = sum(
        1
        for other in db.fans.values()
        if other["id"] != this_id and other.get("device_fingerprint") == fingerprint
    )
    device_pts = min(60, shared_device * DEVICE_SHARE_WEIGHT)

    now = db.now_dt()
    window_start = now.timestamp() - VELOCITY_WINDOW_SECONDS
    velocity = 0
    for qe in db.queue_entries.values():
        if qe.get("fan_id") != this_id:
            continue
        created = db.parse_iso_dt(qe.get("created_at"))
        if created is None:
            continue
        if created.timestamp() >= window_start:
            velocity += 1
    velocity_pts = min(30, max(0, velocity - VELOCITY_FREE) * VELOCITY_WEIGHT)

    email = fan.get("email") or ""
    email_pts = EMAIL_PLUS_PENALTY if "+" in email else 0

    return min(100, max(0, device_pts + velocity_pts + email_pts))


def dynamic_unit_price(event: dict, tier: dict, is_presale: bool) -> int:
    """Per-seat dynamic price (scaffold §1.3.dynamic_unit_price / PRD §3.4)."""
    base = event["face_value_cents"]
    tier_priced = round_half_up(
        Decimal(base) * Decimal(tier["base_multiplier_bps"]) / Decimal(10000)
    )

    if is_presale:
        demand_bps = 0
    else:
        capacity = event["venue_capacity"]
        sold_ratio = Decimal(event["tickets_sold_count"]) / Decimal(capacity)
        if sold_ratio < BAND1_RATIO:
            demand_bps = 0
        elif sold_ratio < BAND2_RATIO:
            demand_bps = BAND1_BPS
        else:
            demand_bps = BAND2_BPS

    unit = round_half_up(
        Decimal(tier_priced) * Decimal(10000 + demand_bps) / Decimal(10000)
    )
    return max(unit, base)


def order_total(unit_price_cents: int, quantity: int) -> tuple:
    """(subtotal, service_fee, total) — pinned rounding (scaffold §1.3.order_total)."""
    subtotal = unit_price_cents * quantity
    service_fee = round_half_up(
        Decimal(subtotal) * Decimal(SERVICE_FEE_BPS) / Decimal(10000)
    )
    total = subtotal + service_fee
    return subtotal, service_fee, total


def refund_amount(subtotal_cents: int, completed_purchase_count: int) -> int:
    """Loyalty-tiered refund (scaffold §1.3.refund_amount / PRD §3.4)."""
    principal = subtotal_cents
    if completed_purchase_count >= LOYALTY_THRESHOLD:
        return principal
    return round_half_up(Decimal(principal) * Decimal(STANDARD_REFUND_BPS) / Decimal(10000))


def resale_price_cap(event: dict) -> int:
    """Resale price cap in cents (scaffold §1.3.resale_price_cap / PRD §3.7)."""
    return round_half_up(
        Decimal(event["face_value_cents"])
        * Decimal(100 + event["resale_cap_pct"])
        / Decimal(100)
    )
