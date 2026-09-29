"""Numeric and temporal constants pinned by the PRD."""

# The logical clock reads exactly this instant before it has ever been set.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# Pagination.
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# Readiness scoring.
DECAY_HORIZON_DAYS = 360
READINESS_FLOOR = 80.00
DEFAULT_VALIDITY_DAYS = 180
MIN_VALIDITY_DAYS = 1
MAX_VALIDITY_DAYS = 3650
MIN_STEP_WEIGHT = 1
MAX_STEP_WEIGHT = 20

# Tier ceilings, in minutes.
TIER_RTO_CAP_MINUTES = {"TIER_1": 60, "TIER_2": 240, "TIER_3": 1440}
TIER_RPO_CAP_MINUTES = {"TIER_1": 15, "TIER_2": 60, "TIER_3": 1440}

# Criticality weight range on an application.
MIN_CRITICALITY_WEIGHT = 1
MAX_CRITICALITY_WEIGHT = 10

# Capacity units contributed per scoped group, by exercise type.
CAPACITY_UNITS_PER_GROUP = {
    "TABLETOP": 0,
    "COMPONENT_FAILOVER": 2,
    "FULL_SITE_FAILOVER": 6,
}

# Production-impact scoring.
IMPACT_TYPE_BASE = {"TABLETOP": 5, "COMPONENT_FAILOVER": 20, "FULL_SITE_FAILOVER": 40}
CAPACITY_COMPONENT_MULTIPLIER = 10
IMPACT_BAND_LEVEL_2_FLOOR = 40.00
IMPACT_BAND_LEVEL_3_FLOOR = 60.00
GOVERNANCE_SURCHARGE = {"LEVEL_1": 1, "LEVEL_2": 3, "LEVEL_3": 5}

# Site calendar.
FULL_SITE_COOLDOWN_MINUTES = 240

# States in which an exercise reserves recovery-site capacity.
RESERVING_EXECUTION_STATES = ("SCHEDULED", "IN_EXECUTION", "FAILOVER_COMPLETE")

# Finding escalation.
ESCALATION_FAILURE_THRESHOLD = 2

# Evidence manifest: one header line plus scope items, step executions and
# non-withdrawn findings.
MANIFEST_HEADER_LINES = 1

# Score comparison tolerance for two-decimal values.
SCORE_TOLERANCE = 0.01
