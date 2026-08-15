"""Domain thresholds — numeric constants from the PRD's pricing, scheduling, and audit rules."""

# Fee constants (PRD §3.4, §3.8)
BASE_FEE_CENTS = {"PURCHASE_SALE": 39500, "LISTING_ONLY": 29500}
RUSH_THRESHOLD_DAYS = 10
RUSH_SURCHARGE_CENTS = 7500
FREE_AMENDMENTS = 1
AMENDMENT_FEE_CENTS = 5000
SUBSCRIPTION_DISCOUNT_PCT = 0.05

# Deadline day-count (PRD §2.9)
BUSINESS_DAY_STATES = ["NY"]

# Reminder schedule (PRD §3.4)
REMINDER_OFFSETS_DAYS = [5, 2, 0]
REMINDER_HOUR_UTC = 9

# Compliance audit state-mandated disclosures (PRD §3.7)
STATE_REQUIRED_DISCLOSURES = {
    "TX": ["T47_DISCLOSURE"],
    "NY": ["NHD_REPORT"],
    "CA": ["TDS_DISCLOSURE", "NHD_REPORT"],
    "CO": [],
}

# Closing calendar minimum gap (PRD §3.4): difference of 0 or 1 day conflicts; 2 or more allowed
MIN_CLOSING_GAP_DAYS = 2

# Logical clock startup default (PRD §2.8)
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"
CLOCK_DEFAULT_DATE = "2026-08-01"

# Common fixture coordinates
DEFAULT_EFFECTIVE_DATE = "2026-08-03"
DEFAULT_CLOSING_DATE = "2026-08-31"
DEFAULT_LIST_PRICE_CENTS = 45000000

# A well-formed UUID that no test ever registers
ABSENT_UUID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
