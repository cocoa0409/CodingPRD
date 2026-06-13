"""Domain thresholds and rates from the PRD's fee and proration math.

NON_EXISTENT_UUID is provided by the framework barrel for missing-resource tests.
"""

# Oversize fee (PRD §3.5)
TIER_MAX_DIM_CM = {"SMALL": 30, "MEDIUM": 50, "LARGE": 80, "XL": 120}
TIER_MAX_WEIGHT_G = {"SMALL": 2000, "MEDIUM": 5000, "LARGE": 15000, "XL": 40000}
DIM_BUCKET_CM = 10
WT_BUCKET_G = 1000
OVERSIZE_DIM_RATE_CENTS = 150
OVERSIZE_WT_RATE_CENTS = 80
OVERSIZE_FEE_CAP_CENTS = 2000

# Overstay fee (PRD §3.5)
GRACE_DAYS = 2
OVERSTAY_DAILY_RATE_CENTS = {"SMALL": 200, "MEDIUM": 300, "LARGE": 500, "XL": 800}

# Forwarding fees (PRD §3.7)
FORWARD_FEE_CENTS = 600
SCAN_FEE_CENTS = 150
PACKAGE_FORWARD_FEE_CENTS = 1200

# Proration / lifecycle windows (PRD §3.3, §3.6, §3.7)
DAYS_PER_MONTH = 30
SUSPEND_BALANCE_THRESHOLD_CENTS = 5000
ABANDONMENT_GRACE_DAYS = 30
PACKAGE_ABANDON_DAYS = 14

# Common defaults used to build reproducible fixtures.
TEST_DEFAULTS = {
    "MONTHLY_FEE_CENTS": 3000,
    "TERM_MONTHS": 1,
    "BASE_CLOCK": "2026-06-01T00:00:00.000Z",
}
