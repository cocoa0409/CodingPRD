"""Domain thresholds and shared constants from the PRD."""

# Logical clock (PRD section 2.4): default before any adjustment.
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

# Canonical cycle calendar used by fixtures (nomination window + induction).
CYCLE_OPEN_ISO = "2026-08-01T00:00:00Z"
CYCLE_CLOSE_ISO = "2026-08-15T00:00:00Z"
CYCLE_AFTER_CLOSE_ISO = "2026-08-16T00:00:00Z"
CYCLE_INDUCTION_ISO = "2026-09-01T00:00:00Z"
CYCLE_AFTER_INDUCTION_ISO = "2026-09-01T12:00:00Z"
CYCLE_LABEL = "2026-FALL"
ACADEMIC_YEAR = "2026-2027"

# Chapter charter defaults (PRD section 3.1 activation preconditions hold:
# weighted >= unweighted and annual >= 2 * per-semester).
DEFAULT_GPA_THRESHOLD_WEIGHTED = 3.50
DEFAULT_GPA_THRESHOLD_UNWEIGHTED = 3.25
DEFAULT_SERVICE_HOURS_ANNUAL = 15
DEFAULT_SERVICE_HOURS_PER_SEMESTER = 6
DEFAULT_NATIONAL_DUES_CENTS = 2000

# Eligibility score (PRD section 3.2).
ELIGIBILITY_SCORE_THRESHOLD = 70.00
WEIGHT_GPA = 0.40
WEIGHT_SERVICE = 0.30
WEIGHT_LEADERSHIP = 0.15
WEIGHT_PROBATION = 0.10
WEIGHT_ATHLETICS = 0.05
LEADERSHIP_POINTS = 50
PROBATION_PENALTY_PER_STRIKE = -20
ATHLETICS_PENALTY = -10
GPA_SCALE = 5.0

# Service hour entry field rules (PRD section 3.3): hours in (0, 12], 0.25 steps.
MAX_ENTRY_HOURS = 12.0
HOUR_INCREMENT = 0.25

# Probation appeal window (PRD section 3.7): strictly before 14 days.
APPEAL_WINDOW_DAYS = 14

# Member standing view field names (PRD section 3.3).
STANDING_FIELDS = (
    "good_standing",
    "verified_service_hours_current_year",
    "verified_service_hours_current_semester",
    "probation_strikes",
    "annual_cumulative_compliant",
    "per_semester_strict_compliant",
)
