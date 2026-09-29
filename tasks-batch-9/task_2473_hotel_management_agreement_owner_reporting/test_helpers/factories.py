"""Request-payload builders.

Every builder returns a plain dict using the contract's field names, with
sensible values for the required fields and ``**overrides`` for everything a
test wants to pin. Optional fields are only present when supplied, so a
builder can also be used to probe a missing-field rejection by popping a key.
"""

from typing import Any, Dict, Optional

from .constants import (
    AllocationBasis,
    BenchmarkSource,
    BudgetDecision,
    CallReason,
    ChargeReviewAction,
    ClaimAction,
    CureAction,
    DisputeAction,
    PositionClass,
    ReviewDecision,
    ReviewDimension,
    ServiceCode,
    VarianceCategory,
    VarianceDecision,
)


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(base)
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Agreements
# ---------------------------------------------------------------------------


def agreement_payload(**overrides: Any) -> Dict[str, Any]:
    """A minimal registration body: only the five fields with no declared default."""
    return _merge(
        {
            "hotel_name": "Test Hotel",
            "owner_entity_name": "Test Owner Holdings LLC",
            "base_fee_pct": 0.03,
            "incentive_fee_pct": 0.10,
            "owner_priority_cents": 12000000,
        },
        overrides,
    )


def expert_agreement_payload(**overrides: Any) -> Dict[str, Any]:
    """The fully specified configuration used by the multi-hop scenarios.

    base_fee_pct 0.0325 over three revenue lines, a 12,000,000 owner priority,
    a two-tier incentive, a funded working capital floor and short review,
    revision, benchmark, period and dispute-round windows.
    """
    return _merge(
        {
            "hotel_name": "Expert Configuration Hotel",
            "owner_entity_name": "Expert Owner Holdings LLC",
            "base_fee_pct": 0.0325,
            "incentive_fee_pct": 0.10,
            "incentive_tier2_pct": 0.15,
            "incentive_tier2_threshold_cents": 5000000,
            "owner_priority_cents": 12000000,
            "ffe_reserve_pct": 0.04,
            "centralized_services_cap_pct": 0.015,
            "working_capital_floor_cents": 500000,
            "initial_working_capital_cents": 1000000,
            "owner_review_window_days": 30,
            "max_revision_rounds": 1,
            "manager_indemnity_cap_cents": 2000000,
            "min_benchmark_months": 2,
            "test_periods_expected": 3,
            "max_dispute_rounds": 1,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Budgets and variances
# ---------------------------------------------------------------------------


def budget_payload(expected_agreement_version: int, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "fiscal_year": 2026,
            "budgeted_revenue_cents": 300000000,
            "budgeted_operating_expenses_cents": 200000000,
            "budgeted_capital_ffe_cents": 4000000,
            "budgeted_capital_brand_cents": 2000000,
            "expected_agreement_version": expected_agreement_version,
        },
        overrides,
    )


def budget_submit_payload(**overrides: Any) -> Dict[str, Any]:
    """A bare submit; pass revised amounts as overrides to restate the budget."""
    return dict(overrides)


def budget_decision_payload(decision: str = BudgetDecision.APPROVE, **overrides: Any) -> Dict[str, Any]:
    return _merge({"decision": decision}, overrides)


def variance_payload(
    category: str = VarianceCategory.OPERATING,
    requested_amount_cents: int = 1000000,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "category": category,
            "requested_amount_cents": requested_amount_cents,
            "justification": "Unbudgeted repair to the chiller plant.",
        },
        overrides,
    )


def variance_decision_payload(decision: str = VarianceDecision.APPROVE, **overrides: Any) -> Dict[str, Any]:
    return _merge({"decision": decision}, overrides)


# ---------------------------------------------------------------------------
# Report packages, benchmarks, charges
# ---------------------------------------------------------------------------


