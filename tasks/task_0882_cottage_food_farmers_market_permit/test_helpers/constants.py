"""Domain thresholds — numeric constants from PRD calculations."""

# Permit term (PRD §2.5): a permit is issued for a fixed term of exactly 365 days.
PERMIT_TERM_DAYS = 365

# Annual sales caps (PRD §3.3), integer cents.
ANNUAL_CAP_CENTS = {
    "CLASS_A": 7_500_000,
    "CLASS_B": 15_000_000,
}

# Permit fee assembly (PRD §3.3), integer cents.
BASE_FEE_BY_CLASS = {"CLASS_A": 2_500, "CLASS_B": 7_500}
INSPECTION_SURCHARGE = 3_000
# Worked totals from PRD §3.3.
PERMIT_FEE_CENTS = {"CLASS_A": 5_000, "CLASS_B": 15_500}

# Booth settlement (PRD §3.5).
MARKET_FEE_RATE = 0.06

# Sales-cap reporting (PRD §3.8).
SAMPLING_EXEMPTION_CENTS = 50_000

# Recall liability projected units by severity (PRD §3.7).
PROJECTED_UNITS_BY_SEVERITY = {"LOW": 10, "MEDIUM": 50, "HIGH": 200}

# Startup logical clock (PRD §2.5).
DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"
