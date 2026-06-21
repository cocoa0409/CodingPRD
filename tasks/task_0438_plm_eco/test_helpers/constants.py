"""Domain thresholds and well-known clock instants for PLM workflows.

NON_EXISTENT_UUID is provided by the framework. These values mirror the
contract literals used in the PRD costing, quorum, and clock narratives.
"""

# Logical clock default at server startup (PRD 2.4).
CLOCK_DEFAULT = "2026-01-01T00:00:00Z"

# Quorum default (PRD 3.5: "required_approvals quorum defaulting to 2").
DEFAULT_REQUIRED_APPROVALS = 2

# Pagination bounds (PRD 2.3).
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "MIN_OFFSET": 0,
}

# Convenience clock instants used by setup helpers when stepping past an
# effectivity_date or a deviation window.
CLOCK = {
    "EARLY_EFFECTIVITY": "2026-01-02T00:00:00Z",
    "PAST_EARLY": "2026-01-03T00:00:00Z",
}
