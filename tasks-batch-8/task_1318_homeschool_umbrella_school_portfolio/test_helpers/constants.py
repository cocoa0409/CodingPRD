"""Domain thresholds — numeric constants from the PRD's calculation narratives."""

# Instructional progress (PRD §2.9 / §3.4)
DAY_QUALIFYING_MINUTES = 240
DAILY_CREDIT_CAP_MINUTES = 600
ATTENDANCE_MINUTES_MIN = 1
ATTENDANCE_MINUTES_MAX = 720

# Credit conversion (PRD §3.8)
HOURS_PER_HALF_CREDIT = 60
MIN_COMPLETION_HOURS = 60

# Graduation credit audit (PRD §3.8)
TOTAL_CREDITS_REQUIRED = 22.0
ENGLISH_REQUIRED = 4.0
MATH_REQUIRED = 3.0
SCIENCE_REQUIRED = 3.0
SOCIAL_STUDIES_REQUIRED = 3.0

# Co-op fee calculation (PRD §3.7)
EARLY_BIRD_DAYS = 30
EARLY_BIRD_PCT = 10
SIBLING_PCT = 15
DISCOUNT_CAP_PCT = 25

# Refund waterfall (PRD §3.7)
ADMIN_FEE_CENTS = 2500
PARTIAL_WINDOW_DAYS = 14
PARTIAL_REFUND_PCT = 50

# Family ledger (PRD §3.7)
FEES_GRACE_DAYS = 30

# Standardized testing (PRD §3.6)
PASSING_PERCENTILE = 23
EXAM_BUFFER_MINUTES = 30

# Academic-year defaults (PRD §3.1)
DEFAULT_TESTING_GRADES = [3, 5, 8, 11]
DEFAULT_REQUIRED_INSTRUCTIONAL_DAYS = 180
DEFAULT_REQUIRED_MINUTES_ELEMENTARY = 54000
DEFAULT_REQUIRED_MINUTES_SECONDARY = 59400

# Logical clock (PRD §2.4)
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Core curriculum subjects (PRD §3.3)
CORE_SUBJECTS = ["READING", "WRITING", "MATH", "SCIENCE", "SOCIAL_STUDIES"]

# Canonical academic-year fixture values shared across tests
CANONICAL_YEAR = {
    "label": "2026-2027",
    "start_date": "2026-08-01",
    "end_date": "2027-05-31",
    "notice_filing_deadline": "2026-09-15T00:00:00Z",
    "portfolio_due_date": "2027-04-30T00:00:00Z",
    "state_report_due_date": "2027-06-15T00:00:00Z",
    "mid_year_date": "2027-01-15",
}

# Standard evaluation score vectors (PRD §3.5: five core subjects, 0..4)
ACCEPT_SCORES = [
    {"subject": "READING", "score": 3},
    {"subject": "WRITING", "score": 3},
    {"subject": "MATH", "score": 3},
    {"subject": "SCIENCE", "score": 3},
    {"subject": "SOCIAL_STUDIES", "score": 3},
]
REMEDIATION_SCORES = [
    {"subject": "READING", "score": 1},
    {"subject": "WRITING", "score": 1},
    {"subject": "MATH", "score": 1},
    {"subject": "SCIENCE", "score": 1},
    {"subject": "SOCIAL_STUDIES", "score": 1},
]

# Graduation-ready posted credit blocks (PRD §3.8 audit minimums, total 22.0)
# (subject, course_title, completed_hours, letter_grade)
GRADUATION_CREDIT_BLOCKS = [
    ("ENGLISH", "English block", 480, "A"),          # 4.0
    ("MATH", "Math block", 360, "A"),                # 3.0
    ("SCIENCE", "Science block", 360, "A"),          # 3.0
    ("SOCIAL_STUDIES", "Social block", 360, "A"),    # 3.0
    ("ELECTIVE", "Elective block", 1080, "A"),       # 9.0
]
