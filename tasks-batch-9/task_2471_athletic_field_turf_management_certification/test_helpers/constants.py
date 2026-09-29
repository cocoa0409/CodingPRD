"""Domain thresholds and pinned literals for the athletic field turf management API.

Every value here is stated in the PRD narrative; nothing is invented.
"""

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------

#: Before the clock has ever been set it reads exactly this instant.
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

#: Path of the out-of-band clock route.
CLOCK_PATH = "/_clock/set_current_utc"

# ---------------------------------------------------------------------------
# Age and warranty (PRD §3.1)
# ---------------------------------------------------------------------------

#: `age_years` divides whole and fractional days by this figure.
DAYS_PER_YEAR = 365.25

WARRANTY_STATUS_NONE = "NONE"
WARRANTY_STATUS_ACTIVE = "ACTIVE"
WARRANTY_STATUS_EXPIRED = "EXPIRED"

# ---------------------------------------------------------------------------
# Impact attenuation thresholds (PRD §3.3, §3.7)
# ---------------------------------------------------------------------------

#: A mean at or below this value is a PASS; the bound is inclusive.
GMAX_ADVISORY_LIMIT = 165.0

#: A mean above the advisory limit but at or below this value is an ADVISORY.
GMAX_MANDATORY_LIMIT = 200.0

#: The safety component's ideal g-max value.
GMAX_IDEAL_VALUE = 90.0

#: Safety component used when `latest_gmax_mean_value` is null.
NO_DATA_SAFETY_COMPONENT = 50.00

#: An impact test carries exactly this many drop readings.
GMAX_READING_COUNT = 3

#: Each individual reading must fall inside this inclusive range.
GMAX_READING_MIN = 50.0
GMAX_READING_MAX = 400.0

# ---------------------------------------------------------------------------
# Wear load factors (PRD §3.6)
# ---------------------------------------------------------------------------

#: Intensity weight keyed on `activity_type`.
ACTIVITY_INTENSITY = {
    "PRACTICE": 1.00,
    "GAME": 1.50,
    "TOURNAMENT": 2.00,
    "COMMUNITY": 0.75,
}

#: Participants at or below this headcount contribute no crowd surcharge.
CROWD_FREE_ALLOWANCE = 40

#: Surcharge earned per participant above the free allowance.
CROWD_STEP = 0.01

#: The crowd surcharge stops growing once it reaches this value.
CROWD_FACTOR_CAP = 0.50

#: Surface factor keyed on the field's `surface_type`.
SURFACE_FACTOR = {
    "NATURAL_GRASS": 1.20,
    "SYNTHETIC_TURF": 0.80,
}

#: Weather factor applied when `weather_condition` is WET (DRY is 1.00).
WET_FACTOR = 1.35
DRY_FACTOR = 1.00

#: A CANCELLED_LATE outcome charges this fraction of the raw load.
LATE_CANCEL_WEAR_FRACTION = 0.50

# ---------------------------------------------------------------------------
# Rest requirement tiers (PRD §3.6)
# ---------------------------------------------------------------------------

#: Marginal tiers as (upper_bound_of_wear_units, rest_hours_per_wear_unit).
#: A null upper bound means "every wear unit above the previous bound".
REST_TIERS = (
    (6.00, 0.50),
    (12.00, 1.00),
    (None, 1.75),
)

#: On a synthetic surface the summed tier hours are multiplied by this.
SYNTHETIC_REST_MULTIPLIER = 0.40

#: On a natural grass surface a WET slot adds this flat surcharge instead.
WET_NATURAL_REST_SURCHARGE_HOURS = 2.00

# ---------------------------------------------------------------------------
# Maintenance recovery credit table (PRD §3.2)
# ---------------------------------------------------------------------------

#: `recovery_credit_hours` frozen on the task at creation, keyed on task type.
RECOVERY_CREDIT_HOURS = {
    "AERATION": 12.00,
    "OVERSEEDING": 24.00,
    "FERTILITY": 6.00,
    "IRRIGATION": 4.00,
    "GROOMING": 3.00,
    "INFILL_REDISTRIBUTION": 6.00,
    "SEAM_INSPECTION": 0.00,
}

#: Agronomic task types, legal only on NATURAL_GRASS.
AGRONOMIC_TASK_TYPES = ("AERATION", "OVERSEEDING", "FERTILITY", "IRRIGATION")

#: Synthetic task types, legal only on SYNTHETIC_TURF.
SYNTHETIC_TASK_TYPES = ("GROOMING", "INFILL_REDISTRIBUTION", "SEAM_INSPECTION")

