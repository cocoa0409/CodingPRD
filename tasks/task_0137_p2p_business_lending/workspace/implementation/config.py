"""Server configuration constants — see SCAFFOLD §1.0 / PRD §2."""
import os

PORT = int(os.environ.get("PORT", 10000))
HOST = "0.0.0.0"

# Auth headers — see PRD §2.1 and SCAFFOLD §1.4 priority 1.
HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"

# Recognised role names — exact spellings per PRD §2.1 / SCAFFOLD §1.7.
ROLES = {
    "PlatformOperator",
    "ComplianceOfficer",
    "Borrower",
    "Investor",
}

# Entity-backed roles: their X-User-ID must resolve to an existing entity
# of the corresponding type on the platform under play. PlatformOperator is
# the only opaque role; X-User-ID is an audit handle.
ENTITY_BACKED_ROLES = {"ComplianceOfficer", "Borrower", "Investor"}

# Pagination — see SCAFFOLD §1.0 / PRD §2.3.
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# Loan term whitelist — see PRD §3.3.
ALLOWED_TERM_MONTHS = (12, 24, 36, 48, 60)

# Pricing constants — see SCAFFOLD §1.3 tiered_interest_rate.
BASE_BPS_TABLE = {"A": 600, "B": 900, "C": 1300, "D": 1800, "E": 2400}
TERM_PREMIUM_BPS_PER_MONTH_OVER_24 = 10

# Funding window & delinquency thresholds — see PRD §3.3 / §3.6.
FUNDING_DEADLINE_DAYS = 14
GRACE_DAYS = 5
INSTALLMENT_INTERVAL_DAYS = 30
DELINQUENT_THRESHOLD = 1
DEFAULT_THRESHOLD = 3
CHARGE_OFF_THRESHOLD = 5

# Investment denomination — see PRD §3.3 / SCAFFOLD validation 17.
MIN_INVESTMENT_CENTS = 2500
INVESTMENT_MULTIPLE_CENTS = 100

# Borrower provisional-grade normalization windows — see PRD §3.2.
PROV_REVENUE_FLOOR_CENTS = 5_000_000      # $50,000
PROV_REVENUE_CEILING_CENTS = 500_000_000  # $5,000,000
PROV_REQUEST_FLOOR_CENTS = 1_000_000      # $10,000
PROV_REQUEST_CEILING_CENTS = 50_000_000   # $500,000

# Borrower final-grade clamp ceilings — see PRD §3.2.
FINAL_CASHFLOW_CEILING_CENTS = 100_000_00     # $100,000
FINAL_RESERVES_CEILING_CENTS = 250_000_00     # $250,000
FINAL_NSF_PENALTY_PER_EVENT = 0.10
FINAL_NSF_PENALTY_CEILING = 0.50

# Grade banding thresholds — inclusive lower bounds. See PRD §3.2.
GRADE_BANDS = (
    (0.80, "A"),
    (0.65, "B"),
    (0.50, "C"),
    (0.35, "D"),
)  # else "E"

# Disclosure subject types — see PRD §3.7.
DISCLOSURE_SUBJECT_TYPES = ("BORROWER", "LISTING", "LOAN", "INVESTMENT")

# Disclosure kinds — see PRD §3.7.
DISCLOSURE_KINDS = (
    "LISTING_OPENED",
    "LISTING_FUNDED",
    "LOAN_ORIGINATED",
    "DELINQUENCY_NOTICE",
    "DEFAULT_NOTICE",
    "CHARGE_OFF_NOTICE",
    "MATERIAL_AMENDMENT",
)
