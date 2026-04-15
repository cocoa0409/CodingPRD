"""Domain thresholds and test defaults from scaffold Table 3."""

# Credit load constants (Table 3: credit_load_computation)
DEFAULT_MAX_CREDITS = 18
PROBATION_MAX_CREDITS = 12
HONORS_MAX_CREDITS = 22

# Pagination defaults (response_envelope.pagination_defaults)
DEFAULT_PAGE_SIZE = 20
MIN_PAGE_SIZE = 1
MAX_PAGE_SIZE = 50

# Schedule conflict buffer (Table 3: schedule_overlap_detection)
TRAVEL_BUFFER_MINUTES = 10

# Waitlist default cap (Table 1: Section.waitlist_cap default)
DEFAULT_WAITLIST_CAP = 10

# CrossDeptPermission default max_courses
DEFAULT_CROSS_DEPT_MAX_COURSES = 2

# Semester phases (for readability in tests)
PHASE_PLANNING = "PLANNING"
PHASE_OPEN_ENROLLMENT = "OPEN_ENROLLMENT"
PHASE_CLOSED_ENROLLMENT = "CLOSED_ENROLLMENT"
PHASE_FINALIZED = "FINALIZED"

# Enrollment statuses
STATUS_PENDING_APPROVAL = "PENDING_APPROVAL"
STATUS_ENROLLED = "ENROLLED"
STATUS_WAITLISTED = "WAITLISTED"
STATUS_DROPPED = "DROPPED"
STATUS_WITHDRAWN = "WITHDRAWN"
STATUS_REJECTED = "REJECTED"

# Academic standings
STANDING_GOOD = "GOOD"
STANDING_PROBATION = "PROBATION"
STANDING_SUSPENDED = "SUSPENDED"

# Course levels
LEVEL_INTRODUCTORY = "INTRODUCTORY"
LEVEL_INTERMEDIATE = "INTERMEDIATE"
LEVEL_ADVANCED = "ADVANCED"
LEVEL_GRADUATE = "GRADUATE"

# Test defaults
TEST_DEFAULTS = {
    "BUDGET_CREDITS": 18,
    "SECTION_CAPACITY": 30,
    "WAITLIST_CAP": 10,
    "CREDIT_HOURS": 3,
    "GPA": 3.5,
}
