"""Request payload builders. Every default is a PRD-legal value."""

from typing import Any, Dict, List, Optional

from . import constants as C

JsonDict = Dict[str, Any]


def _apply(payload: JsonDict, overrides: JsonDict) -> JsonDict:
    """Merge overrides; a value of ``...`` removes the key entirely."""
    for key, value in overrides.items():
        if value is ...:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


def clock_payload(current_utc: str = C.SEED_CLOCK) -> JsonDict:
    return {"current_utc": current_utc}


def client_payload(**overrides: Any) -> JsonDict:
    payload: JsonDict = {
        "name": C.SEED_CLIENT_NAME,
        "client_code": C.SEED_CLIENT_CODE,
        "industry_code": C.SEED_CLIENT_INDUSTRY,
        "decision_process": C.SEED_CLIENT_DECISION_PROCESS,
        "stated_budget_authority_cents": C.SEED_CLIENT_BUDGET_AUTHORITY_CENTS,
        "adverse_party_codes": list(C.SEED_CLIENT_ADVERSE_PARTY_CODES),
    }
    return _apply(payload, overrides)


def consultant_payload(**overrides: Any) -> JsonDict:
    payload: JsonDict = {
        "name": "P. Reyes",
        "grade": C.GRADE_PARTNER,
        "practice_code": C.SEED_PRACTICE_CODE,
        "cost_rate_cents_per_hour": C.SEED_PARTNER_COST_RATE,
    }
    return _apply(payload, overrides)


def opportunity_payload(
    client_id: str, partner_id: str, manager_id: str, **overrides: Any
) -> JsonDict:
    payload: JsonDict = {
        "client_id": client_id,
        "owner_partner_consultant_id": partner_id,
        "scoping_manager_consultant_id": manager_id,
        "requested_practice_code": C.SEED_PRACTICE_CODE,
        "estimated_value_cents": C.SEED_ESTIMATED_VALUE_CENTS,
        "stated_budget_cents": C.SEED_STATED_BUDGET_CENTS,
        "decision_maker_identified": True,
        "target_start_date": C.SEED_TARGET_START_DATE,
        "target_end_date": C.SEED_TARGET_END_DATE,
        "objective_summary": C.SEED_OBJECTIVE_SUMMARY,
    }
    return _apply(payload, overrides)


def conflict_check_payload(
    screened: Optional[List[str]] = None, waiver_obtained: Optional[bool] = None
) -> JsonDict:
    payload: JsonDict = {
        "screened_adverse_party_codes": (
            list(C.SEED_UNRELATED_ADVERSE_PARTY_CODES) if screened is None else screened
        )
    }
    if waiver_obtained is not None:
        payload["waiver_obtained"] = waiver_obtained
    return payload


def verify_budget_payload(verified_budget_cents: int = C.SEED_VERIFIED_BUDGET_CENTS):
    return {"verified_budget_cents": verified_budget_cents}


def scope_payload(**overrides: Any) -> JsonDict:
    payload: JsonDict = {
        "assumptions": list(C.SEED_ASSUMPTIONS),
        "exclusions": list(C.SEED_EXCLUSIONS),
        "client_responsibilities": list(C.SEED_CLIENT_RESPONSIBILITIES),
    }
    return _apply(payload, overrides)


def deliverable_payload(opportunity_id: str, **overrides: Any) -> JsonDict:
    payload: JsonDict = {"opportunity_id": opportunity_id}
    payload.update(C.SEED_D1)
    return _apply(payload, overrides)


def sow_payload(
    opportunity_id: str, expected_opportunity_version: int, **overrides: Any
) -> JsonDict:
    payload: JsonDict = {
        "opportunity_id": opportunity_id,
        "pricing_model": C.PRICING_FIXED_FEE,
        "acceptance_summary": C.SEED_ACCEPTANCE_SUMMARY,
        "expected_opportunity_version": expected_opportunity_version,
    }
    return _apply(payload, overrides)


def sign_payload(signature_name: str = C.SEED_SIGNATURE_NAME, **overrides: Any):
    payload: JsonDict = {"decision": "SIGN", "signature_name": signature_name}
    return _apply(payload, overrides)


def time_entry_payload(
    engagement_id: str,
    deliverable_id: str,
    consultant_id: str,
    week_ending_date: str,
    hours: float,
    billable: bool = True,
) -> JsonDict:
    return {
        "engagement_id": engagement_id,
        "deliverable_id": deliverable_id,
        "consultant_id": consultant_id,
        "week_ending_date": week_ending_date,
        "hours": hours,
        "billable": billable,
    }


def change_request_payload(
    engagement_id: str, expected_engagement_version: int, **overrides: Any
) -> JsonDict:
    payload: JsonDict = {
        "engagement_id": engagement_id,
        "origin": C.CHANGE_ORIGIN_CLIENT_REQUEST,
        "summary": "Client asked for two extra distribution-centre scenarios",
        "added_hours": 160.0,
        "added_grade": C.GRADE_ANALYST,
        "requested_schedule_days": 30,
        "expected_engagement_version": expected_engagement_version,
    }
    return _apply(payload, overrides)


def quality_review_payload(
    engagement_id: str, reviewer_consultant_id: str, **overrides: Any
) -> JsonDict:
    payload: JsonDict = {
        "engagement_id": engagement_id,
        "reviewer_consultant_id": reviewer_consultant_id,
        "checkpoint_type": C.CHECKPOINT_MIDPOINT,
        "window_start_date": "2026-09-20",
        "window_end_date": "2026-09-30",
    }
    return _apply(payload, overrides)


def record_outcome_payload(
    outcome: str = C.REVIEW_PASSED,
    findings_severity: str = C.SEVERITY_NONE,
    **overrides: Any,
) -> JsonDict:
    payload: JsonDict = {"outcome": outcome, "findings_severity": findings_severity}
    return _apply(payload, overrides)


def satisfaction_payload(engagement_id: str, **overrides: Any) -> JsonDict:
    payload: JsonDict = {
        "engagement_id": engagement_id,
        "delivery_score": 8,
        "value_score": 7,
        "communication_score": 9,
        "would_refer": True,
    }
    return _apply(payload, overrides)
