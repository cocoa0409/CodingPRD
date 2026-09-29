"""Pinned constants for every calculation in the PRD."""
from decimal import Decimal

# --- dues_assessment ---------------------------------------------------------
TIER_SEASON_FEE_CENTS = {"COMPETITIVE": 95000, "RECREATIONAL": 61500, "LEARN_TO_ROW": 35500}
TIER_ACCESS_SURCHARGE_CENTS = {"COMPETITIVE": 23500, "RECREATIONAL": 12500, "LEARN_TO_ROW": 0}
LOCKER_FEE_CENTS = 8750
SEASON_MONTHS = 12
PER_SESSION_RATE_CENTS = 4500
TRUEUP_FLOOR_PCT = Decimal("0.40")
ADMIN_FEE_CENTS = 5000

# --- shell_condition_index ---------------------------------------------------
SEVERITY_POINTS = {
    "COSMETIC": Decimal("2"),
    "MINOR": Decimal("6"),
    "MAJOR": Decimal("18"),
    "STRUCTURAL": Decimal("40"),
}
DECAY_PERIOD_DAYS = 30
DECAY_POINTS_PER_PERIOD = Decimal("0.5")
VERIFIED_RESIDUAL_FACTOR = Decimal("0.25")
INDEX_CEILING = 100
MIN_CONDITION_INDEX_TO_SUBMIT = 60

# --- water_posture_evaluation ------------------------------------------------
COLD_WATER_TEMP_C = Decimal("12.8")
COMBINED_TEMP_SUM_C = Decimal("30.0")
WIND_RESTRICT_KT = Decimal("12.0")
WIND_CLOSE_KT = Decimal("20.0")
VIS_RESTRICT_M = 800
VIS_CLOSE_M = 400

# --- session_launch_requirement ---------------------------------------------
MAX_LAUNCHES_PER_SESSION = 2
SHELL_TURNAROUND_BUFFER_MINUTES = 30
SWIM_TEST_VALID_DAYS = 365

# --- regatta_entry_fee -------------------------------------------------------
CLASS_ENTRY_FEE_CENTS = {"1X": 4500, "2X": 7500, "4+": 13500, "8+": 25000}
CLASS_SLOT_UNITS = {"1X": 1, "2X": 1, "4+": 2, "8+": 3}
CLASS_MAX_TIER = {"1X": 4, "2X": 4, "4+": 2, "8+": 1}
AWAY_TRANSPORT_LEVY_CENTS_PER_RACK_UNIT = 5000
LATE_TIER_THRESHOLD_CENTS = 25000
LATE_FEE_PCT_LOW = Decimal("0.10")
LATE_FEE_PCT_HIGH = Decimal("0.15")

# --- scratch_refund ----------------------------------------------------------
REFUND_PCT_FULL = Decimal("1.00")
REFUND_PCT_PARTIAL = Decimal("0.55")
REFUND_PCT_NONE = Decimal("0.00")

# --- coxswain_deadweight_check ----------------------------------------------
MIN_COXSWAIN_WEIGHT_KG = Decimal("55.0")
MAX_ENTRY_DEADWEIGHT_KG = Decimal("15.0")

# --- lane_assignment_order / heat_advancement_selection ---------------------
LANE_PREFERENCE_ORDER = [3, 4, 2, 5, 1, 6, 7, 8]

# --- protest_deposit_ledger --------------------------------------------------
PROTEST_DEPOSIT_CENTS = 5000
MAX_JURY_ROUNDS = 2
PROTEST_WINDOW_MINUTES = 30

# --- lineup shape ------------------------------------------------------------
CLASS_SEAT_COUNT = {"1X": 1, "2X": 2, "4+": 5, "8+": 9}
CLASSES_WITH_COXSWAIN = ("4+", "8+")

