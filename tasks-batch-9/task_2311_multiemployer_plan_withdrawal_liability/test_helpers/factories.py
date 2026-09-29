"""Request-payload builders.

Each factory produces a valid body for one endpoint using only the fields that
endpoint accepts as input, with keyword overrides for the field under test.
Values that must be unique across a run (employer identification numbers) are
generated from a per-process counter.
"""

import itertools
from typing import Any, Dict, Optional

from .constants import (
    BASELINE_ALL_EMPLOYER_CBU,
    BASELINE_ALL_EMPLOYER_CONTRIBUTIONS_CENTS,
    BASELINE_CESSATION_DATE,
    BASELINE_CONTRIBUTION_CENTS,
    BASELINE_CONTRIBUTION_CBU,
    BASELINE_CONTRIBUTION_RATE_CENTS_PER_CBU,
    BASELINE_INTEREST_RATE_BPS,
    BASELINE_UVB_POOL_CENTS,
    BASELINE_UVB_TOTAL_CENTS,
    BASELINE_WITHDRAWAL_PLAN_YEAR,
)
from .types import (
    AllocationMethod,
    CommonControlBasis,
    CoveredWorkStatus,
    DeMinimisVariant,
    Industry,
    PaymentScheduleSource,
    ReportedCause,
)

_ein_counter = itertools.count(1)
_name_counter = itertools.count(1)


def next_ein() -> str:
    """An employer identification number of exactly nine digits, unique per run."""
    return "41{:07d}".format(next(_ein_counter))


def plan_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": f"Regional Pension Fund {next(_name_counter)}",
        "industry": Industry.GENERAL.value,
        "allocation_method": AllocationMethod.MODIFIED_PRESUMPTIVE.value,
        "de_minimis_variant": DeMinimisVariant.STATUTORY.value,
        "interest_rate_bps": BASELINE_INTEREST_RATE_BPS,
        "unattributable_uvb_cents": 0,
        "mass_withdrawal_declared": False,
    }
    payload.update(overrides)
    return payload


def controlled_group_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": f"Holdings Group {next(_name_counter)}",
        "common_control_basis": CommonControlBasis.PARENT_SUBSIDIARY.value,
    }
    payload.update(overrides)
    return payload


def employer_payload(plan_id: str, controlled_group_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "plan_id": plan_id,
        "controlled_group_id": controlled_group_id,
        "legal_name": f"Contributing Employer {next(_name_counter)}",
        "ein": next_ein(),
        "obligation_start_year": 2010,
        "covered_work_status": CoveredWorkStatus.PERFORMING.value,
        "cba_count": 2,
        "directly_attributed_vested_benefits_cents": 0,
        "directly_attributed_assets_cents": 0,
    }
    payload.update(overrides)
    return payload


def valuation_payload(plan_id: str, plan_year: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "plan_id": plan_id,
        "plan_year": plan_year,
        # Windows of the same plan must stay thirty days clear of each other, so
        # each plan year's window closes on 1 October.
        "measurement_window_start": f"{plan_year}-01-01T00:00:00Z",
        "measurement_window_end": f"{plan_year}-10-01T00:00:00Z",
        "uvb_total_cents": BASELINE_UVB_TOTAL_CENTS,
        "uvb_pool_cents": BASELINE_UVB_POOL_CENTS,
        "all_employer_contributions_cents": BASELINE_ALL_EMPLOYER_CONTRIBUTIONS_CENTS,
        "all_employer_cbu": BASELINE_ALL_EMPLOYER_CBU,
        "interest_rate_bps": BASELINE_INTEREST_RATE_BPS,
        "certify_on_create": True,
    }
    payload.update(overrides)
    return payload


def contribution_record_payload(
    employer_id: str,
    plan_year_start: int,
    plan_year_end: int,
    expected_employer_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "employer_id": employer_id,
        "plan_year_start": plan_year_start,
        "plan_year_end": plan_year_end,
        "contribution_base_units": BASELINE_CONTRIBUTION_CBU,
        "contribution_amount_cents": BASELINE_CONTRIBUTION_CENTS,
        "contribution_rate_cents_per_cbu": BASELINE_CONTRIBUTION_RATE_CENTS_PER_CBU,
        "expected_employer_version": expected_employer_version,
    }
    payload.update(overrides)
    return payload


def withdrawal_event_payload(employer_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "employer_id": employer_id,
        "cessation_date": BASELINE_CESSATION_DATE,
        "withdrawal_plan_year": BASELINE_WITHDRAWAL_PLAN_YEAR,
        "reported_cause": ReportedCause.CONTRIBUTION_OBLIGATION_CEASED.value,
        "ceased_cba_count": 0,
    }
    payload.update(overrides)
    return payload


def liability_assessment_payload(withdrawal_event_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"withdrawal_event_id": withdrawal_event_id}
    payload.update(overrides)
    return payload


def payment_schedule_payload(
    liability_assessment_id: str,
    expected_assessment_version: int,
    source: str = PaymentScheduleSource.REVIEW_DECISION.value,
    override_net_assessed_cents: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "liability_assessment_id": liability_assessment_id,
        "expected_assessment_version": expected_assessment_version,
        "source": source,
    }
    if override_net_assessed_cents is not None:
        payload["override_net_assessed_cents"] = override_net_assessed_cents
    payload.update(overrides)
    return payload


def payment_payload(payment_amount_cents: int) -> Dict[str, Any]:
    return {"payment_amount_cents": payment_amount_cents}


def review_request_payload(liability_assessment_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "liability_assessment_id": liability_assessment_id,
        "grounds_summary": "The allocated share overstates the employer's contribution history.",
    }
    payload.update(overrides)
    return payload


def review_decision_payload(
    decision: str,
    assumption_ruling: str,
    recomputed_net_assessed_cents: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "decision": decision,
        "assumption_ruling": assumption_ruling,
    }
    if recomputed_net_assessed_cents is not None:
        payload["recomputed_net_assessed_cents"] = recomputed_net_assessed_cents
    payload.update(overrides)
    return payload


def arbitration_payload(
    liability_assessment_id: str, review_request_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "liability_assessment_id": liability_assessment_id,
        "review_request_id": review_request_id,
    }
    payload.update(overrides)
    return payload


def arbitration_advance_payload(to_status: str) -> Dict[str, Any]:
    return {"to_status": to_status}


def arbitration_award_payload(
    award_outcome: str,
    assumption_ruling: str,
    awarded_net_assessed_cents: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "award_outcome": award_outcome,
        "assumption_ruling": assumption_ruling,
    }
    if awarded_net_assessed_cents is not None:
        payload["awarded_net_assessed_cents"] = awarded_net_assessed_cents
    payload.update(overrides)
    return payload


def asset_sale_payload(
    seller_employer_id: str, buyer_controlled_group_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "seller_employer_id": seller_employer_id,
        "buyer_controlled_group_id": buyer_controlled_group_id,
        "closing_date": "2026-07-01T00:00:00Z",
        "closing_plan_year": 2026,
        "purchase_price_cents": 1_000_000_000,
        "bond_amount_cents": 0,
        "buyer_assumes_contribution_obligation": False,
        "workforce_continuity_pct": 0.0,
        "asset_continuity_pct": 0.0,
        "customer_continuity_pct": 0.0,
    }
    payload.update(overrides)
    return payload


def adjudication_payload(disposition: str) -> Dict[str, Any]:
    return {"disposition": disposition}


def collection_sweep_payload(plan_id: str) -> Dict[str, Any]:
    return {"plan_id": plan_id}


def clock_payload(to_iso8601: str) -> Dict[str, Any]:
    return {"to_iso8601": to_iso8601}
