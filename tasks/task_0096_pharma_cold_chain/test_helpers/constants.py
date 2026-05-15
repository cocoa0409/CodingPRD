"""Domain thresholds — numeric constants from PRD calculations.

PRD §3.3 deviation_classification — duration and magnitude thresholds.
PRD §3.6 shipment_outbound_total — base/surcharge/premium tiered model.
PRD §3.7 recall_report_due_minutes — class-specific offsets.
PRD §3.7 recall_effectiveness — 0.80 threshold, 4 decimal places.
PRD §3.3 CAPA due offsets — 720 min for CRITICAL, 4320 min for MAJOR.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# PRD §3.3 deviation_classification thresholds (inclusive lower bounds).
# CRITICAL: duration >= 240 OR magnitude >= 5.0
# MAJOR:    duration >= 60  OR magnitude >= 2.0
# else:     MINOR
# ---------------------------------------------------------------------------
CRITICAL_DURATION_MIN = 240
MAJOR_DURATION_MIN = 60
CRITICAL_MAGNITUDE_C = 5.0
MAJOR_MAGNITUDE_C = 2.0


# ---------------------------------------------------------------------------
# PRD §3.3 CAPA due offsets (minutes from deviation closure).
# CRITICAL → +720 (12 hours), MAJOR → +4320 (72 hours).
# ---------------------------------------------------------------------------
CAPA_DUE_OFFSET_CRITICAL = 720
CAPA_DUE_OFFSET_MAJOR = 4320


# ---------------------------------------------------------------------------
# PRD §3.7 recall_report_due_minutes — class-specific offsets.
# CLASS_I = 1440 min (24h), CLASS_II = 4320 min (72h),
# CLASS_III = 14400 min (240h / 10d).
# ---------------------------------------------------------------------------
RECALL_CLASS_I_OFFSET = 1440
RECALL_CLASS_II_OFFSET = 4320
RECALL_CLASS_III_OFFSET = 14400


# Recall effectiveness CAPA due offset is 4320 minutes (72 hours) from
# clock_minutes at close, per PRD §3.7.
RECALL_FAILED_CAPA_DUE_OFFSET = 4320


# ---------------------------------------------------------------------------
# PRD §3.7 recall_effectiveness threshold (inclusive).
# Rounded to 4 decimal places (round_half_up) before comparison.
# ---------------------------------------------------------------------------
EFFECTIVENESS_THRESHOLD = 0.80
EFFECTIVENESS_ROUNDING_DECIMALS = 4


# ---------------------------------------------------------------------------
# PRD §3.6 shipment_outbound_total — base packaging cost by zone type
# (whole cents).
# ---------------------------------------------------------------------------
BASE_CENTS_BY_ZONE_TYPE = {
    "FROZEN": 5000,
    "REFRIGERATED": 3000,
    "COOL": 1500,
    "ROOM_TEMP": 500,
    "CONTROLLED_TEMP": 4000,
}

# Packaging-kind surcharge bounds (cents).
DRY_ICE_MIN_CENTS = 2000
DRY_ICE_PER_UNIT_CENTS = 100
PCM_MAX_CENTS = 3000
PCM_PER_UNIT_CENTS = 50

# Special-handling premium (cents) — applies to
# NARCOTIC/PSYCHOTROPIC/BIOLOGICAL/VACCINE products.
SPECIAL_PREMIUM_CENTS = 1000


# ---------------------------------------------------------------------------
# PRD §2.3 pagination defaults.
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100


# ---------------------------------------------------------------------------
# Test-helper defaults (NOT in PRD — convenience values for factories).
# Tests that exercise specific PRD thresholds override these via
# factory kwargs.
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    # Default REFRIGERATED zone temperature band: target 2..8, alarm 0..10.
    "REFRIGERATED_TARGET_LOW_C": 2.0,
    "REFRIGERATED_TARGET_HIGH_C": 8.0,
    "REFRIGERATED_ALARM_LOW_C": 0.0,
    "REFRIGERATED_ALARM_HIGH_C": 10.0,
    # Default FROZEN zone: target -25..-15, alarm -30..-10.
    "FROZEN_TARGET_LOW_C": -25.0,
    "FROZEN_TARGET_HIGH_C": -15.0,
    "FROZEN_ALARM_LOW_C": -30.0,
    "FROZEN_ALARM_HIGH_C": -10.0,
    # Default COOL zone: target 8..15, alarm 5..20.
    "COOL_TARGET_LOW_C": 8.0,
    "COOL_TARGET_HIGH_C": 15.0,
    "COOL_ALARM_LOW_C": 5.0,
    "COOL_ALARM_HIGH_C": 20.0,
    # Default ROOM_TEMP zone: target 15..25, alarm 10..30.
    "ROOM_TEMP_TARGET_LOW_C": 15.0,
    "ROOM_TEMP_TARGET_HIGH_C": 25.0,
    "ROOM_TEMP_ALARM_LOW_C": 10.0,
    "ROOM_TEMP_ALARM_HIGH_C": 30.0,
    # Default capacity for ad-hoc zones.
    "ZONE_CAPACITY_UNITS": 1000,
    "BIN_VOLUME_UNITS": 100,
    "BIN_WEIGHT_LIMIT_KG": 500.0,
    # Default lot fields used in receipt creation.
    "LOT_EXPIRY_MINUTES": 100_000,
    "QUALIFICATION_EXPIRY_MINUTES": 100_000,
    "STABILITY_BUDGET_MINUTES": 50_000,
    "UNIT_WEIGHT_KG": 1.0,
    "RECEIPT_QUANTITY_UNITS": 10,
}


__all__ = [
    "CRITICAL_DURATION_MIN",
    "MAJOR_DURATION_MIN",
    "CRITICAL_MAGNITUDE_C",
    "MAJOR_MAGNITUDE_C",
    "CAPA_DUE_OFFSET_CRITICAL",
    "CAPA_DUE_OFFSET_MAJOR",
    "RECALL_CLASS_I_OFFSET",
    "RECALL_CLASS_II_OFFSET",
    "RECALL_CLASS_III_OFFSET",
    "RECALL_FAILED_CAPA_DUE_OFFSET",
    "EFFECTIVENESS_THRESHOLD",
    "EFFECTIVENESS_ROUNDING_DECIMALS",
    "BASE_CENTS_BY_ZONE_TYPE",
    "DRY_ICE_MIN_CENTS",
    "DRY_ICE_PER_UNIT_CENTS",
    "PCM_MAX_CENTS",
    "PCM_PER_UNIT_CENTS",
    "SPECIAL_PREMIUM_CENTS",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "TEST_DEFAULTS",
]
