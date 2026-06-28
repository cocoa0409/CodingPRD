"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Recording fee
BASE_FIRST_PAGE_CENTS = 2500
ADDL_PAGE_CENTS = 500
INDEX_SURCHARGE_CENTS = 200
FREE_PARTY_ENTRIES = 4
DOCTYPE_SURCHARGE_CENTS = {
    "DEED": 1000,
    "MORTGAGE": 1500,
    "LIEN": 800,
    "UCC": 500,
    "PLAT": 3000,
    "OTHER": 0,
}

# Transfer tax / records-management surcharge
TAX_RATE_BPS = 55           # 0.55%
RMS_BPS = 13                # 0.13%
EXEMPT_THRESHOLD_CENTS = 10000   # consideration <= $100.00 is exempt (inclusive)

# Copy / search fees
CERTIFIED_COPY_FEE_CENTS = 1500
NAME_SEARCH_FEE_CENTS = 800

# Lien / UCC lapse + continuation + tax-lien grace
LIEN_LAPSE_YEARS = 5
CONTINUATION_WINDOW_DAYS = 180
TAX_LIEN_GRACE_DAYS = 30

# Examination margin
MIN_TOP_MARGIN_INCHES = 3.0

# Logical clock startup default
DEFAULT_CLOCK = "2026-01-01T00:00:00Z"
