"""Domain thresholds — numeric constants drawn from the PRD's fee, waiver, and deadline rules."""

# Fee assessment (PRD §3.4 / §2.7)
SEARCH_RATE_CENTS_PER_QH = 1000     # $40/hr = $10 per quarter-hour
REVIEW_RATE_CENTS_PER_QH = 1000     # $40/hr = $10 per quarter-hour
DUP_CENTS_PER_PAGE = 10             # $0.10/page
FREE_PAGES = 100
FREE_SEARCH_HOURS = 2
ADVANCE_PAYMENT_THRESHOLD_CENTS = 25000   # $250.00

# Public-interest fee waiver (PRD §3.4)
W_PUBLIC_UNDERSTANDING = 0.40
W_NOT_COMMERCIAL_INTEREST = 0.30
W_MEANINGFUL_CONTRIBUTION = 0.20
W_ABILITY_TO_DISSEMINATE = 0.10
WAIVER_GRANT_THRESHOLD = 70

# Deadline projection (PRD §2.8 / §3.5)
WORKING_DAYS_BASE = 20
EXTENSION_WORKING_DAYS = 10
APPEAL_WINDOW_DAYS = 90          # calendar days to file an appeal after a determination
REVERSE_NOTICE_DAYS = 10         # calendar days a submitter has to object before lapse

# A non-existent but well-formed UUID for not-found / FK tests.
NON_EXISTENT_UUID = "00000000-0000-4000-8000-000000000000"
