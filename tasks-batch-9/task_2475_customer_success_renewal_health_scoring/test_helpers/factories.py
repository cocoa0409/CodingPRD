"""Request-payload builders, one per write endpoint of PRD §4.

Each builder supplies the fields the PRD marks as required, with values that are
individually unremarkable, and accepts keyword overrides so a test can vary the
single input it cares about. Nothing here supplies a system-managed or computed
field: PRD §2.9 says those "are silently ignored when a client supplies them",
so a factory that volunteered one would hide the very behaviour under test.
"""

from typing import Any, Dict, Optional

from .constants import (
    CODE_KICKOFF,
    ENGAGEMENT_TYPE_QBR,
    PLAY_TYPE_ENABLEMENT_SPRINT,
    PROGRAM_REFERENCE,
    RISK_ADOPTION_DECLINE,
    SEGMENT_ENTERPRISE,
    SENIORITY_CXO,
    SEVERITY_HIGH,
    SEVERITY_S1,
    SIGNAL_SUPPORT_TICKET,
    SIGNAL_USAGE_PERIOD,
    SOURCE_SEAT_SATURATION,
    TIER_HIGH_TOUCH,
)

# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------


def account(**overrides: Any) -> Dict[str, Any]:
    """Body for POST /accounts."""
    payload: Dict[str, Any] = {
        "name": "Northwind Traders",
        "arr_cents": 30_000_000,
        "segment_band": SEGMENT_ENTERPRISE,
        "contract_start_date": "2026-01-01",
        "contract_end_date": "2026-12-31",
    }
    payload.update(overrides)
    return payload


def account_patch(**overrides: Any) -> Dict[str, Any]:
    """Body for PATCH /accounts/{id}."""
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def lifecycle_action(action: str, **overrides: Any) -> Dict[str, Any]:
    """Body for POST /accounts/{id}/lifecycle."""
    payload: Dict[str, Any] = {"action": action}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Managers and coverage
# ---------------------------------------------------------------------------


def csm(**overrides: Any) -> Dict[str, Any]:
    """Body for POST /csms."""
    payload: Dict[str, Any] = {
        "full_name": "Ada Lovelace",
        "coverage_specialty": TIER_HIGH_TOUCH,
        "capacity_units_total": 40,
    }
    payload.update(overrides)
    return payload


def csm_patch(**overrides: Any) -> Dict[str, Any]:
    """Body for PATCH /csms/{id}."""
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def coverage_assignment(
    account_id: str, expected_account_version: int, **overrides: Any
) -> Dict[str, Any]:
    """Body for POST /coverage-assignments.

    PRD §2.7 requires `expected_account_version` on this endpoint, so it is a
    positional argument rather than an override.
    """
    payload: Dict[str, Any] = {
        "account_id": account_id,
        "expected_account_version": expected_account_version,
    }
    payload.update(overrides)
    return payload


def release(**overrides: Any) -> Dict[str, Any]:
    """Body for POST /coverage-assignments/{id}/release."""
    payload: Dict[str, Any] = {"release_reason": "Coverage rebalance"}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------


