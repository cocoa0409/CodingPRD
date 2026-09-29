"""Domain constants for the corporate video / brand film production API.

Everything here is transcribed from the PRD: the six role spellings of §2.1, the
logical clock's startup default from §2.5, the enumerations of §3, and every
named numeric constant that a §3 formula multiplies by. Tests import these rather
than repeating literals, so a rule that moves in the PRD moves in exactly one
place here.
"""

# ─── Roles (PRD §2.1) ──────────────────────────────────────────────────────
# "Six roles exist and their spellings are exact".
ROLE_PRODUCTION_COORDINATOR = "ProductionCoordinator"
ROLE_LINE_PRODUCER = "LineProducer"
ROLE_POST_SUPERVISOR = "PostSupervisor"
ROLE_CLIENT_APPROVER = "ClientApprover"
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"
ROLE_CREW_MEMBER = "CrewMember"

ALL_ROLES = (
    ROLE_PRODUCTION_COORDINATOR,
    ROLE_LINE_PRODUCER,
    ROLE_POST_SUPERVISOR,
    ROLE_CLIENT_APPROVER,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_CREW_MEMBER,
)

# ─── The logical production clock (PRD §2.5) ───────────────────────────────
# "Before the clock is ever set, it reads exactly `2026-08-01T00:00:00Z`".
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# ─── Pagination (PRD §2.3) ─────────────────────────────────────────────────
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
MIN_OFFSET = 0

# ─── Project (PRD §3.1) ────────────────────────────────────────────────────
CHANNELS = ("BROADCAST", "OLV", "SOCIAL", "INTERNAL", "OOH")

PROJECT_DRAFT = "DRAFT"
PROJECT_SCOPED = "SCOPED"
PROJECT_IN_PRODUCTION = "IN_PRODUCTION"
PROJECT_IN_POST = "IN_POST"
PROJECT_DELIVERED = "DELIVERED"
PROJECT_ARCHIVED = "ARCHIVED"

REVIEW_GATE_OPEN = "OPEN"
REVIEW_GATE_CHANGE_ORDER_PENDING = "CHANGE_ORDER_PENDING"

ARCHIVE_NOT_PACKAGED = "NOT_PACKAGED"
ARCHIVE_HANDED_OVER = "HANDED_OVER"
ARCHIVE_RETENTION_EXPIRED = "RETENTION_EXPIRED"

# The three optional project inputs and the defaults the contract assumes.
DEFAULT_CONTRACTED_REVISION_ROUNDS = 2
DEFAULT_RAW_FOOTAGE_RETENTION_MONTHS = 12
DEFAULT_RAW_FOOTAGE_TERABYTES = 0

MIN_USAGE_TERM_MONTHS = 1
MAX_USAGE_TERM_MONTHS = 60

# ─── Deliverable (PRD §3.1) ────────────────────────────────────────────────
ASPECT_RATIOS = ("16:9", "9:16", "1:1", "4:5", "2.39:1")
CAPTION_REQUIREMENTS = ("NONE", "CLOSED_SRT", "BURNED_IN_SUBTITLES", "OPEN_CAPTIONS")

DELIVERABLE_PENDING = "PENDING"
DELIVERABLE_IN_REVIEW = "IN_REVIEW"
DELIVERABLE_CHANGES_REQUESTED = "CHANGES_REQUESTED"
DELIVERABLE_APPROVED = "APPROVED"
DELIVERABLE_HANDED_OVER = "HANDED_OVER"

# ─── Budget lines (PRD §3.2) ───────────────────────────────────────────────
BUDGET_CATEGORIES = ("CREW", "EQUIPMENT", "LOCATION", "TALENT", "POST")
CATEGORY_CREW = "CREW"
CATEGORY_EQUIPMENT = "EQUIPMENT"
CATEGORY_LOCATION = "LOCATION"
CATEGORY_TALENT = "TALENT"
CATEGORY_POST = "POST"

