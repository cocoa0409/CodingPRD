"""Domain thresholds and calculation constants.

Numeric values are pinned by the PRD's calculation narratives (§3.6, §3.8)
and the logical-clock contract (§2.5).
"""

# Logical clock default at server startup (PRD §2.5)
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Interchange rate table (basis points) — PRD §3.6
BASE_RATE_BP_BY_NETWORK_AND_TIER = {
    "VISA": {"QUALIFIED": 145, "MID_QUALIFIED": 185, "NON_QUALIFIED": 230},
    "MASTERCARD": {"QUALIFIED": 148, "MID_QUALIFIED": 188, "NON_QUALIFIED": 235},
    "STAR": {"QUALIFIED": 90, "MID_QUALIFIED": 130, "NON_QUALIFIED": 175},
    "PULSE": {"QUALIFIED": 85, "MID_QUALIFIED": 125, "NON_QUALIFIED": 170},
}
PER_ITEM_CENTS_BY_NETWORK = {"VISA": 10, "MASTERCARD": 11, "STAR": 5, "PULSE": 5}
COMMERCIAL_UPLIFT_BP = 65

# Qualification tier thresholds (seconds) — PRD §3.6
T1_SECONDS = 86400    # 24h — inclusive upper bound for QUALIFIED
T2_SECONDS = 172800   # 48h — exclusive; >T2 → NON_QUALIFIED

# Blocked MCC list per network — PRD §3.6
BLOCKED_MCC_LIST = {
    "VISA": ["7995", "6012"],
    "MASTERCARD": ["7995"],
    "STAR": [],
    "PULSE": [],
}

# Activation-token lifetime (PRD §3.4): expires_at = issued_at + 72 hours
ACTIVATION_TOKEN_TTL_SECONDS = 72 * 3600

# Reissue campaign volume discount (PRD §3.8): 4% on total, floor
VOLUME_DISCOUNT_NUMERATOR = 4
VOLUME_DISCOUNT_DENOMINATOR = 100

# Reissue successor expiry offset (PRD §3.8): now + 36 months
REISSUE_EXPIRY_MONTHS = 36

# Pagination defaults (PRD §2.3)
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MAX_LIMIT = 100
PAGINATION_MIN_LIMIT = 1
