"""Calculation rules implementations.

PRD §2.9 + §3.4 + §3.6 + §3.7. Uses Decimal with ROUND_HALF_UP for precision-sensitive
operations. Temperature magnitudes 2dp, effectiveness ratios 4dp, monetary cents are
rounded per-line before summation.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any


# Tier offsets for recall report deadlines (minutes).
RECALL_TIER_OFFSET: dict[str, int] = {
    "CLASS_I": 1440,
    "CLASS_II": 4320,
    "CLASS_III": 14400,
}


# Packaging->required_zone_type mapping (PRD §3.5).
PACKAGING_FOR_ZONE: dict[str, str] = {
    "FROZEN": "INSULATED_DRY_ICE",
    "REFRIGERATED": "INSULATED_PCM",
    "COOL": "INSULATED_PCM",
    "CONTROLLED_TEMP": "INSULATED_PCM",
    "ROOM_TEMP": "AMBIENT",
}


# Base packaging cost per zone tier (cents) — PRD §3.6.
BASE_CENTS_FOR_ZONE: dict[str, int] = {
    "FROZEN": 5000,
    "REFRIGERATED": 3000,
    "COOL": 1500,
    "ROOM_TEMP": 500,
    "CONTROLLED_TEMP": 4000,
}


SPECIAL_TAGS = {"NARCOTIC", "PSYCHOTROPIC", "BIOLOGICAL", "VACCINE"}


def round_half_up_dp(value: Decimal | float | int, places: int) -> Decimal:
    """Round half-up to `places` decimal places."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    q = Decimal(10) ** (-places)
    return value.quantize(q, rounding=ROUND_HALF_UP)


def round_half_up_cents(value: Decimal | float | int) -> int:
    """Round half-up to whole cents (integer)."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Deviation classification (PRD §3.3)
# ---------------------------------------------------------------------------
def classify_deviation(max_magnitude_c: Decimal | float, duration_minutes: int) -> str:
    """Tier cascade: CRITICAL > MAJOR > MINOR.

    Inclusive lower bounds: >= at every step.
    """
    m = Decimal(str(max_magnitude_c)) if not isinstance(max_magnitude_c, Decimal) else max_magnitude_c
    d = int(duration_minutes)
    if d >= 240 or m >= Decimal("5.0"):
        return "CRITICAL"
    if d >= 60 or m >= Decimal("2.0"):
        return "MAJOR"
    return "MINOR"


# ---------------------------------------------------------------------------
# Recall report deadline (PRD §3.7)
# ---------------------------------------------------------------------------
def compute_report_due_minutes(initiated_at_minutes: int, classification: str) -> int:
    offset = RECALL_TIER_OFFSET.get(classification)
    if offset is None:
        raise ValueError(f"Unknown classification: {classification}")
    return int(initiated_at_minutes) + offset


# ---------------------------------------------------------------------------
# Recall effectiveness (PRD §3.7)
# ---------------------------------------------------------------------------
def compute_effectiveness_ratio(received: int, expected: int) -> Decimal:
    if expected <= 0:
        return Decimal("0.0000")
    ratio = Decimal(received) / Decimal(expected)
    return round_half_up_dp(ratio, 4)


def effectiveness_pass(received: int, expected: int) -> tuple[bool, Decimal]:
    ratio = compute_effectiveness_ratio(received, expected)
    return ratio >= Decimal("0.80"), ratio


def projected_effectiveness(
    received: int,
    expected: int,
    notifications_sent: int,
    returned_customer_count: int,
) -> tuple[bool, Decimal]:
    """Preview-mode projection (PRD §3.7).

    projected_received = received + (notifications_sent - returned_customer_count) * 1.0
    """
    if expected <= 0:
        return False, Decimal("0.0000")
    outstanding = max(0, notifications_sent - returned_customer_count)
    projected_received = Decimal(received) + Decimal(outstanding) * Decimal("1.0")
    ratio = projected_received / Decimal(expected)
    ratio = round_half_up_dp(ratio, 4)
    return ratio >= Decimal("0.80"), ratio


# ---------------------------------------------------------------------------
# Shipment outbound total (PRD §3.6)
# ---------------------------------------------------------------------------
def compute_shipment_total_cents(
    required_zone_type: str,
    packaging_kind: str,
    quantity_units: int,
    product_special_tag: str,
) -> int:
    """Three-component tiered model, rounded per-line then summed."""
    base = Decimal(BASE_CENTS_FOR_ZONE.get(required_zone_type, 0))

    if packaging_kind == "INSULATED_DRY_ICE":
        surcharge = max(Decimal(2000), Decimal(100) * Decimal(quantity_units))
    elif packaging_kind == "INSULATED_PCM":
        surcharge = min(Decimal(3000), Decimal(50) * Decimal(quantity_units))
    else:  # AMBIENT (and any other)
        surcharge = Decimal(0)

    premium = Decimal(1000) if product_special_tag in SPECIAL_TAGS else Decimal(0)

    base_c = round_half_up_cents(base)
    surcharge_c = round_half_up_cents(surcharge)
    premium_c = round_half_up_cents(premium)

    return base_c + surcharge_c + premium_c


# ---------------------------------------------------------------------------
# Temperature classification (PRD §3.3)
# ---------------------------------------------------------------------------
def classify_temperature(
    temp_c: Decimal | float,
    zone: dict[str, Any],
) -> str:
    """Classify reading vs zone thresholds.

    IN_RANGE      iff temp ∈ [target_low, target_high]
    ALARM_LOW     iff temp <= alarm_low
    ALARM_HIGH    iff temp >= alarm_high
    WARNING_LOW   iff alarm_low < temp < target_low
    WARNING_HIGH  iff target_high < temp < alarm_high
    """
    t = Decimal(str(temp_c)) if not isinstance(temp_c, Decimal) else temp_c
    tlo = Decimal(str(zone["target_temp_low_c"]))
    thi = Decimal(str(zone["target_temp_high_c"]))
    alo = Decimal(str(zone["alarm_low_c"]))
    ahi = Decimal(str(zone["alarm_high_c"]))

    if tlo <= t <= thi:
        return "IN_RANGE"
    if t <= alo:
        return "ALARM_LOW"
    if t >= ahi:
        return "ALARM_HIGH"
    if t < tlo:
        return "WARNING_LOW"
    return "WARNING_HIGH"


def magnitude_from_bound(temp_c: Decimal | float, zone: dict[str, Any]) -> Decimal:
    """Compute absolute deviation from the nearest crossed zone bound."""
    t = Decimal(str(temp_c)) if not isinstance(temp_c, Decimal) else temp_c
    tlo = Decimal(str(zone["target_temp_low_c"]))
    thi = Decimal(str(zone["target_temp_high_c"]))
    if t < tlo:
        return round_half_up_dp(tlo - t, 2)
    if t > thi:
        return round_half_up_dp(t - thi, 2)
    return Decimal("0.00")
