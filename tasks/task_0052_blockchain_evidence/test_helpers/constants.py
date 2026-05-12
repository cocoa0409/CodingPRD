"""Domain thresholds — numeric constants from PRD §2.7, §2.8, §3.3, §3.5, §3.7.

Field names mirror PRD prose exactly. Generic NON_EXISTENT_UUID comes from
the framework.
"""
from __future__ import annotations
from typing import Dict


# ---------------------------------------------------------------------------
# Fees (PRD §3.3, §3.5)
# ---------------------------------------------------------------------------
BASE_FEE_BY_TYPE: Dict[str, int] = {
    "DOCUMENT": 200,
    "IMAGE": 300,
    "VIDEO": 800,
    "CODE_REPOSITORY": 500,
    "DATASET": 1000,
}

# Period multipliers — applied to base fee. PRD §3.3.
PERIOD_MULTIPLIER: Dict[int, float] = {
    30: 1.00,
    90: 2.50,
    365: 8.00,
    1095: 20.00,
}

ORIGINAL_DATA_SURCHARGE_CENTS = 50


# ---------------------------------------------------------------------------
# Batch discount tiers (PRD §3.5)
# ---------------------------------------------------------------------------
BATCH_DISCOUNT_TIERS = (
    # (min_count, rate). First match wins, highest-count tier first.
    (100, 0.20),
    (50, 0.15),
    (10, 0.10),
    (2, 0.05),
)


# ---------------------------------------------------------------------------
# Judicial surcharge (PRD §3.7)
# ---------------------------------------------------------------------------
JUDICIAL_BASE_SURCHARGE_CENTS = 5000
JUDICIAL_ORIGINAL_DATA_UPLIFT_CENTS = 1500

AUTHORITY_MULTIPLIER: Dict[str, float] = {
    "COURT_BJ": 1.20,
    "COURT_SH": 1.20,
    "COURT_GZ": 1.10,
    "COURT_SZ": 1.10,
    "PROCURATORATE": 1.00,
    "ARBITRATION": 0.90,
}


# ---------------------------------------------------------------------------
# Chain confirmation thresholds (PRD §2.8)
# ---------------------------------------------------------------------------
CHAIN_CONFIRMATION_THRESHOLD: Dict[str, int] = {
    "ETHEREUM": 12,
    "FABRIC": 1,
    "BSN": 5,
    "COSMOS": 6,
}


# ---------------------------------------------------------------------------
# Limits & batch sizing (PRD §3.3, §3.5)
# ---------------------------------------------------------------------------
MAX_SUBMISSION_ATTEMPTS = 3  # strictly-less-than guard, see PRD §3.3
BATCH_SIZE_MIN = 2
BATCH_SIZE_MAX = 1000


# ---------------------------------------------------------------------------
# Recharge bounds (PRD §3.1)
# ---------------------------------------------------------------------------
RECHARGE_AMOUNT_MIN_CENTS = 100
RECHARGE_AMOUNT_MAX_CENTS = 10_000_000


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def round_half_up(value: float) -> int:
    """Banker-free half-up rounding to integer cents (PRD §2.7)."""
    import math
    # Use the Decimal-equivalent half-up: floor(x + 0.5) for positives.
    if value >= 0:
        return int(math.floor(value + 0.5))
    return -int(math.floor(-value + 0.5))


def preservation_fee_cents(
    *,
    evidence_type: str,
    storage_period_days: int,
    original_data_b64: object,
) -> int:
    """PRD §3.3 single-evidence preservation fee formula.

    base = BASE_FEE_BY_TYPE[evidence_type]
    multiplier = PERIOD_MULTIPLIER[storage_period_days]
    surcharge = 50 if original_data_b64 is not None else 0
    fee = round_half_up(base * multiplier + surcharge)
    """
    base = BASE_FEE_BY_TYPE[evidence_type]
    multiplier = PERIOD_MULTIPLIER[storage_period_days]
    surcharge = (
        ORIGINAL_DATA_SURCHARGE_CENTS if original_data_b64 is not None else 0
    )
    return round_half_up(base * multiplier + surcharge)


def batch_discount_rate(evidence_count: int) -> float:
    """PRD §3.5 batch discount: highest tier that count meets or exceeds."""
    for min_count, rate in BATCH_DISCOUNT_TIERS:
        if evidence_count >= min_count:
            return rate
    return 0.0


def judicial_surcharge_cents(
    *, include_original_data: bool, authority_code: str,
) -> int:
    """PRD §3.7 judicial surcharge formula.

    base = 5000
    uplift = 1500 if include_original_data else 0
    multiplier = AUTHORITY_MULTIPLIER[authority_code]
    surcharge = round_half_up((base + uplift) * multiplier)
    """
    uplift = (
        JUDICIAL_ORIGINAL_DATA_UPLIFT_CENTS if include_original_data else 0
    )
    multiplier = AUTHORITY_MULTIPLIER[authority_code]
    return round_half_up(
        (JUDICIAL_BASE_SURCHARGE_CENTS + uplift) * multiplier
    )


__all__ = [
    "BASE_FEE_BY_TYPE",
    "PERIOD_MULTIPLIER",
    "ORIGINAL_DATA_SURCHARGE_CENTS",
    "BATCH_DISCOUNT_TIERS",
    "JUDICIAL_BASE_SURCHARGE_CENTS",
    "JUDICIAL_ORIGINAL_DATA_UPLIFT_CENTS",
    "AUTHORITY_MULTIPLIER",
    "CHAIN_CONFIRMATION_THRESHOLD",
    "MAX_SUBMISSION_ATTEMPTS",
    "BATCH_SIZE_MIN",
    "BATCH_SIZE_MAX",
    "RECHARGE_AMOUNT_MIN_CENTS",
    "RECHARGE_AMOUNT_MAX_CENTS",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_DEFAULT_OFFSET",
    "round_half_up",
    "preservation_fee_cents",
    "batch_discount_rate",
    "judicial_surcharge_cents",
]
