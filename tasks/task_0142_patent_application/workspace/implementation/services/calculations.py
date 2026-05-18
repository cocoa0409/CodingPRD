"""Fee calculations and derived quantities (SCAFFOLD §1.3).

Every monetary calculation here follows the pinned order specified in the
SCAFFOLD: multiply integer cents by the entity multiplier (numerator/denominator)
using Decimal arithmetic, then round half-up to integer cents. The location of
rounding relative to summation or flat-surcharge addition is fee-specific and
documented inline.
"""

from datetime import datetime

from config import (
    APP_TYPE_DESIGN,
    APP_TYPE_PROVISIONAL,
    APP_TYPE_UTILITY,
    DESIGN_TERM_YEARS,
    ENTITY_MULTIPLIER,
    EXAMINATION_FEE_BASE_CENTS,
    EXCESS_INDEP_CLAIM_UNIT_CENTS,
    EXCESS_TOTAL_CLAIM_UNIT_CENTS,
    EXTENSION_FEE_TABLE_CENTS,
    FILING_FEE_TABLE_CENTS,
    ISSUE_FEE_BASE_CENTS,
    MAINTENANCE_FEE_TABLE_CENTS,
    MAINTENANCE_SURCHARGE_CENTS,
    PCT_NATIONAL_BASE_CENTS,
    PROVISIONAL_TERM_DAYS,
    RISK_ABANDONED_WEIGHT,
    RISK_LAPSED_WEIGHT,
    RISK_PENDING_WEIGHT,
    UTILITY_TERM_YEARS,
)
from utils import (
    add_days,
    add_years_as_days,
    ceil_div,
    days_between_floor,
    multiply_and_round,
    round_half_up_decimal,
)
from decimal import Decimal


# ---------------------------------------------------------------------------
# Fee calculations
# ---------------------------------------------------------------------------
def filing_fee(application_type: str, entity_size: str) -> int:
    """SCAFFOLD §1.3 filing_fee:
        base = filing_fee_table[application_type]
        result_cents = round_half_up(base * entity_multiplier[entity_size])
    """
    base = FILING_FEE_TABLE_CENTS[application_type]
    num, den = ENTITY_MULTIPLIER[entity_size]
    return multiply_and_round(base, num, den)


def excess_claim_fee(claim_count: int, independent_claim_count: int, entity_size: str) -> int:
    """SCAFFOLD §1.3 excess_claim_fee, with PER-COMPONENT rounding.

      excess_total = max(0, claim_count - 20)
      excess_indep = max(0, independent_claim_count - 3)
      excess_total_part = round_half_up(excess_total * UNIT * multiplier)
      excess_indep_part = round_half_up(excess_indep * UNIT * multiplier)
      result = excess_total_part + excess_indep_part

    Computing the sum first and rounding once is explicitly forbidden because
    rounding diverges at odd counts under the half/quarter multipliers.
    """
    excess_total = max(0, claim_count - 20)
    excess_indep = max(0, independent_claim_count - 3)
    if excess_total == 0 and excess_indep == 0:
        return 0
    num, den = ENTITY_MULTIPLIER[entity_size]
    total_part = multiply_and_round(excess_total * EXCESS_TOTAL_CLAIM_UNIT_CENTS, num, den)
    indep_part = multiply_and_round(excess_indep * EXCESS_INDEP_CLAIM_UNIT_CENTS, num, den)
    return total_part + indep_part


def examination_fee(entity_size: str) -> int:
    num, den = ENTITY_MULTIPLIER[entity_size]
    return multiply_and_round(EXAMINATION_FEE_BASE_CENTS, num, den)


def issue_fee(entity_size: str) -> int:
    num, den = ENTITY_MULTIPLIER[entity_size]
    return multiply_and_round(ISSUE_FEE_BASE_CENTS, num, den)


def pct_national_fee(entity_size: str) -> int:
    num, den = ENTITY_MULTIPLIER[entity_size]
    return multiply_and_round(PCT_NATIONAL_BASE_CENTS, num, den)


def extension_months(now: datetime, response_deadline_at: datetime) -> int:
    """Compute months_extension per SCAFFOLD §1.3 extension_fee:

      days_late = max(0, days_between(now, response_deadline_at))
      months = ceil(days_late / 30) if days_late > 0 else 0

    days_between uses floor((now - response_deadline_at) in days).
    """
    days_late = days_between_floor(now, response_deadline_at)
    if days_late <= 0:
        return 0
    return ceil_div(days_late, 30)


def extension_fee(months: int, entity_size: str) -> int:
    """SCAFFOLD §1.3 extension_fee:

      if months == 0: 0
      if months > 3: caller must reject as deadline-passed (we return 0)
      base = extension_fee_table[months]
      result_cents = round_half_up(base * multiplier)
    """
    if months == 0:
        return 0
    if months not in EXTENSION_FEE_TABLE_CENTS:
        return 0  # caller is responsible for rejecting; should never be invoked
    base = EXTENSION_FEE_TABLE_CENTS[months]
    num, den = ENTITY_MULTIPLIER[entity_size]
    return multiply_and_round(base, num, den)


