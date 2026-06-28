"""Domain thresholds — numeric constants from the PRD calculations.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Pentobarbital dosing (PRD §3.5 / §2.8)
DOSE_PER_KG_ML = 0.2
MIN_FLOOR_ML = 1.0
# At weight_kg == 5.0, weight-derived volume (1.0) equals the floor.
DOSE_FLOOR_BOUNDARY_KG = 5.0

# Clinician-travel buffer for same-route stop overlap (PRD §3.3)
TRAVEL_BUFFER_MIN = 30

# Pagination defaults (PRD §2.3)
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# Logical clock startup default (PRD §2.10)
CLOCK_DEFAULT_UTC = "2026-01-01T00:00:00Z"
