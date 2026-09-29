"""Request payload builders.

Every builder returns a plain dict with only the fields the endpoint accepts, so a
test can override exactly the field it is exercising and leave the rest canonical.
Money is always an integer count of cents and is never sent as a string.
"""

import itertools
from typing import Any, Dict, List, Optional

from .constants import (
    CANONICAL_BID_RATES,
    CANONICAL_JOB_PLAN,
    CANONICAL_SOLICITATION,
    CANONICAL_WELL_INPUTS,
)

_well_number_seq = itertools.count(1)
_license_seq = itertools.count(1)
_operator_name_seq = itertools.count(1)


def next_api_well_number() -> str:
    """A fresh well identifier of the state's API numbering format."""
    return "49-001-%05d" % next(_well_number_seq)


def next_license_number() -> str:
    """A fresh contractor licence number."""
    return "P-%05d" % next(_license_seq)


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------
def operator_payload(
    name: Optional[str] = None,
    financial_assurance_tier: str = "INDIVIDUAL",
    bond_amount_cents: int = 5000000,
    region_code: str = "WY",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name or "Cottonwood Energy LLC %d" % next(_operator_name_seq),
        "region_code": region_code,
        "financial_assurance_tier": financial_assurance_tier,
        "bond_amount_cents": bond_amount_cents,
    }
    payload.update(overrides)
    return payload


def enforcement_payload(
    action: str, expected_operator_version: int, memo: Optional[str] = None, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "action": action,
        "expected_operator_version": expected_operator_version,
    }
    if memo is not None:
        payload["memo"] = memo
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Wells and production
# ---------------------------------------------------------------------------
def well_payload(
    operator_id: str, api_well_number: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "api_well_number": api_well_number or next_api_well_number(),
        "operator_id": operator_id,
    }
    payload.update(CANONICAL_WELL_INPUTS)
    payload.update(overrides)
    return payload


def production_payload(
    month: str, oil_bbl: float = 0.0, gas_mcf: float = 0.0, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "month": month,
        "oil_bbl": oil_bbl,
        "gas_mcf": gas_mcf,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Determinations
# ---------------------------------------------------------------------------
def determination_payload(
    expected_well_version: int,
    inspector_notes: str = "orphan candidate",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "inspector_notes": inspector_notes,
        "expected_well_version": expected_well_version,
    }
    payload.update(overrides)
    return payload


def determination_decision_payload(
    action: str, rationale: str = "criteria satisfied", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action, "rationale": rationale}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Site access
# ---------------------------------------------------------------------------
def site_access_payload(
    mode: str = "AGREEMENT",
    surface_owner_name: str = "Halvorsen Ranch",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "surface_owner_name": surface_owner_name,
        "mode": mode,
    }
    payload.update(overrides)
    return payload


def site_access_resolution_payload(
    outcome: str, legal_authority_citation: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome}
    if legal_authority_citation is not None:
        payload["legal_authority_citation"] = legal_authority_citation
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Transfers
# ---------------------------------------------------------------------------
def transfer_payload(to_operator_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_operator_id": to_operator_id}
    payload.update(overrides)
    return payload


def transfer_decision_payload(
    action: str, rationale: str = "operator change requested", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action, "rationale": rationale}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Contractors and procurement
# ---------------------------------------------------------------------------
def contractor_payload(
    name: str = "Bighorn Plugging",
    license_number: Optional[str] = None,
    bond_amount_cents: int = 2500000,
    performance_score: float = 89,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name,
        "license_number": license_number or next_license_number(),
        "bond_amount_cents": bond_amount_cents,
        "performance_score": performance_score,
    }
    payload.update(overrides)
    return payload


def eligibility_payload(
    action: str, reason: str = "expired insurance certificate", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action, "reason": reason}
    payload.update(overrides)
    return payload


def solicitation_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = dict(CANONICAL_SOLICITATION)
    payload.update(overrides)
    return payload


def lifecycle_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(overrides)
    return payload


def bid_payload(
    contractor_id: str,
    rates: Optional[Dict[str, int]] = None,
    technical_score: float = 92,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"contractor_id": contractor_id}
    payload.update(rates if rates is not None else CANONICAL_BID_RATES)
    payload["technical_score"] = technical_score
    payload.update(overrides)
    return payload


def bid_evaluation_payload(outcome: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Plugging jobs
# ---------------------------------------------------------------------------
def plugging_job_payload(
    well_id: str,
    contract_id: str,
    scheduled_start: str = "2026-08-05T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "well_id": well_id,
        "contract_id": contract_id,
        "scheduled_start": scheduled_start,
    }
    payload.update(CANONICAL_JOB_PLAN)
    payload.update(overrides)
    return payload


def field_report_payload(
    cement_sacks_used: int = 100,
    rig_days_used: int = 3,
    casing_removed_ft: int = 500,
    downhole_conditions: str = "cement circulated to surface",
    plug_intervals: Optional[List[Dict[str, int]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "cement_sacks_used": cement_sacks_used,
        "rig_days_used": rig_days_used,
        "casing_removed_ft": casing_removed_ft,
        "downhole_conditions": downhole_conditions,
        "plug_intervals": plug_intervals
        if plug_intervals is not None
        else [{"top_ft": 0, "bottom_ft": 500, "sacks": 100}],
    }
    payload.update(overrides)
    return payload


def job_review_payload(
    action: str, findings: str = "plugging documentation complete", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action, "findings": findings}
    payload.update(overrides)
    return payload


def task_progress_payload(
    action: str, notes: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    if notes is not None:
        payload["notes"] = notes
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Funding
# ---------------------------------------------------------------------------
def funding_source_payload(
    kind: str = "STATE_FUND",
    name: str = "Wyoming orphan well account",
    authorized_cents: int = 20000000,
    expires_at: str = "2027-12-31T00:00:00Z",
    allowable_cost_categories: Optional[List[str]] = None,
    federal_match_required_pct: Optional[int] = None,
    bond_operator_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "kind": kind,
        "name": name,
        "authorized_cents": authorized_cents,
        "expires_at": expires_at,
        "allowable_cost_categories": allowable_cost_categories
        if allowable_cost_categories is not None
        else ["PLUGGING"],
    }
    if federal_match_required_pct is not None:
        payload["federal_match_required_pct"] = federal_match_required_pct
    if bond_operator_id is not None:
        payload["bond_operator_id"] = bond_operator_id
    payload.update(overrides)
    return payload


def allocation_transition_payload(
    action: str, invoice_cents: Optional[int] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    if invoice_cents is not None:
        payload["invoice_cents"] = invoice_cents
    payload.update(overrides)
    return payload


def grant_report_payload(
    period_start: str, period_end: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "period_start": period_start,
        "period_end": period_end,
    }
    payload.update(overrides)
    return payload


def grant_report_submission_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(overrides)
    return payload
