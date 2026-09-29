"""Request-payload builders.

Each builder produces a valid payload for one write endpoint and accepts
keyword overrides so a test can perturb exactly the field under examination.
Business keys the PRD requires to be unique — an investor ``email`` and a firm
``crd_number`` — are made unique per call by a process-local counter so that a
scenario needing several rows does not trip a duplicate gate by accident.
"""

from __future__ import annotations

import itertools
from typing import Any, Dict

from .constants import DEFAULT_RESCISSION_WINDOW_DAYS
from .types import ClassCode, HardshipType, LiquidityEventType, VoteChoice

_counter = itertools.count(1)


def unique_suffix() -> str:
    return f"{next(_counter):05d}"


def offering_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1 offering registration payload."""
    payload = {
        "name": f"Cavendish Income REIT {unique_suffix()}",
        "minimum_offering_amount_cents": 30000000,
        "maximum_offering_amount_cents": 50000000000,
        "escrow_deadline_date": "2026-12-31",
        "initial_offering_price_cents": 1000,
    }
    payload.update(overrides)
    return payload


def share_class_payload(offering_id: str, **overrides: Any) -> Dict[str, Any]:
    """PRD §3.1 share-class payload; defaults to a zero-load class I."""
    payload = {
        "offering_id": offering_id,
        "class_code": ClassCode.I,
        "upfront_selling_commission_bps": 0,
        "dealer_manager_fee_bps": 0,
        "annual_distribution_fee_bps": 0,
        "distribution_fee_cap_bps": 0,
    }
    payload.update(overrides)
    return payload


def investor_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.2 investor account payload; a non-strict state by default."""
    suffix = unique_suffix()
    payload = {
        "legal_name": f"Ines Marchetti {suffix}",
        "email": f"ines.marchetti.{suffix}@example.com",
        "state_code": "TX",
        "net_worth_cents": 5000000000,
        "annual_income_cents": 1000000000,
    }
    payload.update(overrides)
    return payload


def broker_dealer_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.3 broker-dealer registration payload."""
    suffix = unique_suffix()
    payload = {
        "firm_name": f"Ashgrove Placement {suffix}",
        "crd_number": f"CRD-{suffix}",
    }
    payload.update(overrides)
    return payload


def selling_agreement_payload(
    offering_id: str, broker_dealer_id: str, **overrides: Any
) -> Dict[str, Any]:
    """PRD §3.3 selling-agreement payload."""
    payload = {
        "offering_id": offering_id,
        "broker_dealer_id": broker_dealer_id,
        "max_commission_bps": 1300,
    }
    payload.update(overrides)
    return payload


def subscription_payload(
    offering_id: str,
    share_class_id: str,
    investor_id: str,
    selling_agreement_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.4 subscription payload."""
    payload = {
        "offering_id": offering_id,
        "share_class_id": share_class_id,
        "investor_id": investor_id,
        "selling_agreement_id": selling_agreement_id,
        "gross_investment_cents": 250000,
    }
    payload.update(overrides)
    return payload


def nav_record_payload(
    share_class_id: str, expected_share_class_version: int, **overrides: Any
) -> Dict[str, Any]:
    """PRD §3.6 valuation payload, including the §2.8 version echo."""
    payload = {
        "share_class_id": share_class_id,
        "period_start_date": "2026-07-01",
        "period_end_date": "2026-07-31",
        "gross_asset_value_cents": 30000000,
        "other_liabilities_cents": 0,
        "expected_share_class_version": expected_share_class_version,
    }
    payload.update(overrides)
    return payload


def declaration_payload(
    offering_id: str, expected_offering_version: int, **overrides: Any
) -> Dict[str, Any]:
    """PRD §3.7 declaration payload, including the §2.8 version echo."""
    payload = {
        "offering_id": offering_id,
        "record_date": "2026-08-15",
        "payment_date": "2026-08-31",
        "declared_per_share_cents": 5,
        "gaap_net_income_cents": 90000,
        "adjusted_cash_flow_cents": 150000,
        "expected_offering_version": expected_offering_version,
    }
    payload.update(overrides)
    return payload


def repurchase_period_payload(offering_id: str, **overrides: Any) -> Dict[str, Any]:
    """PRD §3.8 repurchase-period payload."""
    payload = {
        "offering_id": offering_id,
        "period_month": "2026-08",
        "opens_at": "2026-08-01T00:00:00Z",
        "request_cutoff_at": "2026-08-26T00:00:00Z",
        "settlement_date": "2026-08-30",
    }
    payload.update(overrides)
    return payload


def repurchase_request_payload(
    repurchase_period_id: str, share_class_id: str, shares_requested_e4: int, **overrides: Any
) -> Dict[str, Any]:
    """PRD §3.8 tender payload; ``investor_id`` is never supplied in the body."""
    payload = {
        "repurchase_period_id": repurchase_period_id,
        "share_class_id": share_class_id,
        "shares_requested_e4": shares_requested_e4,
        "hardship_type": HardshipType.NONE,
    }
    payload.update(overrides)
    return payload


def liquidity_event_payload(offering_id: str, **overrides: Any) -> Dict[str, Any]:
    """PRD §3.9 liquidity-event payload."""
    payload = {
        "offering_id": offering_id,
        "event_type": LiquidityEventType.LISTING,
        "proposed_effective_date": "2026-09-30",
    }
    payload.update(overrides)
    return payload


def stockholder_vote_payload(liquidity_event_id: str, **overrides: Any) -> Dict[str, Any]:
    """PRD §3.9 ballot payload; ``investor_id`` comes from ``X-User-ID``."""
    payload = {
        "liquidity_event_id": liquidity_event_id,
        "choice": VoteChoice.FOR,
    }
    payload.update(overrides)
    return payload


def offering_with_rescission_window(days: int = DEFAULT_RESCISSION_WINDOW_DAYS, **overrides: Any):
    return offering_payload(rescission_window_days=days, **overrides)
