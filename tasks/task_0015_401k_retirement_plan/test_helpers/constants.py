"""Domain thresholds — numeric constants from PRD calculations and limits."""

# ─── Regulatory caps (PRD §3.1 default values) ─────────────────────────────
DEFAULT_ANNUAL_COMPENSATION_LIMIT_CENTS = 34_500_000  # §401(a)(17)
DEFAULT_ANNUAL_DEFERRAL_LIMIT_CENTS = 2_300_000       # §402(g)

# ─── Match calculation (PRD §3.3) ───────────────────────────────────────────
BIWEEKLY_DIVISOR = 26
TIER1_MAX_BPS = 300      # First tier deferral cap (3% of comp)
TIER2_MAX_BPS = 200      # Second tier deferral cap (2% of additional)
SAFE_HARBOR_MAX_BPS = 400  # Safe harbor enhanced cap (4% of comp)

# ─── Vesting (PRD §2.9) ─────────────────────────────────────────────────────
CLIFF_YEARS = 3
GRADED_VESTING_BPS_AT_YOS = {
    0: 0,
    1: 2000,
    2: 4000,
    3: 6000,
    4: 8000,
    5: 10000,
    6: 10000,
}

# ─── Hardship (PRD §3.5) ────────────────────────────────────────────────────
HARDSHIP_HARD_CAP_CENTS = 5_000_000
HARDSHIP_AGE_PENALTY_THRESHOLD_YEARS = 59  # under-59 -> 10% penalty
HARDSHIP_VESTED_FRACTION_BPS = 5000        # half of vested savings

# ─── Loan (PRD §3.4) ────────────────────────────────────────────────────────
LOAN_HARD_CAP_CENTS = 5_000_000
LOAN_VESTED_FRACTION_BPS = 5000
LOAN_MAX_GENERAL_TERM_MONTHS = 60
LOAN_MAX_PRIMARY_RESIDENCE_TERM_MONTHS = 180

# ─── RMD (PRD §3.6) ─────────────────────────────────────────────────────────
RMD_AGE_TRIGGER_YEARS = 73
RMD_JOINT_LIFE_GAP_YEARS = 10  # spouse must be > 10 yr younger

# Representative IRS table entries (PRD §3.6).
UNIFORM_LIFETIME_TABLE = {
    73: 26.5,
    74: 25.5,
    75: 24.6,
    80: 20.2,
    85: 16.0,
}
JOINT_LIFE_TABLE = {
    (73, 60): 27.4,
    (73, 55): 30.7,
    (80, 65): 22.6,
}

# ─── Pagination (PRD §2.3) ──────────────────────────────────────────────────
DEFAULT_LIMIT = 10
MAX_LIMIT = 100
MIN_LIMIT = 1
DEFAULT_OFFSET = 0
