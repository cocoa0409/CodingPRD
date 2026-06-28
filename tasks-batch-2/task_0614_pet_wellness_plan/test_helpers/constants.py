"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# DENTAL weight-surcharge tiers (à-la-carte pricing, PRD §3.5).
DENTAL_MED_KG = 10
DENTAL_LARGE_KG = 25
DENTAL_MED_SURCHARGE_CENTS = 1500
DENTAL_LARGE_SURCHARGE_CENTS = 4000

# Catalogue default base unit prices when a plan has no inclusion line (PRD §3.5).
CATALOG_DEFAULT_UNIT_CENTS = {
    "EXAM": 6000,
    "VACCINE": 3500,
    "DENTAL": 22000,
}

# Renewal window (PRD §3.9): renewal opens 7 days before term ends_at.
RENEWAL_WINDOW_DAYS = 7

# Early-termination fee (PRD §3.8).
EARLY_TERMINATION_FEE_CENTS = 5000

# Contract-term length.
TERM_LENGTH_DAYS = 365

# Pagination defaults (PRD §2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MAX_LIMIT = 100

# Server-startup clock default (PRD §2.4).
CLOCK_DEFAULT_UTC = "2026-01-01T00:00:00.000Z"
