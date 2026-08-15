"""Domain thresholds and shared fixtures data from the PRD.

Numeric constants come from PRD 3.6 (liability cap), PRD 3.8 (claim band),
PRD 2.4 (clock default), and PRD 3.1 (rush capacity default).
"""

# --- Logical clock (PRD 2.4) ---
CLOCK_START = "2026-08-01T00:00:00Z"

# --- Liability cap algorithm (PRD 3.6) ---
LIABILITY_MULTIPLIER = 10
MIN_CAP_CENTS = 25000
MAX_CAP_CENTS = 100000
EXTENDED_COVERAGE_RATE = 0.10

# --- Discrepancy claim band (PRD 3.8) ---
MAX_CLAIM_CENTS = 25000000

# --- Jurisdiction defaults (PRD 3.1) ---
DEFAULT_RUSH_DAILY_CAPACITY = 5

# --- Reference-book defaults used across tests ---
DEFAULT_STATUTE = {
    "effective_from": "2026-01-01",
    "effective_to": None,
    "estoppel_response_days": 10,
    "estoppel_fee_cap_cents": 12000,
    "estoppel_validity_days": 30,
}

DEFAULT_ASSOCIATION = {
    "name": "Sunset HOA",
    "management_company": "Sunset Mgmt",
    "estoppel_fee_cents": 10000,
    "estoppel_validity_days": 30,
}

# Three-department reference configuration (fee / rush surcharge).
CONFIG_A_DEPARTMENTS = (
    {
        "dept_type": "UTILITY",
        "name": "Water & Sewer",
        "research_fee_cents": 5000,
        "rush_surcharge_cents": 2500,
        "supports_rush": True,
    },
    {
        "dept_type": "CODE_ENFORCEMENT",
        "name": "Code Compliance",
        "research_fee_cents": 7000,
        "rush_surcharge_cents": 3000,
        "supports_rush": True,
    },
    {
        "dept_type": "PERMIT",
        "name": "Building Permits",
        "research_fee_cents": 4000,
        "rush_surcharge_cents": 2000,
        "supports_rush": True,
    },
)

UTILITY_ONLY_DEPARTMENTS = (CONFIG_A_DEPARTMENTS[0],)

# Cheap departments whose task fees total exactly 1000 (400 + 350 + 250).
CHEAP_DEPARTMENTS = (
    {
        "dept_type": "UTILITY",
        "name": "Utilities",
        "research_fee_cents": 400,
        "rush_surcharge_cents": 100,
        "supports_rush": True,
    },
    {
        "dept_type": "CODE_ENFORCEMENT",
        "name": "Code",
        "research_fee_cents": 350,
        "rush_surcharge_cents": 100,
        "supports_rush": True,
    },
    {
        "dept_type": "PERMIT",
        "name": "Permits",
        "research_fee_cents": 250,
        "rush_surcharge_cents": 100,
        "supports_rush": True,
    },
)

# --- Canonical findings sets ---
FINDINGS_UTILITY_300K = [{"finding_kind": "UNPAID_UTILITY", "amount_cents": 300000}]
FINDINGS_UTILITY_310K = [{"finding_kind": "UNPAID_UTILITY", "amount_cents": 310000}]
FINDINGS_CODE_ACCRUAL_11500 = [
    {
        "finding_kind": "CODE_VIOLATION",
        "amount_cents": 10000,
        "daily_accrual_cents": 150,
        "days_outstanding": 10,
    }
]
FINDINGS_EMPTY = []

# Default estoppel economics.
ESTOPPEL_FEE_QUOTED = 10000
ESTOPPEL_PAYOFF = 45000