def usage_signal(
    period_end_date: str,
    weekly_active_users: int,
    licensed_seats: int,
    feature_depth_pct: float,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for POST /accounts/{id}/signals with `signal_kind` USAGE_PERIOD."""
    payload: Dict[str, Any] = {
        "signal_kind": SIGNAL_USAGE_PERIOD,
        "period_end_date": period_end_date,
        "weekly_active_users": weekly_active_users,
        "licensed_seats": licensed_seats,
        "feature_depth_pct": feature_depth_pct,
    }
    payload.update(overrides)
    return payload


def support_signal(
    opened_at: str, ticket_severity: str = SEVERITY_S1, **overrides: Any
) -> Dict[str, Any]:
    """Body for POST /accounts/{id}/signals with `signal_kind` SUPPORT_TICKET."""
    payload: Dict[str, Any] = {
        "signal_kind": SIGNAL_SUPPORT_TICKET,
        "ticket_severity": ticket_severity,
        "opened_at": opened_at,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Sponsors, engagements and goals
# ---------------------------------------------------------------------------


def sponsor_contact(**overrides: Any) -> Dict[str, Any]:
    """Body for POST /accounts/{id}/sponsor-contacts."""
    payload: Dict[str, Any] = {
        "full_name": "Dana Reed",
        "seniority": SENIORITY_CXO,
        "is_economic_buyer": True,
    }
    payload.update(overrides)
    return payload


def sponsor_patch(**overrides: Any) -> Dict[str, Any]:
    """Body for PATCH /sponsor-contacts/{id}."""
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def executive_engagement(
    sponsor_contact_id: str, start_at: str, end_at: str, **overrides: Any
) -> Dict[str, Any]:
    """Body for POST /accounts/{id}/executive-engagements."""
    payload: Dict[str, Any] = {
        "sponsor_contact_id": sponsor_contact_id,
        "engagement_type": ENGAGEMENT_TYPE_QBR,
        "start_at": start_at,
        "end_at": end_at,
    }
    payload.update(overrides)
    return payload


def engagement_outcome(outcome: str, **overrides: Any) -> Dict[str, Any]:
    """Body for POST /executive-engagements/{id}/outcome."""
    payload: Dict[str, Any] = {"outcome": outcome}
    payload.update(overrides)
    return payload


def outcome_goal(
    weight_bp: int, target_value: float, **overrides: Any
) -> Dict[str, Any]:
    """Body for POST /accounts/{id}/outcome-goals."""
    payload: Dict[str, Any] = {
        "title": "Reduce ticket volume",
        "weight_bp": weight_bp,
        "target_value": target_value,
    }
    payload.update(overrides)
    return payload


def goal_progress(status: str, **overrides: Any) -> Dict[str, Any]:
    """Body for POST /outcome-goals/{id}/progress."""
    payload: Dict[str, Any] = {"status": status}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Onboarding milestones
# ---------------------------------------------------------------------------


def milestone(
    sequence_index: int, due_date: str, milestone_code: str = CODE_KICKOFF, **overrides: Any
) -> Dict[str, Any]:
    """Body for POST /accounts/{id}/onboarding-milestones."""
    payload: Dict[str, Any] = {
        "milestone_code": milestone_code,
        "sequence_index": sequence_index,
        "due_date": due_date,
    }
    payload.update(overrides)
    return payload


def milestone_transition(action: str, **overrides: Any) -> Dict[str, Any]:
    """Body for POST /onboarding-milestones/{id}/transition."""
    payload: Dict[str, Any] = {"action": action}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Save plays, escalations and commitments
# ---------------------------------------------------------------------------


def save_play(
    account_id: str,
    owner_csm_id: str,
    window_start_date: str,
    window_end_date: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for POST /save-plays."""
    payload: Dict[str, Any] = {
        "account_id": account_id,
        "owner_csm_id": owner_csm_id,
        "risk_code": RISK_ADOPTION_DECLINE,
        "play_type": PLAY_TYPE_ENABLEMENT_SPRINT,
        "window_start_date": window_start_date,
        "window_end_date": window_end_date,
    }
    payload.update(overrides)
    return payload


def save_play_transition(action: str, **overrides: Any) -> Dict[str, Any]:
    """Body for POST /save-plays/{id}/transition."""
    payload: Dict[str, Any] = {"action": action}
    payload.update(overrides)
    return payload


def escalation_case(
    account_id: str, save_play_id: str, severity: str = SEVERITY_HIGH, **overrides: Any
) -> Dict[str, Any]:
    """Body for POST /escalation-cases."""
    payload: Dict[str, Any] = {
        "account_id": account_id,
        "save_play_id": save_play_id,
        "severity": severity,
        "summary": "Adoption stalled after integration failure",
    }
    payload.update(overrides)
    return payload


def escalation_transition(action: str, **overrides: Any) -> Dict[str, Any]:
    """Body for POST /escalation-cases/{id}/transition."""
    payload: Dict[str, Any] = {"action": action}
    payload.update(overrides)
    return payload


def remediation_commitment(
    credit_cents: int,
    due_date: str,
    expected_escalation_case_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for POST /escalation-cases/{id}/remediation-commitments.

    PRD §2.7 requires `expected_escalation_case_version` on this endpoint.
    """
    payload: Dict[str, Any] = {
        "description": "Dedicated integration engineer for one quarter",
        "credit_cents": credit_cents,
        "due_date": due_date,
        "expected_escalation_case_version": expected_escalation_case_version,
    }
    payload.update(overrides)
    return payload


def commitment_transition(action: str, **overrides: Any) -> Dict[str, Any]:
    """Body for POST /remediation-commitments/{id}/transition."""
    payload: Dict[str, Any] = {"action": action}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Renewal forecasts
# ---------------------------------------------------------------------------


def renewal_forecast(
    account_id: str, fiscal_period: str = "2026Q3", **overrides: Any
) -> Dict[str, Any]:
    """Body for POST /renewal-forecasts."""
    payload: Dict[str, Any] = {
        "account_id": account_id,
        "fiscal_period": fiscal_period,
    }
    payload.update(overrides)
    return payload


def forecast_submit(**overrides: Any) -> Dict[str, Any]:
    """Body for POST /renewal-forecasts/{id}/submit."""
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def forecast_reconcile(
    action: str, finance_amount_cents: Optional[int] = None, **overrides: Any
) -> Dict[str, Any]:
    """Body for POST /renewal-forecasts/{id}/reconcile."""
    payload: Dict[str, Any] = {"action": action}
    if finance_amount_cents is not None:
        payload["finance_amount_cents"] = finance_amount_cents
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Expansion opportunities
# ---------------------------------------------------------------------------


def expansion_opportunity(
    account_id: str, estimated_value_cents: int = 5_000_000, **overrides: Any
) -> Dict[str, Any]:
    """Body for POST /expansion-opportunities."""
    payload: Dict[str, Any] = {
        "account_id": account_id,
        "source_signal": SOURCE_SEAT_SATURATION,
        "estimated_value_cents": estimated_value_cents,
    }
    payload.update(overrides)
    return payload


def opportunity_transition(action: str, **overrides: Any) -> Dict[str, Any]:
    """Body for POST /expansion-opportunities/{id}/transition."""
    payload: Dict[str, Any] = {"action": action}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Advocacy enrollments
# ---------------------------------------------------------------------------


def advocacy_enrollment(
    program_type: str = PROGRAM_REFERENCE, **overrides: Any
) -> Dict[str, Any]:
    """Body for POST /accounts/{id}/advocacy-enrollments."""
    payload: Dict[str, Any] = {"program_type": program_type}
    payload.update(overrides)
    return payload


def enrollment_transition(action: str, **overrides: Any) -> Dict[str, Any]:
    """Body for POST /advocacy-enrollments/{id}/transition."""
    payload: Dict[str, Any] = {"action": action}
    payload.update(overrides)
    return payload
