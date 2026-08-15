"""Domain thresholds and canonical timestamps used across PD workflows (PRD §2.4, §2.6, §3)."""

# Credit conversion (PRD §2.6)
HOURS_PER_DISTRICT_CREDIT = 15      # district lane credit: floor(hours*2/3)/10 per entry
HOURS_PER_CEU = 10                  # state CEU: round(hours/10, 2) half-up per entry

# Attendance rate check (PRD §3.4): attended*5 >= total*4
ATTENDANCE_NUMERATOR = 4
ATTENDANCE_DENOMINATOR = 5

# Room turnover buffer (PRD §3.2), minutes
ROOM_TURNOVER_MINUTES = 30

# Workshop rules (PRD §3.10)
ANNUAL_CAP_CENTS = 250000
PREAPPROVAL_LEAD_DAYS = 14
MAX_REVISIONS = 3
WORKSHOP_GRACE_DAYS = 30

# Lane advancement (PRD §3.9)
CREDITS_PER_LANE_STEP = 12.0
LANE_ORDER = ["BA", "BA15", "MA", "MA15", "MA30", "DOC"]
ADVANCEMENT_MONTHS = (8, 9)

# Compliance (PRD §3.7)
COMPLIANCE_ESCALATION_DAYS = 30

# Logical clock anchors (PRD §2.4: startup default is exactly 2026-08-01T00:00:00Z)
CLOCK_INIT = "2026-08-01T00:00:00Z"
CLOCK_IN_SESSION = "2026-08-16T00:00:00Z"   # past standard section starts_at
CLOCK_AFTER_END = "2026-08-21T00:00:00Z"    # past standard section ends_at

# Standard section geometry used by most scenarios
STD_REG_OPENS = "2026-08-01T00:00:00Z"
STD_REG_CLOSES = "2026-08-10T00:00:00Z"
STD_STARTS = "2026-08-15T09:00:00Z"
STD_ENDS = "2026-08-20T17:00:00Z"
STD_MEETING_START = "2026-08-15T10:00:00Z"
STD_MEETING_END = "2026-08-15T12:00:00Z"
STD_TERM = "2026-FALL"
STD_ROOM = "R1"
STD_FISCAL_YEAR = 2026
STD_SCHOOL_YEAR = "2026-2027"
