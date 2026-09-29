"""
Valid-by-default request payload builders.

Each builder returns the minimal payload the PRD declares for that write, filled
with values that satisfy every stated precondition, and merges any keyword
overrides on top so a test can perturb exactly one field. Passing `None` for an
override removes the key entirely, which is how tests probe missing-required-field
and default-application behaviour.
"""

from typing import Any, Dict, List, Optional

from .constants import DEFAULT_CLOCK_UTC


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(base)
    for key, value in overrides.items():
        if value is _OMIT:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


class _Omit:
    """Sentinel meaning "drop this key from the payload entirely"."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<OMIT>"


_OMIT = _Omit()
OMIT = _OMIT

# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------


def clock_payload(current_utc: str = DEFAULT_CLOCK_UTC) -> Dict[str, Any]:
    return {"current_utc": current_utc}


# ---------------------------------------------------------------------------
# Program
# ---------------------------------------------------------------------------


def program_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "name": "WL FY27Q1",
            "fiscal_quarter": "FY27Q1",
            "incentive_budget_usd": 10000.00,
            "interview_incentive_cap_usd": 500.00,
            "min_deal_value_usd": 50000.00,
        },
        overrides,
    )


def incentive_budget_payload(
    incentive_budget_usd, expected_program_version: int, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "incentive_budget_usd": incentive_budget_usd,
            "expected_program_version": expected_program_version,
        },
        overrides,
    )


def interview_guide_payload(
    required_question_keys: Optional[List[str]] = None, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "required_question_keys": required_question_keys
            or [
                "EVALUATION_CRITERIA",
                "COMPETITOR_POSITIONING",
                "PRICING_PERCEPTION",
            ]
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Competitor
# ---------------------------------------------------------------------------


def competitor_payload(program_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {"program_id": program_id, "name": "Northwind", "tier": "PRIMARY"},
        overrides,
    )


# ---------------------------------------------------------------------------
# Deal
# ---------------------------------------------------------------------------


def deal_payload(program_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "program_id": program_id,
            "crm_deal_ref": "CRM-1001",
            "outcome": "LOST",
            "acr_usd": 300000.00,
            "close_date": "2026-06-15T00:00:00.000Z",
            "segment": "ENTERPRISE",
            "sales_rep_user_ref": "rep-77",
        },
        overrides,
    )


def deal_patch_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({}, overrides)


def decline_selection_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({}, overrides)


# ---------------------------------------------------------------------------
# Analyst
# ---------------------------------------------------------------------------


def analyst_payload(program_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "program_id": program_id,
            "full_name": "Ana One",
            "linked_user_ref": "u-ana-1",
            "employment_type": "INTERNAL",
            "certified_until": "2027-01-01T00:00:00.000Z",
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Buyer contact
# ---------------------------------------------------------------------------


def buyer_contact_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "email": "buyer1@acme.test",
            "full_name": "Bea Uno",
            "title_band": "ECONOMIC_BUYER",
        },
        overrides,
    )


def consent_payload(consent_status: str = "GRANTED", **overrides: Any) -> Dict[str, Any]:
    return _merge({"consent_status": consent_status}, overrides)


# ---------------------------------------------------------------------------
# Sampling frame
# ---------------------------------------------------------------------------


def sampling_frame_payload(program_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "program_id": program_id,
            "label": "FY27Q1 Frame",
            "window_start": "2026-04-01T00:00:00.000Z",
            "window_end": "2026-07-01T00:00:00.000Z",
            "quota_won": 2,
            "quota_lost": 2,
            "quota_no_decision": 1,
            "selection_basis": "STRATIFIED_BY_SEGMENT",
        },
        overrides,
    )


def draw_payload(stratum: str = "LOST", **overrides: Any) -> Dict[str, Any]:
    return _merge({"stratum": stratum}, overrides)


# ---------------------------------------------------------------------------
# Interview
# ---------------------------------------------------------------------------


def interview_payload(
    deal_id: str, buyer_contact_id: str, analyst_id: str, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "deal_id": deal_id,
            "buyer_contact_id": buyer_contact_id,
            "analyst_id": analyst_id,
            "scheduled_start_at": "2026-08-10T14:00:00.000Z",
            "scheduled_end_at": "2026-08-10T15:00:00.000Z",
        },
        overrides,
    )


def complete_interview_payload(
    actual_start_at: str = "2026-08-10T14:05:00.000Z",
    actual_end_at: str = "2026-08-10T14:35:00.000Z",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {"actual_start_at": actual_start_at, "actual_end_at": actual_end_at}, overrides
    )


def reschedule_payload(
    scheduled_start_at: str, scheduled_end_at: str, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "scheduled_start_at": scheduled_start_at,
            "scheduled_end_at": scheduled_end_at,
        },
        overrides,
    )


def cancel_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({}, overrides)


def interview_response_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "question_key": "EVALUATION_CRITERIA",
            "verbatim_text": "We scored the three finalists on integration depth.",
            "recorded_at": "2026-08-10T14:10:00.000Z",
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Loss reasons and attribution
# ---------------------------------------------------------------------------


def loss_reason_payload(program_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {"program_id": program_id, "code": "PRICE", "label": "Price"},
        overrides,
    )


def loss_reason_patch_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({}, overrides)


def loss_attribution_payload(
    deal_id: str, primary_reason_id: str, expected_deal_version: int, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "deal_id": deal_id,
            "primary_reason_id": primary_reason_id,
            "weight_primary": 1.00,
            "expected_deal_version": expected_deal_version,
        },
        overrides,
    )


def loss_trends_params(
    window_start: str = "2026-04-01T00:00:00.000Z",
    window_end: str = "2026-07-01T00:00:00.000Z",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge({"window_start": window_start, "window_end": window_end}, overrides)


# ---------------------------------------------------------------------------
# Battlecards
# ---------------------------------------------------------------------------


def battlecard_payload(competitor_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "competitor_id": competitor_id,
            "title": "Northwind Battlecard",
            "version_label": "v1",
        },
        overrides,
    )


def claim_payload(
    evidence_response_ids: List[str], **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "claim_text": "Buyers report our list price lands below theirs at parity scope.",
            "claim_type": "REFERENCE",
            "evidence_response_ids": list(evidence_response_ids),
        },
        overrides,
    )


def legal_decision_payload(decision: str = "APPROVE", **overrides: Any) -> Dict[str, Any]:
    return _merge({"decision": decision}, overrides)


def reopen_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({}, overrides)


# ---------------------------------------------------------------------------
# Enablement
# ---------------------------------------------------------------------------


def enablement_assignment_payload(
    battlecard_id: str, sales_rep_user_ref: str, due_at: str, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "battlecard_id": battlecard_id,
            "sales_rep_user_ref": sales_rep_user_ref,
            "due_at": due_at,
        },
        overrides,
    )


def assignment_complete_payload(quiz_score: int = 90, **overrides: Any) -> Dict[str, Any]:
    return _merge({"quiz_score": quiz_score}, overrides)


# ---------------------------------------------------------------------------
# Product gaps
# ---------------------------------------------------------------------------


def product_gap_payload(
    program_id: str, source_response_id: str, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "program_id": program_id,
            "source_response_id": source_response_id,
            "gap_summary": "Scheduled export jobs cannot target a customer-owned bucket.",
        },
        overrides,
    )


def triage_payload(decision: str = "ACCEPT", **overrides: Any) -> Dict[str, Any]:
    return _merge({"decision": decision}, overrides)


def promote_payload(
    roadmap_epic_ref: str = "EPIC-4210", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"roadmap_epic_ref": roadmap_epic_ref}, overrides)