def package_payload(
    fiscal_year: int = 2026,
    period_month: int = 9,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "fiscal_year": fiscal_year,
            "period_month": period_month,
            "rooms_revenue_cents": 20000000,
            "fnb_revenue_cents": 5000000,
            "other_revenue_cents": 1000000,
            "operating_expenses_cents": 5000000,
            "closing_cash_available_cents": 0,
        },
        overrides,
    )


def expert_package_payload(
    fiscal_year: int = 2026,
    period_month: int = 9,
    **overrides: Any,
) -> Dict[str, Any]:
    """Three revenue lines that each round independently at 0.0325."""
    return _merge(
        {
            "fiscal_year": fiscal_year,
            "period_month": period_month,
            "rooms_revenue_cents": 40000015,
            "fnb_revenue_cents": 12000005,
            "other_revenue_cents": 3000005,
            "operating_expenses_cents": 30000000,
            "closing_cash_available_cents": 6000000,
        },
        overrides,
    )


def benchmark_payload(
    hotel_revpar_cents: int = 10000,
    comp_set_revpar_cents: int = 12000,
    rooms_available: int = 3000,
    source: str = BenchmarkSource.STR_REPORT,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "hotel_revpar_cents": hotel_revpar_cents,
            "comp_set_revpar_cents": comp_set_revpar_cents,
            "rooms_available": rooms_available,
            "source": source,
        },
        overrides,
    )


def charge_payload(
    service_code: str = ServiceCode.RESERVATIONS,
    pool_amount_cents: int = 10000000,
    hotel_basis_share: float = 0.05,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "service_code": service_code,
            "allocation_basis": AllocationBasis.ROOMS_AVAILABLE,
            "pool_amount_cents": pool_amount_cents,
            "hotel_basis_share": hotel_basis_share,
            "allow_deferral": False,
            "supporting_detail_provided": False,
        },
        overrides,
    )


