"""Domain thresholds — numeric constants from the PRD workflows."""
from prd_bench_local_runner.testing import NON_EXISTENT_UUID  # re-exported for convenience

# Candidacy floors used for a SELF_PAY program (PRD §3.2).
DEFAULT_BMI_FLOOR_NO_COMORBIDITY = 40.0
DEFAULT_BMI_FLOOR_WITH_COMORBIDITY = 35.0
DEFAULT_QUALIFYING_COMORBIDITIES = [
    "TYPE_2_DIABETES", "HYPERTENSION", "OSA", "NAFLD", "DYSLIPIDEMIA",
]

# Case-bundle pricing (PRD §3.4 / §3.5), integer cents.
BASE_CENTS = {
    "SLEEVE_GASTRECTOMY": 1_800_000,
    "GASTRIC_BYPASS": 2_500_000,
    "ADJUSTABLE_BAND": 1_500_000,
}
STANDARD_OR_MINUTES = {
    "SLEEVE_GASTRECTOMY": 90,
    "GASTRIC_BYPASS": 150,
    "ADJUSTABLE_BAND": 60,
}
OVERTIME_RATE_CENTS_PER_MIN = 25_000
BMI_SURCHARGE_HIGH = 0.15   # baseline_bmi >= 50
BMI_SURCHARGE_MID = 0.08    # baseline_bmi >= 40

# Weight-loss outcome reference (PRD §3.6).
REFERENCE_BMI = 25.0

# Cancellation refund (PRD §3.5), integer cents.
CANCELLATION_FEE_CENTS = 100_000

# Follow-up series offsets in days (PRD §3.6).
INTERVAL_OFFSET_DAYS = {
    "WEEK_2": 14,
    "WEEK_6": 42,
    "MONTH_3": 90,
    "MONTH_6": 180,
    "MONTH_12": 365,
}
FOLLOW_UP_INTERVAL_CODES = ["WEEK_2", "WEEK_6", "MONTH_3", "MONTH_6", "MONTH_12"]

REQUIRED_MILESTONES = [
    "NUTRITION_CLASS", "EXERCISE_ORIENTATION", "SURGERY_RISKS_CONSENT", "POST_OP_DIET_EDUCATION",
]

# Logical clock default (PRD §2.7).
DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00Z"

# Convenient future surgery window (after the default clock).
DEFAULT_SURGERY_START = "2026-06-15T08:00:00Z"
DEFAULT_SURGERY_END = "2026-06-15T09:30:00Z"
