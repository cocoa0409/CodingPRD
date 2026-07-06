"""Domain thresholds — numeric constants from the PRD's calculations."""

# Supervision-level boundaries (PRD 2.9): strict < at each boundary.
INDEPENDENT_MAX_CENTS = 500_000   # gross < this -> INDEPENDENT
FULL_MIN_CENTS = 5_000_000        # gross >= this -> FULL; in between -> LIMITED

# Tiered bond sizing (PRD 2.8).
TIER1_CENTS = 1_000_000           # first tier covered at 100%
TIER2_CENTS = 4_000_000           # next tier covered at 50% (integer floor div)
# remainder above 5,000,000 covered at 25% (integer floor div)

# Creditor claim period (PRD 3.5).
CLAIM_PERIOD_DAYS = 120

# Judge calendar recess buffer (PRD 3.11).
JUDGE_RECESS_MINUTES = 30

# Waterfall priority ranks (PRD 3.8).
CLAIM_RANK = {
    "SECURED": 0,
    "FUNERAL": 1,
    "ADMIN": 2,
    "TAX": 3,
    "GENERAL": 4,
}

# Logical-clock startup default (PRD 2.12).
CLOCK_DEFAULT = "2026-05-01T00:00:00Z"

# Pagination defaults (PRD 2.3).
DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 100


def bond_required_amount(gross_cents: int, supervision_level: str) -> int:
    """Reference computation of a bond's required_amount_cents (PRD 2.8)."""
    if supervision_level == "INDEPENDENT":
        return 0
    t1 = min(gross_cents, TIER1_CENTS)
    t2 = min(max(gross_cents - TIER1_CENTS, 0), TIER2_CENTS)
    t3 = max(gross_cents - TIER1_CENTS - TIER2_CENTS, 0)
    return t1 + (t2 * 50 // 100) + (t3 * 25 // 100)


def supervision_level(gross_cents: int) -> str:
    """Reference computation of supervision_level (PRD 2.9)."""
    if gross_cents < INDEPENDENT_MAX_CENTS:
        return "INDEPENDENT"
    if gross_cents < FULL_MIN_CENTS:
        return "LIMITED"
    return "FULL"
