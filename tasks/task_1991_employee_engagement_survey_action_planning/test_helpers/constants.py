"""Domain thresholds and default timestamps from the PRD."""

# Calculation constants (PRD §2.11, §3.3-§3.8)
LIKERT_STEP = 25                  # raw score 1..5 -> 0..100 (§3.5)
PARTIAL_WEIGHT = 0.5              # partial invites count at half weight (§3.5)
RATE_DP = 4                       # response_rate / attrition_risk decimals
SCORE_DP = 2                      # dimension / overall / percentile decimals
PRODUCT_DP = 4                    # per-answer weighted product decimals
TENURE_GATE_DAYS = 30             # census/pulse eligibility gate (§3.3)
MIN_ITEMS_TO_ACTIVATE = 3         # bank activation / cycle configure floor (§3.1, §3.3)
MIN_N_FLOOR = 3                   # min_n_threshold range lower bound (§2.6)
MIN_N_CEILING = 20                # min_n_threshold range upper bound (§2.6)
DEFAULT_MIN_N_THRESHOLD = 5       # OrgUnit default (§3.2)
DEFAULT_VERBATIM_N_THRESHOLD = 10  # OrgUnit default (§3.2)
REMINDER_CAP = 3                  # max reminders per invite (§3.4)
FIRST_REMINDER_DELAY_HOURS = 24   # first reminder eligible 24h after open (§3.4)
REMINDER_INTERVAL_HOURS = 48      # subsequent reminders 48h apart (§3.4)
MIN_BENCHMARK_ENTRIES = 5         # benchmark distribution floor (§3.6)
LOW_SCORE_FLOOR = 60.00           # low-engagement floor for risk modifier (§3.8)
RISK_COEFF = 1.75                 # attrition risk coefficient (§3.8)
BASE_RATE_PRIOR = 0.08            # provisional risk prior base rate (§3.8)
WEIGHT_MIN = 0.1                  # survey item weight bounds (§2.11)
WEIGHT_MAX = 5.0

# Logical clock (PRD §2.5)
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# Common timestamps used across scenarios
HIRED_LONG_AGO = "2026-01-01T00:00:00Z"   # safely outside the 30-day tenure gate
DEFAULT_OPENS_AT = "2026-09-01T00:00:00Z"
DEFAULT_CLOSES_AT = "2026-09-15T00:00:00Z"
DEFAULT_PLAN_DUE_AT = "2026-12-01T00:00:00Z"
DEFAULT_ITEM_TARGET_AT = "2026-11-01T00:00:00Z"

TEST_DEFAULTS = {
    "BANK_FRAMEWORK": "CUSTOM",
    "ITEM_WEIGHT": 1.0,
    "ITEM_DIMENSION": "PURPOSE",
    "MIN_N": 3,
    "VERBATIM_N": 5,
    "ANSWER_SCORE": 4,
}
