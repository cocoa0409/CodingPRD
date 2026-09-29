"""Request-payload factories.  Input fields only; never server-derived fields."""

import uuid
from typing import Any, Dict, List, Optional


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


# ---------------------------------------------------------------------------
# Roadmap decisions and research requests
# ---------------------------------------------------------------------------
def create_roadmap_decision_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "title": _unique("Decision"),
        "decision_deadline": "2026-10-01T00:00:00Z",
        "reversibility": "IRREVERSIBLE",
        "impacted_user_count": 12000,
    }
    payload.update(overrides)
    return payload


def create_research_request_payload(
    roadmap_decision_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload = {
        "roadmap_decision_id": roadmap_decision_id,
        "question": "How do power users triage their inbox each morning?",
        "question_type": "DISCOVERY",
        "evidence_gap": "FULL",
    }
    payload.update(overrides)
    return payload


def triage_payload(
    outcome: str, reason: Optional[str] = None, method_override: Optional[str] = None
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome}
    if reason is not None:
        payload["reason"] = reason
    if method_override is not None:
        payload["method_override"] = method_override
    return payload


def resubmit_research_request_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "question": "Which inbox triage steps do power users repeat every morning?",
        "question_type": "DISCOVERY",
        "evidence_gap": "FULL",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Participant pools and participants
# ---------------------------------------------------------------------------
def create_participant_pool_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "name": _unique("Pool"),
        "pool_type": "CUSTOMER_LIST",
        "contact_cap_per_window": 2,
        "contact_window_days": 30,
        "incentive_budget_cents": 20000,
    }
    payload.update(overrides)
    return payload


def create_participant_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "external_ref": _unique("ext"),
        "segment": "POWER_USER",
        "locale": "en-US",
        "pii_on_file": True,
    }
    payload.update(overrides)
    return payload


def create_incentive_settlement_payload(
    study_id: str, mode: str, expected_pool_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload = {
        "study_id": study_id,
        "mode": mode,
        "expected_pool_version": expected_pool_version,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Studies
# ---------------------------------------------------------------------------
def screening_criteria(**overrides: Any) -> Dict[str, Any]:
    """The rubric carries exactly four keys and no others."""
    criteria = {
        "required_segment": "POWER_USER",
        "required_locale": "en-US",
        "target_answers": ["A1", "A3"],
        "disqualifying_answers": ["X9"],
    }
    criteria.update(overrides)
    return criteria


def create_study_payload(
    research_request_id: str, participant_pool_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "research_request_id": research_request_id,
        "participant_pool_id": participant_pool_id,
        "method": "INTERVIEW",
        "target_participant_count": 3,
        "screening_criteria": screening_criteria(),
        "incentive_amount_cents": 5000,
        "fielding_start": "2026-08-03T00:00:00Z",
        "fielding_end": "2026-08-21T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def study_guide_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {"guide_version_label": "G1", "guide_question_count": 8}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Recruitments and sessions
# ---------------------------------------------------------------------------
def screening_answers(**overrides: Any) -> Dict[str, Any]:
    """The answer sheet carries exactly three keys and no others."""
    answers = {
        "segment": "POWER_USER",
        "locale": "en-US",
        "answers": ["A1", "A3"],
    }
    answers.update(overrides)
    return answers


def create_recruitment_payload(participant_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "participant_id": participant_id,
        "screening_answers": screening_answers(),
    }
    payload.update(overrides)
    return payload


def auto_invite_payload(count: int) -> Dict[str, Any]:
    return {"count": count}


def schedule_payload(
    scheduled_start: str, scheduled_end: str, moderator_user_id: str
) -> Dict[str, Any]:
    return {
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "moderator_user_id": moderator_user_id,
    }


def complete_recruitment_payload(actual_duration_min: int = 55) -> Dict[str, Any]:
    return {"actual_duration_min": actual_duration_min}


def no_show_payload(reason: str = "Participant did not join the call") -> Dict[str, Any]:
    return {"reason": reason}


def withdraw_payload(reason: str = "Participant withdrew before the session") -> Dict[str, Any]:
    return {"reason": reason}


# ---------------------------------------------------------------------------
# Consent and artifacts
# ---------------------------------------------------------------------------
def create_consent_record_payload(
    participant_id: str,
    study_id: str,
    scopes: Optional[List[str]] = None,
    retention_days: int = 120,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "participant_id": participant_id,
        "study_id": study_id,
        "scopes": list(scopes) if scopes is not None else ["TRANSCRIPT"],
        "retention_days": retention_days,
    }
    payload.update(overrides)
    return payload


def revoke_consent_payload(reason: str = "Participant asked for erasure") -> Dict[str, Any]:
    return {"reason": reason}


def create_artifact_payload(
    artifact_type: str = "TRANSCRIPT", contains_pii: bool = False, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "artifact_type": artifact_type,
        "contains_pii": contains_pii,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------
def create_theme_payload(
    label: Optional[str] = None, parent_theme_id: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"label": label or _unique("Theme")}
    if parent_theme_id is not None:
        payload["parent_theme_id"] = parent_theme_id
    payload.update(overrides)
    return payload


def create_finding_payload(
    study_id: str, theme_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "study_id": study_id,
        "theme_id": theme_id,
        "statement": "Power users rebuild the same three filters every Monday morning.",
        "severity": "MEDIUM",
    }
    payload.update(overrides)
    return payload


def create_evidence_link_payload(
    artifact_id: str, weight_class: str = "DIRECT_QUOTE", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "artifact_id": artifact_id,
        "excerpt_ref": _unique("00:12:30"),
        "weight_class": weight_class,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Readouts and follow-ups
# ---------------------------------------------------------------------------
def create_readout_payload(
    roadmap_decision_id: str,
    cited_finding_ids: List[str],
    expected_study_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "roadmap_decision_id": roadmap_decision_id,
        "recommendation": "Ship the saved-filter shortcut before the next release train.",
        "recommended_action": "PROCEED",
        "cited_finding_ids": list(cited_finding_ids),
        "expected_study_version": expected_study_version,
    }
    payload.update(overrides)
    return payload


def respond_to_readout_payload(
    outcome: str, note: Optional[str] = None
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome}
    if note is not None:
        payload["note"] = note
    return payload


def create_follow_up_payload(
    owner_user_id: str, due_date: str = "2026-09-01T00:00:00Z", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "owner_user_id": owner_user_id,
        "description": "Wire the saved-filter shortcut into the settings surface.",
        "due_date": due_date,
    }
    payload.update(overrides)
    return payload
