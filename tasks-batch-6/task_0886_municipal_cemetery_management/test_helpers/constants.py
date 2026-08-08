"""Domain thresholds and constants from the PRD calculation rules (§2.6, §3)."""
from prd_bench_local_runner.testing import NON_EXISTENT_UUID  # noqa: F401

# Perpetual-care contribution (PRD §3.2)
CARE_PCT = 0.15
CARE_MIN_CENTS = 25000
RESALE_CARE_PCT = 0.10

# Interment service fee (PRD §3.3)
BASE_FEE_BY_PLOT_TYPE = {
    "GRAVE": 90000,
    "LAWN_CRYPT": 120000,
    "NICHE": 45000,
    "MAUSOLEUM": 150000,
}
DEPTH_TIER_2 = 15000
DEPTH_TIER_3PLUS = 30000
WEEKEND_SURCHARGE = 20000
HOLIDAY_SURCHARGE = 35000
SHORT_NOTICE_SURCHARGE = 25000
SHORT_NOTICE_DAYS = 3
HOLIDAYS = ["2026-01-01", "2026-07-04", "2026-11-26", "2026-12-25"]

# Taxation (PRD §2.6)
TAX_RATE = 0.0725

# Disinterment (PRD §3.6)
DISINTERMENT_FEE_CENTS = 200000
RELOC_CREDIT_PCT = 0.50
REMOVAL_REFUND_PCT = 0.25

# Marker foundation fee (PRD §3.5)
MARKER_FEE_BY_TYPE = {
    "FLAT": 15000,
    "UPRIGHT": 30000,
    "MONUMENT": 60000,
}

# Crew scheduling (PRD §3.3)
CREW_BUFFER_MINUTES = 60

# Logical clock startup default (PRD §2.8)
CLOCK_DEFAULT = "2026-05-01T00:00:00Z"
