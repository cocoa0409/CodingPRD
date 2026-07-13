"""Domain thresholds — numeric constants drawn from the PRD calculations (§3, §2)."""

# Engraving charge (PRD §3.2)
ENGRAVE_RATE_CENTS = {"HUMAN": 250, "PET": 180}
VOLUME_DISCOUNT_PCT = 15

# Material / size-tier pricing (PRD §3.2)
MATERIAL_RATE_CENTS = {"GRANITE": 8, "BRONZE": 15, "MARBLE": 11}
SIZE_TIER_MED_CM2 = 3000
SIZE_TIER_LARGE_CM2 = 6000
SIZE_TIER_MED_PCT = 110
SIZE_TIER_LARGE_PCT = 125

# Contract & deposit (PRD §3.2)
FOUNDATION_FLAT_CENTS = 45000
DEPOSIT_PCT = 0.40

# Restoration costing (PRD §3.8)
RESTORE_RATE_CENTS = {"CLEANING": 2, "REPAIR": 6, "REFINISH": 9}
SEVERE_SURCHARGE_CENTS = 5000

# Warranty window (PRD §3.6)
WARRANTY_MONTHS = {"HUMAN": 120, "PET": 60}

# Crew scheduling buffer (PRD §2.7)
CREW_BUFFER_MINUTES = 60

# Logical clock startup default (PRD §2.11)
CLOCK_STARTUP_DEFAULT = "2026-03-01T00:00:00Z"

# Pagination defaults (PRD §2.3)
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# Canonical order economics used across setups
# (Restful Pines GRANITE 60x40 HUMAN [20,20], permit_fee 12000):
#   provisional merchandise 27700, contract 84700, deposit 33880, balance 50820.
CANON_DEPOSIT_CENTS = 33880
CANON_CONTRACT_CENTS = 84700
