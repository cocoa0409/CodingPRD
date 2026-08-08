"""Domain thresholds — numeric constants from the PRD's calculations (Section 3)."""

# Expense reimbursement (PRD Section 3.7)
STD_RATE_CENTS_PER_MILE = 50
TIER1_MILES = 100
TIER1_RATE_CENTS = 50
TIER2_RATE_CENTS = 35
OTHER_EXPENSE_CAP_CENTS = 5000
MONTHLY_REIMBURSEMENT_CAP_CENTS = 15000

# Contact compliance (PRD Section 3.8)
CONTACT_STANDARD_PER_MONTH = 3

# Background clearance validity (PRD Section 3.2)
BACKGROUND_VALID_DAYS = 365

# Report lead-time (PRD Section 3.6)
REPORT_LEAD_DAYS = 3

# Training requirement (PRD Section 3.1)
TRAINING_HOURS_REQUIRED = 30

# Hearing buffer (PRD Section 3.5)
HEARING_BUFFER_DAYS = 7

# Defaults (PRD Sections 3.1, 3.3)
DEFAULT_MAX_CASELOAD = 2
DEFAULT_BUDGET_CENTS = 20000

# A syntactically-valid UUID that resolves to no entity.
NIL_UUID = "00000000-0000-4000-8000-000000000000"
