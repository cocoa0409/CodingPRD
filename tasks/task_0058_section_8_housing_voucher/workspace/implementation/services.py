"""Calculations, datetime helpers, and common-field management.

All monetary math uses Decimal with ROUND_HALF_UP where the PRD calls for
round-half-up, and integer floor-at-zero where it calls for flooring.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

import db

# ---- Constants (SCAFFOLD §1.3) ------------------------------------------
DEPENDENT_DEDUCTION_CENTS = 48000
ELDERLY_DEDUCTION_CENTS = 40000
REGION_VLI_BASE_CENTS = 4000000
MINIMUM_RENT_CENTS = 5000
MAX_BEDROOM = 6
CURE_WINDOW_DAYS = 14
DEFAULT_TERM_DAYS = 60
DEFAULT_TERM_EXTENSION_DAYS = 30


# ---- Datetime helpers ----------------------------------------------------
def parse_dt(value):
    """Parse an ISO 8601 string into an aware UTC datetime, or raise ValueError."""
    if not isinstance(value, str):
        raise ValueError("datetime must be a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---- Rounding ------------------------------------------------------------
def round_half_up(x):
    """Round a numeric value to the nearest integer, half up."""
    return int(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---- Common-field management (PRD §2.4) ----------------------------------
def stamp_new(record, with_version=True):
    now = db.iso_now()
    record["id"] = db.new_id()
    record["created_at"] = now
    record["_seq"] = db.next_seq()
    if with_version:
        record["updated_at"] = now
        record["version"] = 1
    return record


def touch(record):
    """Bump updated_at + version on any mutation (PRD §2.5)."""
    record["updated_at"] = db.iso_now()
    record["version"] = record.get("version", 1) + 1


# ---- Calculations (SCAFFOLD §1.3) ----------------------------------------
def adjusted_income(annual_income_cents, dependents_count, elderly_or_disabled,
                    childcare_expense_cents):
    dependent_deduction = dependents_count * DEPENDENT_DEDUCTION_CENTS
    elderly_deduction = ELDERLY_DEDUCTION_CENTS if elderly_or_disabled else 0
    childcare_deduction = childcare_expense_cents
    adjusted = (annual_income_cents - dependent_deduction
                - elderly_deduction - childcare_deduction)
    return max(adjusted, 0)


def income_limit_cents(family_size):
    if family_size <= 1:
        factor = Decimal("0.70")
    elif family_size == 2:
        factor = Decimal("0.80")
    elif family_size == 3:
        factor = Decimal("0.90")
    elif family_size == 4:
        factor = Decimal("1.00")
    else:
        factor = Decimal("1.00") + Decimal("0.08") * (family_size - 4)
    raw = Decimal(REGION_VLI_BASE_CENTS) * factor
    return round_half_up(raw)


def occupancy_bedroom_size(family_size):
    if family_size <= 1:
        return 0
    # ceil(family_size / 2)
    bedrooms = -(-family_size // 2)
    return min(bedrooms, MAX_BEDROOM)


def ttp_cents(adjusted_annual_income_cents, annual_income_cents):
    """Total tenant payment: max of three candidates, round ONCE after max."""
    monthly_adjusted = Decimal(adjusted_annual_income_cents) / Decimal(12)
    monthly_gross = Decimal(annual_income_cents) / Decimal(12)
    candidate_30 = Decimal("0.30") * monthly_adjusted
    candidate_10 = Decimal("0.10") * monthly_gross
    ttp_raw = max(candidate_30, candidate_10, Decimal(MINIMUM_RENT_CENTS))
    return round_half_up(ttp_raw)


def subsidy_fields(contract_rent_cents, payment_standard_amount, total_tenant_payment_cents):
    """Returns (hap_subsidy_cents, tenant_rent_burden_cents)."""
    capped_rent = min(contract_rent_cents, payment_standard_amount)
    hap_subsidy = max(capped_rent - total_tenant_payment_cents, 0)
    tenant_burden = contract_rent_cents - hap_subsidy
    return hap_subsidy, tenant_burden


def max_burden_cents(adjusted_annual_income_cents):
    monthly_adjusted = Decimal(adjusted_annual_income_cents) / Decimal(12)
    return round_half_up(Decimal("0.40") * monthly_adjusted)


def lookup_payment_standard_amount(region_id, bedroom_size):
    """Returns amount_cents for the matching PaymentStandard, or None."""
    for ps in db.payment_standards.values():
        if ps["region_id"] == region_id and ps["bedroom_size"] == bedroom_size:
            return ps["amount_cents"]
    return None
