"""Domain thresholds — numeric constants from the PRD's billing rules.

Generic NON_EXISTENT_UUID is imported from the framework. A second
fabricated UUID is provided for body-FK (ERR_REFERENCE_NOT_FOUND) tests.
"""

# 30-day fixed billing cycle / proration / recognition window (PRD §3.5, §3.6, §3.8).
CYCLE_DAYS = 30
RECOGNITION_DAYS = 30

# Dunning schedule (PRD §3.7): max 3 attempts; retry offsets in days indexed
# by dunning_attempt (1 -> +3 days, 2 -> +7 days; the initial attempt is +0).
DUNNING_MAX_ATTEMPTS = 3
DUNNING_RETRY_OFFSETS_DAYS = [0, 3, 7]

# Buffered-gap rule for pause windows (PRD §3.9): 7-day buffer on each side.
MIN_PAUSE_GAP_DAYS = 7

# Tax basis-point denominator (PRD §3.6 step 4).
TAX_BPS_DENOMINATOR = 10000

# Pagination bounds (PRD §2.3).
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_LIMIT_DEFAULT = 10

# A second non-existent UUID for body-FK reference-not-found scenarios.
NON_EXISTENT_PLAN_ID = "00000000-0000-4000-8000-000000000000"
