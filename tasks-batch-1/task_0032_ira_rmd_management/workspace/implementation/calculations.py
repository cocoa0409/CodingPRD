"""All calculation rules from PRD §3 / SCAFFOLD §1.3.

Every formula uses integer-cent arithmetic with sum-then-divide ordering and
floor at the final step. No float anywhere.
"""

from datetime import datetime, timedelta, timezone


# ----- Constants ---------------------------------------------------------------

BASE_LIMIT_CENTS = {
    2024: 700_000,
    2025: 700_000,
    2026: 750_000,
}

CATCH_UP_CENTS = {
    2024: 100_000,
    2025: 100_000,
    2026: 110_000,
}

# Roth phase-out brackets per (tax_year, filing_status) -> (floor_cents, ceiling_cents).
ROTH_PHASEOUT = {
    2024: {
        "SINGLE": (14_600_000, 16_100_000),
        "MARRIED_JOINT": (23_000_000, 24_000_000),
        "MARRIED_SEPARATE": (0, 1_000_000),
        "HEAD_OF_HOUSEHOLD": (14_600_000, 16_100_000),
    },
    2025: {
        "SINGLE": (15_000_000, 16_500_000),
        "MARRIED_JOINT": (23_600_000, 24_600_000),
        "MARRIED_SEPARATE": (0, 1_000_000),
        "HEAD_OF_HOUSEHOLD": (15_000_000, 16_500_000),
    },
    2026: {
        "SINGLE": (15_400_000, 16_900_000),
        "MARRIED_JOINT": (24_200_000, 25_200_000),
        "MARRIED_SEPARATE": (0, 1_000_000),
        "HEAD_OF_HOUSEHOLD": (15_400_000, 16_900_000),
    },
}

# Uniform Lifetime Divisors stored in basis-point form (integer * 100 of the
# decimal divisor — e.g., 2660 represents 26.60).
UNIFORM_LIFETIME_DIVISOR = {
    73: 2660,
    74: 2580,
    75: 2490,
    76: 2410,
    77: 2320,
    78: 2240,
    79: 2150,
    80: 2070,
    81: 1980,
    82: 1900,
    83: 1820,
    84: 1730,
    85: 1650,
}


# ----- Helpers -----------------------------------------------------------------

