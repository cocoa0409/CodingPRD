"""Request-body factories: one per creatable resource, client-supplied fields only.

Each factory returns a fresh dict of the canonical seed values and merges ``**overrides``
last, so a test can vary one field without restating the rest. Derived and system fields
are never included: the server owns those.
"""

from typing import Any, Dict

from .constants import TEST_DEFAULTS
from .types import (
    AmendmentEventType,
    CarrierCreditTier,
    DisputeType,
    EasementType,
    EscalatorType,
    LandownerEntityType,
    OfferType,
    StructureType,
    TenancyType,
    ValuationBasis,
    ValuationMethod,
)

DEFAULTS: Dict[str, Any] = dict(TEST_DEFAULTS)


def portfolio_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "name": DEFAULTS["PORTFOLIO_NAME"],
        "program_code": DEFAULTS["PORTFOLIO_PROGRAM_CODE"],
        "total_capital_cents": DEFAULTS["PORTFOLIO_CAPITAL_CENTS"],
    }
    payload.update(overrides)
    return payload


def capital_adjustment_payload(delta_cents: int, memo: str = "Investor capital call", **overrides: Any) -> Dict[str, Any]:
    """PRD section 3.1 names the two fields of a capital adjustment ``delta_cents`` and ``memo``."""
    payload = {"delta_cents": delta_cents, "memo": memo}
    payload.update(overrides)
    return payload


def financing_facility_payload(portfolio_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "portfolio_id": portfolio_id,
        "facility_name": DEFAULTS["FACILITY_NAME"],
        "advance_rate_bps": DEFAULTS["ADVANCE_RATE_BPS"],
        "valuation_basis": ValuationBasis.MARK_TO_MODEL.value,
        "carrier_concentration_limit_bps": DEFAULTS["CONCENTRATION_LIMIT_BPS_WIDE_OPEN"],
    }
    payload.update(overrides)
    return payload


def pledge_payload(lease_stream_id: str, expected_facility_version: int, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "lease_stream_id": lease_stream_id,
        "pledge_start_date": DEFAULTS["PLEDGE_START_DATE"],
        "pledge_end_date": DEFAULTS["PLEDGE_END_DATE"],
        "expected_facility_version": expected_facility_version,
    }
    payload.update(overrides)
    return payload


def advance_payload(amount_cents: int, **overrides: Any) -> Dict[str, Any]:
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def tower_company_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "legal_name": DEFAULTS["TOWER_COMPANY_NAME"],
        "notice_email": DEFAULTS["TOWER_COMPANY_EMAIL"],
        "rofr_required": False,
        "rofr_window_days": DEFAULTS["ROFR_WINDOW_DAYS"],
    }
    payload.update(overrides)
    return payload


def tower_site_payload(tower_company_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "tower_company_id": tower_company_id,
        "site_code": DEFAULTS["SITE_CODE"],
        "state_code": DEFAULTS["STATE_CODE"],
        "ground_area_sqft": DEFAULTS["GROUND_AREA_SQFT"],
        "structure_type": StructureType.MONOPOLE.value,
    }
    payload.update(overrides)
    return payload


def landowner_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "legal_name": DEFAULTS["LANDOWNER_NAME"],
        "entity_type": LandownerEntityType.LLC.value,
        "contact_email": DEFAULTS["LANDOWNER_EMAIL"],
    }
    payload.update(overrides)
    return payload


def lease_stream_payload(tower_site_id: str, landowner_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "tower_site_id": tower_site_id,
        "landowner_id": landowner_id,
        "current_annual_rent_cents": DEFAULTS["CURRENT_ANNUAL_RENT_CENTS"],
        "escalator_type": EscalatorType.FIXED_PCT.value,
        "escalator_pct_bps": DEFAULTS["ESCALATOR_PCT_BPS"],
        "remaining_term_months": DEFAULTS["REMAINING_TERM_MONTHS"],
    }
    payload.update(overrides)
    return payload


def tenancy_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "carrier_name": DEFAULTS["ANCHOR_CARRIER_NAME"],
        "carrier_credit_tier": CarrierCreditTier.INVESTMENT_GRADE.value,
        "tenancy_type": TenancyType.ANCHOR.value,
        "monthly_rent_share_cents": DEFAULTS["ANCHOR_MONTHLY_RENT_SHARE_CENTS"],
        "term_end_date": DEFAULTS["TENANCY_TERM_END_DATE"],
    }
    payload.update(overrides)
    return payload


def valuation_payload(expected_lease_stream_version: int, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "method": ValuationMethod.LUMP_SUM_PERPETUAL.value,
        "expected_lease_stream_version": expected_lease_stream_version,
    }
    payload.update(overrides)
    return payload


def deal_payload(portfolio_id: str, lease_stream_id: str, valuation_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "portfolio_id": portfolio_id,
        "lease_stream_id": lease_stream_id,
        "valuation_id": valuation_id,
        "easement_type": EasementType.PERPETUAL_EASEMENT.value,
        "revenue_share_bps": DEFAULTS["REVENUE_SHARE_BPS"],
    }
    payload.update(overrides)
    return payload


def offer_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "offer_type": OfferType.LUMP_SUM.value,
        "amount_cents": DEFAULTS["OFFER_AMOUNT_CENTS"],
        "expires_at": DEFAULTS["OFFER_EXPIRES_AT"],
    }
    payload.update(overrides)
    return payload


def title_report_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {"snda_required": False}
    payload.update(overrides)
    return payload


def record_findings_payload(exception_count: int = 0, mortgage_present: bool = False, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "action": "RECORD_FINDINGS",
        "exception_count": exception_count,
        "mortgage_present": mortgage_present,
    }
    payload.update(overrides)
    return payload


def dispute_payload(dispute_type: str = DisputeType.ACCESS.value, description: str = "Access road gated without notice", **overrides: Any) -> Dict[str, Any]:
    payload = {"dispute_type": dispute_type, "description": description}
    payload.update(overrides)
    return payload


def amendment_event_payload(
    gross_amount_cents: int,
    event_type: str = AmendmentEventType.COLOCATION_ADDED.value,
    effective_date: str = "2026-09-01",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "event_type": event_type,
        "gross_amount_cents": gross_amount_cents,
        "effective_date": effective_date,
    }
    payload.update(overrides)
    return payload


def close_payload(recording_ref: str = None, **overrides: Any) -> Dict[str, Any]:
    payload = {"recording_ref": recording_ref or DEFAULTS["RECORDING_REF"]}
    payload.update(overrides)
    return payload


def terminate_payload(reason: str = "Landowner withdrew from talks", **overrides: Any) -> Dict[str, Any]:
    payload = {"reason": reason}
    payload.update(overrides)
    return payload


__all__ = [
    "DEFAULTS",
    "portfolio_payload",
    "capital_adjustment_payload",
    "financing_facility_payload",
    "pledge_payload",
    "advance_payload",
    "tower_company_payload",
    "tower_site_payload",
    "landowner_payload",
    "lease_stream_payload",
    "tenancy_payload",
    "valuation_payload",
    "deal_payload",
    "offer_payload",
    "title_report_payload",
    "record_findings_payload",
    "dispute_payload",
    "amendment_event_payload",
    "close_payload",
    "terminate_payload",
]
