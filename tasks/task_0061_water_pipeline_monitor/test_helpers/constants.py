"""Domain thresholds — numeric constants from PRD calculations and validations.

These are extracted from PRD §2.6, §2.8, §3.4, §3.5, §3.7, §3.8, §3.9.
"""
from __future__ import annotations
from decimal import ROUND_HALF_UP, Decimal


# ---------------------------------------------------------------------------
# Alert severity thresholds (PRD §3.5)
# ---------------------------------------------------------------------------
WARNING_PCT = 15.0      # PRD §3.5: "from 15.0 (inclusive) ... WARNING"
CRITICAL_PCT = 30.0     # PRD §3.5: "at 30.0 and above the severity is CRITICAL"
FLOW_WARNING_RATIO = 1.5    # PRD §3.5: "from 1.5 (inclusive) ... WARNING"
FLOW_CRITICAL_RATIO = 2.5   # PRD §3.5: "at 2.5 and above ... CRITICAL"
CROSS_SENSOR_TOLERANCE_PCT = 10.0  # PRD §3.5: deviation "by at least 10.0 percent"
MIN_HISTORY_HOURS = 168     # PRD §3.5: "at least 168 hours of ACCEPTED readings"
DYNAMIC_BASELINE_WINDOW_DAYS = 28  # PRD §3.5: "over the past 28 days"


# ---------------------------------------------------------------------------
# Alert dedup (PRD §3.5)
# ---------------------------------------------------------------------------
ALERT_DEDUP_WINDOW_S = 900  # PRD §3.5: "900 seconds (the 15-minute dedup window ... inclusive)"


# ---------------------------------------------------------------------------
# Water balance (PRD §3.9)
# ---------------------------------------------------------------------------
APPARENT_LOSS_RATE = 0.04   # PRD §3.9: "multiplied by 0.04 (a fixed 4.0 percent ...)"
WATER_BALANCE_WINDOW_LENGTHS_S = (3600, 86400, 604800)
SECONDS_PER_DAY = 86400


# ---------------------------------------------------------------------------
# Reading temporal-window check (PRD §3.4)
# ---------------------------------------------------------------------------
MAX_BACKDATE_S = 604800     # PRD §3.4: "a backdate window of seven days ... 604800 seconds"
MAX_FORWARD_S = 60          # PRD §3.4: "a forward window of 60 seconds"


# ---------------------------------------------------------------------------
# Device offline detection (PRD §3.4)
# ---------------------------------------------------------------------------
OFFLINE_THRESHOLD = 3       # PRD §3.4: "missed_polls_consecutive reaches 3 or more"


# ---------------------------------------------------------------------------
# Archive tier thresholds (PRD §3.4)
# ---------------------------------------------------------------------------
HOT_RETENTION_S = 86400     # PRD §3.4: "less than 86400 seconds is HOT"
WARM_RETENTION_S = 2592000  # PRD §3.4: "to 2592000 seconds (exclusive) it is WARM"


# ---------------------------------------------------------------------------
# Device config bounds (PRD §3.4)
# ---------------------------------------------------------------------------
POLLING_INTERVAL_MIN_S = 30     # PRD §3.4: "between 30 and 3600 seconds inclusive"
POLLING_INTERVAL_MAX_S = 3600


# ---------------------------------------------------------------------------
# Leak localization (PRD §3.7)
# ---------------------------------------------------------------------------
HAZEN_WILLIAMS_K = 10.67
RHO_G_KPA_PER_M = 9.81
GRADIENT_ANOMALY_THRESHOLD_PCT = 25.0  # PRD §3.7: "at least 25.0 percent"
LOOKBACK_S = 3600
NIGHT_FLOW_THRESHOLD_LPS = 2.0  # PRD §3.7: "at least 2.0 liters per second"


# ---------------------------------------------------------------------------
# WorkOrder priority (PRD §3.8)
# ---------------------------------------------------------------------------
P1_THRESHOLD = 15           # PRD §3.8: "15 or more is P1"
P2_THRESHOLD = 8            # PRD §3.8: "from 8 (inclusive) ... is P2"
DOWNSTREAM_BUCKET_SIZE = 50  # PRD §3.8: "divide by 50, and round up"


# ---------------------------------------------------------------------------
# DMA posture thresholds (PRD §2.8)
# ---------------------------------------------------------------------------
DMA_RESTRICTED_AT = 1       # PRD §2.8: "crosses from zero to one or more ... RESTRICTED"
DMA_FROZEN_AT = 3           # PRD §2.8: "reaches three or more ... FROZEN"


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


# ---------------------------------------------------------------------------
# Rounding helper (PRD §2.6 — "round-half-up as the universal rounding direction")
# ---------------------------------------------------------------------------
def round_half_up(value: float, decimals: int) -> float:
    """Round a float using round-half-up to `decimals` places.

    PRD §2.6: round-half-up is the universal rounding direction.
    """
    if value is None:
        return value
    quant = Decimal(10) ** -decimals
    return float(
        Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP)
    )


__all__ = [
    "WARNING_PCT",
    "CRITICAL_PCT",
    "FLOW_WARNING_RATIO",
    "FLOW_CRITICAL_RATIO",
    "CROSS_SENSOR_TOLERANCE_PCT",
    "MIN_HISTORY_HOURS",
    "DYNAMIC_BASELINE_WINDOW_DAYS",
    "ALERT_DEDUP_WINDOW_S",
    "APPARENT_LOSS_RATE",
    "WATER_BALANCE_WINDOW_LENGTHS_S",
    "SECONDS_PER_DAY",
    "MAX_BACKDATE_S",
    "MAX_FORWARD_S",
    "OFFLINE_THRESHOLD",
    "HOT_RETENTION_S",
    "WARM_RETENTION_S",
    "POLLING_INTERVAL_MIN_S",
    "POLLING_INTERVAL_MAX_S",
    "HAZEN_WILLIAMS_K",
    "RHO_G_KPA_PER_M",
    "GRADIENT_ANOMALY_THRESHOLD_PCT",
    "LOOKBACK_S",
    "NIGHT_FLOW_THRESHOLD_LPS",
    "P1_THRESHOLD",
    "P2_THRESHOLD",
    "DOWNSTREAM_BUCKET_SIZE",
    "DMA_RESTRICTED_AT",
    "DMA_FROZEN_AT",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_DEFAULT_OFFSET",
    "round_half_up",
]
