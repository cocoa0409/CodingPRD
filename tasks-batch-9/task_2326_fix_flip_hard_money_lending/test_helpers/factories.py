"""Request-payload builders.

Each factory returns only the *input* fields the PRD declares for its endpoint;
server-minted, derived and status fields are never supplied. Every builder takes
`**overrides` so a test can vary exactly the one value it cares about, and a
value of ``None`` passed through overrides removes the key entirely (used to
exercise omitted-optional and missing-required behaviour).
"""

from typing import Any, Dict, List, Optional

from .types import (
    BorrowerAction,
    DayCountConvention,
    DrawDecision,
    EntityType,
    MilestoneType,
    PaymentIntent,
    ScopeCode,
    ScopeDecision,
    VerificationMethod,
    WaiverDisputeAction,
    WaiverType,
)

_REMOVE = "__remove__"


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(base)
    for key, value in overrides.items():
        if value is _REMOVE:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


def omit(*keys: str) -> Dict[str, Any]:
    """Sugar: ``factory(**omit("day_count_convention"))`` drops the key."""
    return {key: _REMOVE for key in keys}


# ---------------------------------------------------------------- clock
def clock_payload(to_iso8601: str = "2026-08-10T09:00:00Z", **overrides):
    return _merge({"to_iso8601": to_iso8601}, overrides)


# ---------------------------------------------------------------- borrower
def borrower_payload(**overrides) -> Dict[str, Any]:
    """A TIER_A sponsor: 40 experience + 20 credit + 20 liquidity + 12 career = 92.00."""
    return _merge(
        {
            "legal_entity_name": "Ridgeline Rehab LLC",
            "entity_type": EntityType.LLC.value,
            "guarantor_name": "D. Ruiz",
            "flips_last_24mo": 6,
            "flips_lifetime": 8,
            "credit_score": 760,
            "liquidity_cents": 30_000_000,
            "prior_default_count": 0,
            "declared_target_loan_cents": 30_000_000,
        },
        overrides,
    )


def guarantee_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "guarantor_name": "D. Ruiz",
            "signature_ref": "esign-b1",
            "effective_date": "2026-08-10",
        },
        overrides,
    )


def borrower_status_payload(action: str, **overrides) -> Dict[str, Any]:
    return _merge({"action": action}, overrides)


def approve_sponsor_payload(**overrides) -> Dict[str, Any]:
    return borrower_status_payload(BorrowerAction.APPROVE_SPONSOR.value, **overrides)


def recertify_payload(**overrides) -> Dict[str, Any]:
    return borrower_status_payload(BorrowerAction.RECERTIFY.value, **overrides)


def suspend_payload(**overrides) -> Dict[str, Any]:
    return borrower_status_payload(BorrowerAction.SUSPEND.value, **overrides)


def reinstate_payload(**overrides) -> Dict[str, Any]:
    return borrower_status_payload(BorrowerAction.REINSTATE.value, **overrides)


# ---------------------------------------------------------------- property
def property_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "address_line": "18 Larkspur Ct",
            "county_code": "MARICOPA",
            "purchase_price_cents": 20_000_000,
            "as_is_value_cents": 21_000_000,
            "arv_cents": 32_000_000,
            "appraisal_date": "2026-07-20",
        },
        overrides,
    )


def valuation_payload(**overrides) -> Dict[str, Any]:
    return _merge({"appraisal_date": "2026-09-15"}, overrides)


# ---------------------------------------------------------------- contractor
def contractor_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "business_name": "Vega Roofing",
            "license_number": "LIC-4471",
            "license_expires_on": "2027-12-31",
            "w9_on_file": True,
            "joint_check_required": False,
        },
        overrides,
    )


# ---------------------------------------------------------------- application
def application_payload(borrower_id: str, property_id: str, **overrides):
    return _merge(
        {
            "borrower_id": borrower_id,
            "property_id": property_id,
            "term_months": 9,
            "quoted_rate_bps": 1150,
            "interest_reserve_months": 6,
            "day_count_convention": DayCountConvention.PER_DIEM_360.value,
        },
        overrides,
    )


# ---------------------------------------------------------------- scope lines
def rehab_line_payload(
    scope_code: str = ScopeCode.ROOF.value,
    cost_cents: int = 4_000_000,
    contractor_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "scope_code": scope_code,
            "description": "Tear-off and re-deck",
            "cost_cents": cost_cents,
            "contractor_id": contractor_id,
        },
        overrides,
    )


def scope_review_payload(
    decision: str = ScopeDecision.APPROVE.value, **overrides
) -> Dict[str, Any]:
    return _merge({"decision": decision}, overrides)


def scope_approve_payload(approved_cost_cents: Optional[int] = None, **overrides):
    base: Dict[str, Any] = {"decision": ScopeDecision.APPROVE.value}
    if approved_cost_cents is not None:
        base["approved_cost_cents"] = approved_cost_cents
    return _merge(base, overrides)


def scope_request_revision_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "decision": ScopeDecision.REQUEST_REVISION.value,
            "reviewer_note": "Trim the allowance and resubmit",
        },
        overrides,
    )


def scope_reject_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "decision": ScopeDecision.REJECT.value,
            "reviewer_note": "Out of scope for this budget",
        },
        overrides,
    )


def scope_resubmit_payload(**overrides) -> Dict[str, Any]:
    return _merge({"cost_cents": 2_500_000}, overrides)


