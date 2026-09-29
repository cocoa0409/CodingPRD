"""Named constants stated literally in the PRD.

Nothing here is inferred: every value appears in the narrative, either as a
global threshold or as an enumerated value domain. Tests import these rather
than repeating bare numbers, so a threshold appears once.
"""

from typing import Dict, List, Tuple

# --- Logical clock (PRD 2.9) ------------------------------------------------
# "Before any call is made the clock reads 2026-08-01T00:00:00Z"; it is
# forward-only and advancing it fires no cascade.
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"
CLOCK_PATH = "/_clock/set_current_utc"

# --- Pagination and ordering (PRD 2.3) -------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --- Roles (PRD 2.1) -------------------------------------------------------
ROLE_DATA_ENGINEER = "DataEngineer"
ROLE_MODELER = "Modeler"
ROLE_EXPERIMENT_DESIGNER = "ExperimentDesigner"
ROLE_ANALYTICS_LEAD = "AnalyticsLead"
ROLE_BRAND_PLANNER = "BrandPlanner"
ROLE_AUDITOR = "Auditor"

ALL_ROLES: Tuple[str, ...] = (
    ROLE_DATA_ENGINEER,
    ROLE_MODELER,
    ROLE_EXPERIMENT_DESIGNER,
    ROLE_ANALYTICS_LEAD,
    ROLE_BRAND_PLANNER,
    ROLE_AUDITOR,
)

# Every role except Auditor may advance the clock.
CLOCK_ROLES: Tuple[str, ...] = (
    ROLE_DATA_ENGINEER,
    ROLE_MODELER,
    ROLE_EXPERIMENT_DESIGNER,
    ROLE_ANALYTICS_LEAD,
    ROLE_BRAND_PLANNER,
)

# --- Global thresholds -----------------------------------------------------
# Holdout share ceiling: the assigned share may not exceed 20 percent of the
# market's total_population, compared in exact integers on both sides (PRD 3.6).
MAX_HOLDOUT_POPULATION_PCT = 20

# An experiment must reach a computed_power of at least 0.80 to lock (PRD 3.6).
MIN_EXPERIMENT_POWER = 0.80

# A backtest passes at a holdout_mape_pct of 12.00 or below (PRD 3.5).
MAPE_CEILING_PCT = 12.00

# A refresh below a stability_score of 0.6000 is refused unless overridden.
STABILITY_FLOOR = 0.6000

# A reconciliation gap of 15.00 percent or more is MATERIAL (PRD 3.9).
MATERIALITY_PCT = 15.00

# The calibration multiplier is admissible only inside [0.25, 4.00] (PRD 3.7).
CALIBRATION_MULTIPLIER_FLOOR = 0.25
CALIBRATION_MULTIPLIER_CEILING = 4.00

# Bias direction bands around 1.0 (PRD 3.7).
CALIBRATION_ALIGNMENT_BAND = 0.05
BIAS_OVER_ATTRIBUTED_BELOW = 0.95
BIAS_UNDER_ATTRIBUTED_ABOVE = 1.05

# Contribution confidence interval: 40.0 / sqrt(observation_period_count).
CI_BASE_PCT = 40.0

# Two-sided normal quantile used by the lift interval (PRD 3.6).
Z_ALPHA_TWO_SIDED = 1.96

# The optimizer awards budget in whole steps of this size (PRD 3.8).
MARGINAL_STEP_CENTS = 100000

# A rejected design may be reworked at most twice (PRD 3.6).
MAX_REDESIGNS = 2

# A window needs at least four sales periods before it may be sealed (PRD 3.3).
MIN_SEALED_PERIOD_COUNT = 4

