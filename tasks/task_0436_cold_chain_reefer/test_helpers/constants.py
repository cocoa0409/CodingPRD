"""Domain thresholds — numeric constants from the PRD's calculations."""

# Impairment classification (PRD §2.8): tolerance default + partial span.
DEFAULT_TOLERANCE_DEGREE_MINUTES = 30
TOL_PARTIAL_SPAN = 90  # PARTIAL band width above tolerance

# Detention fee (PRD §3.9)
FREE_TIME_MIN = 120
DET_TIER1_MAX = 4
RATE1_CENTS = 5000
RATE2_CENTS = 7500

# Lumper fee (PRD §3.9)
LUMPER_BASE_CENTS = 7500
PER_PALLET_CENTS = 350
MULTITEMP_SURCHARGE_CENTS = 2500

# Load-integrity score (PRD §3.7)
PRECOOL_PENALTY = 30
DOOR_PENALTY = 5
DOOR_FREE = 2
EXC_PER_DEGREE_HOUR = 10

# Stop window overlap (PRD §3.9)
STOP_SERVICE_MIN = 60
STOP_BUFFER_MIN = 30

# Carrier defaults (PRD §3.1)
DEFAULT_LIABILITY_CAP_CENTS = 5000000

# Pagination (PRD §2.3)
DEFAULT_LIMIT = 10
MAX_LIMIT = 100

# A syntactically-valid UUID that resolves to nothing.
NONEXISTENT_UUID = "00000000-0000-4000-8000-000000000000"