# ---------------------------------------------------------------- origination
def size_payload(**overrides) -> Dict[str, Any]:
    return _merge({}, overrides)


def decision_payload(decision: str = "APPROVE", **overrides) -> Dict[str, Any]:
    return _merge({"decision": decision}, overrides)


def decline_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {"decision": "DECLINE", "decline_reason": "Collateral outside credit box"},
        overrides,
    )


def close_payload(closing_date: str = "2026-08-10", **overrides) -> Dict[str, Any]:
    return _merge({"closing_date": closing_date}, overrides)


# ---------------------------------------------------------------- draws
def line_allocation(rehab_line_item_id: str, claimed_percent_complete: float):
    return {
        "rehab_line_item_id": rehab_line_item_id,
        "claimed_percent_complete": claimed_percent_complete,
    }


def draw_request_payload(
    line_allocations: List[Dict[str, Any]],
    expected_loan_version: int,
    verification_method: str = VerificationMethod.INSPECTION.value,
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "line_allocations": line_allocations,
            "verification_method": verification_method,
            "expected_loan_version": expected_loan_version,
        },
        overrides,
    )


def inspection_visit_payload(
    inspector_id: str,
    window_start: str = "2026-09-15T09:00:00Z",
    window_end: str = "2026-09-15T11:00:00Z",
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "inspector_id": inspector_id,
            "window_start": window_start,
            "window_end": window_end,
        },
        overrides,
    )


def line_verification(rehab_line_item_id: str, verified_percent_complete: float):
    return {
        "rehab_line_item_id": rehab_line_item_id,
        "verified_percent_complete": verified_percent_complete,
    }


def inspection_report_payload(
    line_verifications: List[Dict[str, Any]], **overrides
) -> Dict[str, Any]:
    return _merge(
        {
            "line_verifications": line_verifications,
            "site_notes": "Work observed on site",
        },
        overrides,
    )


def photo_verification_payload(
    line_verifications: List[Dict[str, Any]], photo_count: int, **overrides
) -> Dict[str, Any]:
    return _merge(
        {"line_verifications": line_verifications, "photo_count": photo_count},
        overrides,
    )


def draw_review_payload(
    decision: str = DrawDecision.APPROVE.value, **overrides
) -> Dict[str, Any]:
    return _merge({"decision": decision}, overrides)


def draw_fund_payload(
    funding_date: str = "2026-09-15", **overrides
) -> Dict[str, Any]:
    return _merge({"funding_date": funding_date}, overrides)


# ---------------------------------------------------------------- lien waivers
def lien_waiver_payload(
    loan_id: str,
    contractor_id: str,
    amount_covered_cents: int = 3_400_000,
    waiver_type: str = WaiverType.PARTIAL_UNCONDITIONAL.value,
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "loan_id": loan_id,
            "contractor_id": contractor_id,
            "waiver_type": waiver_type,
            "amount_covered_cents": amount_covered_cents,
            "through_date": "2026-09-15",
        },
        overrides,
    )


def waiver_dispute_payload(
    action: str = WaiverDisputeAction.DISPUTE.value, **overrides
) -> Dict[str, Any]:
    return _merge({"action": action}, overrides)


# ---------------------------------------------------------------- servicing
def accrual_payload(period_start: str, period_end: str, **overrides):
    return _merge({"period_start": period_start, "period_end": period_end}, overrides)


def payment_payload(
    amount_cents: int,
    payment_date: str = "2026-09-15",
    intent: str = PaymentIntent.REGULAR.value,
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "amount_cents": amount_cents,
            "payment_date": payment_date,
            "intent": intent,
        },
        overrides,
    )


def extension_payload(months: int = 1, **overrides) -> Dict[str, Any]:
    return _merge({"months": months}, overrides)


# ---------------------------------------------------------------- exit milestones
def milestone_payload(
    milestone_type: str, effective_date: str, **overrides
) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "milestone_type": milestone_type,
        "effective_date": effective_date,
    }
    if milestone_type in (MilestoneType.LISTED.value, MilestoneType.PRICE_REDUCED.value):
        base["listing_price_cents"] = 34_000_000
    if milestone_type.startswith("REFI_"):
        base["lender_name"] = "Summit Community Bank"
    return _merge(base, overrides)


# ---------------------------------------------------------------- default / recovery
def default_declaration_payload(**overrides) -> Dict[str, Any]:
    return _merge({"reason": "Interest shortfall aged past cure"}, overrides)


def foreclosure_case_payload(
    notice_date: str, county_code: str = "MARICOPA", **overrides
) -> Dict[str, Any]:
    return _merge({"notice_date": notice_date, "county_code": county_code}, overrides)


def takeover_payload(takeover_date: str, **overrides) -> Dict[str, Any]:
    return _merge({"takeover_date": takeover_date}, overrides)


def completion_budget_payload(
    budget_cents: int, expected_foreclosure_case_version: int, **overrides
) -> Dict[str, Any]:
    return _merge(
        {
            "budget_cents": budget_cents,
            "expected_foreclosure_case_version": expected_foreclosure_case_version,
        },
        overrides,
    )


def disposition_payload(
    sale_price_cents: int,
    sale_date: str,
    completion_spend_cents: int = 0,
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "sale_price_cents": sale_price_cents,
            "sale_date": sale_date,
            "completion_spend_cents": completion_spend_cents,
        },
        overrides,
    )
