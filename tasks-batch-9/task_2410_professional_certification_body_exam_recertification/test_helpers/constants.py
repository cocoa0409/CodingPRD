"""Domain thresholds and numeric constants stated in the PRD.

Every value here is quoted from PRD prose, not invented. Tests import these so a
single edit propagates, and so the numeric literal in a test reads as domain
language rather than a magic number.
"""

# ---------------------------------------------------------------------------
# The logical clock (PRD §2.4)
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Program tuning-knob defaults (PRD §3.1)
# ---------------------------------------------------------------------------

PROGRAM_DEFAULTS = {
    "psychometric_stat_basis": "OPERATIONAL_ONLY",
    "min_discrimination": 0.15,
    "min_p_value": 0.20,
    "max_p_value": 0.95,
    "min_responses_for_stats": 30,
    "form_retirement_tolerance_pct": 10,
    "min_panelists": 5,
    "panel_trim_count": 1,
    "cut_score_sem_multiplier": 0.5,
    "education_recency_years": 10,
    "min_experience_months": 24,
    "audit_every_nth": 3,
    "eligibility_valid_days": 365,
    "exam_fee_cents": 45000,
    "max_attempts_per_cycle": 3,
    "retake_wait_days": 45,
    "cycle_length_months": 36,
    "required_ceu_credits": 60,
    "ceu_credit_accrual_basis": "STRICT_CYCLE",
    "ceu_carryover_max_credits": 10,
    "recert_grace_days": 90,
}

# ---------------------------------------------------------------------------
# Continuing-education credit multipliers and per-cycle caps (PRD §3.11)
# ---------------------------------------------------------------------------

CEU_MULTIPLIERS = {
    "LIVE_INSTRUCTION": 1.0,
    "SELF_STUDY": 0.5,
    "PRESENTING": 2.0,
    "PUBLICATION": 5.0,
    "VOLUNTEER": 0.25,
}

CEU_CATEGORY_CAPS = {
    "SELF_STUDY": 20.0,
    "VOLUNTEER": 5.0,
}

CEU_CARRYOVER_LOOKBACK_DAYS = 90

# ---------------------------------------------------------------------------
# Reinstatement fee arithmetic (PRD §3.11)
# ---------------------------------------------------------------------------

REINSTATEMENT_BASE_CENTS = 25000
REINSTATEMENT_LATE_DAY_RATE_CENTS = 250
REINSTATEMENT_MAX_SURCHARGE_CENTS = 30000
REINSTATEMENT_ADMIN_RATE_LOW = 0.02        # subtotal at most 30000 cents
REINSTATEMENT_ADMIN_RATE_MID = 0.05        # subtotal above 30000, at most 45000
REINSTATEMENT_ADMIN_RATE_HIGH = 0.08       # subtotal above 45000
REINSTATEMENT_TIER_LOW_CEILING_CENTS = 30000
REINSTATEMENT_TIER_MID_CEILING_CENTS = 45000

# ---------------------------------------------------------------------------
# Scheduling and delivery (PRD §3.7 – §3.8)
# ---------------------------------------------------------------------------

PROCTOR_POOL_CEILING_SEATS = 50
CANDIDATE_WINDOW_BUFFER_MINUTES = 120
CHECKIN_WINDOW_OPENS_MINUTES_BEFORE = 30

# ---------------------------------------------------------------------------
# Score equating band (PRD §3.8)
# ---------------------------------------------------------------------------

SCALED_SCORE_FLOOR = 200
SCALED_SCORE_CUT_ANCHOR = 500
SCALED_SCORE_CEILING = 800
PASS_SCALED_SCORE = 500

# ---------------------------------------------------------------------------
# Cut-score clamp (PRD §3.5)
# ---------------------------------------------------------------------------

CUT_SCORE_LOWER_BOUND_FRACTION = 0.40
CUT_SCORE_UPPER_BOUND_FRACTION = 0.90

# ---------------------------------------------------------------------------
# Sanctions and bars (PRD §3.9, §3.12)
# ---------------------------------------------------------------------------

SECURITY_BAR_DAYS = 730
SANCTION_MONTHS_MIN = 1
SANCTION_MONTHS_MAX = 60

# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

# ---------------------------------------------------------------------------
# Rounding discipline (PRD §2.6)
# ---------------------------------------------------------------------------

ITEM_STAT_DECIMALS = 4
STANDARD_SETTING_DECIMALS = 6
CEU_CREDIT_DECIMALS = 2