def _ensure_tz(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def year_diff_from_eoy(tax_year: int, date_of_birth) -> int:
    """Integer year difference between Dec 31 of tax_year and date_of_birth.

    PRD §3.3: 'the integer year difference between December 31 of the tax_year
    and date_of_birth.'
    """
    eoy = datetime(tax_year, 12, 31, tzinfo=timezone.utc)
    dob = _ensure_tz(date_of_birth)
    years = eoy.year - dob.year
    # Adjust if the day-month on dob has not yet been reached by Dec 31 — but
    # Dec 31 is the end of the year, so the owner's birthday has always passed
    # in the same calendar year unless dob is later than Dec 31 of the same year
    # (impossible). So the integer year difference is simply eoy.year - dob.year.
    return years


def age_at_instant(clock_dt, date_of_birth) -> float:
    """Owner's age (in years, with .5 granularity) at an explicit clock instant.

    Used by the 1099-R box-7 code mapping for the 59.5 boundary.
    """
    clock_dt = _ensure_tz(clock_dt)
    dob = _ensure_tz(date_of_birth)
    delta_days = (clock_dt - dob).days
    # 365.25 average days per year handles leap years uniformly enough for the
    # 59.5 boundary check.
    return delta_days / 365.25


# ----- Calculation rules ------------------------------------------------------

def contribution_limit(owner: dict, account_type: str, tax_year: int) -> int:
    """PRD §3.3 cap math. Returns integer cents."""
    age_at_year_end = year_diff_from_eoy(tax_year, owner["date_of_birth"])
    base = BASE_LIMIT_CENTS.get(tax_year, BASE_LIMIT_CENTS[2026])
    catch_up = CATCH_UP_CENTS.get(tax_year, CATCH_UP_CENTS[2026]) if age_at_year_end >= 50 else 0
    if account_type == "TRADITIONAL":
        return base + catch_up
    # ROTH: feed combined headroom into phase-out
    return roth_eligibility(
        owner["modified_agi_cents"],
        owner["filing_status"],
        tax_year,
        base + catch_up,
    )


def roth_eligibility(modified_agi_cents: int, filing_status: str, tax_year: int, headroom_cents: int) -> int:
    """PRD §3.3 Roth phase-out — sum-then-floor."""
    table = ROTH_PHASEOUT.get(tax_year, ROTH_PHASEOUT[2026])
    floor, ceiling = table[filing_status]
    if modified_agi_cents <= floor:
        return headroom_cents
    if modified_agi_cents >= ceiling:
        return 0
    phaseout_width = ceiling - floor
    reduction = headroom_cents * (modified_agi_cents - floor) // phaseout_width
    allowed = headroom_cents - reduction
    # Floor to nearest 1000 cents ($10) — applied once, at the very end.
    return (allowed // 1000) * 1000


def backdoor_roth_pro_rata(gross: int, pretax: int, aftertax: int) -> tuple:
    """PRD §3.5 Backdoor Roth split. Returns (taxable_cents, nontaxable_cents).

    Sum-then-divide; floor-divide at the final ratio step; any cent of remainder
    lands on the taxable side.
    """
    total_basis = pretax + aftertax
    if total_basis == 0:
        return (gross, 0)
    nontaxable = gross * aftertax // total_basis
    taxable = gross - nontaxable
    return (taxable, nontaxable)


def distribution_basis_split(account: dict, amount_cents: int) -> tuple:
    """PRD §3.4 Traditional-distribution basis split.

    Returns (pre_drop, aft_drop). pre_drop absorbs the remainder.
    """
    pre = account["pretax_basis_cents"]
    aft = account["aftertax_basis_cents"]
    total = pre + aft
    if total == 0:
        return (0, 0)
    aft_drop = amount_cents * aft // total
    pre_drop = amount_cents - aft_drop
    return (pre_drop, aft_drop)


def compute_taxable_distribution(account: dict, gross: int) -> int:
    """PRD §3.4 1099-R box 2a for a distribution.

    On ROTH it is 0; on TRADITIONAL with zero basis sum it equals gross;
    otherwise gross minus the nontaxable portion (floor-divide at the final step).
    """
    if account["account_type"] == "ROTH":
        return 0
    total_basis = account["pretax_basis_cents"] + account["aftertax_basis_cents"]
    if total_basis == 0:
        return gross
    nontaxable = gross * account["aftertax_basis_cents"] // total_basis
    return gross - nontaxable


def map_distribution_code(distribution_reason: str, owner_age_years: float) -> str:
    """PRD §3.4 box-7 distribution_code mapping. Order matters."""
    if distribution_reason == "ROLLOVER":
        return "G"
    if distribution_reason == "INHERITED":
        return "4"
    if distribution_reason == "RETURN_OF_CONTRIBUTION":
        return "8"
    if owner_age_years < 59.5 and distribution_reason == "EARLY":
        return "1"
    if distribution_reason == "RMD":
        return "7"
    if owner_age_years >= 59.5:
        return "7"
    return "2"


def rmd_required_amount(owner: dict, tax_year: int, traditional_accounts: list, clock_utc) -> int:
    """PRD §3.7 — sum balances across ACTIVE/FROZEN Traditional accounts of a
    living owner aged >= 73 and divide by the Uniform Lifetime divisor for the
    owner's year-end age.
    """
    age = year_diff_from_eoy(tax_year, owner["date_of_birth"])
    if age < 73:
        return 0
    # Sort by opened_at ASC, tie-break by created_at ASC. Never by id.
    sorted_accounts = sorted(
        traditional_accounts,
        key=lambda a: (a["opened_at"], a["created_at"]),
    )
    total_balance = sum(a["cash_balance_cents"] for a in sorted_accounts)
    if age not in UNIFORM_LIFETIME_DIVISOR:
        # Owners older than the table top -> use the maximum-age divisor as a
        # safe extension (not explicitly forbidden by PRD; falls back to age 85
        # entry which has the smallest divisor / largest RMD).
        max_age = max(UNIFORM_LIFETIME_DIVISOR.keys())
        divisor_x100 = UNIFORM_LIFETIME_DIVISOR[max_age]
    else:
        divisor_x100 = UNIFORM_LIFETIME_DIVISOR[age]
    required_cents = (total_balance * 100) // divisor_x100
    return required_cents


def rmd_deadline(owner: dict, tax_year: int) -> tuple:
    """PRD §3.7 deadline computation. Returns (deadline_dt, is_first_rmd_year)."""
    age_at_year_end = year_diff_from_eoy(tax_year, owner["date_of_birth"])
    is_first = (age_at_year_end == 73)
    if is_first:
        # April 1 of tax_year + 1
        deadline = datetime(tax_year + 1, 4, 1, 0, 0, 0, 0, tzinfo=timezone.utc)
    else:
        # December 31 of tax_year
        deadline = datetime(tax_year, 12, 31, 23, 59, 59, 999_000, tzinfo=timezone.utc)
    return (deadline, is_first)


def secure_inherited_required_amount(inherited_balance_cents: int, secure_deadline_at, clock_utc) -> int:
    """PRD §3.7 SECURE Act ten-year pace. Even allocation.

    years_remaining = ceil((secure_deadline_at - clock_utc) / 365 days).
    On the final year, required_amount_cents = entire remaining balance.
    """
    if secure_deadline_at is None:
        return 0
    secure_deadline_at = _ensure_tz(secure_deadline_at)
    clock_utc = _ensure_tz(clock_utc)
    days_remaining = (secure_deadline_at - clock_utc).total_seconds() / 86400.0
    if days_remaining <= 0:
        return inherited_balance_cents
    # ceil(days / 365)
    years_remaining = int(days_remaining // 365) + (1 if (days_remaining % 365) > 0 else 0)
    if years_remaining <= 1:
        return inherited_balance_cents
    return inherited_balance_cents // years_remaining
