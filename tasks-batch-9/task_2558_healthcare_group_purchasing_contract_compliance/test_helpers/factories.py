"""Request-payload builders.

Each builder returns the canonical, PRD-valid body for one endpoint and accepts
keyword overrides so a test can vary exactly one field.  Passing ``None`` for an
optional key is meaningful (it sends JSON null); to *omit* a key entirely, pop it
from the returned dict or use the ``omit`` helper.
"""

from typing import Any, Dict, Iterable, List, Optional

from .constants import (
    DEFAULT_BASE_PRICE_CENTS,
    DEFAULT_FLOOR_PRICE_CENTS,
    DEFAULT_LEAKAGE_ALERT_THRESHOLD_PCT,
    FULL_TIER_LADDER,
    HOLDBACK_LADDER,
    TIER_0,
)

Json = Dict[str, Any]


def omit(payload: Json, *keys: str) -> Json:
    """Copy of ``payload`` with ``keys`` absent (not null)."""
    return {k: v for k, v in payload.items() if k not in keys}


def _merge(base: Json, overrides: Json) -> Json:
    merged = dict(base)
    merged.update(overrides)
    return merged


# --- contracts -------------------------------------------------------------


def contract_payload(**overrides: Any) -> Json:
    """Canonical contract: three-rung tier ladder, two-rung holdback ladder."""
    base: Json = {
        "contract_code": "C-SUT-1",
        "supplier_name": "Acme Surgical",
        "category_code": "CAT-SUT",
        "effective_from": "2026-01-01",
        "effective_to": "2026-12-31",
        "admin_fee_bps": 300,
        "member_share_bps": 6000,
        "requires_clinical_review": False,
        "share_basis": "COLLECTED",
        "leakage_alert_threshold_pct": DEFAULT_LEAKAGE_ALERT_THRESHOLD_PCT,
        "tiers": [dict(row) for row in FULL_TIER_LADDER],
        "holdback_tiers": [dict(row) for row in HOLDBACK_LADDER],
    }
    return _merge(base, overrides)


def tier_row(
    tier_code: str,
    min_committed_volume_units: int,
    min_compliance_pct: float,
    discount_bps: int,
) -> Json:
    return {
        "tier_code": tier_code,
        "min_committed_volume_units": min_committed_volume_units,
        "min_compliance_pct": min_compliance_pct,
        "discount_bps": discount_bps,
    }


def holdback_row(min_gross_pool_cents: int, holdback_bps: int) -> Json:
    return {
        "min_gross_pool_cents": min_gross_pool_cents,
        "holdback_bps": holdback_bps,
    }


def tiers_payload(tiers: Iterable[Json]) -> Json:
    return {"tiers": [dict(row) for row in tiers]}


# --- contract items --------------------------------------------------------


def contract_item_payload(**overrides: Any) -> Json:
    base: Json = {
        "vendor_item_number": "V-1",
        "item_description": "Suture 3-0 absorbable",
        "uom": "EA",
        "units_per_uom": 1,
        "base_price_cents": DEFAULT_BASE_PRICE_CENTS,
        "floor_price_cents": DEFAULT_FLOOR_PRICE_CENTS,
        "requires_evidence": False,
    }
    return _merge(base, overrides)


def base_price_payload(base_price_cents: int, expected_contract_version: Any) -> Json:
    return {
        "base_price_cents": base_price_cents,
        "expected_contract_version": expected_contract_version,
    }


# --- members ---------------------------------------------------------------


def item_master_row(
    member_item_number: str,
    description: str = "Suture 3-0",
    units_per_uom: int = 1,
) -> Json:
    return {
        "member_item_number": member_item_number,
        "description": description,
        "units_per_uom": units_per_uom,
    }


def member_payload(**overrides: Any) -> Json:
    base: Json = {
        "member_code": "M-1",
        "name": "Riverbend Regional Hospital",
        "aggregation_group_code": "AGG-NORTH",
        "item_master": [item_master_row("MI-1")],
    }
    return _merge(base, overrides)


def item_master_payload(rows: Iterable[Json]) -> Json:
    return {"item_master": [dict(row) for row in rows]}


# --- clinical evidence reviews --------------------------------------------


def evidence_review_payload(
    contract_id: str,
    clinical_efficacy_score: float = 8.00,
    safety_score: float = 7.00,
    supply_resilience_score: float = 6.00,
    summary: Optional[str] = "Meta-analysis of 14 trials.",
    **overrides: Any
) -> Json:
    base: Json = {
        "contract_id": contract_id,
        "clinical_efficacy_score": clinical_efficacy_score,
        "safety_score": safety_score,
        "supply_resilience_score": supply_resilience_score,
    }
    if summary is not None:
        base["summary"] = summary
    return _merge(base, overrides)


