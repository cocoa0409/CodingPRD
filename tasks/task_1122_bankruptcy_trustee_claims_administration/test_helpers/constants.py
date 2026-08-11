"""Domain thresholds — numeric constants from PRD calculations (§3.4, §3.5, §3.7)."""

# §326(a)-style trustee commission tiers (PRD §3.7), amounts in cents.
COMMISSION_T1_CAP_CENTS = 500000        # first $5,000 of basis at 25%
COMMISSION_T2_CAP_CENTS = 4500000       # next $45,000 of basis at 10%
COMMISSION_T3_CAP_CENTS = 95000000      # next $950,000 of basis at 5%
COMMISSION_T4_THRESHOLD_CENTS = 100000000  # everything above $1,000,000 at 3%

# Preference / fraudulent-transfer lookback windows in whole days (PRD §3.5).
PREFERENCE_NON_INSIDER_DAYS = 90
PREFERENCE_INSIDER_DAYS = 365
FRAUDULENT_TRANSFER_DAYS = 730

# Sale minimum-price gate (PRD §3.4): gross >= max(sale_costs, half of scheduled value).
MIN_FRACTION_OF_SCHEDULED = 0.50

# Logical clock (PRD §2.4): server startup default logical time.
DEFAULT_LOGICAL_TIME = "2026-05-01T00:00:00Z"

# Default objection window (PRD §3.1): days a sale order or fee approval sits.
DEFAULT_OBJECTION_WINDOW_DAYS = 30

TEST_DEFAULTS = {
    "TRUSTEE_USER_ID": "trust-0001",
    "FILED_ON": "2026-01-15T00:00:00Z",
    "BAR_DATE": "2026-06-01T00:00:00Z",
}
