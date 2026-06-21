"""Domain thresholds and canonical numeric constants for the LIHTC Compliance API.

Derived from the PRD's calculation rules (§2.6, §3.1, §3.3, §3.5, §3.7, §3.8). Money is
in integer cents throughout; NON_EXISTENT_UUID is supplied by the framework.
"""

# Household-size factor in basis points by imputed household size (PRD §3.1).
HH_FACTOR_BP = {1: 7000, 2: 8000, 3: 9000, 4: 10000, 5: 10800, 6: 11600}

# AMI percentage by designation band (PRD §3.1).
AMI_PCT = {"AMI_40": 40, "AMI_50": 50, "AMI_60": 60, "AMI_80": 80}

# Credit factor in basis points by credit type (PRD §3.5).
CREDIT_BP = {"NINE_PERCENT": 900, "FOUR_PERCENT": 400}

THRESHOLDS = {
    "RENT_PCT": 30,                 # gross rent ceiling = 30% of annual income limit (PRD §3.1)
    "MONTHS": 12,                   # monthly figure (PRD §3.1)
    "OVER_INCOME_PCT": 140,         # over-income threshold = 140% of income limit (PRD §3.3)
    "UPCS_PASS_THRESHOLD": 60,      # inspection passes when score >= 60 (PRD §3.8)
    "UPCS_MAX_SCORE": 100,          # score = 100 - sum(deduction_points) (PRD §3.8)
    "INSPECTION_BUFFER_DAYS": 7,    # 7-day separation buffer (PRD §3.8)
    "TWENTY_FIFTY_PCT": 25,         # >= 25% designated (PRD §3.7)
    "FORTY_SIXTY_PCT": 40,          # >= 40% designated (PRD §3.7)
    "AVERAGE_INCOME_CEILING": 60.00,  # average designation <= 60.00 (PRD §3.7)
}

# ─── Canonical literals (project AMI = 96,000.00 -> 9_600_000 cents) ─────
# These are the pre-computed expected values used across the test suite. They are pinned
# to the PRD's stated formulas; do not recompute in tests — assert against these.
TEST_DEFAULTS = {
    "PROJECT_AMI_CENTS": 9_600_000,
    "BUILDING_ELIGIBLE_BASIS_CENTS": 100_000_000,
    # Unit AMI_50, br1, ua 9000:
    "AMI_50_BR1_INCOME_LIMIT_CENTS": 3_840_000,
    "AMI_50_BR1_GROSS_RENT_CEILING_CENTS": 96_000,
    "AMI_50_BR1_NET_MAX_RENT_CENTS": 87_000,
    "AMI_50_BR1_OVER_140_CENTS": 5_376_000,
    # Unit AMI_60, br2, ua 12500:
    "AMI_60_BR2_INCOME_LIMIT_CENTS": 5_184_000,
    "AMI_60_BR2_GROSS_RENT_CEILING_CENTS": 129_600,
    "AMI_60_BR2_NET_MAX_RENT_CENTS": 117_100,
    "AMI_60_BR2_OVER_140_CENTS": 7_257_600,
}
