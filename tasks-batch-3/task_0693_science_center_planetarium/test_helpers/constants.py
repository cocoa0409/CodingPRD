"""Domain thresholds — numeric constants from the PRD's pricing and scheduling rules."""

# Logical clock: server startup default instant (PRD 2.4).
DEFAULT_CLOCK_ISO = "2026-03-01T00:00:00Z"

# Membership lifecycle.
MEMBERSHIP_TERM_DAYS = 365

# Show booking hold window (PRD 3.4).
HOLD_WINDOW_MINUTES = 30

# Venue defaults (PRD 3.1).
DEFAULT_TURNOVER_BUFFER_MINUTES = 15
DEFAULT_ACCESSIBLE_SEATS = 0

# show_admission_pricing discount percentages (PRD 3.4).
PATRON_BASE_DISCOUNT_PCT = 1.00
FAMILY_DISCOUNT_PCT = 0.50
INDIVIDUAL_BASE_DISCOUNT_PCT = 0.25

# group_invoice_total constants (PRD 3.5).
CHAPERONE_FREE_RATIO = 10
GROUP_STUDENT_PCT = 0.30
GROUP_DEPOSIT_PCT = 0.25

# program_tuition_pricing constants (PRD 3.6).
PATRON_TUITION_PCT = 0.40
STD_MEMBER_TUITION_PCT = 0.15
EARLY_BIRD_SEATS = 3
EARLY_BIRD_OFF_CENTS = 1000

# rental_quote constants (PRD 3.7).
GUEST_TIER_1 = 20
RATE_1_CENTS = 500
RATE_2_CENTS = 300
RENTAL_DEPOSIT_PCT = 0.25

# astc_reciprocal_eligibility (PRD 3.2).
CENTER_ZIP_PREFIX = "606"
RECIPROCAL_RADIUS_MILES = 90
