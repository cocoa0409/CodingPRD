"""Payload factories -- one per creation endpoint, input fields only."""

from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS

_EMAIL_COUNTER = {"n": 0}


def unique_email(prefix: str = "member") -> str:
    """A member email must be unique across all members and contain an '@'."""
    _EMAIL_COUNTER["n"] += 1
    return f"{prefix}{_EMAIL_COUNTER['n']}@example.org"


def create_fiscal_period_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "label": TEST_DEFAULTS["PERIOD_LABEL"],
        "start_date": TEST_DEFAULTS["PERIOD_START_DATE"],
        "end_date": TEST_DEFAULTS["PERIOD_END_DATE"],
        "monthly_expense_base_cents": TEST_DEFAULTS["MONTHLY_EXPENSE_BASE_CENTS"],
        "reserve_balance_cents": TEST_DEFAULTS["RESERVE_BALANCE_CENTS"],
    }
    payload.update(overrides)
    return payload


def benefit_payload(
    benefit_code: str,
    fulfillment_type: str,
    annual_fair_market_value_cents: int,
) -> Dict[str, Any]:
    """One entry of a tier's benefits array."""
    return {
        "benefit_code": benefit_code,
        "fulfillment_type": fulfillment_type,
        "annual_fair_market_value_cents": annual_fair_market_value_cents,
    }


def create_membership_tier_payload(
    benefits: Optional[List[Dict[str, Any]]] = None, **overrides
) -> Dict[str, Any]:
    payload = {
        "tier_code": TEST_DEFAULTS["TIER_CODE"],
        "name": TEST_DEFAULTS["TIER_NAME"],
        "renewal_cadence": "MONTHLY",
        "contribution_amount_cents": TEST_DEFAULTS["TIER_CONTRIBUTION_AMOUNT_CENTS"],
        "benefits": [] if benefits is None else benefits,
    }
    payload.update(overrides)
    return payload


def create_member_payload(tier_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "tier_id": tier_id,
        "email": unique_email(),
        "full_name": "Ana Rivera",
    }
    payload.update(overrides)
    return payload


def create_coverage_area_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "area_code": TEST_DEFAULTS["AREA_CODE"],
        "name": TEST_DEFAULTS["AREA_NAME"],
        "editorial_lead_user_id": TEST_DEFAULTS["EDITORIAL_LEAD_USER_ID"],
    }
    payload.update(overrides)
    return payload


def create_funder_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "legal_name": TEST_DEFAULTS["FUNDER_LEGAL_NAME"],
        "funder_type": "FOUNDATION",
    }
    payload.update(overrides)
    return payload


def independence_clearance_payload(
    decision: str = "CLEAR", basis: str = "SELF_ATTESTED", **overrides
) -> Dict[str, Any]:
    payload = {"decision": decision, "basis": basis}
    payload.update(overrides)
    return payload


def create_firewall_disclosure_payload(
    funder_id: str, coverage_area_id: str, expected_funder_version: int, **overrides
) -> Dict[str, Any]:
    payload = {
        "funder_id": funder_id,
        "coverage_area_id": coverage_area_id,
        "disclosure_text": TEST_DEFAULTS["DISCLOSURE_TEXT"],
        "expected_funder_version": expected_funder_version,
    }
    payload.update(overrides)
    return payload


def create_influence_contact_payload(funder_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "funder_id": funder_id,
        "contact_type": "ROUTINE_STEWARDSHIP",
        "occurred_at": "2026-08-01T00:00:00Z",
        "summary": "The funder asked for a programme update over coffee.",
    }
    payload.update(overrides)
    return payload


def create_gift_offer_payload(
    funder_id: str, fiscal_period_id: str, **overrides
) -> Dict[str, Any]:
    payload = {
        "funder_id": funder_id,
        "fiscal_period_id": fiscal_period_id,
        "offered_amount_cents": 200000,
        "designation": "UNRESTRICTED",
    }
    payload.update(overrides)
    return payload


def create_grant_proposal_payload(
    funder_id: str, fiscal_period_id: str, **overrides
) -> Dict[str, Any]:
    payload = {
        "funder_id": funder_id,
        "fiscal_period_id": fiscal_period_id,
        "title": TEST_DEFAULTS["PROPOSAL_TITLE"],
        "requested_amount_cents": TEST_DEFAULTS["REQUESTED_AMOUNT_CENTS"],
        "restriction_type": "UNRESTRICTED",
    }
    payload.update(overrides)
    return payload


def restricted_grant_proposal_payload(
    funder_id: str, fiscal_period_id: str, coverage_area_id: str, **overrides
) -> Dict[str, Any]:
    payload = create_grant_proposal_payload(
        funder_id,
        fiscal_period_id,
        restriction_type="PROGRAM_RESTRICTED",
        coverage_area_id=coverage_area_id,
        restriction_start_date=TEST_DEFAULTS["RESTRICTION_START_DATE"],
        restriction_end_date=TEST_DEFAULTS["RESTRICTION_END_DATE"],
        reporting_cadence="NONE",
        award_probability_bps=6000,
    )
    payload.update(overrides)
    return payload


def create_contribution_payload(
    fiscal_period_id: str, revenue_stream: str, amount_cents: int, **overrides
) -> Dict[str, Any]:
    payload = {
        "fiscal_period_id": fiscal_period_id,
        "revenue_stream": revenue_stream,
        "amount_cents": amount_cents,
        "received_date": TEST_DEFAULTS["PERIOD_START_DATE"],
    }
    payload.update(overrides)
    return payload


def create_collaboration_payload(
    coverage_area_id: str, fiscal_period_id: str, **overrides
) -> Dict[str, Any]:
    payload = {
        "coverage_area_id": coverage_area_id,
        "fiscal_period_id": fiscal_period_id,
        "title": TEST_DEFAULTS["COLLABORATION_TITLE"],
        "window_start": TEST_DEFAULTS["WINDOW_START"],
        "window_end": TEST_DEFAULTS["WINDOW_END"],
        "total_cost_cents": TEST_DEFAULTS["TOTAL_COST_CENTS"],
        "lead_credit_bps": 6000,
        "lead_cost_share_bps": 6000,
    }
    payload.update(overrides)
    return payload


def create_collaboration_partner_payload(
    partner_org_name: str = "Delta River Report",
    credit_share_bps: int = 4000,
    cost_share_bps: int = 4000,
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "partner_org_name": partner_org_name,
        "credit_share_bps": credit_share_bps,
        "cost_share_bps": cost_share_bps,
    }
    payload.update(overrides)
    return payload
