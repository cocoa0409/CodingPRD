"""Domain constants taken verbatim from PRD §3 / scaffold §1.3.

Centralised so every calculation references the same pinned values.
"""

# Credit-band ordering (PRD §3.2 soft pull; positions 0..3).
BAND_ORDER = ["SUBPRIME", "NEAR_PRIME", "PRIME", "SUPER_PRIME"]
FICO_BANDS = set(BAND_ORDER)

RATE_TYPES = {"FIXED", "VARIABLE"}
POOL_RATE_TYPES = {"FIXED", "VARIABLE", "ANY"}
MEMBER_TIERS = {"NONE", "SILVER", "GOLD", "PLATINUM"}
TERM_MONTHS = {60, 84, 120, 180, 240}
FORBEARANCE_REASONS = {"JOB_LOSS", "MEDICAL", "NATURAL_DISASTER", "OTHER"}

ROLES = {
    "Borrower",
    "Cosigner",
    "Underwriter",
    "DisbursementOfficer",
    "ServicingAgent",
    "PlatformAdmin",
}

# DTI amortization factors keyed on requested term (PRD §3.2 / scaffold §1.3).
AMORT_FACTORS = {
    60: "0.0188",
    84: "0.0142",
    120: "0.0110",
    180: "0.0080",
    240: "0.0065",
}
MAX_DTI_RATIO = "0.4300"

# estimated_apr band surcharge in bps (PRD §3.2 / scaffold §1.3).
BAND_SURCHARGE_BPS = {
    "SUBPRIME": 300,
    "NEAR_PRIME": 150,
    "PRIME": 50,
    "SUPER_PRIME": 0,
}

# locked_apr discounts (PRD §3.4 / scaffold §1.3).
AUTOPAY_DISCOUNT_BPS = 25
MEMBER_DISCOUNT_BPS = {"NONE": 0, "SILVER": 10, "GOLD": 25, "PLATINUM": 50}
APR_FLOOR_BPS = 200

# Offer time-to-live (PRD §3.2): expires_at = clock_now + 48 hours.
OFFER_TTL_HOURS = 48

# Interest accrual (PRD §3.9).
DAYS_PER_YEAR = 365

# On-time determination / cosigner release (PRD §3.9, §3.10).
GRACE_DAYS = 5
COSIGNER_RELEASE_STREAK = 3
