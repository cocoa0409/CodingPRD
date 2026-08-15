"""Domain thresholds and constants from the PRD's calculation narratives (§3)."""

# Regulatory windows (PRD §3.2)
ACK_WINDOW_DAYS = 7                    # grievance acknowledgment window (calendar)
GRIEVANCE_STANDARD_DAYS = 30           # standard grievance response window (calendar)
EXPEDITED_DAYS = 7                     # CRITICAL / alleged-abuse grievance window
COMPLAINT_TARGET_DAYS = 3              # complaint internal target
REOPEN_WINDOW_DAYS = 15                # re-anchor window after reopen (PRD §3.9)

# Priority score (PRD §3.2)
PRIORITY_CAP = 100
PRIORITY_URGENCY_CAP = 40
PRIORITY_URGENCY_SLOPE = 4
PRIORITY_URGENCY_FREE_DAYS = 10
PRIORITY_REOPEN_BONUS = 10
PRIORITY_SEVERITY_BASE = {"STANDARD": 20, "URGENT": 35, "CRITICAL": 50}
PRIORITY_VULNERABLE_BONUS = 15
PRIORITY_UNSET_DUE_DAYS = 999

# Service recovery (PRD §3.8)
CASE_CAP_CENTS = 50000                 # per-case recovery ceiling (integer cents)
DEFAULT_ISSUANCE_LIMIT_CENTS = 10000   # default self-approve ceiling per advocate

# Interview booking buffer (PRD §3.3)
BOOKING_BUFFER_SECONDS = 900

# Reportable events (PRD §3.7)
ABUSE_FILING_HOURS = 48
STANDARD_FILING_BUSINESS_DAYS = 5

# Satisfaction follow-up (PRD §3.9)
FOLLOWUP_DUE_BUSINESS_DAYS = 5
FOLLOWUP_EXPIRY_BUSINESS_DAYS = 10
FOLLOWUP_REOPEN_MAX_SCORE = 2

# Systemic threshold sweep (PRD §3.2)
SYSTEMIC_COUNT = 3
SYSTEMIC_ROLLING_WINDOW_DAYS = 30

# Trend analytics (PRD §3.9)
BP_BASE = 10000

# Staffing defaults (PRD §3.1)
DEFAULT_MAX_CONCURRENT_ROUNDINGS = 2
DEFAULT_MAX_CONCURRENT_ASSIGNMENTS = 5

# Logical clock startup default (PRD §2.4)
CLOCK_START_ISO = "2026-08-01T00:00:00.000Z"

# Content standard section sets (PRD §3.4)
BASE_LETTER_SECTIONS = [
    "PATIENT_SUMMARY",
    "INVESTIGATION_STEPS",
    "FINDINGS",
    "RESOLUTION",
    "CONTACT_INFO",
]
RISK_LETTER_SECTIONS = ["RISK_DISCLOSURE", "QAPI_REFERENCE"]
FULL_LETTER_SECTIONS = BASE_LETTER_SECTIONS + RISK_LETTER_SECTIONS