BUDGET_LINE_PLANNED = "PLANNED"
BUDGET_LINE_COMMITTED = "COMMITTED"

DEFAULT_MARKUP_PCT = 0
MAX_MARKUP_PCT = 0.35

# ─── The not-to-exceed allowance gate (PRD §2.8) ───────────────────────────
# "the allowance is `budget_ceiling_cents` multiplied by 1.05, rounded half up".
POST_APPROVAL_ALLOWANCE_MULT = 1.05

# ─── Talent engagements (PRD §3.3) ─────────────────────────────────────────
UNION = "UNION"
NON_UNION = "NON_UNION"
USAGE_BUYOUT = "USAGE_BUYOUT"
UNION_SESSION_REUSE = "UNION_SESSION_REUSE"

ENGAGEMENT_DRAFT = "DRAFT"
ENGAGEMENT_CONFIRMED = "CONFIRMED"
ENGAGEMENT_COMPLETED = "COMPLETED"

BASIS_PROVISIONAL = "PROVISIONAL"
BASIS_FINAL = "FINAL"

# "one channel gives 0.50, two channels 0.85, three channels 1.20, and four or
# more channels 1.60" — the count is clamped at four.
BUYOUT_CHANNEL_MULT = {1: 0.50, 2: 0.85, 3: 1.20, 4: 1.60}
# "1.00 when the term is 12 months or fewer, 1.35 when it is more than 12 and at
# most 24, 1.65 when it is more than 24 and at most 36, and 2.00 for any longer".
BUYOUT_TERM_BANDS = ((12, 1.00), (24, 1.35), (36, 1.65))
BUYOUT_TERM_MULT_ABOVE = 2.00

AGENT_FEE_PCT = 0.10
UNION_PENSION_HEALTH_PCT = 0.1975
REUSE_CYCLE_PCT = 0.35
REUSE_CYCLE_DAYS = 91
MONTH_DAYS = 30

# ─── Locations and shoot days (PRD §3.4) ───────────────────────────────────
LOCATION_SCOUTED = "SCOUTED"
LOCATION_HOLD = "HOLD"
LOCATION_CONFIRMED = "CONFIRMED"

SHOOT_DAY_PLANNED = "PLANNED"
SHOOT_DAY_CONFIRMED = "CONFIRMED"
SHOOT_DAY_WRAPPED = "WRAPPED"
SHOOT_DAY_CANCELLED = "CANCELLED"

CALL_SHEET_DRAFT = "DRAFT"
CALL_SHEET_PUBLISHED = "PUBLISHED"

MIN_STAGE_COUNT = 1
MAX_STAGE_COUNT = 12

# ─── Compliance certificates (PRD §3.5) ────────────────────────────────────
CERT_FILM_PERMIT = "FILM_PERMIT"
CERT_LIABILITY_COI = "LIABILITY_COI"
CERT_TYPES = (CERT_FILM_PERMIT, CERT_LIABILITY_COI)

CERT_SUBMITTED = "SUBMITTED"
CERT_ISSUED = "ISSUED"
CERT_DENIED = "DENIED"
CERT_EXPIRED = "EXPIRED"  # derived only, via effective_status

DECISION_ISSUE = "ISSUE"
DECISION_DENY = "DENY"

POSTURE_BLOCKED = "BLOCKED"
POSTURE_RESTRICTED = "RESTRICTED"
POSTURE_OPEN = "OPEN"

# "at least three are confirmed" — the call-sheet crew floor.
MIN_CONFIRMED_CREW_FOR_CALL_SHEET = 3

# ─── Crew and equipment (PRD §3.6) ─────────────────────────────────────────
DEPARTMENTS = ("CAMERA", "GRIP_ELECTRIC", "SOUND", "ART", "PRODUCTION", "POST")
DEPT_CAMERA = "CAMERA"
DEPT_GRIP_ELECTRIC = "GRIP_ELECTRIC"
DEPT_SOUND = "SOUND"
DEPT_ART = "ART"
DEPT_PRODUCTION = "PRODUCTION"
DEPT_POST = "POST"