#: The aggregate of concurrent tasks per staff member that is refused.
MAX_CONCURRENT_STAFF_TASKS = 2

# ---------------------------------------------------------------------------
# Condition index (PRD §3.7, §3.8)
# ---------------------------------------------------------------------------

#: Four wear units cost one index point on the wear component.
WEAR_UNITS_PER_INDEX_POINT = 4.00

#: AGRONOMIC variant weights.
AGRONOMIC_WEIGHT_WEAR = 0.50
AGRONOMIC_WEIGHT_AGE = 0.20
AGRONOMIC_WEIGHT_SAFETY = 0.30

#: CERTIFICATION variant weights (and the safety-only cap that follows).
CERTIFICATION_WEIGHT_WEAR = 0.20
CERTIFICATION_WEIGHT_AGE = 0.20
CERTIFICATION_WEIGHT_SAFETY = 0.60

# ---------------------------------------------------------------------------
# Booking allocation (PRD §3.5)
# ---------------------------------------------------------------------------

#: Changeover buffer applied symmetrically on each side of a booking window.
CHANGEOVER_BUFFER_MINUTES = 30

#: Activity classes a RESTRICTED field still accepts.
RESTRICTED_ACTIVITY_TYPES = ("PRACTICE", "COMMUNITY")

#: Activity classes only an OPEN field accepts.
OPEN_ONLY_ACTIVITY_TYPES = ("GAME", "TOURNAMENT")

# ---------------------------------------------------------------------------
# Certification (PRD §3.8)
# ---------------------------------------------------------------------------

#: The completeness review window ends at `submitted_at_utc`, both bounds inclusive.
CERTIFICATION_WINDOW_DAYS = 180

#: Component weights of the documentation completeness score.
COMPLETENESS_WEIGHTS = {
    "SAFETY_TEST": 30,
    "AGRONOMIC_PROGRAM": 20,
    "STRIPING_LAYOUT": 15,
    "GOAL_ANCHORING": 15,
    "SURFACE_SPEC_COMPLIANCE": 10,
    "REMEDIATION_CLOSURE": 10,
}

#: Synthetic surface-specification requirement.
REQUIRED_INFILL_DEPTH_MM = 51.0

#: Natural grass surface-specification requirement.
REQUIRED_NITROGEN_LB_PER_1000_SQ_FT = 3.00

#: APPROVE gates.
MIN_CERTIFICATION_COMPLETENESS_SCORE = 90.00
MIN_CERTIFICATION_CONDITION_INDEX = 55.00

#: An approval certifies the field for this many days from the current instant.
CERTIFICATION_VALID_DAYS = 365

#: `infill_depth_mm` range (PRD §2.6).
INFILL_DEPTH_MIN_MM = 0.0
INFILL_DEPTH_MAX_MM = 80.0

#: `nitrogen_lb_per_1000_sq_ft` range (PRD §2.6).
NITROGEN_RATE_MIN = 0.00
NITROGEN_RATE_MAX = 6.00

# ---------------------------------------------------------------------------
# Capital planning (PRD §3.9)
# ---------------------------------------------------------------------------

#: Unit construction cost keyed on `target_surface_type`.
COST_PER_SQ_FT_CENTS = {
    "NATURAL_GRASS": 22,
    "SYNTHETIC_TURF": 65,
}

#: Disposal cost per square foot when the existing surface is synthetic.
SYNTHETIC_DISPOSAL_CENTS_PER_SQ_FT = 5

#: Contingency tiers as (exclusive_upper_bound_of_subtotal, rate).
#: A null bound means "this subtotal or more".
CONTINGENCY_TIERS = (
    (2000000, 0.10),
    (5000000, 0.07),
    (None, 0.05),
)

#: Warranty penalty shared by both priority variants.
WARRANTY_EXPIRED_PENALTY = 8.00

#: REMAINING_LIFE variant.
AGE_POINTS_PER_YEAR = 6.00
WEAR_UNITS_PER_PRIORITY_POINT = 25.00
WEAR_POINTS_CAP = 20.00

#: CONDITION_RISK variant.
CONDITION_POINTS_PER_INDEX_POINT = 0.80
MANDATORY_ORDER_POINTS = 5.00
PRIORITY_LOOKBACK_DAYS = 365

#: Approval floor on `replacement_priority_score`.
MIN_APPROVAL_PRIORITY_SCORE = 20.00

#: A budget locks when commitment reaches this fraction of the authorisation.
BUDGET_LOCK_TRIGGER_RATIO = 0.90

#: Disposal diversion policy floor.
MIN_DIVERSION_RATIO = 0.75

# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------

DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100
