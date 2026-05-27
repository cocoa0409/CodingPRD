"""Domain thresholds and fee tables — numeric constants from PRD §3.

These tables encode the exact fee bases and multipliers stated in PRD §3.3,
§3.5, §3.7, §3.8, and the micro-eligibility ceilings stated in PRD §3.1.
Tests compute expected amounts via these constants rather than hard-coding
numbers inline, so a one-off arithmetic typo at the test layer is unlikely.
"""

# Entity-size multipliers (PRD §2.6)
ENTITY_MULTIPLIER = {
    "LARGE": 1.00,
    "SMALL": 0.50,
    "MICRO": 0.20,
}

# Filing fee bases in cents (PRD §3.3)
FILING_BASE_CENTS = {
    "UTILITY": 32000,
    "DESIGN": 22000,
    "PROVISIONAL": 30000,
    "PCT_NATIONAL": 32000,
}

# Excess-claim bases in cents (PRD §3.3)
EXCESS_CLAIM_BASE_CENTS = 10000        # per claim over 20
EXCESS_INDEP_BASE_CENTS = 48000        # per indep claim over 3

# Issue fee bases in cents (PRD §3.7)
ISSUE_BASE_CENTS = {
    "UTILITY": 120000,
    "DESIGN": 74000,
    "PCT_NATIONAL": 120000,
}

# Extension fee bases by months (PRD §3.5)
EXTENSION_BASE_CENTS = {
    1: 22000,
    2: 64000,
    3: 148000,
}

# Maintenance fee bases by window (PRD §3.7, §3.8)
MAINTENANCE_BASE_CENTS = {
    1: 200000,
    2: 376000,
    3: 772000,
}

# Late surcharge (PRD §3.8)
LATE_SURCHARGE_BASE_CENTS = 16000

# Micro-entity eligibility thresholds (PRD §3.1)
MICRO_INCOME_CEILING_CENTS = 24600000   # $246,000
MICRO_PRIOR_APPS_CEILING = 4

# Term lengths (PRD §3.7)
UTILITY_TERM_YEARS = 20
DESIGN_TERM_YEARS = 15
PROVISIONAL_TERM_MONTHS = 12


def _round_half_up(value: float) -> int:
    """Round-half-up to integer (PRD §2.6). Python's round() uses banker's
    rounding, so we implement explicit half-up to match the contract."""
    return int(value + 0.5) if value >= 0 else -int(-value + 0.5)


def filing_fee_cents(application_type: str, entity_size: str) -> int:
    """Expected FILING fee per PRD §3.3 = base * multiplier, round_half_up."""
    return _round_half_up(FILING_BASE_CENTS[application_type] *
                          ENTITY_MULTIPLIER[entity_size])


def issue_fee_cents(application_type: str, entity_size: str) -> int:
    """Expected ISSUE fee per PRD §3.7 = base * multiplier, round_half_up."""
    return _round_half_up(ISSUE_BASE_CENTS[application_type] *
                          ENTITY_MULTIPLIER[entity_size])


def extension_fee_cents(months: int, entity_size: str) -> int:
    """Expected EXTENSION fee per PRD §3.5. 0 months => 0 cents."""
    if months == 0:
        return 0
    return _round_half_up(EXTENSION_BASE_CENTS[months] *
                          ENTITY_MULTIPLIER[entity_size])


def maintenance_base_fee_cents(window_number: int, entity_size: str) -> int:
    """Maintenance base fee per PRD §3.7 = base * multiplier, round_half_up."""
    return _round_half_up(MAINTENANCE_BASE_CENTS[window_number] *
                          ENTITY_MULTIPLIER[entity_size])


def maintenance_late_surcharge_cents(entity_size: str) -> int:
    """Maintenance late surcharge per PRD §3.8 = base * multiplier, round_half_up."""
    return _round_half_up(LATE_SURCHARGE_BASE_CENTS *
                          ENTITY_MULTIPLIER[entity_size])


def excess_claims_fee_cents(claim_count: int, independent_claim_count: int,
                            entity_size: str) -> int:
    """Excess-claims fee per PRD §3.3 — scale each term first, sum, then round once."""
    excess_total = max(0, claim_count - 20)
    excess_indep = max(0, independent_claim_count - 3)
    mult = ENTITY_MULTIPLIER[entity_size]
    scaled_total = excess_total * EXCESS_CLAIM_BASE_CENTS * mult
    scaled_indep = excess_indep * EXCESS_INDEP_BASE_CENTS * mult
    return _round_half_up(scaled_total + scaled_indep)
