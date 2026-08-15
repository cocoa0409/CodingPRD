"""Domain thresholds and shared literals from the PRD.

Score constants (PRD §3.2), the two-midnight threshold (PRD §2.8), escalation
tier thresholds (PRD §3.7), the clinical-completeness floor (PRD §3.3), the
peer-to-peer duration/clearance/reschedule constants (PRD §3.5), and the
logical-clock startup default (PRD §2.11).
"""

# --- Medical necessity score (PRD §3.2) ---
SEVERITY_CAP = 12
INTENSITY_CAP = 12
SEVERITY_WEIGHT = 5
INTENSITY_WEIGHT = 5
COMORBIDITY_CAP = 3
COMORBIDITY_WEIGHT_MEDICARE = 4
COMORBIDITY_WEIGHT_OTHER = 2
SCORE_CAP = 100
CRITERIA_MET_THRESHOLD = 60

# --- Two-midnight benchmark (PRD §2.8) ---
TWO_MIDNIGHT_THRESHOLD = 2

# --- CC44 rebill estimate (PRD §2.7) ---
RATE_SCALE = 1000

# --- Escalation tiers (PRD §3.7) ---
TIER1_OPEN_DAYS = 2
TIER2_OPEN_DAYS = 4
TIER3_OPEN_DAYS = 6

# --- Clinical documentation completeness gate (PRD §3.3) ---
CLINICAL_SUMMARY_MIN_CHARS = 50

# --- Peer-to-peer scheduling (PRD §3.5) ---
P2P_MIN_DURATION_MINUTES = 15
P2P_CALENDAR_CLEARANCE_MINUTES = 15
P2P_RESCHEDULE_HARD_CAP = 2

# --- Logical clock (PRD §2.11) ---
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# --- Shared clinical narratives (>= 50 characters) ---
LONG_CLINICAL_SUMMARY = (
    "Patient with acute decompensated heart failure requiring IV diuresis."
)
LONG_CLINICAL_UPDATE = (
    "Day 2: still on IV diuresis, net negative 1.5L, continued monitoring."
)
SHORT_CLINICAL_SUMMARY = "short"

# --- Canonical timeline used across deadline/window scenarios ---
ADMIT_AT = "2026-08-01T08:00:00Z"
EXPECTED_DISCHARGE_AT = "2026-08-03T10:00:00Z"  # exactly 2 midnight crossings
DENIAL_DECIDED_AT = "2026-08-02T12:00:00Z"
# 72h peer-to-peer window from the denial decision (PRD §3.5)
P2P_WINDOW_DEADLINE = "2026-08-05T12:00:00Z"
# 60 calendar days appeal horizon from the denial decision (PRD §3.3)
APPEAL_DEADLINE = "2026-10-01T12:00:00Z"
# 48h concurrent-review cadence from the approval decision (PRD §3.4)
REVIEW_DUE_FIRST = "2026-08-04T12:00:00Z"

TEST_DEFAULTS = {
    "CADENCE_HOURS": 48,
    "P2P_WINDOW_HOURS": 72,
    "APPEAL_DEADLINE_DAYS": 60,
    "BED_DAY_BUDGET": 30,
}
