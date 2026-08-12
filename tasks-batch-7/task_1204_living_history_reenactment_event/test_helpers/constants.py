"""Domain thresholds and shared values from the PRD's calculation rules."""

# PRD section 3.4: fixed inspection window and conflict buffer.
INSPECTION_WINDOW_MINUTES = 45
INSPECTION_BUFFER_MINUTES = 15

# PRD section 3.8: multi-day discount applies when requested_days >= 3.
VENDOR_MULTI_DAY_THRESHOLD_DAYS = 3

# PRD section 3.7: parking units per vehicle class.
OVERSIZE_UNITS = 2
STANDARD_UNITS = 1

# PRD section 3.1: max_minor_per_adult default when omitted.
DEFAULT_MAX_MINOR_PER_ADULT = 4

# PRD section 2.5: logical clock value at server startup.
STARTUP_LOGICAL_TIME = "2026-05-01T00:00:00Z"

# Canonical event timestamps used across the suite.
EVENT_STARTS_AT = "2026-07-10T08:00:00Z"
EVENT_ENDS_AT = "2026-07-12T18:00:00Z"
EARLY_BIRD_CUTOFF_AT = "2026-06-15T00:00:00Z"
VENDOR_INSURANCE_DEADLINE_AT = "2026-07-01T00:00:00Z"
AGREEMENT_EFFECTIVE_FROM = "2026-07-01T00:00:00Z"
AGREEMENT_EFFECTIVE_UNTIL = "2026-07-31T00:00:00Z"

# Canonical logical-clock positions used by pricing / settlement tests.
CLOCK_EARLY_BIRD = "2026-05-10T12:00:00Z"
CLOCK_AFTER_CUTOFF = "2026-06-20T12:00:00Z"
CLOCK_AT_CUTOFF = "2026-06-15T00:00:00Z"
CLOCK_MID_EVENT = "2026-07-11T00:00:00Z"
CLOCK_LATE_INSURANCE = "2026-07-02T09:00:00Z"
CLOCK_ON_TIME_INSURANCE = "2026-06-20T09:00:00Z"
CLOCK_SETTLEMENT_IN_FORCE = "2026-07-13T09:00:00Z"
CLOCK_AGREEMENT_LAPSED = "2026-08-02T00:00:00Z"

# Canonical expected amounts (integer cents), derived from the PRD formulas
# applied to the canonical event terms used by the fixtures:
#   adult_day 2599 x3 with 20% early bird: round_half_up(7797 * 0.8) = 6238
#   child_day 1200 x2 with 20% early bird: 2400 * 0.8 = 1920
#   + service fee 350 -> 8508 (quoted / early-bird final)
#   undiscounted: 7797 + 2400 + 350 = 10547 (final after the cutoff)
CANONICAL_QUOTED_TOTAL_CENTS = 8508
CANONICAL_FINAL_AFTER_CUTOFF_CENTS = 10547

# Canonical vendor fees: frontage 20 * days 3 * rate 900 = 54000;
# days >= 3 -> 54000 * 0.9 = 48600; max(48600, 5000) = 48600.
CANONICAL_VENDOR_PROVISIONAL_FEE_CENTS = 48600
# Late insurance adds the 2500 surcharge at settlement -> 51100.
CANONICAL_VENDOR_FINAL_LATE_FEE_CENTS = 51100
CANONICAL_VENDOR_LATE_BALANCE_CENTS = 2500
