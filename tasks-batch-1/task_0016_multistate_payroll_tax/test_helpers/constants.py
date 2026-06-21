"""Domain thresholds and numeric constants from the PRD calculations (§3.4, §3.5)."""

# ─── Federal income tax ────────────────────────────────────────────────────
PAY_PERIODS_PER_YEAR = 26

# Standard deduction in cents (per filing status) — PRD §3.4
STANDARD_DEDUCTION_CENTS = {
    "SINGLE": 1_460_000,
    "MARRIED_JOINT": 2_920_000,
    "HEAD_OF_HOUSEHOLD": 2_190_000,
}

# ─── FICA Social Security ──────────────────────────────────────────────────
SS_WAGE_BASE_CENTS = 16_860_000        # $168,600.00 (PRD §3.4)
SS_RATE_BASIS_POINTS = 620             # 6.20%

# ─── Medicare ──────────────────────────────────────────────────────────────
MEDICARE_RATE_BASIS_POINTS = 145       # 1.45%
ADDL_MEDICARE_THRESHOLD_CENTS = 20_000_000   # $200,000.00 YTD
ADDL_MEDICARE_RATE_BASIS_POINTS = 90         # 0.90%

# ─── Garnishment / CCPA ────────────────────────────────────────────────────
CCPA_MAX_BASIS_POINTS_CREDITOR_ONLY = 2500       # 25.00%
CCPA_MAX_BASIS_POINTS_WITH_CHILD_SUPPORT = 5000  # 50.00%

# ─── Test-default literal seeds (used by factories and fixtures) ──────────
TEST_DEFAULTS = {
    "PAY_PERIOD_START_2025_11": "2025-11-01T00:00:00.000Z",
    "PAY_PERIOD_END_2025_11": "2025-11-15T23:59:59.999Z",
    "PAY_DATE_2025_11_15": "2025-11-15T00:00:00.000Z",
    "DEFAULT_HOURLY_RATE_CENTS": 5000,      # $50.00/hr
    "DEFAULT_REGULAR_HOURS_E2": 4000,       # 40.00 hrs
}

# Pre-computed federal SINGLE 2025 bracket schedule (PRD §3.2 references)
# PRD §3.2: brackets_json items use `upper_cents_or_null` (null = open-ended top)
FED_BRACKETS_2025_SINGLE = [
    {"lower_cents": 0, "upper_cents_or_null": 1_175_000, "rate_basis_points": 1000},
    {"lower_cents": 1_175_000, "upper_cents_or_null": 4_775_000, "rate_basis_points": 1200},
    {"lower_cents": 4_775_000, "upper_cents_or_null": None, "rate_basis_points": 2200},
]
FED_SUPPLEMENTAL_BP_2025 = 2200

CA_BRACKETS_2025_SINGLE = [
    {"lower_cents": 0, "upper_cents_or_null": 1_000_000, "rate_basis_points": 100},
    {"lower_cents": 1_000_000, "upper_cents_or_null": None, "rate_basis_points": 200},
]
CA_SUPPLEMENTAL_BP_2025 = 1100

NY_BRACKETS_2025_SINGLE = [
    {"lower_cents": 0, "upper_cents_or_null": 800_000, "rate_basis_points": 400},
    {"lower_cents": 800_000, "upper_cents_or_null": None, "rate_basis_points": 600},
]
NY_SUPPLEMENTAL_BP_2025 = 1100

NYC_BRACKETS_2025_SINGLE = [
    {"lower_cents": 0, "upper_cents_or_null": None, "rate_basis_points": 300},
]
NYC_SUPPLEMENTAL_BP_2025 = 300
