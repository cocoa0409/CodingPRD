"""Domain thresholds, office parameter defaults and canonical instants.

Every value here is stated in the PRD; nothing is invented.
"""

# --------------------------------------------------------------------------
# Logical clock (PRD 2.7)
# --------------------------------------------------------------------------

#: The server startup default; the clock reads exactly this before it is set.
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"


# --------------------------------------------------------------------------
# Office policy parameter defaults (PRD 2.10)
# --------------------------------------------------------------------------

DEFAULT_CE_THRESHOLD_DISTURBANCE_HECTARES = 5.0
DEFAULT_EA_THRESHOLD_DISTURBANCE_HECTARES = 100.0
DEFAULT_MIN_SCOPING_DAYS = 30
DEFAULT_MIN_EA_COMMENT_DAYS = 30
DEFAULT_MIN_EIS_COMMENT_DAYS = 45
DEFAULT_OBJECTION_WINDOW_DAYS = 45
DEFAULT_CUMULATIVE_RADIUS_KM = 25.0
DEFAULT_SIGNIFICANCE_THRESHOLD = 60.0
DEFAULT_INTENSITY_WEIGHT = 0.6
DEFAULT_CONTEXT_WEIGHT = 0.4
DEFAULT_MIN_ALTERNATIVE_FEASIBILITY = 60.0
DEFAULT_MAX_MITIGATED_REDUCTION_POINTS = 18.0
DEFAULT_COST_PER_REDUCTION_POINT_CENTS = 250000
DEFAULT_MONITORING_ESCALATION_FACTOR = 1.035
DEFAULT_MAX_BINDING_OBLIGATION_CENTS = 900000000
DEFAULT_EXTRAORDINARY_CIRCUMSTANCE_CODES = [
    "EC_HISTORIC",
    "EC_ENDANGERED_SPECIES",
    "EC_WETLAND",
]
DEFAULT_EC_SEVERITY_TRIGGER_THRESHOLD = 3
DEFAULT_MIN_SCREENED_IN_ALTERNATIVES_EA = 1
DEFAULT_MIN_SCREENED_IN_ALTERNATIVES_EIS = 2

#: All twenty configurable office parameters with their declared defaults.
OFFICE_PARAMETER_DEFAULTS = {
    "ce_threshold_disturbance_hectares": DEFAULT_CE_THRESHOLD_DISTURBANCE_HECTARES,
    "ea_threshold_disturbance_hectares": DEFAULT_EA_THRESHOLD_DISTURBANCE_HECTARES,
    "min_scoping_days": DEFAULT_MIN_SCOPING_DAYS,
    "min_ea_comment_days": DEFAULT_MIN_EA_COMMENT_DAYS,
    "min_eis_comment_days": DEFAULT_MIN_EIS_COMMENT_DAYS,
    "objection_window_days": DEFAULT_OBJECTION_WINDOW_DAYS,
    "cumulative_radius_km": DEFAULT_CUMULATIVE_RADIUS_KM,
    "significance_threshold": DEFAULT_SIGNIFICANCE_THRESHOLD,
    "intensity_weight": DEFAULT_INTENSITY_WEIGHT,
    "context_weight": DEFAULT_CONTEXT_WEIGHT,
    "min_alternative_feasibility": DEFAULT_MIN_ALTERNATIVE_FEASIBILITY,
    "max_mitigated_reduction_points": DEFAULT_MAX_MITIGATED_REDUCTION_POINTS,
    "cost_per_reduction_point_cents": DEFAULT_COST_PER_REDUCTION_POINT_CENTS,
    "monitoring_escalation_factor": DEFAULT_MONITORING_ESCALATION_FACTOR,
    "max_binding_obligation_cents": DEFAULT_MAX_BINDING_OBLIGATION_CENTS,
    "extraordinary_circumstance_codes": DEFAULT_EXTRAORDINARY_CIRCUMSTANCE_CODES,
    "ec_severity_trigger_threshold": DEFAULT_EC_SEVERITY_TRIGGER_THRESHOLD,
    "min_screened_in_alternatives_ea": DEFAULT_MIN_SCREENED_IN_ALTERNATIVES_EA,
    "min_screened_in_alternatives_eis": DEFAULT_MIN_SCREENED_IN_ALTERNATIVES_EIS,
}


# --------------------------------------------------------------------------
# Agency scheduling parameter defaults (PRD 3.1)
# --------------------------------------------------------------------------

DEFAULT_MAX_CONCURRENT_CONSULTATIONS = 2
DEFAULT_HANDOFF_BUFFER_DAYS = 3
DEFAULT_STATUTORY_RESPONSE_DAYS = 135


# --------------------------------------------------------------------------
# Pinned arithmetic constants (PRD 3.4, 3.7, 3.9)
# --------------------------------------------------------------------------

#: Alternative feasibility weights: 0.65 on alignment, 0.35 on cost factor.
FEASIBILITY_ALIGNMENT_WEIGHT = 0.65
FEASIBILITY_COST_WEIGHT = 0.35

#: Cumulative baseline footprint weight is 1 + hectares/200, added term capped.
CUMULATIVE_FOOTPRINT_DIVISOR = 200.0
CUMULATIVE_FOOTPRINT_CAP = 0.5
CUMULATIVE_TEMPORAL_FACTORS = {
    "PAST": 0.75,
    "PRESENT": 1.0,
    "REASONABLY_FORESEEABLE": 0.85,
}
#: Crowding multiplier adds 0.05 per included entry beyond the first three.
CUMULATIVE_CROWDING_FREE_ENTRIES = 3
CUMULATIVE_CROWDING_STEP = 0.05

#: Significance uplift applies to the amount above this cumulative score.
CUMULATIVE_UPLIFT_FLOOR = 40.0
CUMULATIVE_UPLIFT_RATE = 0.15
#: The direct significance term is capped here before mitigation subtraction.
SIGNIFICANCE_DIRECT_TERM_CAP = 100.0

#: Area tier adders, keyed by the inclusive upper bound of the tier.
AREA_TIER_ADDERS = [
    (0.0, 0.0),
    (5.0, 2.0),
    (25.0, 4.0),
    (100.0, 7.0),
]
AREA_TIER_ADDER_ABOVE_TOP = 11.0

#: Contingency fee rate tiers keyed on the frozen credit_points figure.
FEE_RATE_CREDIT_10_OR_MORE = 0.05
FEE_RATE_CREDIT_5_TO_10 = 0.035
FEE_RATE_CREDIT_BELOW_5 = 0.02


# --------------------------------------------------------------------------
# Pagination (PRD 2.3)
# --------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0
