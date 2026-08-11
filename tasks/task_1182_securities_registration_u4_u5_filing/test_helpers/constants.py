"""Domain thresholds — numeric constants from the PRD's fee/deadline rules."""

# PRD Section 2.5 — fixed startup clock reading.
STARTUP_CLOCK_UTC = "2026-05-01T00:00:00Z"

# PRD Section 2.6 — filing-deadline day counts.
AMENDMENT_WINDOW_DAYS = 30
U5_WINDOW_DAYS = 30
INQUIRY_RESPONSE_DAYS = 15

# PRD Section 3.4 — exam credit validity window.
EXAM_CREDIT_DAYS = 120

# PRD Sections 3.2 / 3.7 — renewal fee schedule.
STATE_JURISDICTION_FEE_CENTS = 5000
SRO_JURISDICTION_FEE_CENTS = 0
FIRST_REGISTRATION_BASE_CENTS = 10000
ADDITIONAL_REGISTRATION_BASE_CENTS = 5000
LATE_BLOCK_DAYS = 14
LATE_PCT_PER_BLOCK = 25
LATE_PCT_CAP = 100

# PRD Section 3.5 — deficiency hard stop.
MAX_DEFICIENCIES = 3

# PRD Section 3.9 — comment accuracy scoring.
CONTRADICTION_THRESHOLD = 1

# PRD Section 2.10 step 9 — minimum field lengths.
MIN_EXPLANATION_LEN = 20
MIN_NARRATIVE_LEN = 20
MIN_INQUIRY_TEXT_LEN = 20
MIN_RESPONSE_TEXT_LEN = 20
MIN_COMMENT_TEXT_LEN = 10
