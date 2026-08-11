"""Domain thresholds and constants named by the PRD workflow rules (§2-§3)."""

# Logical clock startup default (PRD §2.5: "Before any call to the clock-setting
# capability, the logical clock reads exactly 2026-05-01T00:00:00Z").
DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"

# Payment schedule / late fees (PRD §3.5)
LATE_FEE_PCT = 0.05            # five percent of the installment's amount_cents
GRACE_DAYS = 10                # OPEN -> LATE once clock passes due_date + 10 days
OPEN_LEAD_DAYS = 30            # SCHEDULED -> OPEN thirty days before due_date

# Waiver authority (PRD §3.5: outstanding balances of one hundred thousand cents or less)
WAIVER_AUTHORITY_CAP_CENTS = 100000

# Tenant standing (PRD §3.7)
NON_COMPLIANCE_PENALTY = 15    # score drop per record entering NON_COMPLIANT
SUSPENSION_THRESHOLD = 50      # strictly below 50 suspends; exactly 50 does not
SCORE_FLOOR = 0
SCORE_CAP = 100

# Compliance cure window (PRD §3.7: due_date plus thirty days)
CURE_DAYS = 30

# Statutory notice (PRD §2.9, §3.9)
DEFAULT_NOTICE_LEAD_DAYS = 180
LEASE_ACCEPTANCE_WINDOW_DAYS = 30   # lease creation within accepted_at + 30 days
ADJUSTMENT_INSTALLMENT_DUE_DAYS = 30  # true-up adjustment due thirty days after clock

# Early-termination reimbursement (PRD §3.8)
DAYS_PER_YEAR = 365
AGREED_VALUE_RESIDUAL_PCT = [1.0, 0.75, 0.55, 0.35, 0.15, 0.0]

# Bid evaluation score weights (PRD §3.3)
W_RENT = 0.6
W_COMPLIANCE = 0.25
W_EXPERIENCE = 0.15
EXPERIENCE_CAP_YEARS = 20

# Pagination defaults (PRD §2.3)
PAGE_DEFAULT_LIMIT = 10
PAGE_MAX_LIMIT = 100
