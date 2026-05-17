"""Domain thresholds — numeric constants used by tests.

Each constant traces back to a verbatim sentence in PRD.md.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Logical clock — PRD §2.5
# ---------------------------------------------------------------------------
# PRD §2.5: "On clinic creation, now_ts is set to the deterministic epoch
# 2025-01-01T00:00:00.000Z."
CLOCK_EPOCH: str = "2025-01-01T00:00:00.000Z"


# ---------------------------------------------------------------------------
# Unit-hour economy — PRD §2.9
# ---------------------------------------------------------------------------
# PRD §2.9: "The system tracks therapy in 15-minute billing units …
# Whenever a real-world duration must be converted into units, the
# minute-count is divided by 15 and rounded up to the next whole unit."
MINUTES_PER_UNIT: int = 15


# ---------------------------------------------------------------------------
# Supervision ratio — PRD §2.10
# ---------------------------------------------------------------------------
# PRD §2.10: "The plan may only activate when this ratio is greater than
# or equal to 0.10 — the boundary is inclusive, so a ratio of exactly
# 0.10 passes, but 0.099999 fails."
SUPERVISION_RATIO_MIN: float = 0.10

# PRD §2.10: "a dynamic ratio is computed against the actual sessions
# delivered in the trailing 30 days ending at the clinic's current
# now_ts."
SUPERVISION_WINDOW_DAYS: int = 30


# ---------------------------------------------------------------------------
# Patient progress score window — PRD §3.7
# ---------------------------------------------------------------------------
# PRD §3.7: "Both are weighted averages of progress_rating values
# weighted by billed_units, computed over the trailing 90-day window
# ending at the clinic's current now_ts".
PROGRESS_WINDOW_DAYS: int = 90


# ---------------------------------------------------------------------------
# Reimbursement tiered rates (cents per unit) — PRD §3.6
# ---------------------------------------------------------------------------
# PRD §3.6: "DIRECT_RBT is reimbursed at 3333 cents per unit
# (approximately $33.33 per 15 minutes), BCBA_SUPERVISION at 6800 cents
# per unit, and PARENT_TRAINING at 5000 cents per unit."
RATE_DIRECT_RBT_CENTS: int = 3333
RATE_BCBA_SUPERVISION_CENTS: int = 6800
RATE_PARENT_TRAINING_CENTS: int = 5000

TIERED_RATES_CENTS = {
    "DIRECT_RBT": RATE_DIRECT_RBT_CENTS,
    "BCBA_SUPERVISION": RATE_BCBA_SUPERVISION_CENTS,
    "PARENT_TRAINING": RATE_PARENT_TRAINING_CENTS,
}

# PRD §3.6: "when the payer has no specific entry, the default
# patient-responsibility percentage is fifteen one-hundredths."
PATIENT_RESPONSIBILITY_DEFAULT: float = 0.15


# ---------------------------------------------------------------------------
# Appeal haircut — PRD §3.6
# ---------------------------------------------------------------------------
# PRD §3.6: "the haircut factor is (1 − 0.05) raised to the power of
# appeal_round, so the first appeal pays at 95% of the base line
# amount, the second appeal pays at 90.25% of the base line amount".
APPEAL_HAIRCUT_PER_ROUND: float = 0.05

# PRD §3.6: "a third appeal attempt is rejected with
# ERR_APPEAL_LIMIT_REACHED."
APPEAL_ROUND_MAX: int = 2


# ---------------------------------------------------------------------------
# Authorization — PRD §3.4
# ---------------------------------------------------------------------------
# PRD §3.4: "the integer approved_units (in the inclusive range 1 to
# 4000 — recall that one unit equals 15 minutes)".
APPROVED_UNITS_MIN: int = 1
APPROVED_UNITS_MAX: int = 4000

# PRD §3.4: "the elapsed span between them must be at least 90 days and
# at most 366 days (both bounds inclusive)."
AUTH_WINDOW_DAYS_MIN: int = 90
AUTH_WINDOW_DAYS_MAX: int = 366


# ---------------------------------------------------------------------------
# Treatment plan parent-training target range — PRD §3.3
# ---------------------------------------------------------------------------
# PRD §3.3: "weekly_parent_training_hours_target must fall in the closed
# range from 0.5 to 4.0".
PARENT_TRAINING_TARGET_MIN: float = 0.5
PARENT_TRAINING_TARGET_MAX: float = 4.0


# ---------------------------------------------------------------------------
# Evaluation — PRD §3.2
# ---------------------------------------------------------------------------
# PRD §3.2: "The recommended hours must be an integer in the inclusive
# range from 5 to 40."
RECOMMENDED_WEEKLY_HOURS_MIN: int = 5
RECOMMENDED_WEEKLY_HOURS_MAX: int = 40


# ---------------------------------------------------------------------------
# Session — PRD §3.5
# ---------------------------------------------------------------------------
# PRD §3.5: "its length in minutes — planned_end minus planned_start
# measured in whole minutes — must be in the inclusive range from 15 to
# 480 minutes (that is, between 1 and 32 units inclusive)."
SESSION_MIN_MINUTES: int = 15
SESSION_MAX_MINUTES: int = 480
SESSION_MIN_UNITS: int = 1
SESSION_MAX_UNITS: int = 32

# PRD §3.5: "Parent-training sessions impose an additional restriction on
# the patient — the planned interval expanded by 15 minutes on each side
# must not collide with any other session".
PARENT_TRAINING_BUFFER_MINUTES: int = 15

# PRD §3.5: "the progress_rating, an integer in the inclusive range
# from 1 to 5."
PROGRESS_RATING_MIN: int = 1
PROGRESS_RATING_MAX: int = 5


# ---------------------------------------------------------------------------
# CPT codes — PRD §3.4 / §3.5
# ---------------------------------------------------------------------------
# PRD §3.4: "the cpt_code (one of 97151 for evaluation, 97153 for direct
# RBT therapy, 97155 for BCBA supervision, or 97156 for parent training)"
CPT_CODE_EVAL: str = "97151"
CPT_CODE_DIRECT_RBT: str = "97153"
CPT_CODE_BCBA_SUPERVISION: str = "97155"
CPT_CODE_PARENT_TRAINING: str = "97156"
CPT_CODES_ALL = (
    CPT_CODE_EVAL,
    CPT_CODE_DIRECT_RBT,
    CPT_CODE_BCBA_SUPERVISION,
    CPT_CODE_PARENT_TRAINING,
)

# Session-type ↔ CPT code mapping — PRD §3.5.
SESSION_TYPE_CPT_MAP = {
    "DIRECT_RBT": CPT_CODE_DIRECT_RBT,
    "BCBA_SUPERVISION": CPT_CODE_BCBA_SUPERVISION,
    "PARENT_TRAINING": CPT_CODE_PARENT_TRAINING,
}


# ---------------------------------------------------------------------------
# Treatment-plan auto-expiration — PRD §3.3
# ---------------------------------------------------------------------------
# PRD §3.3: "A plan moves to EXPIRED automatically when the clinic's
# now_ts advances past 365 days after its activated_at."
TREATMENT_PLAN_LIFETIME_DAYS: int = 365


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
# PRD §2.3: "The default limit is 10; the minimum accepted value is 1
# and the maximum accepted value is 100. The default offset is 0;
# values less than 0 are rejected."
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Time conversions (seconds) — used by clock-advance fixtures.
# ---------------------------------------------------------------------------
SECONDS_PER_MINUTE: int = 60
SECONDS_PER_HOUR: int = 3600
SECONDS_PER_DAY: int = 86_400


# ---------------------------------------------------------------------------
# Test defaults — anchored values used by fixtures.
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "DEFAULT_PAYER_NAME": "TestPayer",
    "DEFAULT_DOB": "2018-06-15",
    "DEFAULT_LICENSE_NUMBER_PREFIX": "LIC",
    # Recommended weekly hours used by setup-evaluation flow.
    "DEFAULT_RECOMMENDED_WEEKLY_HOURS": 20,
    # Treatment plan default targets: 20 direct, 2 supervision (ratio 0.10),
    # 1 parent training.
    "DEFAULT_WEEKLY_DIRECT_HOURS_TARGET": 20,
    "DEFAULT_WEEKLY_SUPERVISION_HOURS_TARGET": 2.0,
    "DEFAULT_WEEKLY_PARENT_TRAINING_HOURS_TARGET": 1.0,
    # Authorization defaults — generous quota.
    "DEFAULT_APPROVED_UNITS": 240,
    # 180 days — comfortably inside the 90–366 day window.
    "DEFAULT_AUTH_WINDOW_DAYS": 180,
    # Default session minute durations (in units of 15 minutes).
    "DEFAULT_SESSION_MINUTES": 60,  # 4 units
    "DEFAULT_PROGRESS_RATING": 4,
    # Diagnosis code (ICD-10 example used in PRD §3.2).
    "DEFAULT_DIAGNOSIS_CODE": "F84.0",
    "DEFAULT_SEVERITY_LEVEL": "LEVEL_2",
}


__all__ = [
    "CLOCK_EPOCH",
    "MINUTES_PER_UNIT",
    "SUPERVISION_RATIO_MIN",
    "SUPERVISION_WINDOW_DAYS",
    "PROGRESS_WINDOW_DAYS",
    "RATE_DIRECT_RBT_CENTS",
    "RATE_BCBA_SUPERVISION_CENTS",
    "RATE_PARENT_TRAINING_CENTS",
    "TIERED_RATES_CENTS",
    "PATIENT_RESPONSIBILITY_DEFAULT",
    "APPEAL_HAIRCUT_PER_ROUND",
    "APPEAL_ROUND_MAX",
    "APPROVED_UNITS_MIN",
    "APPROVED_UNITS_MAX",
    "AUTH_WINDOW_DAYS_MIN",
    "AUTH_WINDOW_DAYS_MAX",
    "PARENT_TRAINING_TARGET_MIN",
    "PARENT_TRAINING_TARGET_MAX",
    "RECOMMENDED_WEEKLY_HOURS_MIN",
    "RECOMMENDED_WEEKLY_HOURS_MAX",
    "SESSION_MIN_MINUTES",
    "SESSION_MAX_MINUTES",
    "SESSION_MIN_UNITS",
    "SESSION_MAX_UNITS",
    "PARENT_TRAINING_BUFFER_MINUTES",
    "PROGRESS_RATING_MIN",
    "PROGRESS_RATING_MAX",
    "CPT_CODE_EVAL",
    "CPT_CODE_DIRECT_RBT",
    "CPT_CODE_BCBA_SUPERVISION",
    "CPT_CODE_PARENT_TRAINING",
    "CPT_CODES_ALL",
    "SESSION_TYPE_CPT_MAP",
    "TREATMENT_PLAN_LIFETIME_DAYS",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "SECONDS_PER_MINUTE",
    "SECONDS_PER_HOUR",
    "SECONDS_PER_DAY",
    "TEST_DEFAULTS",
]
