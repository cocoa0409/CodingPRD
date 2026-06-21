"""Domain thresholds — numeric constants drawn from PRD §3.6, §3.7, §3.8."""

# PRD §3.6 — lottery weighting formula constants.
BASE_WEIGHT = 1.000
SIBLING_BOOST = 0.500
IN_BOUNDARY_BOOST = 0.300
POVERTY_INDEX_MAX_BOOST = 0.400  # at 100% catchment poverty
FAMILY_POVERTY_FLAG_BOOST = 0.200

# PRD §3.6 — inter-district-transfer cap fraction (floor(0.10 * total_seats)).
IDT_CAP_FRACTION = 0.10

# PRD §3.7 — family risk score weights and clamp.
DECLINED_WEIGHT = 0.35
WAITLISTED_WEIGHT = 0.15
ENROLLED_WEIGHT = -0.20
RISK_MIN_SCORE = 0.000
RISK_MAX_SCORE = 1.000

# PRD §3.8 — school acceptance rate "competitive" threshold (strict less-than).
ACCEPTANCE_RATE_HOT_THRESHOLD = 0.300

# Common test clock defaults.
DEFAULT_CLOCK_ISO = "2026-01-01T00:00:00Z"
DEFAULT_OPENS_AT = "2026-01-02T00:00:00Z"
DEFAULT_CLOSES_AT = "2026-02-01T00:00:00Z"
DEFAULT_LOTTERY_RUNS_AT = "2026-02-02T00:00:00Z"
DEFAULT_CYCLE_LABEL = "2026-27"

# Choice-rank bounds (PRD §3.4: "an integer from 1 to 5 inclusive").
MIN_CHOICE_RANK = 1
MAX_CHOICE_RANK = 5

# Grade bounds (PRD §3.1: "kindergarten is grade 0, ... `grade_max` may not
# exceed 12").
MIN_GRADE = 0
MAX_GRADE = 12

# Offer response window (PRD §3.5: "respond_by is exactly seven days after offered_at").
OFFER_RESPONSE_DAYS = 7
