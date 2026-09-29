"""Shared literals: clock instants, published thresholds and the recurring amounts.

Every figure here is one the PRD states outright.  Nothing is derived, so a test
that cites a constant from this module is citing the specification.
"""

# ---------------------------------------------------------------------------
# The logical clock (PRD 1, 2.4)
# ---------------------------------------------------------------------------
# The clock reads exactly this instant when the service starts.
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

# The instant the suite advances to before building a resolution, so that every
# server-stamped field has a value distinguishable from the start of the clock.
SETUP_CLOCK = "2026-08-03T09:00:00Z"
LATER_CLOCK = "2026-08-04T09:00:00Z"

# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------
LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0

# ---------------------------------------------------------------------------
# The basis-point scale (PRD 2.6)
# ---------------------------------------------------------------------------
BPS_WHOLE = 10000

# ---------------------------------------------------------------------------
# Readiness standardization gates (PRD 3.1)
# ---------------------------------------------------------------------------
READINESS_SCORE_FLOOR_BPS = 9800
READINESS_VARIANCE_CEILING_BPS = 25

# A package of 200 records with 4 malformed scores exactly 9800 bps, which the
# PRD says clears the floor.
CLEAN_RECORD_COUNT = 200
CLEAN_MALFORMED_COUNT = 4

# ---------------------------------------------------------------------------
# Insurance limits (PRD 3.5)
# ---------------------------------------------------------------------------
SMDIA_CENTS = 25000000
REVOCABLE_BENEFICIARY_CAP = 5

# ---------------------------------------------------------------------------
# The liquidation baseline and bid pricing (PRD 3.8)
# ---------------------------------------------------------------------------
ADMIN_COST_PER_DEPOSITOR_CENTS = 150000
MAX_RETENTION_BPS = 5000
RETAINED_SHORTFALL_BASE_BPS = 3000
RETAINED_SHORTFALL_STRESS_BPS = 4200
EXPECTED_LOSS_RATE_BPS = 1800
LSF_TIER_A_CEILING_CENTS = 5000000
LSF_TIER_B_CEILING_CENTS = 20000000
LSF_TIER_A_BPS = 25
LSF_TIER_B_BPS = 40
LSF_TIER_C_BPS = 60

# ---------------------------------------------------------------------------
# Bidder eligibility floors (PRD 3.7)
# ---------------------------------------------------------------------------
BIDDER_MIN_TIER1_CAPITAL_RATIO_BPS = 1000
BIDDER_MAX_CAMELS_COMPOSITE = 2

# ---------------------------------------------------------------------------
# Interval semantics (PRD 3.7, 3.8)
# ---------------------------------------------------------------------------
DATA_ROOM_BUFFER_MINUTES = 60

# ---------------------------------------------------------------------------
# The recurring two-account single-ownership depositor (PRD 3.4 worked example)
# ---------------------------------------------------------------------------
# 20000000 + 9000001 pooled against one standard maximum.
ACCOUNT_A_BALANCE_CENTS = 20000000
ACCOUNT_B_BALANCE_CENTS = 9000001
POOLED_ATTRIBUTED_CENTS = 29000001
POOLED_INSURED_CENTS = 25000000
POOLED_UNINSURED_CENTS = 4000001

# The floor-then-remainder hold allocation of that uninsured amount across the
# two accounts, in created_at ascending order (PRD 3.6).
HOLD_ACCOUNT_A_CENTS = 2758622
HOLD_ACCOUNT_B_CENTS = 1241379

# The two-certificate dividend round the PRD works through in 2.6.
DIVIDEND_RATE_BPS = 3333
CERT_FACE_LARGE_CENTS = 4000001
CERT_FACE_SMALL_CENTS = 2000001
DIVIDEND_LARGE_CENTS = 1333200
DIVIDEND_SMALL_CENTS = 666600
DIVIDEND_TOTAL_ROUND_PER_PART_CENTS = 1999800
DIVIDEND_TOTAL_IF_SUMMED_FIRST_CENTS = 1999801

# ---------------------------------------------------------------------------
# Audit identities recorded on a determination (PRD 2.1, 2.10)
# ---------------------------------------------------------------------------
PREPARER_USER_ID = "agent-001"
CERTIFIER_USER_ID = "certifier-001"
