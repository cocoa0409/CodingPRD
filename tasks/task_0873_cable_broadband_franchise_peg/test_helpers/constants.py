"""Domain thresholds — numeric constants from the PRD calculations."""

# Build-out liquidated damages (PRD 3.3)
PER_HOME_DAMAGE_CENTS = 2500

# Audit underpayment assessment (PRD 3.5)
DAILY_INTEREST_RATE = 0.0005
PENALTY_TIER_HIGH_PCT = 0.10
PENALTY_TIER_HIGH_RATE = 0.15
PENALTY_TIER_MID_PCT = 0.05
PENALTY_TIER_MID_RATE = 0.10
PENALTY_TIER_LOW_RATE = 0.05
PENALTY_CAP_CENTS = 5_000_000

# Complaint SLA windows in hours, keyed by category (PRD 3.6)
SLA_HOURS = {
    "SERVICE_INTERRUPTION": 24,
    "BILLING": 72,
    "OTHER": 168,
}
# Number of ESCALATED complaints at/above which compliance flips to IN_VIOLATION.
ESCALATION_VIOLATION_THRESHOLD = 2

# Deemed-approval window for franchise applications (PRD 3.8)
DEEMED_APPROVAL_DAYS = 120

# Right-of-way permit clearance gap in hours (PRD 3.2)
PERMIT_BUFFER_HOURS = 24

# Logical-clock startup default (PRD 2.4)
CLOCK_DEFAULT = "2026-05-01T00:00:00Z"

# Reusable numeric fixtures used across the pinned test scenarios.
# Report gross 100010/50010/33330 at rate 0.05 -> fee_due 9169 (round-per-line-then-sum).
DEFAULT_GROSS = (100010, 50010, 33330)
DEFAULT_FEE_DUE = 9169
# Audited gross 120010/50010/33330 -> audited fee 10169; principal 1000, total 1200.
DEFAULT_AUDITED_GROSS = (120010, 50010, 33330)
DEFAULT_AUDITED_FEE = 10169
