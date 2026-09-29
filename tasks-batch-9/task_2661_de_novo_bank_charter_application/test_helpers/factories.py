"""
Payload factories for the De Novo Bank Charter Application API.

Each factory returns a valid request body with sensible defaults that satisfy
every schema rule in the PRD, and accepts keyword overrides so a test can bend
exactly the one field it is about. Money is always emitted as a Python int
because PRD 2.5 requires integer cents on the wire, never a string and never a
decimal.
"""

from typing import Any, Dict, Optional

from .types import (
    AUTHORITY_CHARTERING,
    CATEGORY_CAPITAL,
    CHARTER_TYPE_NATIONAL,
    CRITICALITY_CRITICAL,
    DIMENSION_FINGERPRINT,
    DOMAIN_LENDING,
    EXAM_SCOPE_FULL,
    FINGERPRINT_CLEARED,
    FUNDING_EVENT_FUND,
    METRIC_ASSET_GROWTH,
    ROLE_ON_BOARD_DIRECTOR,
    SERVICE_CORE_PROCESSING,
)


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides, and drop any key whose override is the sentinel None-drop."""
    payload = dict(base)
    for key, value in overrides.items():
        if value is _DROP:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


class _Drop:
    """Sentinel: pass field=DROP to omit a field the factory would otherwise emit."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "DROP"


_DROP = _Drop()
DROP = _DROP


# ---------------------------------------------------------------------------
# OrganizingGroup (PRD 3.1)
# ---------------------------------------------------------------------------
def organizing_group_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "proposed_bank_name": "Cascade Charter Bank",
            "home_state_code": "WA",
            "charter_type": CHARTER_TYPE_NATIONAL,
            "target_opening_date": "2027-03-01T00:00:00Z",
        },
        overrides,
    )


def advance_payload(target_stage: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"target_stage": target_stage}, overrides)


# ---------------------------------------------------------------------------
# Organizer (PRD 3.1)
# ---------------------------------------------------------------------------
def organizer_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "full_name": "Theo Nakamura",
            "role_on_board": ROLE_ON_BOARD_DIRECTOR,
            "is_independent": True,
            "affiliation_code": "IND_C",
            "banking_years": 10,
            "regulatory_experience_score": 54,
        },
        overrides,
    )


def background_result_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {"dimension": DIMENSION_FINGERPRINT, "outcome": FINGERPRINT_CLEARED}, overrides
    )


def qualification_waiver_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "waiver_rationale": (
                "Examiner panel reviewed the full background file and accepted the "
                "compensating controls."
            )
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# BusinessPlan (PRD 3.2)
# ---------------------------------------------------------------------------
def business_plan_payload(group_id: str, expected_group_version: int, **overrides: Any):
    return _merge(
        {
            "group_id": group_id,
            "expected_group_version": expected_group_version,
            "opening_tier1_capital_cents": 4_000_000_000,
            "projected_assets_y1_cents": 25_000_000_000,
            "projected_assets_y2_cents": 34_000_000_000,
            "projected_assets_y3_cents": 43_000_000_000,
            "projected_loans_y1_cents": 15_000_000_000,
            "projected_loans_y2_cents": 21_000_000_000,
            "projected_loans_y3_cents": 28_000_000_000,
            "projected_deposits_y1_cents": 21_000_000_000,
            "projected_deposits_y2_cents": 29_000_000_000,
            "projected_deposits_y3_cents": 37_000_000_000,
            "projected_net_income_y1_cents": -250_000_000,
            "projected_net_income_y2_cents": 120_000_000,
            "projected_net_income_y3_cents": 460_000_000,
            "projected_branch_count": 3,
        },
        overrides,
    )


def stress_scenario_payload(scenario_code: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "scenario_code": scenario_code,
            "credit_loss_rate_bps": 60,
            "nim_compression_bps": 15,
            "expense_overrun_cents": 0,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# CapitalRaise and Subscription (PRD 3.4)
# ---------------------------------------------------------------------------
def capital_raise_payload(group_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "group_id": group_id,
            "target_gross_cents": 4_300_000_000,
            "minimum_gross_cents": 4_100_000_000,
            "offering_price_cents_per_share": 1000,
            "max_shares": 5_000_000,
            "organizational_expense_claim_cents": 150_000_000,
        },
        overrides,
    )


