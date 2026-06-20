"""Domain thresholds — numeric constants drawn from the PRD's calculation rules."""

# Patient-responsibility tiered coinsurance rates (PRD §3.7)
COINSURANCE_RATES = {
    "MEDICARE": 0.20,
    "COMMERCIAL": 0.10,
    "SELF_PAY": 1.00,
}

# Patient-assistance caps and incidental surcharge (PRD §3.7), integer cents
ASSISTANCE_CAP_CENTS = 50000          # $500.00 estimate cap
ASSISTANCE_CAP_CENTS_FINAL = 60000    # $600.00 final cap
INCIDENTAL_SURCHARGE_CENTS = 7500     # $75.00 disclosure/counseling surcharge

# QNS minimum DNA yield per specimen type (nanograms) (PRD §3.4)
QNS_MIN_NG = {
    "BLOOD": 50,
    "SALIVA": 30,
    "TISSUE": 100,
}

# Pathogenicity weighting (PRD §3.10)
PATHOGENICITY_POINTS = {
    "BENIGN": 0,
    "LIKELY_BENIGN": 1,
    "VUS": 2,
    "LIKELY_PATHOGENIC": 4,
    "PATHOGENIC": 8,
}
INCIDENTAL_WEIGHT = 2
MAX_PER_GENE_PTS = 8

# Incidental-findings policy minor/adult boundary (PRD §3.8)
ADULT_AGE_YEARS = 18

# Sequencer default turnaround buffer (PRD §3.5)
DEFAULT_TURNAROUND_BUFFER_MINUTES = 60

# Pagination defaults (PRD §2.3)
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MAX_LIMIT = 100

# Test-fixed clock instant used across the design indices.
DEFAULT_CLOCK = "2026-06-19T00:00:00.000Z"