def maintenance_fee_amount(stage: str, now: datetime, due_at: datetime, grace_end_at: datetime,
                           entity_size: str) -> int:
    """SCAFFOLD §1.3 maintenance_fee, with PINNED order:

      result = round_half_up(base * multiplier) + surcharge

    The surcharge is added AFTER rounding the entity-adjusted base. The
    surcharge is a flat 16000 cents that does NOT receive the multiplier.
    """
    base = MAINTENANCE_FEE_TABLE_CENTS[stage]
    num, den = ENTITY_MULTIPLIER[entity_size]
    adjusted = multiply_and_round(base, num, den)
    if now > due_at and now <= grace_end_at:
        return adjusted + MAINTENANCE_SURCHARGE_CENTS
    return adjusted


# ---------------------------------------------------------------------------
# Derived quantities
# ---------------------------------------------------------------------------
def compute_total_fees_paid(application_id: str, fee_transactions: dict) -> int:
    """Recompute Application.total_fees_paid_cents.

    SCAFFOLD §1.3 total_fees_paid:
      result = sum(amount_cents WHERE application_id == this.id)
      ordered by paid_at ASC, ties broken by id ASC.

    Because addition is commutative, ordering does not change the sum; we
    nonetheless honour the spec by accumulating in the documented order so
    any future variants (per-row decimal arithmetic) stay consistent.
    """
    rows = [t for t in fee_transactions.values() if t["application_id"] == application_id]
    rows.sort(key=lambda t: (t["paid_at"], t["id"]))
    total = 0
    for t in rows:
        total += t["amount_cents"]
    return total


def compute_application_expiration(application: dict, maintenance_fees: dict) -> str | None:
    """SCAFFOLD §1.3 application_expiration.

      if PROVISIONAL: filed_at + 365 days
      elif UTILITY:   granted_at + 20 years
      elif DESIGN:    granted_at + 15 years
      effective = min(forward_expires_at, earliest_lapsed_grace_period_end_at_or_infinity)

    Returns the expires_at value (the effective expiration date) as an ISO
    string, or None if not computable yet.
    """
    app_type = application["application_type"]
    forward_iso = application.get("expires_at")
    forward_dt = None
    if forward_iso is not None:
        from utils import parse_iso8601
        forward_dt = parse_iso8601(forward_iso)

    earliest_lapsed = None
    for mf in maintenance_fees.values():
        if mf["application_id"] == application["id"] and mf["status"] == "LAPSED":
            from utils import parse_iso8601
            grace_end_dt = parse_iso8601(mf["grace_period_end_at"])
            if earliest_lapsed is None or grace_end_dt < earliest_lapsed:
                earliest_lapsed = grace_end_dt

    if forward_dt is None and earliest_lapsed is None:
        return None
    if forward_dt is None:
        chosen = earliest_lapsed
    elif earliest_lapsed is None:
        chosen = forward_dt
    else:
        chosen = min(forward_dt, earliest_lapsed)
    from utils import iso_now
    return iso_now(chosen)


def compute_forward_expires_at(application: dict) -> datetime | None:
    """Compute the statutory forward-looking expires_at for an Application.

    PROVISIONAL: filed_at + 365 days
    UTILITY: granted_at + 20 years
    DESIGN: granted_at + 15 years
    Returns None if the relevant anchor is not yet set.
    """
    from utils import parse_iso8601
    app_type = application["application_type"]
    if app_type == APP_TYPE_PROVISIONAL:
        if not application.get("filed_at"):
            return None
        return add_days(parse_iso8601(application["filed_at"]), PROVISIONAL_TERM_DAYS)
    if app_type == APP_TYPE_UTILITY:
        if not application.get("granted_at"):
            return None
        return add_years_as_days(parse_iso8601(application["granted_at"]), UTILITY_TERM_YEARS)
    if app_type == APP_TYPE_DESIGN:
        if not application.get("granted_at"):
            return None
        return add_years_as_days(parse_iso8601(application["granted_at"]), DESIGN_TERM_YEARS)
    return None


# ---------------------------------------------------------------------------
# Applicant risk scoring (SCAFFOLD §1.3 applicant_risk_score)
# ---------------------------------------------------------------------------
def compute_applicant_risk_score(applicant_id: str, applications: dict,
                                 office_actions: dict, maintenance_fees: dict) -> int:
    """Risk score in [0, 100] with weights:
        LAPSED MaintenanceFee   = 25 each
        ABANDONED Application   = 15 each
        PENDING OfficeAction    =  5 each
    Then clamp to [0, 100].
    """
    owned_app_ids = {a["id"] for a in applications.values() if a["applicant_id"] == applicant_id}

    lapsed_count = sum(
        1
        for mf in maintenance_fees.values()
        if mf["application_id"] in owned_app_ids and mf["status"] == "LAPSED"
    )
    abandoned_count = sum(
        1
        for a in applications.values()
        if a["applicant_id"] == applicant_id and a["status"] == "ABANDONED"
    )
    pending_oa_count = sum(
        1
        for oa in office_actions.values()
        if oa["application_id"] in owned_app_ids and oa["status"] == "PENDING"
    )

    raw = (
        RISK_LAPSED_WEIGHT * lapsed_count
        + RISK_ABANDONED_WEIGHT * abandoned_count
        + RISK_PENDING_WEIGHT * pending_oa_count
    )
    # Round half-up; raw is already an integer because all weights are integers,
    # but we still funnel through Decimal to keep the rounding contract uniform.
    rounded = round_half_up_decimal(Decimal(raw))
    if rounded < 0:
        return 0
    if rounded > 100:
        return 100
    return int(rounded)
