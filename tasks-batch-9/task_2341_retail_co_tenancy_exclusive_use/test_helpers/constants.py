"""Numeric and textual constants pinned by the PRD.

Everything here is a value the PRD states literally: pagination defaults, the
logical-clock default instant, the rent-reduction tier table, the abatement
accrual convention, the estoppel fee schedule, the exclusive-use scope severity
ranking and the posture thresholds.
"""

# --------------------------------------------------------------------------
# Envelope / pagination (PRD §2.2, §2.3)
# --------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

RESPONSE_META_FIELDS = ("api_request_id", "api_request_timestamp")
PAGINATION_META_FIELDS = ("limit", "offset", "total_count", "has_more")

# --------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# --------------------------------------------------------------------------
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# --------------------------------------------------------------------------
# Entity defaults (PRD §3)
# --------------------------------------------------------------------------
DEFAULT_OCCUPANCY_GRACE_DAYS = 90
DEFAULT_CONDITION_GRACE_PERIOD_DAYS = 30
DEFAULT_CONDITION_CURE_PERIOD_DAYS = 120
DEFAULT_REQUIRED_ANCHOR_COUNT = 0
DEFAULT_MAX_REDUCTION_PCT = 50.0
DEFAULT_GLA_CARVE_OUT_SQFT = 0
DEFAULT_INCIDENTAL_SALES_PCT_CAP = 0.0
DEFAULT_PROTECTED_BASELINE_CENTS = 0
DEFAULT_NOTICE_CURE_PERIOD_DAYS = 30
DEFAULT_CURE_EXTENSION_DAYS = 0
MAX_CURE_EXTENSION_DAYS = 90
DEFAULT_PROJECTED_INCIDENTAL_SALES_PCT = 0.0
DEFAULT_REMOVED_GLA_SQFT = 0
DEFAULT_SUBSTITUTION_ALLOWED = False
DEFAULT_MIN_SUBSTITUTE_GLA_SQFT = 0

# --------------------------------------------------------------------------
# Co-tenancy rent reduction (PRD §3.5)
# --------------------------------------------------------------------------
MIN_REDUCTION_PCT = 5.0
ANCHOR_DARK_BONUS_PCT = 10.0
SUBSTITUTE_RENT_SHORTFALL_PCT = 20.0
TIER_1_MAX_SHORTFALL_PCT = 5.0
TIER_1_MULTIPLIER = 1.0
TIER_2_MAX_SHORTFALL_PCT = 15.0
TIER_2_MULTIPLIER = 1.5
TIER_3_MULTIPLIER = 2.0

# --------------------------------------------------------------------------
# Abatement ledger accrual (PRD §2.7, §3.5)
# --------------------------------------------------------------------------
DAYS_PER_ACCRUAL_MONTH = 30
ACCRUAL_MONTHS_DECIMAL_PLACES = 4

# --------------------------------------------------------------------------
# Estoppel fee assessment (PRD §3.8)
# --------------------------------------------------------------------------
BASE_ESTOPPEL_FEE_CENTS = 25000
PER_DISCLOSURE_FEE_CENTS = 5000
BREACH_DISCLOSURE_FEE_CENTS = 15000
TIER_A_MAX_SUBTOTAL_CENTS = 40000
TIER_A_SURCHARGE_PCT = 10.0
TIER_B_MAX_SUBTOTAL_CENTS = 75000
TIER_B_SURCHARGE_PCT = 15.0
TIER_C_SURCHARGE_PCT = 20.0

# --------------------------------------------------------------------------
# Exclusive-use screening severity (PRD §3.2)
# --------------------------------------------------------------------------
SCOPE_SEVERITY = {
    "CENTER_WIDE": 3,
    "RADIUS_INCLUSIVE": 2,
    "PAD_EXCLUDED": 1,
}

# --------------------------------------------------------------------------
# Center posture derivation (PRD §2.6)
# --------------------------------------------------------------------------
FREEZE_BREACHED_CONDITION_COUNT = 2
FREEZE_OCCUPANCY_PCT = 50.0
WATCH_OCCUPANCY_PCT = 70.0

# --------------------------------------------------------------------------
# Optimistic concurrency field names (PRD §2.8)
# --------------------------------------------------------------------------
EXPECTED_CENTER_VERSION_FIELD = "expected_center_version"
EXPECTED_LEASE_VERSION_FIELD = "expected_lease_version"

# --------------------------------------------------------------------------
# Records without the common mutable fields (PRD §2.4)
# --------------------------------------------------------------------------
IMMUTABLE_RECORD_FIELDS = ("id", "created_at")
