"""Domain thresholds and shared values (PRD §2.4, §3.6, §3.9)."""

# Logical clock startup default (PRD §2.4).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_DATE = "2026-08-01"

# Current disclosure version used by the standard program config.
DISCLOSURE_VERSION = "D1"

# Waiver authority caps in cents (PRD §3.6).
TELLER_CAP_CENTS = 5000
SUPERVISOR_CAP_CENTS = 20000
MANAGER_CAP_CENTS = 100000

# Scrutiny thresholds (PRD §3.9).
SCRUTINY_WAIVER_RATIO_BPS = 1500
SCRUTINY_AVG_FEES_CENTI = 1200

# Standard program configuration shared by most scenarios.
STANDARD_PROGRAM = {
    "fee_amount_cents": 3500,
    "daily_fee_cap_cents": 10500,
    "max_daily_fees_count": 3,
    "de_minimis_threshold_cents": 500,
    "sustained_overdraft_days_threshold": 5,
    "sustained_overdraft_fee_cents": 3000,
    "charge_off_grace_business_days": 10,
    "notice_window_days": 30,
    "steering_fee_count_threshold": 6,
    "steering_window_days": 90,
    "offer_expiry_days": 30,
    "posting_order_policy": "CHRONOLOGICAL",
    "current_disclosure_version": DISCLOSURE_VERSION,
}

# Monday-Friday business dates used across scenarios (PRD §2.4).
MON = "2026-08-03"
TUE = "2026-08-04"
WED = "2026-08-05"
THU = "2026-08-06"
FRI = "2026-08-07"
SATURDAY = "2026-08-08"
SUNDAY = "2026-08-09"
