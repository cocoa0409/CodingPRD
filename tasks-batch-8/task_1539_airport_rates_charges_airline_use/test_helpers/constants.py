"""Domain thresholds and shared values — numeric constants from the PRD."""

# Fixed startup reading of the logical clock (PRD: the logical clock section).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # Non-signatory landing fee markup percent applied to the signatory fee.
    "NON_SIGNATORY_MARKUP_PCT": 125,
    # Landing-fee charge unit size in kilograms.
    "RATE_UNIT_KG": 1000,
    # Remainder at or above this many kilograms rounds up one full unit.
    "REMAINDER_ROUND_UP_KG": 500,
    # Minimum consultation period: adopt allowed at created_at + this many days.
    "CONSULTATION_MIN_DAYS": 30,
    # Countersign deadline: adopted_at + this many days.
    "COUNTERSIGN_WINDOW_DAYS": 30,
    # Dispute window length in days from publish-review or last resolve.
    "DISPUTE_WINDOW_DAYS": 45,
    # Payment due date stamped on each line at publish-review.
    "PAYMENT_DUE_DAYS": 60,
    # PFC per-passenger charge in cents ($4.50).
    "PFC_PER_PAX_CENTS": 450,
    # Annual cap on collectible enplaned passengers.
    "PFC_ANNUAL_CAP_PAX": 2000000,
    # Occupancy overlay threshold percent of gross rentable square footage.
    "OCCUPANCY_HIGH_TIER_PCT": 85,
    # Signatory-volume rebate percent under the occupancy overlay.
    "VOLUME_REBATE_PCT": 5,
}

# Standard logical-clock waypoints used across tests.
CLOCK_AT_ADOPT = "2026-09-01T00:00:00Z"
CLOCK_AT_ACTIVITY = "2026-09-10T00:00:00Z"
CLOCK_AT_VOTING = "2026-09-30T00:00:00Z"
CLOCK_PAST_DUE = "2027-01-15T00:00:00Z"

# Standard activity date: inside the year's window and before the voting and
# settlement waypoints above.
DEFAULT_ACTIVITY_DATE = "2026-09-05T00:00:00Z"
