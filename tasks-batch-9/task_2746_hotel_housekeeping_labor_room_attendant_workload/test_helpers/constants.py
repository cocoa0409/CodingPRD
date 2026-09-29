"""Domain constants for the Hotel Housekeeping Labor & Workload API test suite.

Every value here is taken from the PRD: the role names of PRD 2.1, the endpoint
paths of PRD 4, the enumerated state values of PRD 3, the precision rules of
PRD 2.6 and the logical-clock epoch of PRD 2.4.
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# Roles (PRD 2.1)
# --------------------------------------------------------------------------

ROLE_DIRECTOR = "HousekeepingDirector"
ROLE_SUPERVISOR = "Supervisor"
ROLE_ROOM_ATTENDANT = "RoomAttendant"
ROLE_LAUNDRY_LEAD = "LaundryLead"
ROLE_FRONT_DESK = "FrontDeskAgent"
ROLE_COMPLIANCE = "ComplianceOfficer"

ALL_ROLES = (
    ROLE_DIRECTOR,
    ROLE_SUPERVISOR,
    ROLE_ROOM_ATTENDANT,
    ROLE_LAUNDRY_LEAD,
    ROLE_FRONT_DESK,
    ROLE_COMPLIANCE,
)

# Roles backed by a persisted Attendant row: X-User-ID is the Attendant id.
ENTITY_BACKED_ROLES = (ROLE_SUPERVISOR, ROLE_ROOM_ATTENDANT)

# Roles whose X-User-ID is an opaque operator identifier.
OPAQUE_ROLES = (
    ROLE_DIRECTOR,
    ROLE_LAUNDRY_LEAD,
    ROLE_FRONT_DESK,
    ROLE_COMPLIANCE,
)

# --------------------------------------------------------------------------
# Endpoint paths (PRD 4)
# --------------------------------------------------------------------------

PATH_PROPERTIES = "/housekeeping/properties"
PATH_ROOM_TYPES = "/housekeeping/room-types"
PATH_ROOMS = "/housekeeping/rooms"
PATH_ATTENDANTS = "/housekeeping/attendants"
PATH_FORECAST_DAYS = "/housekeeping/forecast-days"
PATH_SHIFT_ROSTERS = "/housekeeping/shift-rosters"
PATH_ROOM_ASSIGNMENTS = "/housekeeping/room-assignments"
PATH_INSPECTIONS = "/housekeeping/inspections"
PATH_LINEN_ITEMS = "/housekeeping/linen-items"
PATH_LAUNDRY_CYCLES = "/housekeeping/laundry-cycles"
PATH_LOST_FOUND_ITEMS = "/housekeeping/lost-found-items"
PATH_SERVICE_ENROLLMENTS = "/housekeeping/service-enrollments"
PATH_CLOCK_SET = "/_clock/set_current_utc"

# --------------------------------------------------------------------------
# Logical clock (PRD 2.4)
# --------------------------------------------------------------------------

# "Before any call to the clock-setting capability, the logical clock reads
# exactly 2026-08-01T00:00:00Z".
CLOCK_EPOCH = "2026-08-01T00:00:00.000Z"

# The pinned business instant used by most scenarios in this suite.
DEFAULT_CLOCK = "2026-08-03T07:00:00.000Z"
DEFAULT_BUSINESS_DATE = "2026-08-03"

# --------------------------------------------------------------------------
# Property enums and defaults (PRD 3.1)
# --------------------------------------------------------------------------

ORDINANCE_NONE = "NONE"
ORDINANCE_SQFT_CAP_2200 = "SQFT_CAP_2200"
ORDINANCE_CREDIT_CAP_STRICT = "CREDIT_CAP_STRICT"

# Waiver headroom factor by ordinance profile (PRD 3.3).
WAIVER_HEADROOM_FACTOR = {
    ORDINANCE_NONE: 1.25,
    ORDINANCE_SQFT_CAP_2200: 1.25,
    ORDINANCE_CREDIT_CAP_STRICT: 1.00,
}

# Property parameter defaults (PRD 3.1).
DEFAULT_CREDIT_MINUTE_VALUE = 30
DEFAULT_STANDARD_SHIFT_MINUTES = 480
DEFAULT_PRE_POST_SHIFT_MINUTES = 45
DEFAULT_MIN_DAILY_PAID_MINUTES = 240
DEFAULT_MAX_DAILY_CREDITS = 16.00
DEFAULT_MAX_DAILY_SQUARE_FEET = 2200
DEFAULT_LAUNDRY_SLA_MINUTES = 240
DEFAULT_LAUNDRY_CAPACITY_SETS = 300
DEFAULT_RECLEAN_THRESHOLD_SCORE = 85.0
DEFAULT_INSPECTION_SAMPLE_RATE = 0.20
DEFAULT_PROBATION_SAMPLE_RATE = 0.50
DEFAULT_REST_BUFFER_MINUTES = 10

# --------------------------------------------------------------------------
# Room enums (PRD 3.1)
# --------------------------------------------------------------------------

PROGRAM_DAILY = "DAILY"
PROGRAM_EVERY_OTHER_DAY = "EVERY_OTHER_DAY"
PROGRAM_OPT_OUT = "OPT_OUT"

OCCUPANCY_VACANT = "VACANT"
OCCUPANCY_STAYOVER = "STAYOVER"
OCCUPANCY_DUE_OUT = "DUE_OUT"
OCCUPANCY_ARRIVAL = "ARRIVAL"

CLEAN_CLEAN = "CLEAN"
CLEAN_DIRTY = "DIRTY"
CLEAN_IN_SERVICE = "IN_SERVICE"
CLEAN_INSPECTED_PASS = "INSPECTED_PASS"
CLEAN_RECLEAN_REQUIRED = "RECLEAN_REQUIRED"
CLEAN_OUT_OF_ORDER = "OUT_OF_ORDER"

# --------------------------------------------------------------------------
# Attendant enums (PRD 3.1)
# --------------------------------------------------------------------------

ATTENDANT_ACTIVE = "ACTIVE"
ATTENDANT_ON_LEAVE = "ON_LEAVE"
ATTENDANT_TERMINATED = "TERMINATED"

# --------------------------------------------------------------------------
# ForecastDay enums (PRD 3.2)
# --------------------------------------------------------------------------

FORECAST_DRAFT = "DRAFT"
FORECAST_PUBLISHED = "PUBLISHED"
FORECAST_CLOSED = "CLOSED"

# --------------------------------------------------------------------------
# ShiftRoster enums (PRD 2.8, 3.7)
# --------------------------------------------------------------------------

ROSTER_PLANNED = "PLANNED"
ROSTER_CLOCKED_IN = "CLOCKED_IN"
ROSTER_CLOSED = "CLOSED"

COMPLIANCE_COMPLIANT = "COMPLIANT"
COMPLIANCE_AT_LIMIT = "AT_LIMIT"
COMPLIANCE_BREACH_BLOCKED = "BREACH_BLOCKED"
COMPLIANCE_WAIVER_GRANTED = "WAIVER_GRANTED"

WAIVER_NONE = "NONE"
WAIVER_REQUESTED = "REQUESTED"
WAIVER_GRANTED = "GRANTED"
WAIVER_DENIED = "DENIED"

PRODUCTIVITY_PENDING = "PENDING"
PRODUCTIVITY_ON_TARGET = "ON_TARGET"
PRODUCTIVITY_OVER_TARGET = "OVER_TARGET"
PRODUCTIVITY_QUALITY_HOLD = "QUALITY_HOLD"

WAIVER_DECISION_GRANT = "GRANT"
WAIVER_DECISION_DENY = "DENY"

# --------------------------------------------------------------------------
# RoomAssignment enums (PRD 3.4, 3.5)
# --------------------------------------------------------------------------

SERVICE_CHECKOUT = "CHECKOUT"
SERVICE_STAYOVER = "STAYOVER"
SERVICE_DEEP_CLEAN = "DEEP_CLEAN"
SERVICE_LINEN_REFRESH = "LINEN_REFRESH"

ASSIGN_ASSIGNED = "ASSIGNED"
ASSIGN_IN_PROGRESS = "IN_PROGRESS"
ASSIGN_COMPLETED = "COMPLETED"
ASSIGN_INSPECTED_PASS = "INSPECTED_PASS"
ASSIGN_RECLEAN_REQUIRED = "RECLEAN_REQUIRED"
ASSIGN_CANCELLED = "CANCELLED"
ASSIGN_DEFERRED = "DEFERRED"

# "The counted set is the roster's assignments whose status is ASSIGNED,
# IN_PROGRESS, COMPLETED, INSPECTED_PASS or RECLEAN_REQUIRED." (PRD 2.8)
COUNTED_STATUSES = (
    ASSIGN_ASSIGNED,
    ASSIGN_IN_PROGRESS,
    ASSIGN_COMPLETED,
    ASSIGN_INSPECTED_PASS,
    ASSIGN_RECLEAN_REQUIRED,
)

# "performed assignments, meaning those whose status is COMPLETED,
# INSPECTED_PASS or RECLEAN_REQUIRED" (PRD 3.5)
PERFORMED_STATUSES = (
    ASSIGN_COMPLETED,
    ASSIGN_INSPECTED_PASS,
    ASSIGN_RECLEAN_REQUIRED,
)

# --------------------------------------------------------------------------
# Inspection (PRD 3.6)
# --------------------------------------------------------------------------

INSPECTION_PASS = "PASS"
INSPECTION_FAIL = "FAIL"

INSPECTION_WEIGHTS = {
    "bathroom_points": 0.30,
    "linen_points": 0.25,
    "dust_points": 0.20,
    "amenity_points": 0.15,
    "floor_points": 0.10,
}

# --------------------------------------------------------------------------
# Linen and laundry (PRD 3.8)
# --------------------------------------------------------------------------

LINEN_SHEET_SET = "SHEET_SET"
LINEN_TOWEL_SET = "TOWEL_SET"
LINEN_DUVET_COVER = "DUVET_COVER"

SHORTAGE_OK = "OK"
SHORTAGE_WATCH = "WATCH"
SHORTAGE_SHORTAGE = "SHORTAGE"
SHORTAGE_ESCALATED = "ESCALATED"

CYCLE_QUEUED = "QUEUED"
CYCLE_RETURNED = "RETURNED"
CYCLE_LATE_ESCALATED = "LATE_ESCALATED"
CYCLE_VOIDED = "VOIDED"

# --------------------------------------------------------------------------
# Service enrollments (PRD 3.9)
# --------------------------------------------------------------------------

ENROLLMENT_ACTIVE = "ACTIVE"
ENROLLMENT_COMPLETED = "COMPLETED"
ENROLLMENT_VOIDED = "VOIDED"

POINTS_PER_SKIP_OPT_OUT = 500
POINTS_PER_SKIP_EVERY_OTHER_DAY = 250

# --------------------------------------------------------------------------
# Lost and found (PRD 3.9)
# --------------------------------------------------------------------------

CATEGORY_HIGH_VALUE = "HIGH_VALUE"
CATEGORY_ID_DOCUMENT = "ID_DOCUMENT"
CATEGORY_STANDARD = "STANDARD"
CATEGORY_PERISHABLE = "PERISHABLE"

RETENTION_DAYS_BY_CATEGORY = {
    CATEGORY_HIGH_VALUE: 90,
    CATEGORY_ID_DOCUMENT: 60,
    CATEGORY_STANDARD: 30,
    CATEGORY_PERISHABLE: 0,
}

ITEM_LOGGED = "LOGGED"
ITEM_STORED = "STORED"
ITEM_CLAIM_PENDING = "CLAIM_PENDING"
ITEM_RELEASED = "RELEASED"
ITEM_SHIPPED = "SHIPPED"
ITEM_DISPOSED = "DISPOSED"
ITEM_DONATED = "DONATED"

PROOF_PHOTO_ID = "PHOTO_ID"
PROOF_DESCRIPTION_MATCH = "DESCRIPTION_MATCH"
PROOF_RECEIPT = "RECEIPT"

DISPOSITION_RELEASED = "RELEASED"
DISPOSITION_SHIPPED = "SHIPPED"
DISPOSITION_DISPOSED = "DISPOSED"
DISPOSITION_DONATED = "DONATED"

CLAIM_APPROVE = "APPROVE"
CLAIM_DENY = "DENY"

# --------------------------------------------------------------------------
# Precision (PRD 2.6)
# --------------------------------------------------------------------------

CREDIT_PLACES = 2
CREDIT_QUANTUM = 0.25
MIN_ASSIGNMENT_CREDITS = 0.25
MAX_ASSIGNMENT_CREDITS = 3.00
SCORE_PLACES = 1
COVERAGE_PLACES = 4

# Absolute tolerances used by the assertion helpers.
CREDIT_TOLERANCE = 0.005
SCORE_TOLERANCE = 0.05
COVERAGE_TOLERANCE = 0.00005
PCT_TOLERANCE = 0.005
