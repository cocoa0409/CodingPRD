"""Numeric and temporal constants declared by the PRD, plus the instants and
codes that the test scenarios reuse."""

# --------------------------------------------------------------------------
# Business constants fixed by the PRD
# --------------------------------------------------------------------------

# An out-of-market service fee is waived when the line's extended price
# reaches this threshold.
FEE_WAIVER_EXTENDED_THRESHOLD_CENTS = 500000

# Share of an accrued operator rebate funded by the manufacturer.
MANUFACTURER_FUNDING_SHARE_PCT = 60

# Compliance percentage floor -> rebate rate percentage, highest band first.
REBATE_RATE_TIERS = [
    (95.00, 4.00),
    (90.00, 3.00),
    (80.00, 1.50),
    (0.00, 0.00),
]

# A cost change of this magnitude or more is a major change.
MAJOR_CHANGE_PCT = 10.00

# Notice window granted for a change that is not major.
MINOR_NOTICE_DAYS = 7

# Minimum audit variance percentage that permits upholding a dispute.
AUDIT_TOLERANCE_PCT = 0.50

# Compliance percentage at or above which a contract is not restricted.
CONTRACT_MINIMUM_COMPLIANCE_PCT = 80.00

# Breached deviation count that forces a RESTRICTED posture.
DEVIATION_BREACH_POSTURE_LIMIT = 1

# Maximum number of manufacturer revision rounds on a deviation agreement.
MAX_REVISION_ROUNDS = 3

# Changeover buffer required between coverage windows for the same DC.
DC_COVERAGE_BUFFER_DAYS = 14

# Rolling window in which only one live notice may exist per product.
NOTICE_WINDOW_DAYS = 30


# --------------------------------------------------------------------------
# The logical clock
# --------------------------------------------------------------------------

CLOCK_STARTUP_UTC = "2026-08-01T00:00:00Z"


# --------------------------------------------------------------------------
# Instants reused by the scenarios
# --------------------------------------------------------------------------

TERM_START = "2026-08-01T00:00:00Z"
TERM_END = "2027-07-31T23:59:59Z"

AUG_START = "2026-08-01T00:00:00Z"
AUG_04 = "2026-08-04T00:00:00Z"
AUG_05 = "2026-08-05T00:00:00Z"
AUG_06 = "2026-08-06T00:00:00Z"
AUG_08 = "2026-08-08T00:00:00Z"
AUG_10 = "2026-08-10T00:00:00Z"
AUG_30 = "2026-08-30T00:00:00Z"
AUG_31 = "2026-08-31T00:00:00Z"
SEP_START = "2026-09-01T00:00:00Z"
SEP_05 = "2026-09-05T00:00:00Z"
SEP_14 = "2026-09-14T00:00:00Z"
SEP_15 = "2026-09-15T00:00:00Z"
OCT_START = "2026-10-01T00:00:00Z"
OCT_05 = "2026-10-05T00:00:00Z"
NOV_START = "2026-11-01T00:00:00Z"
DEC_START = "2026-12-01T00:00:00Z"


# --------------------------------------------------------------------------
# Pagination
# --------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
MIN_OFFSET = 0