# --- enum sets ---------------------------------------------------------------
TIERS = ("COMPETITIVE", "RECREATIONAL", "LEARN_TO_ROW")
CLUB_ROLES = ("ATHLETE", "COXSWAIN", "COACH", "LAUNCH_DRIVER", "JURY", "EQUIPMENT_MANAGER")
MEMBER_STATUSES = ("ACTIVE", "DUES_HOLD", "SUSPENDED", "WITHDRAWN")
INVOICE_STATUSES = ("ISSUED", "PARTIALLY_PAID", "PAID", "DELINQUENT", "VOIDED")
BOAT_CLASSES = ("1X", "2X", "4+", "8+")
TIER_RESTRICTIONS = ("COMPETITIVE_ONLY", "ANY")
SHELL_STATUSES = ("AVAILABLE", "ASSIGNED", "DAMAGED", "IN_REPAIR", "RETIRED")
SEVERITIES = ("COSMETIC", "MINOR", "MAJOR", "STRUCTURAL")
REPORT_STATUSES = ("REPORTED", "TRIAGED", "REPAIR_SCHEDULED", "VERIFIED", "CONDEMNED", "CLOSED_NO_ACTION")
TRAFFIC_PATTERNS = ("STANDARD_COUNTERCLOCKWISE", "REVERSED_CLOCKWISE", "NARROW_CHANNEL")
POSTURES = ("OPEN", "RESTRICTED", "CLOSED")
SESSION_KINDS = ("PRACTICE", "LEARN_TO_ROW", "RACE_PREP")
SESSION_STATUSES = ("PLANNED", "CLEARED", "LAUNCHED", "RETURNED", "CANCELLED")
VENUE_KINDS = ("HOME", "AWAY")
REGATTA_STATUSES = ("OPEN_FOR_ENTRY", "ENTRIES_CLOSED", "RACING", "COMPLETE", "CANCELLED")
ENTRY_STATUSES = ("DRAFT", "LINEUP_DECLARED", "SUBMITTED", "CONFIRMED", "RACED", "SCRATCHED")
SEAT_ROLES = ("ROWER", "COXSWAIN")
WEIGH_IN_STATUSES = ("NOT_REQUIRED", "PENDING", "PASSED", "FAILED")
ELIGIBILITY_STATUSES = ("ELIGIBLE", "BLOCKED_DUES", "BLOCKED_CERT", "BLOCKED_SAFETY")
ROUND_KINDS = ("HEAT", "SEMI", "FINAL")
ROUND_ORDER = {"HEAT": 0, "SEMI": 1, "FINAL": 2}
HEAT_STATUSES = ("SCHEDULED", "LANES_ASSIGNED", "RESULTS_PROVISIONAL", "RESULTS_OFFICIAL")
LANE_STATUSES = ("PENDING", "PROVISIONAL", "OFFICIAL", "DISQUALIFIED", "VOIDED")
GROUND_CODES = ("INTERFERENCE", "LANE_VIOLATION", "EQUIPMENT", "FALSE_START")
PROTEST_STATUSES = ("FILED", "UNDER_JURY_REVIEW", "REMANDED", "UPHELD", "DENIED", "WITHDRAWN")
TRAILER_STATUSES = ("OPEN", "SEALED", "DEPARTED", "ARRIVED", "RETURNED")
DISPOSITIONS = ("REPAIR", "CLOSE_NO_ACTION")
DECISIONS = ("UPHELD", "DENIED", "REMAND")
REMEDIES = ("DISQUALIFY", "RE_ROW")

# --- terminal states ---------------------------------------------------------
TERMINAL = {
    "member": ("WITHDRAWN",),
    "invoice": ("PAID", "VOIDED"),
    "shell": ("RETIRED",),
    "report": ("VERIFIED", "CONDEMNED", "CLOSED_NO_ACTION"),
    "session": ("RETURNED", "CANCELLED"),
    "regatta": ("COMPLETE", "CANCELLED"),
    "entry": ("RACED", "SCRATCHED"),
    "heat": ("RESULTS_OFFICIAL",),
    "lane": ("OFFICIAL", "VOIDED"),
    "protest": ("UPHELD", "DENIED", "WITHDRAWN"),
    "trailer": ("RETURNED",),
}