def charge_review_payload(
    action: str,
    adjusted_amount_cents: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    if adjusted_amount_cents is not None:
        payload["adjusted_amount_cents"] = adjusted_amount_cents
    payload.update(overrides)
    return payload


def contest_payload(**overrides: Any) -> Dict[str, Any]:
    return charge_review_payload(ChargeReviewAction.CONTEST, **overrides)


def reaffirm_payload(**overrides: Any) -> Dict[str, Any]:
    return charge_review_payload(ChargeReviewAction.REAFFIRM, **overrides)


def adjust_payload(adjusted_amount_cents: int, **overrides: Any) -> Dict[str, Any]:
    return charge_review_payload(
        ChargeReviewAction.ADJUST, adjusted_amount_cents=adjusted_amount_cents, **overrides
    )


def owner_review_payload(
    dimension: str = ReviewDimension.FINANCIAL,
    decision: str = ReviewDecision.ACCEPT,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge({"dimension": dimension, "decision": decision}, overrides)


# ---------------------------------------------------------------------------
# Working capital, true-up, performance tests
# ---------------------------------------------------------------------------


def working_capital_call_payload(
    amount_cents: int = 500000,
    reason: str = CallReason.FLOOR_RESTORATION,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge({"amount_cents": amount_cents, "reason": reason}, overrides)


def fund_payload(funded_amount_cents: int, **overrides: Any) -> Dict[str, Any]:
    return _merge({"funded_amount_cents": funded_amount_cents}, overrides)


def true_up_payload(expected_agreement_version: int, fiscal_year: int = 2026, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "fiscal_year": fiscal_year,
            "expected_agreement_version": expected_agreement_version,
        },
        overrides,
    )


def performance_test_payload(fiscal_year: int = 2026, **overrides: Any) -> Dict[str, Any]:
    return _merge({"fiscal_year": fiscal_year}, overrides)


def cure_payload(action: str, payment_amount_cents: Optional[int] = None, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    if payment_amount_cents is not None:
        payload["payment_amount_cents"] = payment_amount_cents
    payload.update(overrides)
    return payload


def elect_cure_payload(**overrides: Any) -> Dict[str, Any]:
    return cure_payload(CureAction.ELECT_CURE, **overrides)


def pay_cure_payload(payment_amount_cents: int, **overrides: Any) -> Dict[str, Any]:
    return cure_payload(CureAction.PAY_CURE, payment_amount_cents=payment_amount_cents, **overrides)


def terminate_payload(**overrides: Any) -> Dict[str, Any]:
    return dict(overrides)


# ---------------------------------------------------------------------------
# Brand disputes and employment claims
# ---------------------------------------------------------------------------


def brand_dispute_payload(
    franchise_requirement_ref: str = "BSR-2026-014",
    estimated_cost_cents: int = 1500000,
    remediation_start_utc: str = "2026-09-01T00:00:00Z",
    remediation_deadline_utc: str = "2026-12-01T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "franchise_requirement_ref": franchise_requirement_ref,
            "estimated_cost_cents": estimated_cost_cents,
            "remediation_start_utc": remediation_start_utc,
            "remediation_deadline_utc": remediation_deadline_utc,
        },
        overrides,
    )


def dispute_round_payload(
    action: str,
    cost_estimate_cents: Optional[int] = None,
    funding_source: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    if cost_estimate_cents is not None:
        payload["cost_estimate_cents"] = cost_estimate_cents
    if funding_source is not None:
        payload["funding_source"] = funding_source
    payload.update(overrides)
    return payload


def manager_response_payload(cost_estimate_cents: int, **overrides: Any) -> Dict[str, Any]:
    return dispute_round_payload(
        DisputeAction.MANAGER_RESPONSE, cost_estimate_cents=cost_estimate_cents, **overrides
    )


def owner_counter_payload(cost_estimate_cents: int, **overrides: Any) -> Dict[str, Any]:
    return dispute_round_payload(
        DisputeAction.OWNER_COUNTER, cost_estimate_cents=cost_estimate_cents, **overrides
    )


def escalate_payload(**overrides: Any) -> Dict[str, Any]:
    return dispute_round_payload(DisputeAction.ESCALATE_TO_FRANCHISOR, **overrides)


def resolve_owner_funds_payload(funding_source: str, **overrides: Any) -> Dict[str, Any]:
    return dispute_round_payload(
        DisputeAction.RESOLVE_OWNER_FUNDS, funding_source=funding_source, **overrides
    )


def resolve_waived_payload(**overrides: Any) -> Dict[str, Any]:
    return dispute_round_payload(DisputeAction.RESOLVE_WAIVED, **overrides)


def rescind_payload(**overrides: Any) -> Dict[str, Any]:
    return dispute_round_payload(DisputeAction.RESCIND_RESOLUTION, **overrides)


def employment_claim_payload(
    position_class: str = PositionClass.GM,
    claim_amount_cents: int = 3000001,
    gross_negligence: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "position_class": position_class,
            "claim_amount_cents": claim_amount_cents,
            "gross_negligence": gross_negligence,
        },
        overrides,
    )


def claim_allocation_payload(action: str = ClaimAction.ALLOCATE, **overrides: Any) -> Dict[str, Any]:
    return _merge({"action": action}, overrides)


__all__ = [
    "adjust_payload",
    "agreement_payload",
    "benchmark_payload",
    "brand_dispute_payload",
    "budget_decision_payload",
    "budget_payload",
    "budget_submit_payload",
    "charge_payload",
    "charge_review_payload",
    "claim_allocation_payload",
    "contest_payload",
    "cure_payload",
    "dispute_round_payload",
    "elect_cure_payload",
    "employment_claim_payload",
    "escalate_payload",
    "expert_agreement_payload",
    "expert_package_payload",
    "fund_payload",
    "manager_response_payload",
    "owner_counter_payload",
    "owner_review_payload",
    "package_payload",
    "pay_cure_payload",
    "performance_test_payload",
    "reaffirm_payload",
    "rescind_payload",
    "resolve_owner_funds_payload",
    "resolve_waived_payload",
    "terminate_payload",
    "true_up_payload",
    "variance_decision_payload",
    "variance_payload",
    "working_capital_call_payload",
]
