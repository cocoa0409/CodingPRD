"""Domain thresholds — numeric constants from the PRD calculation rules."""

# Chaperone ratio: one chaperone per N signed students, selected by grade band.
RATIO_BY_BAND = {
    "ELEMENTARY": 8,
    "MIDDLE": 12,
    "HIGH": 15,
}

# Extra chaperone added when the trip has a water activity.
WATER_EXTRA = 1

# Travel buffer (seconds) applied on each side of a trip window when checking
# whether a guardian can be cleared as a chaperone on two overlapping trips.
TRAVEL_BUFFER_SECONDS = 3600

# Pagination defaults / bounds from the global response contract.
PAGINATION = {
    "default_limit": 10,
    "min_limit": 1,
    "max_limit": 100,
    "default_offset": 0,
}
