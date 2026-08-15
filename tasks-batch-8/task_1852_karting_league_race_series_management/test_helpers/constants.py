"""Domain thresholds and shared values — numeric constants from PRD sections
3.4, 3.5 and 3.8, plus the standard class/event fixtures used across tests."""

# PRD 3.4: the second failed inspection disqualifies the entry outright.
TECH_FAIL_DISQUALIFY_THRESHOLD = 2

# PRD 3.5: the fastest-lap bonus applies only when the fastest finisher placed
# tenth or better.
FASTEST_LAP_MAX_POSITION = 10

# PRD 3.8: practice billing — FLAT is a fixed 4000 cents; METERED multiplies the
# minutes used by 150 cents per minute and applies 8.25% tax, rounded half-up
# to whole cents per booking at check-out.
FLAT_SESSION_FEE_CENTS = 4000
RATE_CENTS_PER_MINUTE = 150
TAX_RATE = 0.0825

# Standard SENIOR class window: ages 16-44 inclusive, 170.0 kg minimum combined
# weight, 5000-cent entry fee, rentals admitted.
SENIOR_MIN_AGE = 16
SENIOR_MAX_AGE = 44
SENIOR_MIN_COMBINED_WEIGHT_KG = 170.0
SENIOR_ENTRY_FEE_CENTS = 5000

# A measured weight comfortably above the SENIOR minimum (passes inspection).
PASSING_WEIGHT_KG = 171.0

# Points schemes used across tests.
DEFAULT_POINTS_SCHEME = [25, 22, 20]
FULL_POINTS_SCHEME = [25, 22, 20, 18, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1]

# Event dates used across tests.
DEFAULT_EVENT_DATE = "2026-09-05T00:00:00Z"
SECOND_EVENT_DATE = "2026-09-19T00:00:00Z"
