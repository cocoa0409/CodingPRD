"""Request payload builders.

Every builder returns a dict of PRD-declared field names carrying valid default
values, and every builder accepts ``**overrides`` so a test can vary exactly the
one input it is about.
"""

from typing import Any, Dict, Optional

from .constants import STARTUP_CLOCK


def clock_payload(to_iso8601: str = STARTUP_CLOCK, **overrides: Any) -> Dict[str, Any]:
    """Body for repositioning the logical clock; answers with ``current_utc``
    (PRD §2.4)."""
    payload: Dict[str, Any] = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Registries (PRD §3.1)
# ---------------------------------------------------------------------------


def team_member_payload(
    full_name: str = "Dana Ruiz",
    org_title: str = "VP Operations",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for registering a crisis roster member (PRD §3.1)."""
    payload: Dict[str, Any] = {"full_name": full_name, "org_title": org_title}
    payload.update(overrides)
    return payload


def monitored_channel_payload(
    name: str = "National Wire",
    channel_type: str = "MEDIA",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for registering a monitored channel (PRD §3.1)."""
    payload: Dict[str, Any] = {"name": name, "channel_type": channel_type}
    payload.update(overrides)
    return payload


def verify_escalation_path_payload(
    verified_contact_reference: str = "TS-ESCALATION-4471",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for verifying a channel's trust-and-safety path (PRD §3.1)."""
    payload: Dict[str, Any] = {
        "verified_contact_reference": verified_contact_reference
    }
    payload.update(overrides)
    return payload


def prepared_material_payload(
    scenario_code: str = "PRODUCT_RECALL",
    material_type: str = "HOLDING_TEMPLATE",
    title: str = "Recall holding template",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for filing dark-site material (PRD §3.1)."""
    payload: Dict[str, Any] = {
        "scenario_code": scenario_code,
        "material_type": material_type,
        "title": title,
    }
    payload.update(overrides)
    return payload


def material_review_payload(
    reviewer_notes: str = "Legal and comms re-read; language current.",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for a content review that restarts the decay curve (PRD §3.1)."""
    payload: Dict[str, Any] = {"reviewer_notes": reviewer_notes}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Signals (PRD §3.2)
# ---------------------------------------------------------------------------


def issue_signal_payload(
    channel_id: str,
    headline: str = "Outlet questions product safety",
    reach_score: int = 75,
    sentiment_score: float = 0.0,
    source_credibility_tier: str = "A",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for recording an observed issue signal (PRD §3.2)."""
    payload: Dict[str, Any] = {
        "channel_id": channel_id,
        "headline": headline,
        "reach_score": reach_score,
        "sentiment_score": sentiment_score,
        "source_credibility_tier": source_credibility_tier,
    }
    payload.update(overrides)
    return payload


def link_signal_payload(incident_id: str, **overrides: Any) -> Dict[str, Any]:
    """Body for linking an OPEN signal to an incident (PRD §3.2)."""
    payload: Dict[str, Any] = {"incident_id": incident_id}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Incidents (PRD §3.3, §3.4, §3.9)
# ---------------------------------------------------------------------------


def incident_payload(
    title: str = "Regional product recall",
    scenario_code: str = "PRODUCT_RECALL",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for opening an incident file (PRD §3.3)."""
    payload: Dict[str, Any] = {"title": title, "scenario_code": scenario_code}
    payload.update(overrides)
    return payload


def assert_privilege_payload(
    privilege_basis: str = "Counsel-directed investigation of recall exposure.",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for asserting attorney-client privilege (PRD §3.4)."""
    payload: Dict[str, Any] = {"privilege_basis": privilege_basis}
    payload.update(overrides)
    return payload


def waive_privilege_payload(
    waiver_reason: str = "Investigation complete; hold no longer required.",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for waiving privilege (PRD §3.4)."""
    payload: Dict[str, Any] = {"waiver_reason": waiver_reason}
    payload.update(overrides)
    return payload


def resolve_incident_payload(
    reputation_index_after: float = 42.70, **overrides: Any
) -> Dict[str, Any]:
    """Body for resolving an incident (PRD §3.9)."""
    payload: Dict[str, Any] = {"reputation_index_after": reputation_index_after}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Crisis-team seats (PRD §3.3)
# ---------------------------------------------------------------------------


def team_assignment_payload(
    incident_id: str,
    member_id: str,
    team_role: str,
    decision_authority: str = "FULL",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for seating a member in a crisis-team role (PRD §3.3)."""
    payload: Dict[str, Any] = {
        "incident_id": incident_id,
        "member_id": member_id,
        "team_role": team_role,
        "decision_authority": decision_authority,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Statements and approvals (PRD §3.5, §3.6)
# ---------------------------------------------------------------------------


def statement_payload(
    incident_id: str,
    expected_incident_version: int,
    statement_type: str = "HOLDING",
    body: str = "We are aware of the reports and are investigating.",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for drafting a statement under incident optimistic concurrency
    (PRD §3.5, §2.8)."""
    payload: Dict[str, Any] = {
        "incident_id": incident_id,
        "statement_type": statement_type,
        "body": body,
        "expected_incident_version": expected_incident_version,
    }
    payload.update(overrides)
    return payload


def revise_statement_payload(
    body: str = "Revised: we have begun a full review with independent experts.",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for rewriting a REVISION_REQUESTED statement (PRD §3.5)."""
    payload: Dict[str, Any] = {"body": body}
    payload.update(overrides)
    return payload


def withdraw_statement_payload(
    withdraw_reason: str = "Superseded by counsel-approved language.",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for withdrawing a statement (PRD §3.6)."""
    payload: Dict[str, Any] = {"withdraw_reason": withdraw_reason}
    payload.update(overrides)
    return payload


def decide_payload(
    decision: str = "APPROVE",
    decision_comment: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for recording an approval decision (PRD §3.5)."""
    payload: Dict[str, Any] = {"decision": decision}
    if decision_comment is not None:
        payload["decision_comment"] = decision_comment
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Stakeholder notices (PRD §3.6)
# ---------------------------------------------------------------------------


def stakeholder_notice_payload(
    incident_id: str,
    statement_id: str,
    audience: str = "EMPLOYEE",
    estimated_reach: int = 1000,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for queueing an audience notice (PRD §3.6)."""
    payload: Dict[str, Any] = {
        "incident_id": incident_id,
        "statement_id": statement_id,
        "audience": audience,
        "estimated_reach": estimated_reach,
    }
    payload.update(overrides)
    return payload


def release_notice_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for releasing a notice; carries the statutory override flag only
    when a test sets it (PRD §3.6)."""
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def cancel_notice_payload(
    cancel_reason: str = "Audience list withdrawn by comms.", **overrides: Any
) -> Dict[str, Any]:
    """Body for cancelling a queued or blocked notice (PRD §3.6)."""
    payload: Dict[str, Any] = {"cancel_reason": cancel_reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Media interviews (PRD §3.7)
# ---------------------------------------------------------------------------


def media_interview_payload(
    incident_id: str,
    spokesperson_member_id: str,
    channel_id: str,
    scheduled_start_at: str,
    scheduled_end_at: str,
    outlet_name: str = "Evening Business Report",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for booking a media interview (PRD §3.7)."""
    payload: Dict[str, Any] = {
        "incident_id": incident_id,
        "spokesperson_member_id": spokesperson_member_id,
        "channel_id": channel_id,
        "outlet_name": outlet_name,
        "scheduled_start_at": scheduled_start_at,
        "scheduled_end_at": scheduled_end_at,
    }
    payload.update(overrides)
    return payload


def confirm_interview_payload(
    high_risk_answers_approved_count: int = 3, **overrides: Any
) -> Dict[str, Any]:
    """Body for confirming an interview booking (PRD §3.7)."""
    payload: Dict[str, Any] = {
        "high_risk_answers_approved_count": high_risk_answers_approved_count
    }
    payload.update(overrides)
    return payload


def cancel_interview_payload(
    cancel_reason: str = "Spokesperson stood down.", **overrides: Any
) -> Dict[str, Any]:
    """Body for cancelling an interview (PRD §3.7)."""
    payload: Dict[str, Any] = {"cancel_reason": cancel_reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Misinformation claims (PRD §3.8)
# ---------------------------------------------------------------------------


def misinformation_claim_payload(
    incident_id: str,
    channel_id: str,
    claim_text: str = "Post alleges the recall covers unaffected lots.",
    virality_score: float = 60.00,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for logging a misinformation claim (PRD §3.8)."""
    payload: Dict[str, Any] = {
        "incident_id": incident_id,
        "channel_id": channel_id,
        "claim_text": claim_text,
        "virality_score": virality_score,
    }
    payload.update(overrides)
    return payload


def issue_correction_payload(
    correction_statement_id: str,
    correction_window_start: str,
    correction_window_end: str,
    expected_channel_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for the correction fork, under channel optimistic concurrency
    (PRD §3.8, §2.8)."""
    payload: Dict[str, Any] = {
        "correction_statement_id": correction_statement_id,
        "correction_window_start": correction_window_start,
        "correction_window_end": correction_window_end,
        "expected_channel_version": expected_channel_version,
    }
    payload.update(overrides)
    return payload


def close_claim_payload(
    outcome_note: str = "Handled and documented.", **overrides: Any
) -> Dict[str, Any]:
    """Body for closing a claim on either fork (PRD §3.8)."""
    payload: Dict[str, Any] = {"outcome_note": outcome_note}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Post-crisis review (PRD §3.9)
# ---------------------------------------------------------------------------


def score_review_payload(
    scoring_method: str = "ADJUSTED",
    playbook_update_count: int = 2,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for scoring the retrospective (PRD §3.9)."""
    payload: Dict[str, Any] = {
        "scoring_method": scoring_method,
        "playbook_update_count": playbook_update_count,
    }
    payload.update(overrides)
    return payload
