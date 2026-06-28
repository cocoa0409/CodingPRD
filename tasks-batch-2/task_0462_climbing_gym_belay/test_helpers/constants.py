"""Domain thresholds — numeric constants from the PRD's quantitative rules.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Money / pricing constants (PRD section 3.7)
DAY_PASS_BASE_CENTS = 2500
GEAR_BUNDLE_CENTS = 1200
YOUTH_DISCOUNT_RATE = 0.20

BASIC_FEE_CENTS = 9000
YOUTH_TEAM_FEE_CENTS = 6000

LATE_FEE_PER_DAY_CENTS = 800
RENTAL_DUE_HOURS = 24

# Time windows (PRD sections 3.1, 3.2, 3.4, 3.3)
WAIVER_VALID_DAYS = 365
CERT_VALID_DAYS = 365
CYCLE_DAYS = 30
GRACE_DAYS = 7

# Certification pass rule (PRD section 3.4 / 3.7)
CERT_PASS_THRESHOLD = 80
CERT_STATION_FLOOR = 60

# Route difficulty multipliers (PRD section 3.7)
SLAB_MULT = 1.0
OVERHANG_MULT = 1.25
ROOF_MULT = 1.50

# A syntactically-valid UUID that is never minted by the server (for 404 tests).
NONEXISTENT_UUID = "00000000-0000-4000-8000-000000000000"

# Default clock anchor used across most setups.
DEFAULT_CLOCK = "2026-06-01T00:00:00Z"
