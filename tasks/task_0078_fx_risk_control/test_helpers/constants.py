"""Domain thresholds — numeric constants from PRD §2 / §3 calculations."""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Utilization & warning thresholds (PRD §3.2)
# ---------------------------------------------------------------------------
WARNING_PCT = 80      # utilization_pct >= 80 is WARNING (inclusive)
BREACH_PCT = 100      # utilization_pct >= 100 is BREACH (inclusive)


# ---------------------------------------------------------------------------
# Counterparty tier table (PRD §3.6)
# ---------------------------------------------------------------------------
INVESTMENT_TIER_USD = 100_000_000.00
STANDARD_TIER_USD = 50_000_000.00
SPECULATIVE_TIER_USD = 10_000_000.00
WATCH_TIER_USD = 1_000_000.00

# Internal-score band cutoffs (PRD §3.6)
INTERNAL_INVESTMENT_FLOOR = 80
INTERNAL_STANDARD_FLOOR = 60
INTERNAL_SPECULATIVE_FLOOR = 40

# Severity ranks for rating_band — INVESTMENT least severe, WATCH most severe.
BAND_SEVERITY = {
    "INVESTMENT": 0,
    "STANDARD": 1,
    "SPECULATIVE": 2,
    "WATCH": 3,
}

EXTERNAL_RATING_TO_BAND = {
    "AAA": "INVESTMENT",
    "AA": "INVESTMENT",
    "A": "STANDARD",
    "BBB": "STANDARD",
    "BB": "SPECULATIVE",
    "B": "SPECULATIVE",
    "CCC": "WATCH",
    "NR": "WATCH",
}


def band_from_external(external_rating: str) -> str:
    return EXTERNAL_RATING_TO_BAND[external_rating]


def band_from_internal(internal_score: int) -> str:
    if internal_score >= INTERNAL_INVESTMENT_FLOOR:
        return "INVESTMENT"
    if internal_score >= INTERNAL_STANDARD_FLOOR:
        return "STANDARD"
    if internal_score >= INTERNAL_SPECULATIVE_FLOOR:
        return "SPECULATIVE"
    return "WATCH"


def worse_band(b1: str, b2: str) -> str:
    return b1 if BAND_SEVERITY[b1] >= BAND_SEVERITY[b2] else b2


def credit_limit_for_band(band: str) -> float:
    return {
        "INVESTMENT": INVESTMENT_TIER_USD,
        "STANDARD": STANDARD_TIER_USD,
        "SPECULATIVE": SPECULATIVE_TIER_USD,
        "WATCH": WATCH_TIER_USD,
    }[band]


# ---------------------------------------------------------------------------
# Large-trade compliance threshold (PRD §3.4 / §3.9)
# ---------------------------------------------------------------------------
LARGE_TRADE_THRESHOLD_USD = 10_000_000.00


# ---------------------------------------------------------------------------
# VaR (PRD §3.8)
# ---------------------------------------------------------------------------
Z_99 = 2.326


# ---------------------------------------------------------------------------
# EOD cutoff (PRD §3.2)
# ---------------------------------------------------------------------------
EOD_CUTOFF_UTC = "17:00:00"


# ---------------------------------------------------------------------------
# Settlement failure cascade (PRD §3.7)
# ---------------------------------------------------------------------------
SETTLEMENT_FAILURE_SCORE_PENALTY = 5


# ---------------------------------------------------------------------------
# Test defaults — sensible values fixtures use unless caller overrides
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "DESK_CODE": "G10_SPOT",
    "INTRADAY_CAP_USD": 10_000_000.00,
    "OVERNIGHT_CAP_USD": 10_000_000.00,
    "STOP_LOSS_CAP_USD": 100_000.00,
    "PAIR_CODE": "EURUSD",
    "PAIR_BASE": "EUR",
    "PAIR_QUOTE": "USD",
    "PAIR_MID_RATE": 1.000000,
    "PAIR_VOL": 0.008000,
    "CLOCK_INTRADAY_ISO": "2026-05-13T10:00:00.000Z",
    "CLOCK_OVERNIGHT_ISO": "2026-05-13T17:00:00.000Z",
    "EXPIRES_FAR_FUTURE": "2026-12-31T23:59:00.000Z",
    "EXPIRES_PAST": "2020-01-01T00:00:00.000Z",
}


def round_half_up(value: float, decimals: int) -> float:
    """Pure-Python half-up rounding, matching PRD §2.6 'rounded half-up'.

    Used by tests when computing expected values for comparison.
    """
    from decimal import Decimal, ROUND_HALF_UP
    quant = Decimal(10) ** -decimals
    return float(
        Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP)
    )


__all__ = [
    "WARNING_PCT",
    "BREACH_PCT",
    "INVESTMENT_TIER_USD",
    "STANDARD_TIER_USD",
    "SPECULATIVE_TIER_USD",
    "WATCH_TIER_USD",
    "INTERNAL_INVESTMENT_FLOOR",
    "INTERNAL_STANDARD_FLOOR",
    "INTERNAL_SPECULATIVE_FLOOR",
    "BAND_SEVERITY",
    "EXTERNAL_RATING_TO_BAND",
    "band_from_external",
    "band_from_internal",
    "worse_band",
    "credit_limit_for_band",
    "LARGE_TRADE_THRESHOLD_USD",
    "Z_99",
    "EOD_CUTOFF_UTC",
    "SETTLEMENT_FAILURE_SCORE_PENALTY",
    "TEST_DEFAULTS",
    "round_half_up",
]
