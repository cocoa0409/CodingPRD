"""Server configuration constants and named values from the scaffold.

All numeric constants and structural names live here so the rest of the codebase
can refer to them by symbolic name. See SCAFFOLD §1.3 / §1.4 / §1.7 and PRD §2.
"""
import os

# ── Runtime ─────────────────────────────────────────────────────────────────
PORT = int(os.environ.get("PORT", 10000))
HOST = "0.0.0.0"

# ── Auth headers — PRD §2.1, SCAFFOLD §1.4 priority 1 ───────────────────────
HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"

# ── Recognised role names — SCAFFOLD §1.7 ───────────────────────────────────
ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_LOAN_OFFICER = "LoanOfficer"
ROLE_FINANCE_MANAGER = "FinanceManager"
ROLE_COLLECTIONS_AGENT = "CollectionsAgent"
ROLE_CUSTOMER = "Customer"

ROLES = {
    ROLE_PLATFORM_ADMIN,
    ROLE_LOAN_OFFICER,
    ROLE_FINANCE_MANAGER,
    ROLE_COLLECTIONS_AGENT,
    ROLE_CUSTOMER,
}

# Entity-backed roles: their X-User-ID must equal a stored Customer.id.
ENTITY_BACKED_ROLES = {ROLE_CUSTOMER}

# ── Pagination defaults — SCAFFOLD §1.0 ─────────────────────────────────────
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ── FICO tier thresholds — SCAFFOLD §1.3 fico_tier_assignment ──────────────
FICO_MIN = 300
FICO_MAX = 850
TIER_1_MIN = 720
TIER_2_MIN = 660
TIER_3_MIN = 600
TIER_4_MIN = 540

TIER_1 = "TIER_1"
TIER_2 = "TIER_2"
TIER_3 = "TIER_3"
TIER_4 = "TIER_4"
TIER_5_DECLINED = "TIER_5_DECLINED"

# ── Loan tier minimum down payments in bps of MSRP ─────────────────────────
LOAN_MIN_DP_BPS = {
    TIER_1: 500,
    TIER_2: 1000,
    TIER_3: 2000,
    TIER_4: 3500,
}

# ── Lease tier minimum down payments in bps of MSRP ─────────────────────────
LEASE_MIN_DP_BPS = {
    TIER_1: 800,
    TIER_2: 1200,
    TIER_3: 1800,
}

# Lease eligibility — TIER_4 and TIER_5_DECLINED are rejected.
LEASE_ELIGIBLE_TIERS = {TIER_1, TIER_2, TIER_3}

# ── FICO tier APR (loans) in basis points ──────────────────────────────────
TIER_APR_BPS = {
    TIER_1: 450,
    TIER_2: 650,
    TIER_3: 950,
    TIER_4: 1450,
}

# ── FICO tier money factor (leases) in micro-units ─────────────────────────
TIER_MONEY_FACTOR_MICRO = {
    TIER_1: 2000,
    TIER_2: 2800,
    TIER_3: 4000,
}

# ── Calculation constants ──────────────────────────────────────────────────
LEASE_TAX_BPS = 800           # 8% local lease tax
UPLIFT_THRESHOLD = 3          # lifetime defaults that trigger APR uplift
APR_UPLIFT_BPS = 300          # 3.00% uplift
DEFAULT_GRACE_DAYS = 15       # LATE → DEFAULTED after this many days past due
PENALTY_PER_MILE_CENTS = 25   # $0.25 per overage mile
DISPOSITION_FEE_CENTS = 39500 # $395.00 on RETURN
PURCHASE_OPTION_FEE_CENTS = 35000  # $350.00
GAP_PREMIUM_BPS = 50          # 0.50% per month
PREPAYMENT_PENALTY_BPS = 200  # 2.00%

# ── Allowed term months ────────────────────────────────────────────────────
LOAN_TERMS = (36, 48, 60, 72)
LEASE_TERMS = (24, 36, 48)

# ── Vehicle residual factor bounds ─────────────────────────────────────────
RESIDUAL_FACTOR_MIN_BPS = 1000
RESIDUAL_FACTOR_MAX_BPS = 8000

# ── Mileage allowance bounds ───────────────────────────────────────────────
MILEAGE_ALLOWANCE_MIN = 10000
MILEAGE_ALLOWANCE_MAX = 75000

# ── Clock advance bounds ───────────────────────────────────────────────────
CLOCK_ADVANCE_MIN = 1
CLOCK_ADVANCE_MAX = 365

# ── VIN length ─────────────────────────────────────────────────────────────
VIN_LENGTH = 17