def subscription_payload(
    capital_raise_id: str,
    subscriber_name: str = "Harbor Trust LP",
    shares: int = 2_000_000,
    organizer_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "capital_raise_id": capital_raise_id,
        "subscriber_name": subscriber_name,
        "shares": shares,
    }
    if organizer_id is not None:
        payload["organizer_id"] = organizer_id
    return _merge(payload, overrides)


def funding_payload(funding_event: str = FUNDING_EVENT_FUND, **overrides: Any):
    return _merge({"funding_event": funding_event}, overrides)


def screening_payload(outcome: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"outcome": outcome}, overrides)


# ---------------------------------------------------------------------------
# RegulatoryFiling and ApprovalCondition (PRD 3.5, 3.6)
# ---------------------------------------------------------------------------
def regulatory_filing_payload(
    group_id: str,
    pinned_business_plan_id: str,
    authority: str = AUTHORITY_CHARTERING,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "group_id": group_id,
            "authority": authority,
            "pinned_business_plan_id": pinned_business_plan_id,
        },
        overrides,
    )


def filing_decision_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"decision": decision}, overrides)


def approval_condition_payload(
    condition_code: str = "CAP-01",
    category: str = CATEGORY_CAPITAL,
    is_pre_opening_blocking: bool = True,
    deadline_utc: str = "2026-12-01T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "condition_code": condition_code,
            "category": category,
            "is_pre_opening_blocking": is_pre_opening_blocking,
            "deadline_utc": deadline_utc,
        },
        overrides,
    )


def evidence_payload(
    evidence_reference: str = "BOARD-MIN-2026-09-14-CAPITAL-CERT", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"evidence_reference": evidence_reference}, overrides)


def adjudication_payload(disposition: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"disposition": disposition}, overrides)


# ---------------------------------------------------------------------------
# PolicyDocument, VendorContract and ConversionWindow (PRD 3.7)
# ---------------------------------------------------------------------------
def policy_document_payload(
    group_id: str,
    drafted_by_organizer_id: str,
    domain: str = DOMAIN_LENDING,
    document_title: str = "Credit and Lending Policy",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "group_id": group_id,
            "domain": domain,
            "drafted_by_organizer_id": drafted_by_organizer_id,
            "document_title": document_title,
        },
        overrides,
    )


def policy_review_payload(outcome: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"outcome": outcome}, overrides)


def vendor_contract_payload(
    group_id: str,
    service_domain: str = SERVICE_CORE_PROCESSING,
    vendor_name: str = "Meridian Core Systems",
    criticality: str = CRITICALITY_CRITICAL,
    due_diligence_score: int = 88,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "group_id": group_id,
            "service_domain": service_domain,
            "vendor_name": vendor_name,
            "annual_cost_cents": 90_000_000,
            "contract_term_months": 60,
            "due_diligence_score": due_diligence_score,
            "criticality": criticality,
        },
        overrides,
    )


def vendor_advance_payload(target_status: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"target_status": target_status}, overrides)


def conversion_window_payload(
    vendor_contract_id: str,
    expected_vendor_contract_version: int,
    window_start_utc: str = "2026-09-01T12:00:00Z",
    window_end_utc: str = "2026-09-02T12:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "vendor_contract_id": vendor_contract_id,
            "expected_vendor_contract_version": expected_vendor_contract_version,
            "window_start_utc": window_start_utc,
            "window_end_utc": window_end_utc,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# ReadinessExam and DeviationRequest (PRD 3.8, 3.9)
# ---------------------------------------------------------------------------
def readiness_exam_payload(
    window_start_utc: str = "2026-10-05T09:00:00Z",
    window_end_utc: str = "2026-10-07T17:00:00Z",
    exam_scope: str = EXAM_SCOPE_FULL,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "window_start_utc": window_start_utc,
            "window_end_utc": window_end_utc,
            "exam_scope": exam_scope,
        },
        overrides,
    )


def exam_result_payload(outcome: str, finding_count: int = 0, **overrides: Any):
    return _merge({"outcome": outcome, "finding_count": finding_count}, overrides)


def deviation_request_payload(
    group_id: str,
    baseline_plan_id: str,
    actual_value: int,
    metric: str = METRIC_ASSET_GROWTH,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "group_id": group_id,
            "baseline_plan_id": baseline_plan_id,
            "metric": metric,
            "actual_value": actual_value,
            "narrative": (
                "First-year balance sheet growth outran the pinned projection because "
                "commercial deposit inflows arrived ahead of schedule."
            ),
        },
        overrides,
    )


def deviation_decision_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"decision": decision}, overrides)
