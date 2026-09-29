"""Request-payload builders.

Each builder returns the minimum body the PRD declares as required for its
endpoint and lets the caller override or extend it with keyword arguments.
Optional fields are deliberately *omitted* rather than defaulted, so a test
that wants to observe a PRD-declared default gets it from the server.
"""

from typing import Any, Dict, List, Optional

from .constants import (
    ALL_DIMENSIONS,
    JULY_END,
    JULY_START,
)

JsonDict = Dict[str, Any]


def _with_overrides(payload: JsonDict, overrides: JsonDict) -> JsonDict:
    payload.update(overrides)
    return payload


# ─── Business units (PRD §3.1) ────────────────────────────────────────────
def business_unit_payload(
    name: str = "Ops",
    cost_center_code: str = "CC-400",
    **overrides: Any,
) -> JsonDict:
    return _with_overrides({"name": name, "cost_center_code": cost_center_code}, overrides)


# ─── Tagging policies (PRD §3.2) ──────────────────────────────────────────
def tagging_policy_payload(
    name: str = "Std",
    mandatory_dimensions: Optional[List[str]] = None,
    **overrides: Any,
) -> JsonDict:
    return _with_overrides(
        {
            "name": name,
            "mandatory_dimensions": (
                list(ALL_DIMENSIONS) if mandatory_dimensions is None else list(mandatory_dimensions)
            ),
        },
        overrides,
    )


# ─── Provisioning requests (PRD §3.3) ─────────────────────────────────────
def provisioning_request_payload(
    tagging_policy_id: str,
    business_unit_id: str,
    owner_user_id: str,
    resource_kind: str = "COMPUTE",
    requested_tags: Optional[Dict[str, str]] = None,
    monthly_run_rate_cents: int = 10000,
    **overrides: Any,
) -> JsonDict:
    return _with_overrides(
        {
            "tagging_policy_id": tagging_policy_id,
            "business_unit_id": business_unit_id,
            "resource_kind": resource_kind,
            "requested_tags": (
                {"team": "ops", "environment": "dev", "application": "api"}
                if requested_tags is None
                else dict(requested_tags)
            ),
            "monthly_run_rate_cents": monthly_run_rate_cents,
            "owner_user_id": owner_user_id,
        },
        overrides,
    )


# ─── Cost records (PRD §3.4) ──────────────────────────────────────────────
def cost_record_payload(
    list_cost_cents: int,
    resource_kind: str = "STORAGE",
    billing_period_start: str = JULY_START,
    billing_period_end: str = JULY_END,
    cloud_resource_id: Optional[str] = None,
    **overrides: Any,
) -> JsonDict:
    payload: JsonDict = {
        "billing_period_start": billing_period_start,
        "billing_period_end": billing_period_end,
        "resource_kind": resource_kind,
        "list_cost_cents": list_cost_cents,
    }
    if cloud_resource_id is not None:
        payload["cloud_resource_id"] = cloud_resource_id
    return _with_overrides(payload, overrides)


# ─── Commitments (PRD §3.4) ───────────────────────────────────────────────
def commitment_payload(
    commitment_type: str = "RESERVED_INSTANCE",
    region: str = "us-east-1",
    term_start: str = JULY_START,
    term_end: str = JULY_END,
    hourly_commit_cents: int = 50,
    covered_resource_kind: Optional[str] = "COMPUTE",
    **overrides: Any,
) -> JsonDict:
    payload: JsonDict = {
        "commitment_type": commitment_type,
        "region": region,
        "term_start": term_start,
        "term_end": term_end,
        "hourly_commit_cents": hourly_commit_cents,
    }
    if covered_resource_kind is not None:
        payload["covered_resource_kind"] = covered_resource_kind
    return _with_overrides(payload, overrides)


# ─── Allocation runs and pools (PRD §3.5) ─────────────────────────────────
def allocation_run_payload(
    mode: str = "SHOWBACK",
    period_start: str = JULY_START,
    period_end: str = JULY_END,
    scope_business_unit_id: Optional[str] = None,
    **overrides: Any,
) -> JsonDict:
    payload: JsonDict = {
        "mode": mode,
        "period_start": period_start,
        "period_end": period_end,
    }
    if scope_business_unit_id is not None:
        payload["scope_business_unit_id"] = scope_business_unit_id
    return _with_overrides(payload, overrides)


def shared_cost_pool_payload(
    participant_business_unit_ids: List[str],
    name: str = "Untagged Storage",
    methodology: str = "EVEN_SPLIT",
    proportional_basis: Optional[str] = None,
    **overrides: Any,
) -> JsonDict:
    payload: JsonDict = {
        "name": name,
        "methodology": methodology,
        "participant_business_unit_ids": list(participant_business_unit_ids),
    }
    if proportional_basis is not None:
        payload["proportional_basis"] = proportional_basis
    return _with_overrides(payload, overrides)


def manual_adjustment_payload(
    expected_allocation_run_version: int,
    business_unit_id: str,
    allocated_cents: int,
    memo: str = "true-up",
    **overrides: Any,
) -> JsonDict:
    return _with_overrides(
        {
            "expected_allocation_run_version": expected_allocation_run_version,
            "business_unit_id": business_unit_id,
            "allocated_cents": allocated_cents,
            "memo": memo,
        },
        overrides,
    )


# ─── Disputes (PRD §3.7) ──────────────────────────────────────────────────
def dispute_payload(
    chargeback_invoice_id: str,
    reason_code: str = "UNTAGGED_ABSORPTION",
    claimed_credit_cents: int = 1000,
    narrative: str = "not our storage",
    **overrides: Any,
) -> JsonDict:
    return _with_overrides(
        {
            "chargeback_invoice_id": chargeback_invoice_id,
            "reason_code": reason_code,
            "claimed_credit_cents": claimed_credit_cents,
            "narrative": narrative,
        },
        overrides,
    )


def dispute_resolution_payload(
    outcome: str, granted_credit_cents: int = 0, **overrides: Any
) -> JsonDict:
    return _with_overrides(
        {"outcome": outcome, "granted_credit_cents": granted_credit_cents}, overrides
    )


# ─── Budgets (PRD §3.9) ───────────────────────────────────────────────────
def budget_payload(
    business_unit_id: str,
    amount_cents: int = 10000,
    forecast_cents: int = 9000,
    period_start: str = JULY_START,
    period_end: str = JULY_END,
    accuracy_basis: Optional[str] = None,
    **overrides: Any,
) -> JsonDict:
    payload: JsonDict = {
        "business_unit_id": business_unit_id,
        "period_start": period_start,
        "period_end": period_end,
        "amount_cents": amount_cents,
        "forecast_cents": forecast_cents,
    }
    if accuracy_basis is not None:
        payload["accuracy_basis"] = accuracy_basis
    return _with_overrides(payload, overrides)


# ─── Unit economics (PRD §3.9) ────────────────────────────────────────────
def unit_economics_driver_payload(
    business_unit_id: str,
    allocation_run_id: str,
    driver_name: str = "ORDERS",
    driver_volume: int = 1,
    **overrides: Any,
) -> JsonDict:
    return _with_overrides(
        {
            "business_unit_id": business_unit_id,
            "allocation_run_id": allocation_run_id,
            "driver_name": driver_name,
            "driver_volume": driver_volume,
        },
        overrides,
    )


# ─── Remediation (PRD §3.8) ───────────────────────────────────────────────
def remediation_task_payload(
    cloud_resource_id: str, kind: str = "IDLE_TERMINATE", **overrides: Any
) -> JsonDict:
    return _with_overrides({"cloud_resource_id": cloud_resource_id, "kind": kind}, overrides)
