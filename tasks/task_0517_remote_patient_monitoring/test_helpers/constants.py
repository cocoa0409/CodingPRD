"""Domain thresholds — numeric constants from the PRD's calculations and bands."""

# Breach threshold bands (§2.9)
BREACH_THRESHOLDS = {
    "BP_SYS_WARN": 140,
    "BP_SYS_CRIT": 180,
    "BP_DIA_WARN": 90,
    "BP_DIA_CRIT": 120,
    "GLU_HI_WARN": 250,
    "GLU_HI_CRIT": 400,
    "GLU_LO_WARN": 70,
    "GLU_LO_CRIT": 54,
    "SPO2_WARN": 92,
    "SPO2_CRIT": 88,
    "WEIGHT_GAIN_KG": 1.4,
}

# Care-time aggregation (§3.7)
MAX_MINUTES_PER_DAY = 60
CARE_TIME_FLOOR = 20  # 99457 eligibility floor (§3.8)

# Billing eligibility (§3.8)
DEVICE_DAY_FLOOR = 16  # 99454 eligibility floor

# Payer defaults (§3.1)
DEFAULT_TIMELY_FILING_DAYS = 90
DEFAULT_REQUIRES_ACTIVE_CONSENT = True

# Logical clock default (§2.12)
CLOCK_DEFAULT = "2026-05-01T00:00:00Z"

# Standard Medicare-ish rate set used across difficulty fixtures.
RATE_99453_CENTS = 1965
RATE_99454_CENTS = 4774
RATE_99457_CENTS = 4877
