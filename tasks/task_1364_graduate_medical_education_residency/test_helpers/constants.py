"""Domain thresholds and shared values (PRD §2.4, §2.6, §3)."""

# --- Logical clock (PRD §2.4) ---
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

# --- Academic calendar (PRD §2.6, §3.1) ---
BLOCKS_PER_YEAR = 13
BLOCK_DAYS = 28
YEAR_SPAN_DAYS = 364
YEAR_LABEL = "2026-2027"
YEAR_START = "2026-07-01"
YEAR_END = "2027-06-30"
YEAR2_LABEL = "2027-2028"
YEAR2_START = "2027-07-01"
YEAR2_END = "2028-06-29"

# --- Duty-hour surveillance (PRD §3.5) ---
HOURS_LIMIT = 80.00              # rolling 4-week average; strictly greater violates
REST_MIN_HOURS = 8.00            # gap strictly less than this violates
DAY_OFF_WINDOW_DAYS = 28
DAY_OFF_MIN = 4                  # days_off strictly fewer than this violates
MAX_SHIFT_HOURS = 28.00          # per-log duration cap (inclusive)
WEEKS_IN_WINDOW = 4
AUTO_REMEDIATION_THRESHOLD = 3   # unresolved violations that auto-create a plan

# --- Moonlighting (PRD §3.6) ---
MOON_MIN_HPW = 1.00
MOON_MAX_HPW = 24.00
STANDING_CHANGE_REASON = "STANDING_CHANGE"

# --- Complement / funding (PRD §3.2) ---
DEFAULT_POSITIONS = 2
DEFAULT_BUDGET_CENTS = 100000000
DEFAULT_STIPEND_CENTS = 6000000
# Stipend rounding reference: 6,500,007 -> 500,001 per block -> 6,500,013 per year.
PINNED_STIPEND_INPUT = 6500007
PINNED_STIPEND_YEAR_CENTS = 6500013

# --- Case logs (PRD §3.7) ---
ASSIST_WEIGHT = 0.5
ASSIST_CAP_RATIO = 0.25

# --- Milestones / CCC (PRD §3.7) ---
COMPETENCIES = [
    "PATIENT_CARE",
    "MEDICAL_KNOWLEDGE",
    "PROFESSIONALISM",
    "COMMUNICATION",
    "PRACTICE_BASED_LEARNING",
    "SYSTEMS_BASED_PRACTICE",
]
PD_WEIGHT = 2.0
FACULTY_WEIGHT = 1.0
CCC_QUORUM = 3

# --- Violations workflow (PRD §3.5) ---
JUSTIFICATION_MIN_LEN = 10

# --- Citations / survey (PRD §3.9) ---
SURVEY_COMPLIANCE_THRESHOLD = 70.00   # below this flags an area / response rate
SERIOUS_ESCALATION_COUNT = 3          # flagged_area_count >= 3 -> SERIOUS citations
PROBATIONARY_SERIOUS_COUNT = 2        # unresolved SERIOUS citations -> PROBATIONARY

# --- System-authored texts (PRD §3.5, §3.7, §3.8) ---
AUTO_REMEDIATION_GOALS = "Automatic remediation: repeated duty-hour violations"
CCC_REMEDIATION_GOALS = "Clinical Competency Committee remediation (outcome NEEDS_IMPROVEMENT)"
CCC_PROBATION_REASON = "CCC outcome UNSATISFACTORY"
REMEDIATION_FAILURE_REASON = "Remediation plan failure"
REMEDIATION_AUTO_DAYS = 90
