"""Domain thresholds — numeric constants from the PRD's calculations and rules."""

# Residency adjudication threshold (PRD §3.1): RESIDENT requires proof_state_code
# matching declared_state_code AND continuous_months >= 12.
RESIDENCY_MIN_MONTHS = 12

# License-fee calculation (PRD §3.5).
NONRESIDENT_MULTIPLIER = 2.5
AGENT_SURCHARGE_CENTS = 300

# Draw priority-score / preference-point cap (PRD §3.8).
MAX_PREFERENCE_POINTS = 12

# Replacement admin-fee calculation (PRD §3.10).
REPLACEMENT_BASE_CENTS = 1500
TAG_REPLACEMENT_SURCHARGE_CENTS = 1000
NONRESIDENT_REPLACEMENT_SURCHARGE_CENTS = 500

# Pagination defaults (PRD §2.3).
DEFAULT_PAGE_LIMIT = 10
