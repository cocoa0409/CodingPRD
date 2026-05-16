"""Calculation rules (PRD §3.2 / §3.7, SCAFFOLD calculations table)."""

from decimal import Decimal

from services.money import to_decimal, round2, round2_float


# Source-type sets
MAGI_COUNTABLE_BASE = {
    "WAGES", "SELF_EMPLOYMENT", "INTEREST", "DIVIDENDS",
    "CAPITAL_GAINS", "UNEMPLOYMENT", "OTHER",
}
MAGI_EXCLUDED = {"CHILD_SUPPORT", "TANF", "SSI"}
# SOCIAL_SECURITY: countable only when applicant.dependent_status == PRIMARY

FREQ_MULTIPLIER = {
    "ANNUAL": 1,
    "MONTHLY": 12,
    "BIWEEKLY": 26,
    "WEEKLY": 52,
}

FEDERAL_EXEMPT_ASSET_TYPES = {"PRIMARY_RESIDENCE", "RETIREMENT", "LIFE_INSURANCE"}


def annualize_income_record(record: dict) -> Decimal:
    """Annualize one IncomeRecord according to frequency."""
    mult = FREQ_MULTIPLIER.get(record["frequency"], 1)
    return to_decimal(record["gross_amount"]) * to_decimal(mult)


def is_countable_for_magi(source_type: str, dependent_status: str) -> bool:
    if source_type in MAGI_COUNTABLE_BASE:
        return True
    if source_type == "SOCIAL_SECURITY" and dependent_status == "PRIMARY":
        return True
    return False


def compute_applicant_magi(applicant: dict, income_records: list) -> Decimal:
    """Sum annualized countable income for one applicant, rounded HALF_UP to 2dp."""
    total = Decimal("0")
    dep = applicant["dependent_status"]
    for rec in income_records:
        if not is_countable_for_magi(rec["source_type"], dep):
            continue
        total += annualize_income_record(rec)
    return round2(total)


def asset_exempt_under_federal(asset_type: str) -> bool:
    return asset_type in FEDERAL_EXEMPT_ASSET_TYPES


def asset_exempt_under_state(asset_type: str, state_exempt_list) -> bool:
    if not state_exempt_list:
        return False
    return asset_type in state_exempt_list


def asset_countable_value(asset: dict, rule_variant: str, state_exempt_list) -> Decimal:
    """Per-record countable value under the given rule variant.

    FEDERAL: exempt iff federal_exempt
    STATE:   exempt iff federal_exempt OR state_exempt
    """
    fed = asset_exempt_under_federal(asset["asset_type"])
    st = asset_exempt_under_state(asset["asset_type"], state_exempt_list)
    if rule_variant == "FEDERAL":
        exempt = fed
    else:  # STATE
        exempt = fed or st
    if exempt:
        return round2(0)
    return round2(asset["market_value"])


def applicant_countable_assets(asset_records, rule_variant, state_exempt_list) -> Decimal:
    total = Decimal("0")
    for a in asset_records:
        total += asset_countable_value(a, rule_variant, state_exempt_list)
    return round2(total)


def effective_household_size(applicants: list) -> int:
    """Count of non-EXCLUDED applicants + count of is_pregnant=True applicants.

    Pregnant applicants count twice in the denominator (once for self, once
    for the pregnancy). Excluded applicants do not count at all.
    """
    base = sum(1 for a in applicants if a["dependent_status"] != "EXCLUDED")
    preg = sum(1 for a in applicants if a.get("is_pregnant") is True)
    return base + preg


def household_size_basic(applicants: list) -> int:
    """Count of non-EXCLUDED applicants (used for the Household.household_size field)."""
    return sum(1 for a in applicants if a["dependent_status"] != "EXCLUDED")


def fpl_threshold_amount(effective_size: int, policy: dict) -> Decimal:
    """fpl_base_amount + (effective_size - 1) * fpl_per_member_amount; 0 if size==0."""
    if effective_size <= 0:
        return Decimal("0")
    base = to_decimal(policy["fpl_base_amount"])
    per = to_decimal(policy["fpl_per_member_amount"])
    return round2(base + (Decimal(effective_size) - Decimal(1)) * per)


def compute_total_magi(applicants_magi_sum: Decimal, rule_variant: str, policy: dict) -> Decimal:
    """STATE: max(0, sum - state_disregard); FEDERAL: sum."""
    s = to_decimal(applicants_magi_sum)
    if rule_variant == "STATE":
        disregard = to_decimal(policy.get("state_disregard_amount", 0) or 0)
        adjusted = s - disregard
        if adjusted < 0:
            adjusted = Decimal("0")
        return round2(adjusted)
    return round2(s)


def compute_fpl_percent(total_magi: Decimal, threshold: Decimal):
    """(total_magi / threshold) * 100, rounded HALF_UP to 2 decimals.

    Returns Decimal or None if threshold is zero.
    """
    if threshold == 0:
        return None
    raw = to_decimal(total_magi) / to_decimal(threshold) * Decimal("100")
    return round2(raw)


# --- Premium estimate (PRD §3.7) ----------------------------------------

BASE_PREMIUM_PER_FPL_UNIT = Decimal("30.00")
AGE_FLOOR = 18
AGE_CEIL = 64
AGE_FACTOR_PER_YEAR = Decimal("0.02")


def age_factor_for(age: int) -> Decimal:
    if age < AGE_FLOOR:
        return Decimal("1.0")
    capped = min(age, AGE_CEIL)
    return Decimal("1.0") + (Decimal(capped) - Decimal(AGE_FLOOR)) * AGE_FACTOR_PER_YEAR


def share_factor_for(new_snapshot_fpl_percent) -> Decimal:
    if new_snapshot_fpl_percent is None:
        return Decimal("0")
    raw = (to_decimal(new_snapshot_fpl_percent) - Decimal("100")) / Decimal("100")
    if raw < 0:
        return Decimal("0")
    return raw


def per_member_premium(age: int, new_snapshot_fpl_percent) -> Decimal:
    """Per-member premium rounded to 2 decimals HALF_UP."""
    af = age_factor_for(age)
    sf = share_factor_for(new_snapshot_fpl_percent)
    return round2(af * sf * BASE_PREMIUM_PER_FPL_UNIT)


def premium_estimate_total(applicants_with_age, new_snapshot_fpl_percent) -> float:
    """Sum per-member premiums (already rounded), then round the sum HALF_UP to 2dp.

    Per-member-first ordering (PRD §3.7).
    """
    total = Decimal("0")
    for age in applicants_with_age:
        total += per_member_premium(age, new_snapshot_fpl_percent)
    return round2_float(total)
