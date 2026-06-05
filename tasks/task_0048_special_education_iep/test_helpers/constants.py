"""Domain thresholds — numeric constants from the PRD's calculations (PRD §3.3, §3.7, §3.8, §3.9)."""

# Eligibility composite (PRD §3.3)
ELIGIBILITY_THRESHOLD = 15.0
W_ADAPTIVE = 0.30
W_ACADEMIC = 0.20
GAP_WEIGHT_INITIAL = 0.5
GAP_WEIGHT_TRIENNIAL = 0.6

# LRE (PRD §3.8)
DAYS_PER_WEEK = 5
FULL_INCLUSION_FLOOR = 80.0
RESOURCE_FLOOR = 40.0

# Transition planning (PRD §3.9)
TRANSITION_AGE = 16

# Triennial reevaluation window (PRD §3.1, §3.2)
REEVAL_WINDOW_DAYS = 1095

# Pagination (PRD §2.3)
PAGINATION = {
    "default_limit": 10,
    "min_limit": 1,
    "max_limit": 100,
    "default_offset": 0,
}
