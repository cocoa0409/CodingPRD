"""Calculation rules from §1.3 — all monetary math uses Decimal + ROUND_HALF_UP."""

from decimal import Decimal, ROUND_HALF_UP


# ---- Entity multipliers (LARGE/SMALL/MICRO) --------------------------------
ENTITY_MULTIPLIER = {
    "LARGE": Decimal("1.00"),
    "SMALL": Decimal("0.50"),
    "MICRO": Decimal("0.20"),
}


# ---- Filing fees (cents) ---------------------------------------------------
FILING_BASE_CENTS = {
    "UTILITY": 32000,
    "DESIGN": 22000,
    "PROVISIONAL": 30000,
    "PCT_NATIONAL": 32000,
}


# ---- Excess-claims fees (per claim) ----------------------------------------
EXCESS_CLAIM_BASE_CENTS = 10000   # > 20 total claims
EXCESS_INDEP_BASE_CENTS = 48000   # > 3 independent claims


# ---- Issue fees (cents) ----------------------------------------------------
ISSUE_BASE_CENTS = {
    "UTILITY": 120000,
    "DESIGN": 74000,
    "PCT_NATIONAL": 120000,
    # PROVISIONAL not eligible
}


# ---- Extension fees (cents, indexed by months 1/2/3) -----------------------
EXTENSION_BASE_CENTS = {
    0: 0,
    1: 22000,
    2: 64000,
    3: 148000,
}


# ---- Maintenance fees (base per window) ------------------------------------
MAINTENANCE_BASE_CENTS = {
    1: 200000,
    2: 376000,
    3: 772000,
}
LATE_SURCHARGE_BASE_CENTS = 16000


# ---- Micro-entity eligibility constants ------------------------------------
MICRO_INCOME_CEILING_CENTS = 24600000
MICRO_PRIOR_APPS_CEILING = 4


# ---- Rounding helper -------------------------------------------------------

def _round_half_up_int(value) -> int:
    """Round a Decimal/number to nearest integer using ROUND_HALF_UP."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _multiplier(entity_size: str) -> Decimal:
    if entity_size not in ENTITY_MULTIPLIER:
        raise ValueError(f"Unknown entity_size: {entity_size}")
    return ENTITY_MULTIPLIER[entity_size]


# ---- Calculations ----------------------------------------------------------

def filing_fee(application_type: str, entity_size: str) -> int:
    """§1.3 FILING_FEE."""
    base = FILING_BASE_CENTS.get(application_type)
    if base is None:
        raise ValueError(f"No filing fee for application_type={application_type}")
    return _round_half_up_int(Decimal(base) * _multiplier(entity_size))


def excess_claims_fee(claim_count: int, independent_claim_count: int, entity_size: str) -> int:
    """§1.3 EXCESS_CLAIMS_FEE — discount-then-sum-then-round (once).

    Each scaled term is held as Decimal; only the SUM is rounded.
    """
    multiplier = _multiplier(entity_size)
    excess_total = max(0, int(claim_count) - 20)
    excess_indep = max(0, int(independent_claim_count) - 3)
    term_total = Decimal(excess_total) * Decimal(EXCESS_CLAIM_BASE_CENTS) * multiplier
    term_indep = Decimal(excess_indep) * Decimal(EXCESS_INDEP_BASE_CENTS) * multiplier
    return _round_half_up_int(term_total + term_indep)


def issue_fee(application_type: str, entity_size: str) -> int:
    """§1.3 ISSUE_FEE."""
    base = ISSUE_BASE_CENTS.get(application_type)
    if base is None:
        raise ValueError(f"No issue fee for application_type={application_type}")
    return _round_half_up_int(Decimal(base) * _multiplier(entity_size))


def extension_fee(extension_months_requested: int, entity_size: str) -> int:
    """§1.3 EXTENSION_FEE."""
    months = int(extension_months_requested)
    if months == 0:
        return 0
    base = EXTENSION_BASE_CENTS.get(months)
    if base is None:
        raise ValueError(f"No extension fee for months={months}")
    return _round_half_up_int(Decimal(base) * _multiplier(entity_size))


def maintenance_base_fee(window_number: int, entity_size: str) -> int:
    """§1.3 MAINTENANCE_FEE — base (no surcharge)."""
    base = MAINTENANCE_BASE_CENTS.get(int(window_number))
    if base is None:
        raise ValueError(f"No maintenance base for window {window_number}")
    return _round_half_up_int(Decimal(base) * _multiplier(entity_size))


def maintenance_surcharge(entity_size: str) -> int:
    """§1.3 MAINTENANCE_FEE late surcharge, rounded independently of base."""
    return _round_half_up_int(Decimal(LATE_SURCHARGE_BASE_CENTS) * _multiplier(entity_size))


def micro_eligible(applicant: dict) -> bool:
    """§1.3 MICRO_ELIGIBILITY predicate."""
    income = applicant.get("gross_income_prior_year_cents")
    prior = applicant.get("prior_applications_filed", 0) or 0
    year = applicant.get("micro_qualifying_year")
    if income is None:
        return False
    if int(income) > MICRO_INCOME_CEILING_CENTS:
        return False
    if int(prior) > MICRO_PRIOR_APPS_CEILING:
        return False
    if year is None:
        return False
    return True
