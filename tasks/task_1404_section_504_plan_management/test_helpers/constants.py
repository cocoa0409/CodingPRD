"""Domain thresholds — numeric constants from PRD §2.10, §2.11, §3."""

# Calendar / temporal windows (PRD §3.2, §3.3, §3.6, §3.7)
REFERRAL_REVIEW_WINDOW_DAYS = 15          # referral review_deadline = submitted_at + 15 days
DETERMINATION_WINDOW_DAYS = 60            # determination_deadline = evaluation_started_at + 60 days
ANNUAL_WINDOW_DAYS = 365                  # annual review due 365 days after anchor
ANNUAL_GRACE_DAYS = 14                    # annual review overdue strictly after 365 + 14
RE_EVAL_WINDOW_DAYS = 1095                # re-evaluation due 3 * 365 days after anchor
TESTING_MIN_LEAD_DAYS = 14                # exactly 14 days passes, 13 fails
TESTING_REVIEW_DEADLINE_DAYS = 7          # review_deadline = submitted_at + 7 days
TRAINING_VALIDITY_YEARS_DAYS = 2 * 365    # training expires_at = trained_at + 2 years

# School posture scoring (PRD §2.10)
GRIEVANCE_WEIGHT = 20
OCR_FLAG_WEIGHT = 50
OVERDUE_REVIEW_WEIGHT = 15
OVERDUE_REVIEW_CAP = 30
TRAINING_GAP_WEIGHT = 25
TRAINING_FLOOR = 0.95
PROBATION_THRESHOLD = 30
AUDIT_HOLD_THRESHOLD = 60
COMPOSITE_CAP = 100

# Suspension lever (PRD §3.5)
SUSPENSION_COMPLIANCE_FLOOR = 60          # implementation_compliance_pct strictly below 60

# Logical clock default (PRD §2.5)
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Bootstrap identity for District504Director-level admin calls made before any
# StaffMember exists (school creation, clock control).
BOOTSTRAP_DIRECTOR_ID = "bootstrap-director"
