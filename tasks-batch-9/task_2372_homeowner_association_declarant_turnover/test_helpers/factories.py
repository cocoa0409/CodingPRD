"""Request payload builders.

Each builder returns a payload that satisfies the PRD's request-shape rules
(§2.7 rung 6) with neutral defaults, so a test only has to name the fields the
scenario under test actually cares about. ``**overrides`` is merged last; pass
``None`` for a key to drop it from the payload entirely, which is how the
"required field missing" cases are expressed.
"""

from typing import Any, Dict

from .constants import (
    CLAIM_ACTION_RESERVE,
    CONTRACT_ACTION_REQUEST_ASSIGNMENT,
    DIMENSION_FINANCIAL,
    FUNDING_METHOD_COMPONENT_FULL_FUNDING,
    MILESTONE_BUILD_COMPLETE,
    RECORDS_ACTION_DELIVER,
    RECORDS_CATEGORIES,
    SEAT_TYPE_DECLARANT_APPOINTED,
    STUDY_ACTION_RECOMPUTE,
    TRIGGER_BASIS_PERCENT_SOLD,
)


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides, dropping any key whose override value is ``None``."""
    payload = dict(base)
    for key, value in overrides.items():
        if value is None:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


# ─── Associations (§3.1) ──────────────────────────────


def association_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "name": "Wisteria Park Homeowners Association",
            "total_planned_lots": 10,
            "turnover_threshold_pct": 75.00,
            "fixed_turnover_date": "2027-01-01",
            "statute_of_repose_years": 5,
            "reserve_pool_cents": 1000000,
            "reserve_claim_pool_cents": 3000000,
            "declarant_monthly_subsidy_cents": 100000,
        },
        overrides,
    )


# ─── Turnover cases (§3.1) ────────────────────────────


def turnover_case_payload(association_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {"association_id": association_id, "total_seats": 5},
        overrides,
    )


def certify_trigger_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"trigger_basis": TRIGGER_BASIS_PERCENT_SOLD}, overrides)


def advance_payload(dimension: str = DIMENSION_FINANCIAL, **overrides: Any) -> Dict[str, Any]:
    return _merge({"dimension": dimension}, overrides)


# ─── Lots (§3.1) ──────────────────────────────────────


def lot_payload(association_id: str, lot_number: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {"association_id": association_id, "lot_number": lot_number},
        overrides,
    )


def close_sale_payload(closing_date: str = "2026-06-15", **overrides: Any) -> Dict[str, Any]:
    return _merge({"closing_date": closing_date}, overrides)


# ─── Components (§3.2) ────────────────────────────────


def component_payload(association_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "association_id": association_id,
            "name": "Clubhouse",
            "category": "STRUCTURE",
            "replacement_cost_cents": 5000000,
            "useful_life_years": 25,
            "effective_age_years": 5,
            "promised_completion_date": "2027-06-30",
        },
        overrides,
    )


def milestone_payload(
    milestone: str = MILESTONE_BUILD_COMPLETE, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"milestone": milestone}
    if milestone == MILESTONE_BUILD_COMPLETE:
        payload["effective_date"] = "2026-01-15T00:00:00Z"
    return _merge(payload, overrides)


# ─── Records transfer items (§3.5) ────────────────────


def records_item_payload(
    turnover_case_id: str, category: str = RECORDS_CATEGORIES[0], **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {"turnover_case_id": turnover_case_id, "category": category},
        overrides,
    )


def records_transition_payload(
    action: str = RECORDS_ACTION_DELIVER, **overrides: Any
) -> Dict[str, Any]:
    return _merge({"action": action}, overrides)


# ─── Directors (§3.4) ─────────────────────────────────


def director_payload(
    turnover_case_id: str,
    seat_type: str = SEAT_TYPE_DECLARANT_APPOINTED,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "turnover_case_id": turnover_case_id,
            "full_name": "Dana Whitfield",
            "seat_type": seat_type,
        },
        overrides,
    )


# ─── Subsidy ledger (§3.6) ────────────────────────────


def subsidy_entry_payload(
    association_id: str,
    direction: str = "ACCRUAL",
    amount_cents: int = 100000,
    period_month: str = "2026-03",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "association_id": association_id,
            "direction": direction,
            "amount_cents": amount_cents,
            "period_month": period_month,
        },
        overrides,
    )


def reversal_payload(reason: str = "Duplicate posting", **overrides: Any) -> Dict[str, Any]:
    return _merge({"reason": reason}, overrides)


# ─── Audit engagements (§3.6) ─────────────────────────


def audit_engagement_payload(
    association_id: str,
    period_start: str = "2026-01-01",
    period_end: str = "2026-03-31",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "association_id": association_id,
            "period_start": period_start,
            "period_end": period_end,
        },
        overrides,
    )


# ─── Reserve studies (§3.7) ───────────────────────────


def reserve_study_payload(
    association_id: str,
    funding_method: str = FUNDING_METHOD_COMPONENT_FULL_FUNDING,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "association_id": association_id,
            "funding_method": funding_method,
            "planned_annual_contribution_cents": 200000,
            "projected_annual_expenditure_cents": 200000,
        },
        overrides,
    )


def study_action_payload(
    action: str = STUDY_ACTION_RECOMPUTE, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    if action == STUDY_ACTION_RECOMPUTE:
        payload["method"] = FUNDING_METHOD_COMPONENT_FULL_FUNDING
    return _merge(payload, overrides)


# ─── Defect claims (§3.8) ─────────────────────────────


def defect_claim_payload(
    association_id: str, component_id: str, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "association_id": association_id,
            "component_id": component_id,
            "defect_summary": "Stucco delamination along the north elevation",
            "repair_cost_estimate_cents": 1500000,
            "diminution_value_cents": 850000,
        },
        overrides,
    )


def claim_action_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    if action == CLAIM_ACTION_RESERVE:
        payload["valuation_basis"] = "REPAIR_COST"
    return _merge(payload, overrides)


# ─── Vendor contracts (§3.5) ──────────────────────────


def vendor_contract_payload(
    association_id: str, component_id: str, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "association_id": association_id,
            "component_id": component_id,
            "vendor_name": "Meridian Grounds Care",
            "developer_affiliated": False,
            "annual_cost_cents": 480000,
            "service_window_start": "2026-01-01",
            "service_window_end": "2027-01-01",
        },
        overrides,
    )


def contract_action_payload(
    action: str = CONTRACT_ACTION_REQUEST_ASSIGNMENT, **overrides: Any
) -> Dict[str, Any]:
    return _merge({"action": action}, overrides)


# ─── Assessment schedules (§3.9) ──────────────────────


def assessment_schedule_payload(
    association_id: str,
    expected_association_version: int,
    fiscal_year: int = 2027,
    projected_operating_cost_cents: int = 4000000,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "association_id": association_id,
            "fiscal_year": fiscal_year,
            "projected_operating_cost_cents": projected_operating_cost_cents,
            "expected_association_version": expected_association_version,
        },
        overrides,
    )
