"""Domain thresholds and numeric constants from the PRD."""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Performance calculations (PRD §3.2)
# ---------------------------------------------------------------------------
REFERENCE_IRRADIANCE_W_M2 = 1000
MINUTES_PER_HOUR = 60


# ---------------------------------------------------------------------------
# Station operational-status thresholds (PRD §3.1)
# ---------------------------------------------------------------------------
DEGRADED_THRESHOLD = 0.20
OUT_OF_SERVICE_THRESHOLD = 0.50


# ---------------------------------------------------------------------------
# Alarm dedup (PRD §3.3)
# ---------------------------------------------------------------------------
DEDUP_WINDOW_SECONDS = 300


# ---------------------------------------------------------------------------
# Defect (PRD §3.5)
# ---------------------------------------------------------------------------
RECURRENCE_ESCALATION_THRESHOLD = 3
REOPEN_GRACE_DAYS = 30


# ---------------------------------------------------------------------------
# Settlement (PRD §3.6)
# ---------------------------------------------------------------------------
RECONCILIATION_TOLERANCE = 0.005
RECONCILIATION_FLOOR = 0.001


# ---------------------------------------------------------------------------
# Subsidy (PRD §3.7)
# ---------------------------------------------------------------------------
SUBSIDY_MIN_PAYOUT_CNY = 100
APPROVAL_DUE_DAYS = 90
ARREARS_GRACE_DAYS = 30


# ---------------------------------------------------------------------------
# Investor share invariants (PRD §3.6)
# ---------------------------------------------------------------------------
BASIS_POINTS_TOTAL = 10000


# ---------------------------------------------------------------------------
# Downsampling bucket sizes (PRD §3.2)
# ---------------------------------------------------------------------------
AGG_15MIN_BUCKET_MIN = 15
AGG_1H_BUCKET_MIN = 60
AGG_1DAY_BUCKET_MIN = 1440


# ---------------------------------------------------------------------------
# Pagination defaults (PRD §2.3)
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100


# ---------------------------------------------------------------------------
# Misc time
# ---------------------------------------------------------------------------
SECONDS_PER_DAY = 86400
SECONDS_PER_HOUR = 3600


# ---------------------------------------------------------------------------
# Test defaults — convenience values used by factories/fixtures.
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "INSTALLED_CAPACITY_KW": 100.000,
    "AC_CAPACITY_KW": 100.000,
    "FEED_IN_TARIFF": 0.5000,
    "MODULE_WP": 540.0,
    "INVERTER_AC_KW": 50.0,
    "TRANSFORMER_KVA": 1000.0,
    "PRIMARY_KV": 35.0,
    "SECONDARY_KV": 0.4,
}


__all__ = [
    "REFERENCE_IRRADIANCE_W_M2",
    "MINUTES_PER_HOUR",
    "DEGRADED_THRESHOLD",
    "OUT_OF_SERVICE_THRESHOLD",
    "DEDUP_WINDOW_SECONDS",
    "RECURRENCE_ESCALATION_THRESHOLD",
    "REOPEN_GRACE_DAYS",
    "RECONCILIATION_TOLERANCE",
    "RECONCILIATION_FLOOR",
    "SUBSIDY_MIN_PAYOUT_CNY",
    "APPROVAL_DUE_DAYS",
    "ARREARS_GRACE_DAYS",
    "BASIS_POINTS_TOTAL",
    "AGG_15MIN_BUCKET_MIN",
    "AGG_1H_BUCKET_MIN",
    "AGG_1DAY_BUCKET_MIN",
    "DEFAULT_LIMIT",
    "MIN_LIMIT",
    "MAX_LIMIT",
    "SECONDS_PER_DAY",
    "SECONDS_PER_HOUR",
    "TEST_DEFAULTS",
]
