"""Domain thresholds and rounding helpers for the Cold Chain Logistics suite.

Numeric constants are derived from the PRD calculation rules in
§2.7 (precision / rounding), §3.3 (driver hours-of-service), §3.5
(temperature reading validity), §3.6 (alert severity classification),
§3.9 (damage-amount calculation), and §3.10 (responsibility split).
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

# ---------------------------------------------------------------------------
# Temperature reading validity (PRD §3.5)
# ---------------------------------------------------------------------------
TEMP_FLOOR_CELSIUS = -80.0
TEMP_CEILING_CELSIUS = 80.0
GPS_LAT_MIN = -90.0
GPS_LAT_MAX = 90.0
GPS_LNG_MIN = -180.0
GPS_LNG_MAX = 180.0

# ---------------------------------------------------------------------------
# Alert severity classification (PRD §3.6)
# ---------------------------------------------------------------------------
CRITICAL_DURATION_SECONDS = 1800
MAJOR_DURATION_SECONDS = 600
CRITICAL_PEAK_DEVIATION_C = 5.00
MAJOR_PEAK_DEVIATION_C = 2.00

# Channel sets per level
CHANNELS_WARNING = {"DRIVER"}
CHANNELS_MAJOR = {"DRIVER", "DISPATCH"}
CHANNELS_CRITICAL = {"DRIVER", "DISPATCH", "CUSTOMER"}

# ---------------------------------------------------------------------------
# Damage amount calculation (PRD §3.9)
# ---------------------------------------------------------------------------
DAMAGE_FACTOR_MINOR = Decimal("0.30")
DAMAGE_FACTOR_MODERATE = Decimal("0.60")
DAMAGE_FACTOR_TOTAL_LOSS = Decimal("1.00")

DAMAGE_FACTOR = {
    "MINOR": DAMAGE_FACTOR_MINOR,
    "MODERATE": DAMAGE_FACTOR_MODERATE,
    "TOTAL_LOSS": DAMAGE_FACTOR_TOTAL_LOSS,
}

# ---------------------------------------------------------------------------
# Driver hours-of-service (PRD §3.1, §3.3)
# ---------------------------------------------------------------------------
DRIVER_MAX_DAILY_MINUTES_DEFAULT = 660
DRIVER_MAX_DAILY_MINUTES_FLOOR = 1
DRIVER_MAX_DAILY_MINUTES_CEILING = 1440

# ---------------------------------------------------------------------------
# Polling cadence (PRD §3.2)
# ---------------------------------------------------------------------------
POLLING_INTERVAL_DEFAULT_SECONDS = 60
POLLING_INTERVAL_MIN_SECONDS = 10
POLLING_INTERVAL_MAX_SECONDS = 3600

# ---------------------------------------------------------------------------
# Vehicle constraints (PRD §3.1)
# ---------------------------------------------------------------------------
COMPARTMENT_COUNT_MIN = 1
COMPARTMENT_COUNT_MAX = 6

# ---------------------------------------------------------------------------
# Depart pre-window (PRD §3.4)
# ---------------------------------------------------------------------------
DEPART_PRE_WINDOW_SECONDS = 3600  # may depart at most 1h before planned_start_at

# ---------------------------------------------------------------------------
# Pagination defaults (PRD §2.3)
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


# ---------------------------------------------------------------------------
# Rounding helpers
# ---------------------------------------------------------------------------
def round_half_up_to_cent(value: Any) -> int:
    """PRD §2.7: 'All monetary quantities are integer cents.
    Damage-amount calculations round half up to the nearest whole cent.'"""
    return int(
        Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )


def round_half_up_to_two_decimals(value: Any) -> Decimal:
    """PRD §2.7: 'Temperature values are stored to two decimal places and
    rounded half up.' Also responsibility-split percentages."""
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def expected_per_unit_damage_cents(
    unit_value_cents: int, damage_class: str, salvage_pct: Any,
) -> int:
    """Expected per-unit damage in cents per PRD §3.9 formula.

    'the per-unit damage in cents is the per-unit value multiplied by the
    damage factor for damage_class multiplied by one minus salvage_pct,
    rounded half up to a whole cent'."""
    factor = DAMAGE_FACTOR[damage_class]
    multiplier = Decimal("1.0") - Decimal(str(salvage_pct))
    raw = Decimal(unit_value_cents) * factor * multiplier
    return round_half_up_to_cent(raw)


def expected_damage_amount_cents(
    *,
    cargo_value_cents: int,
    cargo_quantity: int,
    damaged_quantity: int,
    damage_class: str,
    salvage_pct: Any,
    variant: str,
    insured_cap_cents: int,
    invoice_unit_value_cents: int = 0,
) -> int:
    """End-to-end damage_amount_cents calculation per PRD §3.9.

    'First, the damage factor lookup table assigns 0.30 to MINOR, 0.60 to
    MODERATE, and 1.00 to TOTAL_LOSS.'
    'Under variant of INSURED_VALUE, the per-unit value in cents is the
    floor of the task's cargo_value_cents divided by the task's
    cargo_quantity.'
    'Under variant of INVOICE_VALUE, the per-unit value is
    invoice_unit_value_cents supplied in the payload.'
    'the per-unit damage ... rounded half up to a whole cent ... the raw
    total is the per-unit damage in cents multiplied by damaged_quantity ...
    damage_amount_cents is the smaller of the raw total and the task's
    vehicle insured_cap_cents'."""
    if variant == "INSURED_VALUE":
        unit_value_cents = cargo_value_cents // cargo_quantity
    elif variant == "INVOICE_VALUE":
        unit_value_cents = invoice_unit_value_cents
    else:  # pragma: no cover - defensive
        raise ValueError(f"Unknown variant {variant!r}")
    per_unit = expected_per_unit_damage_cents(
        unit_value_cents, damage_class, salvage_pct,
    )
    raw_total = per_unit * damaged_quantity
    return min(raw_total, insured_cap_cents)


__all__ = [
    "TEMP_FLOOR_CELSIUS", "TEMP_CEILING_CELSIUS",
    "GPS_LAT_MIN", "GPS_LAT_MAX", "GPS_LNG_MIN", "GPS_LNG_MAX",
    "CRITICAL_DURATION_SECONDS", "MAJOR_DURATION_SECONDS",
    "CRITICAL_PEAK_DEVIATION_C", "MAJOR_PEAK_DEVIATION_C",
    "CHANNELS_WARNING", "CHANNELS_MAJOR", "CHANNELS_CRITICAL",
    "DAMAGE_FACTOR_MINOR", "DAMAGE_FACTOR_MODERATE", "DAMAGE_FACTOR_TOTAL_LOSS",
    "DAMAGE_FACTOR",
    "DRIVER_MAX_DAILY_MINUTES_DEFAULT",
    "DRIVER_MAX_DAILY_MINUTES_FLOOR",
    "DRIVER_MAX_DAILY_MINUTES_CEILING",
    "POLLING_INTERVAL_DEFAULT_SECONDS",
    "POLLING_INTERVAL_MIN_SECONDS",
    "POLLING_INTERVAL_MAX_SECONDS",
    "COMPARTMENT_COUNT_MIN", "COMPARTMENT_COUNT_MAX",
    "DEPART_PRE_WINDOW_SECONDS",
    "PAGINATION_DEFAULT_LIMIT", "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT", "PAGINATION_DEFAULT_OFFSET",
    "round_half_up_to_cent", "round_half_up_to_two_decimals",
    "expected_per_unit_damage_cents", "expected_damage_amount_cents",
]
