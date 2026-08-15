"""Domain thresholds and constants — every value below is stated verbatim in
the PRD (sections 2.5, 2.7, 3.1-3.8).

Deliberately absent: the per-line-of-authority base commission rates. The PRD
(section 3.6) names a "base commission rate fixed for the application's
line_of_authority" but never publishes the rate table, so no absolute
commission amount is derivable from the contract and no constant is defined
here for it.
"""

# PRD 2.5 — the logical clock's startup value; the server must not fall back
# to wall-clock time.
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# PRD 3.5 — submission premium floor.
MIN_PREMIUM_CENTS = 500

# PRD 3.1 — CE defaults applied at license creation.
DEFAULT_CE_REQUIRED_HOURS = 24
DEFAULT_CE_ETHICS_REQUIRED_HOURS = 3

# PRD 3.3 — renewal window legs and the renewal extension.
RENEWAL_WINDOW_DAYS_BEFORE = 90
RENEWAL_GRACE_DAYS_AFTER = 30
RENEWAL_EXTENSION_MONTHS = 24

# PRD 3.5 — just-in-time filing window measured from the triggering
# application's submitted_at.
JIT_FILING_WINDOW_DAYS = 15

# PRD 3.8 — inquiry response clock measured from received_at.
INQUIRY_RESPONSE_DAYS = 30

# PRD 3.4 — FOR_CAUSE termination filing deadline measured from
# termination_initiated_at.
FOR_CAUSE_FILING_DAYS = 30

# PRD 3.7 — minimum spacing between CONFIRMED probations for one subject+state.
PROBATION_SPACING_DAYS = 365

# PRD 3.6 — volume-multiplier tier thresholds and values, and the agency
# uplift factor.
TIER2_THRESHOLD_CENTS = 100_000_000
TIER3_THRESHOLD_CENTS = 500_000_000
VOLUME_MULT_TIER1 = 1.00
VOLUME_MULT_TIER2 = 1.10
VOLUME_MULT_TIER3 = 1.25
AGENCY_UPLIFT = 1.05

# Common test timestamps (logical-clock instants).
DEFAULT_ISSUE_DATE = "2026-01-01T00:00:00Z"
DEFAULT_EXPIRATION_DATE = "2028-01-01T00:00:00Z"
DEFAULT_EFFECTIVE_DATE = "2026-01-15T00:00:00Z"
RENEWAL_WINDOW_CLOCK = "2027-12-01T00:00:00Z"