def scores_payload(
    clinical_efficacy_score: float,
    safety_score: float,
    supply_resilience_score: float,
) -> Json:
    return {
        "clinical_efficacy_score": clinical_efficacy_score,
        "safety_score": safety_score,
        "supply_resilience_score": supply_resilience_score,
    }


def resubmit_payload(
    clinical_efficacy_score: float,
    safety_score: float,
    supply_resilience_score: float,
    summary: Optional[str] = None,
) -> Json:
    payload = scores_payload(
        clinical_efficacy_score, safety_score, supply_resilience_score
    )
    if summary is not None:
        payload["summary"] = summary
    return payload


# --- commitments -----------------------------------------------------------


def commitment_payload(
    member_id: str,
    contract_id: str,
    elected_tier_code: str = TIER_0,
    committed_volume_units: int = 100,
    effective_from: str = "2026-08-01",
    **overrides: Any
) -> Json:
    base: Json = {
        "member_id": member_id,
        "contract_id": contract_id,
        "elected_tier_code": elected_tier_code,
        "committed_volume_units": committed_volume_units,
        "effective_from": effective_from,
    }
    return _merge(base, overrides)


def signer_payload(signer_name: str = "R. Vasquez") -> Json:
    return {"signer_name": signer_name}


def reason_payload(reason: str) -> Json:
    return {"reason": reason}


# --- cross references ------------------------------------------------------


def cross_reference_payload(
    member_id: str,
    contract_item_id: str,
    member_item_number: str = "MI-1",
    match_type: str = "EXACT",
    conversion_factor: float = 1.0,
    **overrides: Any
) -> Json:
    base: Json = {
        "member_id": member_id,
        "contract_item_id": contract_item_id,
        "member_item_number": member_item_number,
        "match_type": match_type,
        "conversion_factor": conversion_factor,
    }
    return _merge(base, overrides)


# --- price activations -----------------------------------------------------


def price_activation_payload(
    commitment_id: str,
    contract_item_id: str,
    activation_type: str = "TIER_PRICE",
    effective_from: str = "2026-08-01",
    effective_to: str = "2026-12-31",
    requested_price_cents: Optional[int] = None,
    **overrides: Any
) -> Json:
    base: Json = {
        "commitment_id": commitment_id,
        "contract_item_id": contract_item_id,
        "activation_type": activation_type,
        "effective_from": effective_from,
        "effective_to": effective_to,
    }
    if requested_price_cents is not None:
        base["requested_price_cents"] = requested_price_cents
    return _merge(base, overrides)


# --- distributor files -----------------------------------------------------


def purchase_line_row(
    member_item_number: str,
    quantity_units: int,
    unit_price_paid_cents: int,
    purchase_date: str,
) -> Json:
    return {
        "member_item_number": member_item_number,
        "quantity_units": quantity_units,
        "unit_price_paid_cents": unit_price_paid_cents,
        "purchase_date": purchase_date,
    }


def distributor_file_payload(
    member_id: str,
    contract_id: str,
    lines: List[Json],
    distributor_code: str = "D-A",
    period_start: str = "2026-08-01",
    period_end: str = "2026-09-01",
    **overrides: Any
) -> Json:
    base: Json = {
        "member_id": member_id,
        "contract_id": contract_id,
        "distributor_code": distributor_code,
        "period_start": period_start,
        "period_end": period_end,
        "lines": [dict(row) for row in lines],
    }
    return _merge(base, overrides)


# --- compliance measurements ----------------------------------------------


def measurement_payload(
    commitment_id: str,
    expected_commitment_version: Any,
    period_start: str = "2026-08-01",
    period_end: str = "2026-09-01",
    **overrides: Any
) -> Json:
    base: Json = {
        "commitment_id": commitment_id,
        "period_start": period_start,
        "period_end": period_end,
        "expected_commitment_version": expected_commitment_version,
    }
    return _merge(base, overrides)


# --- admin fee distributions ----------------------------------------------


def distribution_payload(
    contract_id: str,
    period_start: str = "2026-08-01",
    period_end: str = "2026-09-01",
    **overrides: Any
) -> Json:
    base: Json = {
        "contract_id": contract_id,
        "period_start": period_start,
        "period_end": period_end,
    }
    return _merge(base, overrides)


def collect_payload(collected_fee_cents: int) -> Json:
    return {"collected_fee_cents": collected_fee_cents}


# --- query parameter helpers ----------------------------------------------


def leakage_window(from_date: str, to_date: str) -> Json:
    return {"from_date": from_date, "to_date": to_date}


def page(limit: Optional[int] = None, offset: Optional[int] = None, **filters: Any) -> Json:
    params: Json = {}
    if limit is not None:
        params["limit"] = limit
    if offset is not None:
        params["offset"] = offset
    params.update(filters)
    return params
