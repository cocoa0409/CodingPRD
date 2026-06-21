"""Domain thresholds — numeric constants drawn from PRD §2.7, §2.8, §3.3, §3.5, §3.7, §3.8."""

# ─── Capped Plan of Care annual dollar limits (PRD §2.7), in cents ───
CAPPED_DOLLAR_LIMIT_CENTS = {
    "MEDICARE": 20000,
    "COMMERCIAL": 50000,
    "MEDICAID": 10000,
    "VA_TRICARE": 30000,
    "SELF_PAY": 100000,
}

# ─── Capped Plan of Care posture (PRD §2.7) ─────────────────────────
WARNING_RATIO = 0.90  # inclusive boundary for AT_CAP_WARNING

# ─── CMS 8-minute rule constants (PRD §3.3, §3.5) ────────────────────
UNIT_MINUTES = 15
MIN_BILLABLE_MINUTES = 8

# ─── CPT per-unit rates in cents (PRD §3.5) ──────────────────────────
CPT_RATE_CENTS = {
    "CPT_97110_THER_EX": 3200,
    "CPT_97112_NEURO_REED": 3900,
    "CPT_97140_MANUAL": 3500,
    "CPT_97530_THER_ACT": 3700,
}

# ─── MPPR factor (PRD §3.5, §2.8) ────────────────────────────────────
MPPR_FACTOR = 0.5

# ─── MIPS composite-score constants (PRD §3.7) ───────────────────────
MIPS_BASE_SCORE = {
    "MIPS128_FALL_RISK": 60.0,
    "MIPS131_PAIN_ASSESSMENT": 18.0,
    "MIPS182_FUNCTIONAL_OUTCOME": 70.0,
}
MIPS_NUMERATOR_BONUS = 25.0
MIPS_ENGAGEMENT_PER_HEP = 3.5
MIPS_ENGAGEMENT_CAP = 10.0
MIPS_IMPROVEMENT_FACTOR = 0.5
MIPS_IMPROVEMENT_CAP = 15.0
MIPS_ACCEPTANCE_THRESHOLD = 30.0

# ─── Discharge outcome thresholds (PRD §3.8) ─────────────────────────
DISCHARGE_SUCCESS_THRESHOLD = 0.80
DISCHARGE_PARTIAL_THRESHOLD = 0.40

# ─── Test defaults used by factories / fixtures ──────────────────────
DEFAULT_DIAGNOSIS_ICD10 = "M54.5"
DEFAULT_LICENSE_STATE = "CA"
