"""Domain thresholds and numeric constants from the PRD's calculations.

Generic NON_EXISTENT_UUID comes from the framework; a well-formed but
absent UUID is also provided for path/FK not-found tests.
"""

# Cycle / proration / refund math (PRD Sections 3.5, 3.10, 3.8).
CYCLE_DAYS = 30

# SINGLE_WASH cancellation per-wash value (PRD Section 3.10).
PER_WASH_VALUE_CENTS = 400

# Fleet volume-discount tiers keyed on active_vehicle_count (PRD Section 2.10).
FLEET_TIER_2_PCT = 0.05   # count >= 2
FLEET_TIER_5_PCT = 0.10   # count >= 5
FLEET_TIER_10_PCT = 0.15  # count >= 10

# Usage-intensity abuse caps (PRD Section 3.7).
ACUTE_CAP = 8
CHRONIC_CAP = 12.00

# Invoice retry maximum attempts (PRD Section 3.4).
MAX_ATTEMPTS = 3

# A syntactically valid UUID that names no persisted resource.
ABSENT_UUID = "00000000-0000-4000-8000-000000000000"
