"""Domain thresholds and pinned constants, all stated verbatim in the PRD.

Note: the PRD pins the labor rate, discount tiers, valuation decay parameters,
wear-index weights/references/clamp, acceptance tolerances, drift tolerance,
warranty classes, training classes, obsolescence multiplier, sibling gap, and
offer validity window. The per-decision-class base prices, base-hour
allowances, per-machine-type market bases and replacement costs are described
by the PRD only as configured values without pinned numbers, so no test may
assert a quote/residual/surcharge literal that depends on them; tests derive
those outcomes from live API reads plus the pinned percentages/rounding rules.
"""
from decimal import ROUND_HALF_UP, Decimal

THRESHOLDS = {
    # Wear index (PRD §3.2)
    "PD_REF": 20.0,
    "SR_REF": 10.0,
    "BL_REF": 15.0,
    "W_PD": 0.5,
    "W_SR": 0.3,
    "W_BL": 0.2,
    "WEAR_CLAMP": 1.5,
    "FULL_REBUILD_MIN_WEAR": 80.0,
    "MECHANICAL_REBUILD_MIN_WEAR": 40.0,
    # Quote (PRD §3.3)
    "LABOR_RATE_CENTS": 14500,
    "TIER1_MIN_CENTS": 50_000_000,
    "TIER2_MIN_CENTS": 100_000_000,
    "TIER1_RATE": Decimal("0.02"),
    "TIER2_RATE": Decimal("0.05"),
    # Acceptance (PRD §3.6)
    "TOL_POS_MICRONS": 20.0,
    "TOL_REP_MICRONS": 10.0,
    "N_SAMPLES": 5,
    # Rework / escalation surcharges (PRD §3.6)
    "REWORK_FAIL_RATE": Decimal("0.05"),
    "ESCALATION_RETRY_RATE": Decimal("0.10"),
    "ESCALATION_STREAK": 3,
    # Warranty (PRD §3.8)
    "DRIFT_TOL_MICRONS": 15.0,
    # Trade-in (PRD §3.9)
    "DEPRECIATION_PER_YEAR": Decimal("0.88"),
    "SCRAP_FLOOR_CENTS": 2_000_000,
    "OFFER_VALIDITY_DAYS": 30,
    # Obsolescence multiplier on part lines (PRD §3.4)
    "OBSOLETE_MULTIPLIER": Decimal("1.8"),
    # Staged shipment sibling gap (PRD §3.5)
    "MIN_GAP_DAYS": 2,
}

WARRANTY_MONTHS_BY_DECISION = {
    "RETROFIT_ONLY": 6,
    "MECHANICAL_REBUILD": 12,
    "FULL_REBUILD": 24,
}

SESSIONS_REQUIRED_BY_DECISION = {
    "RETROFIT_ONLY": 1,
    "MECHANICAL_REBUILD": 2,
    "FULL_REBUILD": 3,
}

# Logical clock startup default (PRD §2.7).
CLOCK_STARTUP_DEFAULT = "2026-05-01T00:00:00Z"


def round_half_up_cents(value) -> int:
    """Round-half-up to a whole cent, the PRD's single money-rounding rule (§2.5)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(value) -> float:
    """Round-half-up to exactly 2 decimal places for micron quantities (§2.5)."""
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