DEFAULT_MIN_TURNAROUND_HOURS = 10
MAX_MIN_TURNAROUND_HOURS = 24

BOOKING_HELD = "HELD"
BOOKING_CONFIRMED = "CONFIRMED"
BOOKING_COMPLETED = "COMPLETED"
BOOKING_RELEASED = "RELEASED"

STRAIGHT_TIME_HOURS = 10
OT1_SPAN_HOURS = 2
OT1_MULT = 1.5
OT2_MULT = 2.0
OT2_THRESHOLD_HOURS = 12

RESERVATION_RESERVED = "RESERVED"
RESERVATION_RETURNED = "RETURNED"
RESERVATION_RELEASED = "RELEASED"

PREP_WINDOW_HOURS = 48
RETURN_WINDOW_HOURS = 48

# ─── Call sheets and wrap (PRD §3.7) ───────────────────────────────────────
CALL_SHEET_LEAD_HOURS = 12

# ─── Cuts, QC and the review loop (PRD §3.8) ───────────────────────────────
REVIEW_DRAFT = "DRAFT"
REVIEW_SUBMITTED = "SUBMITTED"
REVIEW_APPROVED = "APPROVED"
REVIEW_CHANGES_REQUESTED = "CHANGES_REQUESTED"
REVIEW_SUPERSEDED = "SUPERSEDED"

TECHNICAL_PENDING_QC = "PENDING_QC"
TECHNICAL_QC_PASSED = "QC_PASSED"
TECHNICAL_QC_FAILED = "QC_FAILED"

QC_ASPECT_RATIO_MISMATCH = "ASPECT_RATIO_MISMATCH"
QC_DURATION_OUT_OF_TOLERANCE = "DURATION_OUT_OF_TOLERANCE"
QC_CAPTION_REQUIREMENT_UNMET = "CAPTION_REQUIREMENT_UNMET"
QC_UNREQUESTED_CAPTION_ASSET = "UNREQUESTED_CAPTION_ASSET"

# "a difference of exactly one second passes, a difference of two seconds fails".
DURATION_TOLERANCE_SECONDS = 1

DECISION_APPROVE = "APPROVE"
DECISION_REQUEST_CHANGES = "REQUEST_CHANGES"

# ─── Change orders (PRD §3.9) ──────────────────────────────────────────────
TRIGGER_REVISION_ROUND_EXCEEDED = "REVISION_ROUND_EXCEEDED"
TRIGGER_DELIVERABLE_ADDED_AFTER_SCOPE_LOCK = "DELIVERABLE_ADDED_AFTER_SCOPE_LOCK"

CHANGE_ORDER_PENDING_APPROVAL = "PENDING_APPROVAL"
CHANGE_ORDER_APPROVED = "APPROVED"
CHANGE_ORDER_REJECTED = "REJECTED"
CHANGE_ORDER_VOIDED = "VOIDED"

DECISION_REJECT = "REJECT"
DECISION_VOID = "VOID"

EXTRA_ROUND_LABOR_CENTS = 480000
NEW_DELIVERABLE_LABOR_CENTS = 620000

# "0.25 when the day count is 7 or fewer, 0.15 when it is more than 7 and 14 or
# fewer, and 0.00 for anything further out".
RUSH_BANDS = ((7, 0.25), (14, 0.15))
RUSH_PCT_BEYOND = 0.00

# "0.12 when `subtotal_cents` is at least 1,000,000 cents, 0.15 when it is at
# least 500,000 but below 1,000,000, and 0.18 below 500,000".
PRODUCER_FEE_BANDS = ((1000000, 0.12), (500000, 0.15))
PRODUCER_FEE_PCT_BELOW = 0.18

SECONDS_PER_DAY = 86400

# ─── Archive handover and retention (PRD §3.10) ────────────────────────────
# "calendar month lengths are deliberately not used, so a 12-month retention term
# is exactly 360 days".
RETENTION_MONTH_DAYS = 30
