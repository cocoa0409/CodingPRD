"""Payload factories for the commuter benefit service.

Every money amount is a whole-cent Python ``int`` -- never a string and never a
float -- because the service performs exact whole-cent integer arithmetic.
Every factory accepts keyword overrides so a test can pin one field and inherit
sane values for the rest.
"""

import itertools
from typing import Any, Dict, Optional

from .constants import (
    DEFAULT_CLOCK,
    REGION_AUS,
)

_counter = itertools.count(1)


def unique_suffix() -> str:
    """Monotonic suffix so repeated factory calls never collide on a unique key."""
    return f"{next(_counter):04d}"


def _clean(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop keys whose value is the sentinel ``...`` so callers can omit fields."""
    return {k: v for k, v in payload.items() if v is not Ellipsis}


# --------------------------------------------------------------------- employer
def employer_payload(
    legal_name: Optional[str] = None,
    region_code: str = REGION_AUS,
    transit_group_limit_cents: int = 30000,
    parking_group_limit_cents: int = 30000,
    program_cap_cents: int = 5000000,
    pretax_ratio_cap_pct: Any = Ellipsis,
    spill_policy: Any = Ellipsis,
    rollover_policy: Any = Ellipsis,
    rollover_cap_cents: Any = Ellipsis,
    forfeiture_grace_days: Any = Ellipsis,
    **extra: Any,
) -> Dict[str, Any]:
    payload = {
        "legal_name": legal_name or f"Commuter Program {unique_suffix()}",
        "region_code": region_code,
        "transit_group_limit_cents": transit_group_limit_cents,
        "parking_group_limit_cents": parking_group_limit_cents,
        "program_cap_cents": program_cap_cents,
        "pretax_ratio_cap_pct": pretax_ratio_cap_pct,
        "spill_policy": spill_policy,
        "rollover_policy": rollover_policy,
        "rollover_cap_cents": rollover_cap_cents,
        "forfeiture_grace_days": forfeiture_grace_days,
    }
    payload.update(extra)
    return _clean(payload)


# ------------------------------------------------------------ benefit category
def benefit_category_payload(
    employer_id: str,
    category_type: str = "TRANSIT_PASS",
    monthly_exclusion_limit_cents: int = 30000,
    pretax_allowed: Any = Ellipsis,
    posttax_allowed: Any = Ellipsis,
    **extra: Any,
) -> Dict[str, Any]:
    payload = {
        "employer_id": employer_id,
        "category_type": category_type,
        "monthly_exclusion_limit_cents": monthly_exclusion_limit_cents,
        "pretax_allowed": pretax_allowed,
        "posttax_allowed": posttax_allowed,
    }
    payload.update(extra)
    return _clean(payload)


# --------------------------------------------------------------------- employee
def employee_payload(
    employer_id: str,
    external_ref: Optional[str] = None,
    work_region_code: str = REGION_AUS,
    payroll_cycle: str = "MONTHLY",
    hire_date: str = "2026-02-01T00:00:00Z",
    **extra: Any,
) -> Dict[str, Any]:
    payload = {
        "employer_id": employer_id,
        "external_ref": external_ref or f"EMP-{unique_suffix()}",
        "work_region_code": work_region_code,
        "payroll_cycle": payroll_cycle,
        "hire_date": hire_date,
    }
    payload.update(extra)
    return _clean(payload)


# ---------------------------------------------------------------- transit media
def transit_media_payload(
    sku: Optional[str] = None,
    media_type: str = "PAPER_PASS",
    region_code: str = REGION_AUS,
    eligible_category_type: str = "TRANSIT_PASS",
    unit_price_cents: int = 6000,
    lead_days: Any = Ellipsis,
    replacement_fee_cents: Any = Ellipsis,
    requires_physical_fulfillment: Any = Ellipsis,
    **extra: Any,
) -> Dict[str, Any]:
    payload = {
        "sku": sku or f"SKU-{unique_suffix()}",
        "media_type": media_type,
        "region_code": region_code,
        "eligible_category_type": eligible_category_type,
        "unit_price_cents": unit_price_cents,
        "lead_days": lead_days,
        "replacement_fee_cents": replacement_fee_cents,
        "requires_physical_fulfillment": requires_physical_fulfillment,
    }
    payload.update(extra)
    return _clean(payload)


# -------------------------------------------------------------- election window
def election_window_payload(
    employer_id: str,
    benefit_month: str = "2026-08",
    opens_at: str = "2026-07-01T00:00:00Z",
    cutoff_at: str = "2026-08-20T00:00:00Z",
    fulfillment_lead_days: Any = Ellipsis,
    mid_month_change_allowed: Any = Ellipsis,
    **extra: Any,
) -> Dict[str, Any]:
    payload = {
        "employer_id": employer_id,
        "benefit_month": benefit_month,
        "opens_at": opens_at,
        "cutoff_at": cutoff_at,
        "fulfillment_lead_days": fulfillment_lead_days,
        "mid_month_change_allowed": mid_month_change_allowed,
    }
    payload.update(extra)
    return _clean(payload)


# -------------------------------------------------------------- benefit account
def benefit_account_payload(
    employee_id: str,
    benefit_category_id: str,
    opening_rollover_cents: Any = Ellipsis,
    **extra: Any,
) -> Dict[str, Any]:
    payload = {
        "employee_id": employee_id,
        "benefit_category_id": benefit_category_id,
        "opening_rollover_cents": opening_rollover_cents,
    }
    payload.update(extra)
    return _clean(payload)


# --------------------------------------------------------------------- election
def election_payload(
    employee_id: str,
    election_window_id: str,
    benefit_category_id: str,
    expected_account_version: int,
    pretax_amount_cents: int = 5000,
    posttax_amount_cents: Any = Ellipsis,
    transit_media_id: Any = Ellipsis,
    media_quantity: Any = Ellipsis,
    **extra: Any,
) -> Dict[str, Any]:
    payload = {
        "employee_id": employee_id,
        "election_window_id": election_window_id,
        "benefit_category_id": benefit_category_id,
        "pretax_amount_cents": pretax_amount_cents,
        "posttax_amount_cents": posttax_amount_cents,
        "transit_media_id": transit_media_id,
        "media_quantity": media_quantity,
        "expected_account_version": expected_account_version,
    }
    payload.update(extra)
    return _clean(payload)


# ------------------------------------------------------------------ order batch
def order_batch_payload(
    election_window_id: str, region_code: str = REGION_AUS, **extra: Any
) -> Dict[str, Any]:
    payload = {"election_window_id": election_window_id, "region_code": region_code}
    payload.update(extra)
    return _clean(payload)


# ------------------------------------------------------------------ media order
def media_order_payload(
    election_id: str,
    transit_media_id: str,
    order_batch_id: str,
    expected_election_version: int,
    quantity: int = 1,
    coverage_start_at: str = "2026-08-01T00:00:00Z",
    coverage_end_at: str = "2026-08-31T00:00:00Z",
    **extra: Any,
) -> Dict[str, Any]:
    payload = {
        "election_id": election_id,
        "transit_media_id": transit_media_id,
        "order_batch_id": order_batch_id,
        "quantity": quantity,
        "coverage_start_at": coverage_start_at,
        "coverage_end_at": coverage_end_at,
        "expected_election_version": expected_election_version,
    }
    payload.update(extra)
    return _clean(payload)


# ------------------------------------------------------------- card transaction
def card_transaction_payload(
    election_id: str,
    amount_cents: int = 2000,
    merchant_category_code: int = 4111,
    merchant_name: str = "TRANSIT FARE VENDING",
    transaction_at: str = DEFAULT_CLOCK,
    **extra: Any,
) -> Dict[str, Any]:
    payload = {
        "election_id": election_id,
        "amount_cents": amount_cents,
        "merchant_category_code": merchant_category_code,
        "merchant_name": merchant_name,
        "transaction_at": transaction_at,
    }
    payload.update(extra)
    return _clean(payload)


# -------------------------------------------------------- substantiation claim
def substantiation_claim_payload(
    card_transaction_id: str,
    claimed_amount_cents: int,
    doc_type: str = "RECEIPT",
    **extra: Any,
) -> Dict[str, Any]:
    payload = {
        "card_transaction_id": card_transaction_id,
        "claimed_amount_cents": claimed_amount_cents,
        "doc_type": doc_type,
    }
    payload.update(extra)
    return _clean(payload)


# ------------------------------------------------------------------ payroll file
def payroll_file_payload(
    employer_id: str, period_month: str = "2026-08", **extra: Any
) -> Dict[str, Any]:
    payload = {"employer_id": employer_id, "period_month": period_month}
    payload.update(extra)
    return _clean(payload)


def compliance_assessment_payload(
    assessment_month: str = "2026-08", **extra: Any
) -> Dict[str, Any]:
    payload = {"assessment_month": assessment_month}
    payload.update(extra)
    return _clean(payload)
