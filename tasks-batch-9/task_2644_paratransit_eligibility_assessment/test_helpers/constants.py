"""Business constants the contract pins by value.

Nothing here is a guess: every number, window length and default appears
literally in the specification, and the tests import these names instead of
re-typing the magic numbers.
"""

# --- The logical clock ------------------------------------------------------
# Before the clock has ever been set it reads exactly this instant.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# --- Calendar-date windows (whole days added to a date) ---------------------
STATUTORY_DETERMINATION_WINDOW_DAYS = 21
SUSPENSION_RESPONSE_WINDOW_DAYS = 14
REFERRAL_RESPONSE_WINDOW_DAYS = 14
APPEAL_FILING_WINDOW_DAYS = 60
APPEAL_DECISION_WINDOW_DAYS = 30

# --- Rolling windows (inclusive at both ends) -------------------------------
CONDUCT_WINDOW_DAYS = 90
CONDUCT_WINDOW_LOOKBACK_DAYS = 89  # today minus 89 is the window's first day
VISITOR_WINDOW_DAYS = 365
VISITOR_WINDOW_LOOKBACK_DAYS = 364  # service date minus 364 opens the window

# --- Presumptive eligibility ------------------------------------------------
PRESUMPTIVE_THRESHOLD_DAYS = 21

# --- Term table (days) keyed by granted category ----------------------------
TERM_DAYS_UNCONDITIONAL = 1825
TERM_DAYS_CONDITIONAL = 1095
TERM_DAYS_TEMPORARY = 180
TERM_DAYS_INELIGIBLE = 0

TERM_DAYS_BY_CATEGORY = {
    "UNCONDITIONAL": TERM_DAYS_UNCONDITIONAL,
    "CONDITIONAL": TERM_DAYS_CONDITIONAL,
    "TEMPORARY": TERM_DAYS_TEMPORARY,
    "INELIGIBLE": TERM_DAYS_INELIGIBLE,
}

# Categories a rider can be referred to travel training on.
TRAINABLE_CATEGORIES = ("CONDITIONAL", "TEMPORARY")

# --- Recommendation ladder thresholds ---------------------------------------
SCORE_MIN = 0
SCORE_MAX = 4
LOW_SCORE_CEILING = 1  # lower of the two scores at most 1 -> UNCONDITIONAL
SHORT_DISTANCE_METERS = 400  # below 400 m with a high score -> CONDITIONAL
HIGH_SCORE_FLOOR = 3
SCORE_SUM_CEILING = 4  # scores summing to at most 4 -> UNCONDITIONAL
LONG_DISTANCE_METERS = 800  # 800 m or more without heat sensitivity -> INELIGIBLE

# --- Assessment slots and vehicles ------------------------------------------
EVALUATOR_BUFFER_MINUTES = 15
DEFAULT_SITE_IS_WHEELCHAIR_ACCESSIBLE = True
DEFAULT_WHEELCHAIR_POSITIONS = 0
DEFAULT_AMBULATORY_SEATS = 0
DEFAULT_VEHICLE_STATUS = "IN_SERVICE"

# --- Conduct points ---------------------------------------------------------
POINTS_NO_SHOW = 2
POINTS_LATE_CANCEL = 1
POINTS_OTHER_EVENT_TYPES = 0
CHARGEABLE_EVENT_TYPES = ("NO_SHOW", "LATE_CANCEL")
ZERO_POINT_EVENT_TYPES = ("COMPLETED", "CANCEL_IN_ADVANCE", "AGENCY_FAULT_NO_SHOW")

# --- The three simultaneous suspension thresholds ---------------------------
SUSPENSION_POINTS_THRESHOLD = 6  # at least 6
SUSPENSION_MISS_COUNT_THRESHOLD = 3  # at least 3
SUSPENSION_RATIO_THRESHOLD_PCT = 10.0  # strictly greater than 10.0

# Statuses that make a proceeding live, blocking a second auto-proposal.
LIVE_PROCEEDING_STATUSES = (
    "PROPOSED",
    "NOTICE_SENT",
    "RIDER_RESPONDED",
    "RESPONSE_LAPSED",
    "UPHELD_PENDING",
    "ACTIVE",
)

# --- Suspension duration ladder --------------------------------------------
SUSPENSION_LADDER_DAYS = [7, 14, 21, 30]

# Proceeding statuses that count toward prior_upheld_suspension_count.
PRIOR_UPHELD_COUNTING_STATUSES = ("UPHELD_PENDING", "ACTIVE", "SERVED", "VOID")

# --- Visitor eligibility ----------------------------------------------------
VISITOR_DAYS_ALLOWED = 21
VISITOR_SERVICE_DATE_MAX_LEAD_DAYS = 90  # no later than today plus 90 days

# --- Travel training -------------------------------------------------------
COMPETENCY_CONFIRMED_MIN_SCORE = 80
COMPETENCY_SCORE_MIN = 0
COMPETENCY_SCORE_MAX = 100

# --- Application pipeline ---------------------------------------------------
# A packet in any of these statuses blocks another submission by the rider.
ACTIVE_PIPELINE_STATUSES = (
    "SUBMITTED",
    "RETURNED_INCOMPLETE",
    "PENDING_VERIFICATION",
    "ASSESSMENT_REQUIRED",
    "ASSESSMENT_SCHEDULED",
    "ASSESSMENT_COMPLETE",
)
TERMINAL_APPLICATION_STATUS = "DETERMINED"

# --- Appeals ----------------------------------------------------------------
# Appeal statuses that keep continued service and under_appeal alive.
APPEAL_IN_FLIGHT_STATUSES = ("FILED", "REVIEWER_ASSIGNED", "HEARING_SCHEDULED", "HEARD")

# --- Pagination -------------------------------------------------------------
DEFAULT_LIMIT = 10
DEFAULT_OFFSET = 0
MIN_LIMIT = 1
MAX_LIMIT = 100

# --- Elapsed-day arithmetic -------------------------------------------------
SECONDS_PER_DAY = 86400

# --- The day-close sweep's six counters, in step order ---------------------
SWEEP_COUNTERS = [
    "appeals_heard_count",
    "proceedings_advanced_count",
    "determinations_expired_count",
    "referrals_withdrawn_count",
    "presumptive_granted_count",
    "appeals_overdue_count",
]

# --- The five-key functional questionnaire ---------------------------------
FUNCTIONAL_ANSWER_KEYS = [
    "can_board_bus_steps",
    "can_navigate_unfamiliar_route",
    "max_walk_distance_meters",
    "uses_mobility_aid_outdoors",
    "has_cognitive_impairment",
]