# --- Value domains ---------------------------------------------------------
CHANNEL_TYPES: Tuple[str, ...] = (
    "SEARCH",
    "SOCIAL",
    "VIDEO",
    "DISPLAY",
    "OOH",
    "TV",
    "RETAIL_MEDIA",
)
CHANNEL_STATUSES: Tuple[str, ...] = ("ACTIVE", "PAUSED", "RETIRED")
DATA_POSTURES: Tuple[str, ...] = ("OPEN", "RESTRICTED", "FROZEN")
CELL_ASSIGNMENT_STATES: Tuple[str, ...] = (
    "UNASSIGNED",
    "TREATMENT",
    "CONTROL",
    "WASHOUT",
)
WINDOW_STATUSES: Tuple[str, ...] = ("OPEN", "SEALED", "REOPENED")
GRANULARITIES: Tuple[str, ...] = ("WEEKLY", "DAILY")
CONTROL_VARIABLES: Tuple[str, ...] = (
    "PRICE_INDEX",
    "DISTRIBUTION_INDEX",
    "MACRO_INDEX",
    "SEASONALITY_WEEK_OF_YEAR",
)
SEASONALITY_MODES: Tuple[str, ...] = ("NONE", "WEEK_OF_YEAR", "MONTH_OF_YEAR")
CARRYOVER_MODES: Tuple[str, ...] = ("EFFECT_PERIOD", "SPEND_PERIOD")
FIT_STATUSES: Tuple[str, ...] = ("PENDING", "FITTED", "STALE_FIT")
VALIDATION_STATUSES: Tuple[str, ...] = (
    "UNVALIDATED",
    "HOLDOUT_PASSED",
    "HOLDOUT_FAILED",
)
CALIBRATION_STATUSES: Tuple[str, ...] = (
    "NOT_REQUIRED",
    "PENDING_CALIBRATION",
    "CALIBRATED",
    "STALE",
)
PUBLICATION_STATUSES: Tuple[str, ...] = ("UNPUBLISHED", "PUBLISHED", "SUPERSEDED")
DESIGN_TYPES: Tuple[str, ...] = ("GEO_HOLDOUT", "AUDIENCE_SPLIT")
READOUT_METHODS: Tuple[str, ...] = ("DIFF_IN_DIFF", "SYNTHETIC_CONTROL")
EXPERIMENT_STATUSES: Tuple[str, ...] = (
    "DRAFT",
    "DESIGN_LOCKED",
    "CELLS_ASSIGNED",
    "RUNNING",
    "READ_OUT",
    "ACCEPTED",
    "REJECTED",
    "CLOSED",
)
BIAS_DIRECTIONS: Tuple[str, ...] = (
    "OVER_ATTRIBUTED",
    "UNDER_ATTRIBUTED",
    "ALIGNED",
)
SCENARIO_STATUSES: Tuple[str, ...] = (
    "DRAFT",
    "OPTIMIZED",
    "FROZEN",
    "APPROVED",
    "INVALIDATED",
)
CONSTRAINT_BINDINGS: Tuple[str, ...] = ("NONE", "FLOOR", "CEILING")
REPORT_BASES: Tuple[str, ...] = ("RAW", "CALIBRATED")
REPORT_STATUSES: Tuple[str, ...] = ("CURRENT", "STALE")

# The occupancy test treats these experiment statuses as live (PRD 3.6).
LIVE_EXPERIMENT_STATUSES: Tuple[str, ...] = (
    "DESIGN_LOCKED",
    "CELLS_ASSIGNED",
    "RUNNING",
    "READ_OUT",
    "ACCEPTED",
)

# --- The power step table, verbatim from PRD 3.6 ---------------------------
# Upper bounds are strict: a power_index of exactly 2.5000 lands on the 0.8000
# row, while 2.4999 lands on 0.7500.
POWER_STEP_TABLE: List[Tuple[float, float]] = [
    (1.0000, 0.2000),
    (1.6000, 0.4500),
    (2.0000, 0.6500),
    (2.5000, 0.7500),
    (2.8000, 0.8000),
    (3.2400, 0.9000),
]
POWER_TOP_STEP = 0.9500

# --- Declared decimal places (PRD 2.6) -------------------------------------
DECIMALS_UNIT_QUANTITY = 4
DECIMALS_PERCENTAGE = 2
DECIMALS_MARGINAL_ROI = 6
DECIMALS_SYNTHETIC_WEIGHT = 6
DECIMALS_SQRT_INTERMEDIATE = 12

# --- Collection tie-breaks after created_at ASC (PRD 2.3) ------------------
LIST_TIE_BREAKS: Dict[str, Tuple[str, ...]] = {
    "markets": ("market_code",),
    "media-channels": ("channel_code",),
    "geo-cells": ("cell_code",),
    "spend-observations": ("period_start_date", "channel_code"),
    "sales-observations": ("period_start_date", "channel_code"),
    "channel-contributions": ("channel_code",),
    "budget-allocations": ("channel_code",),
    "data-windows": ("window_start_date",),
    "experiments": ("start_date",),
    "budget-scenarios": ("planning_start_date",),
    "model-runs": ("created_at",),
    "calibration-records": ("created_at",),
    "reconciliation-reports": ("created_at",),
}
