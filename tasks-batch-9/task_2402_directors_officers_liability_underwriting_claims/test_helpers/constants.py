"""Domain thresholds and pinned constants drawn from the PRD's calculations."""

# The logical clock's fixed startup default, before any operator sets it.
STARTUP_CLOCK_UTC = "2026-08-01T00:00:00Z"

# ─── Risk scoring ────────────────────────────────────────────────────────────

SECTOR_MULTIPLIERS = {
    "BIOTECH": 1.30,
    "FINANCIAL": 1.25,
    "TECH": 1.15,
    "ENERGY": 1.10,
    "INDUSTRIAL": 1.00,
    "CONSUMER": 0.95,
}

RISK_BAND_THRESHOLDS = {"LOW": 0.0, "MODERATE": 40.0, "ELEVATED": 70.0, "SEVERE": 100.0}

FINANCIAL_SUBSCORE_CAP = 60
GOVERNANCE_SUBSCORE_CAP = 50
LITIGATION_SUBSCORE_CAP = 70
OPEN_LITIGATION_SURCHARGE = 10
MATERIAL_WEAKNESS_CAP = 3
DEBT_TO_EQUITY_THRESHOLD = 2.0
INDEPENDENT_DIRECTOR_RATIO_THRESHOLD = 0.50

CASE_TYPE_WEIGHTS = {
    "SECURITIES_CLASS_ACTION": 20,
    "REGULATORY_ENFORCEMENT": 15,
    "DERIVATIVE": 12,
    "FIDUCIARY": 8,
    "MERGER_OBJECTION": 5,
    "EMPLOYMENT_PRACTICES": 3,
}

RECENCY_FULL_WEIGHT_DAYS = 1095
RECENCY_HALF_WEIGHT_DAYS = 2190

DISCLOSURE_STALE_DAYS = 540
SUBMISSION_EXPIRY_DAYS = 90
DEFAULT_ERP_DAYS = 90

# ─── Premium build-up ────────────────────────────────────────────────────────

# Increased-limit bands: (band width in dollars, factor). The final band is open-ended.
ILF_BANDS = [
    (5_000_000, 1.00),
    (5_000_000, 0.65),
    (10_000_000, 0.45),
    (None, 0.30),
]

BAND_RATES = {"LOW": 9_000, "MODERATE": 14_000, "ELEVATED": 22_000, "SEVERE": 34_000}

SIDE_C_LOADS = {"LISTED": 0.20, "PRIVATE": 0.08, "NONE": 0.00}

RETENTION_CREDIT_BLOCK_USD = 250_000
RETENTION_CREDIT_PER_BLOCK = 0.05
RETENTION_CREDIT_CAP = 0.35

NET_PREMIUM_FLOOR_USD = 25_000.00
NET_PREMIUM_CEILING_USD = 2_500_000.00

COMMISSION_RATE = 0.125
PREMIUM_TAX_RATE = 0.035

PREMIUM_DUE_DAYS = 30
POLICY_NUMBER_PREFIX = "DO-"

# ─── Run-off tail ────────────────────────────────────────────────────────────

TAIL_FACTORS = {1: 0.75, 2: 1.10, 3: 1.45, 6: 2.25}
PERMITTED_TAIL_YEARS = [1, 2, 3, 6]
SEVERITY_LOAD = 0.20
DAYS_PER_YEAR = 365
RETURN_PREMIUM_DAY_CAP = 365

# ─── Tower ───────────────────────────────────────────────────────────────────

DIC_SHARE_CAP = 0.40
FULL_PARTICIPATION = 1.00

# ─── Negotiation ─────────────────────────────────────────────────────────────

MAX_NEGOTIATION_ROUNDS = 4
PREMIUM_IMPACT_MIN = -0.25
PREMIUM_IMPACT_MAX = 0.25

# ─── Capacity posture ────────────────────────────────────────────────────────

CAPACITY_RESTRICTED_UTILISATION = 0.80
CAPACITY_EXHAUSTED_UTILISATION = 1.00

# ─── Hammer clause ───────────────────────────────────────────────────────────

HAMMER_PCT_ON_CONSENT = 1.00
HAMMER_PCT_ON_REFUSE = 0.70

# ─── Eligible coverage parts by claim type ───────────────────────────────────

ELIGIBLE_PARTS_BY_CLAIM_TYPE = {
    "SECURITIES_CLASS_ACTION": ["SIDE_A", "SIDE_B", "SIDE_C"],
    "DERIVATIVE": ["SIDE_A", "SIDE_B"],
    "REGULATORY_ENFORCEMENT": ["SIDE_A", "SIDE_B"],
    "EMPLOYMENT_PRACTICES": ["SIDE_A", "SIDE_B"],
    "FIDUCIARY": ["SIDE_A", "SIDE_B"],
    "INSURED_VS_INSURED": ["SIDE_A"],
}

# ─── Pagination ──────────────────────────────────────────────────────────────

DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100

# ─── Ops-run counters reported by the epoch advance ──────────────────────────

OPS_RUN_COUNTERS = [
    "activated_policy_count",
    "expired_policy_count",
    "delinquent_policy_count",
    "lapsed_quote_count",
    "expired_submission_count",
    "reverted_submission_count",
    "lapsed_circumstance_report_count",
    "expired_runoff_count",
]

__all__ = [
    "STARTUP_CLOCK_UTC", "SECTOR_MULTIPLIERS", "RISK_BAND_THRESHOLDS",
    "FINANCIAL_SUBSCORE_CAP", "GOVERNANCE_SUBSCORE_CAP", "LITIGATION_SUBSCORE_CAP",
    "OPEN_LITIGATION_SURCHARGE", "MATERIAL_WEAKNESS_CAP", "DEBT_TO_EQUITY_THRESHOLD",
    "INDEPENDENT_DIRECTOR_RATIO_THRESHOLD", "CASE_TYPE_WEIGHTS",
    "RECENCY_FULL_WEIGHT_DAYS", "RECENCY_HALF_WEIGHT_DAYS", "DISCLOSURE_STALE_DAYS",
    "SUBMISSION_EXPIRY_DAYS", "DEFAULT_ERP_DAYS", "ILF_BANDS", "BAND_RATES",
    "SIDE_C_LOADS", "RETENTION_CREDIT_BLOCK_USD", "RETENTION_CREDIT_PER_BLOCK",
    "RETENTION_CREDIT_CAP", "NET_PREMIUM_FLOOR_USD", "NET_PREMIUM_CEILING_USD",
    "COMMISSION_RATE", "PREMIUM_TAX_RATE", "PREMIUM_DUE_DAYS", "POLICY_NUMBER_PREFIX",
    "TAIL_FACTORS", "PERMITTED_TAIL_YEARS", "SEVERITY_LOAD", "DAYS_PER_YEAR",
    "RETURN_PREMIUM_DAY_CAP", "DIC_SHARE_CAP", "FULL_PARTICIPATION",
    "MAX_NEGOTIATION_ROUNDS", "PREMIUM_IMPACT_MIN", "PREMIUM_IMPACT_MAX",
    "CAPACITY_RESTRICTED_UTILISATION", "CAPACITY_EXHAUSTED_UTILISATION",
    "HAMMER_PCT_ON_CONSENT", "HAMMER_PCT_ON_REFUSE", "ELIGIBLE_PARTS_BY_CLAIM_TYPE",
    "DEFAULT_PAGE_LIMIT", "MIN_PAGE_LIMIT", "MAX_PAGE_LIMIT", "OPS_RUN_COUNTERS",
]
