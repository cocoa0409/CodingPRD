"""Request-payload factories.

Each factory produces only the client-supplied input fields of one endpoint;
server-owned fields (`id`, `created_at`, `updated_at`, `version`, computed
rollups, statuses) are never included, because PRD 2.4 states a
client-supplied `id` "is ignored" and every status field is server-managed.
Keyword overrides let a caller vary exactly the field under test.
"""
from __future__ import annotations

import itertools
from typing import Any, Dict, List, Optional

_counter = itertools.count(1)


def unique_suffix() -> str:
    """A monotone suffix for fields the PRD requires to be unique."""
    return str(next(_counter)).zfill(4)


# --------------------------------------------------------------------------
# Evaluation forms and behaviours (PRD 3.1)
# --------------------------------------------------------------------------
def behavior_payload(
    code: str,
    weight_pct: float,
    *,
    label: Optional[str] = None,
    guidance_text: Optional[str] = None,
    compliance_critical: Optional[bool] = None,
    auto_fail_on_violation: Optional[bool] = None,
    max_points: Optional[int] = None,
    allows_not_applicable: Optional[bool] = None,
) -> Dict[str, Any]:
    """One element of the `behaviors` array.

    Only `code`, `label`, `weight_pct` and `guidance_text` are required; the
    four flags are omitted unless explicitly supplied, so the server's
    declared defaults are exercised.
    """
    payload: Dict[str, Any] = {
        "code": code,
        "label": label if label is not None else code.replace("_", " ").title(),
        "weight_pct": weight_pct,
        "guidance_text": (
            guidance_text
            if guidance_text is not None
            else "Score {} against the published standard.".format(code)
        ),
    }
    if compliance_critical is not None:
        payload["compliance_critical"] = compliance_critical
    if auto_fail_on_violation is not None:
        payload["auto_fail_on_violation"] = auto_fail_on_violation
    if max_points is not None:
        payload["max_points"] = max_points
    if allows_not_applicable is not None:
        payload["allows_not_applicable"] = allows_not_applicable
    return payload


#: The four-behaviour scorecard used by most scenarios.  Weights sum to
#: 100.00 as PRD 3.1 demands; DISCLOSE is both compliance-critical and an
#: automatic-fail trigger; SURVEY permits "NA".
CANONICAL_BEHAVIORS: List[Dict[str, Any]] = [
    behavior_payload(
        "DISCLOSE",
        30.00,
        label="Recording disclosure",
        compliance_critical=True,
        auto_fail_on_violation=True,
    ),
    behavior_payload("GREET", 20.00, label="Branded greeting"),
    behavior_payload("RESOLVE", 35.00, label="Issue resolution"),
    behavior_payload(
        "SURVEY", 15.00, label="Survey invitation", allows_not_applicable=True
    ),
]

#: A five-behaviour scorecard of equal 20.00 weights scored out of three
#: points, which makes per-behaviour rounding observable.
THIRDS_BEHAVIORS: List[Dict[str, Any]] = [
    behavior_payload("EMPATHY", 20.00, label="Empathy statement", max_points=3),
    behavior_payload(
        "VERIFY",
        20.00,
        label="Identity verification",
        compliance_critical=True,
        auto_fail_on_violation=True,
        max_points=3,
    ),
    behavior_payload("DOCUMENT", 20.00, label="Case documentation", max_points=3),
    behavior_payload("OFFER", 20.00, label="Next best action", max_points=3),
    behavior_payload("CLOSE", 20.00, label="Closing", max_points=3),
]

#: Every behaviour of the thirds scorecard scored one point out of three.
THIRDS_ALL_ONE: Dict[str, Any] = {
    "EMPATHY": 1,
    "VERIFY": 1,
    "DOCUMENT": 1,
    "OFFER": 1,
    "CLOSE": 1,
}


def evaluation_form_payload(
    *,
    name: Optional[str] = None,
    version_label: Optional[str] = None,
    auto_fail_policy: str = "COMPLIANCE_SECTION_ZERO",
    behaviors: Optional[List[Dict[str, Any]]] = None,
    min_compliance_item_score: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for POST /evaluation-forms."""
    suffix = unique_suffix()
    payload: Dict[str, Any] = {
        "name": name if name is not None else "Voice Quality Scorecard {}".format(suffix),
        "version_label": version_label if version_label is not None else "v{}".format(suffix),
        "auto_fail_policy": auto_fail_policy,
        "behaviors": [dict(b) for b in (behaviors if behaviors is not None else CANONICAL_BEHAVIORS)],
    }
    if min_compliance_item_score is not None:
        payload["min_compliance_item_score"] = min_compliance_item_score
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Agents, evaluators and interactions (PRD 3.2)
# --------------------------------------------------------------------------
def agent_payload(
    *,
    external_ref: Optional[str] = None,
    full_name: str = "Ada Agent",
    team_code: str = "TEAM-A",
    hire_date: str = "2025-03-01T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for POST /agents."""
    payload: Dict[str, Any] = {
        "external_ref": external_ref if external_ref is not None else "A-{}".format(unique_suffix()),
        "full_name": full_name,
        "team_code": team_code,
        "hire_date": hire_date,
    }
    payload.update(overrides)
    return payload


def evaluator_payload(
    *,
    full_name: str = "Eve Evaluator",
    max_open_assignments: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for POST /evaluators.

    `max_open_assignments` is omitted unless supplied so the declared default
    of three is exercised.
    """
    payload: Dict[str, Any] = {"full_name": full_name}
    if max_open_assignments is not None:
        payload["max_open_assignments"] = max_open_assignments
    payload.update(overrides)
    return payload


def interaction_payload(
    agent_id: str,
    *,
    channel: str = "VOICE",
    started_at: str = "2026-08-03T10:00:00Z",
    ended_at: str = "2026-08-03T10:10:00Z",
    required_disclosures: Optional[List[str]] = None,
    customer_flagged: Optional[bool] = None,
    csat_score: Optional[int] = None,
    repeat_contact_within_72h: Optional[bool] = None,
    include_csat: bool = True,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for POST /interactions."""
    payload: Dict[str, Any] = {
        "agent_id": agent_id,
        "channel": channel,
        "started_at": started_at,
        "ended_at": ended_at,
    }
    if required_disclosures is not None:
        payload["required_disclosures"] = list(required_disclosures)
    if customer_flagged is not None:
        payload["customer_flagged"] = customer_flagged
    if include_csat and csat_score is not None:
        payload["csat_score"] = csat_score
    if repeat_contact_within_72h is not None:
        payload["repeat_contact_within_72h"] = repeat_contact_within_72h
    payload.update(overrides)
    return payload


def consent_review_payload(
    consent_outcome: str,
    *,
    captured_disclosures: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for POST /interactions/{id}/consent-review."""
    payload: Dict[str, Any] = {"consent_outcome": consent_outcome}
    if captured_disclosures is not None:
        payload["captured_disclosures"] = list(captured_disclosures)
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Analytics scans (PRD 3.3)
# --------------------------------------------------------------------------
def analytics_scan_payload(
    interaction_id: str,
    expected_interaction_version: int,
    *,
    silence_pct: float = 20.00,
    sentiment_delta: float = 0.00,
    flagged_categories: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for POST /analytics-scans."""
    payload: Dict[str, Any] = {
        "interaction_id": interaction_id,
        "silence_pct": silence_pct,
        "sentiment_delta": sentiment_delta,
        "expected_interaction_version": expected_interaction_version,
    }
    if flagged_categories is not None:
        payload["flagged_categories"] = list(flagged_categories)
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Sampling plans and selections (PRD 3.4)
# --------------------------------------------------------------------------
def source_mix(random_pct: int = 50, targeted_pct: int = 25, customer_flagged_pct: int = 25) -> Dict[str, int]:
    """The three-key `source_mix` object of a sampling plan."""
    return {
        "random_pct": random_pct,
        "targeted_pct": targeted_pct,
        "customer_flagged_pct": customer_flagged_pct,
    }


ALL_RANDOM_MIX = {"random_pct": 100, "targeted_pct": 0, "customer_flagged_pct": 0}


def sample_plan_payload(
    form_id: str,
    *,
    period_start: str = "2026-08-01T00:00:00Z",
    period_end: str = "2026-08-31T23:59:59Z",
    per_agent_target_volume: int = 4,
    mix: Optional[Dict[str, int]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for POST /sample-plans."""
    payload: Dict[str, Any] = {
        "form_id": form_id,
        "period_start": period_start,
        "period_end": period_end,
        "per_agent_target_volume": per_agent_target_volume,
        "source_mix": dict(mix) if mix is not None else dict(ALL_RANDOM_MIX),
    }
    payload.update(overrides)
    return payload


def sample_selection_payload(
    plan_id: str,
    interaction_id: str,
    *,
    source: str = "RANDOM",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for POST /sample-selections."""
    payload: Dict[str, Any] = {
        "plan_id": plan_id,
        "interaction_id": interaction_id,
        "source": source,
    }
    payload.update(overrides)
    return payload


def assign_payload(
    assigned_evaluator_id: str,
    *,
    review_window_start: str = "2026-08-05T09:00:00Z",
    review_window_end: str = "2026-08-05T11:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for POST /sample-selections/{id}/assign."""
    payload: Dict[str, Any] = {
        "assigned_evaluator_id": assigned_evaluator_id,
        "review_window_start": review_window_start,
        "review_window_end": review_window_end,
    }
    payload.update(overrides)
    return payload


def exclude_payload(exclusion_reason: str = "EVALUATOR_UNAVAILABLE", **overrides: Any) -> Dict[str, Any]:
    """Body for POST /sample-selections/{id}/exclude."""
    payload: Dict[str, Any] = {"exclusion_reason": exclusion_reason}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Evaluations (PRD 3.5)
# --------------------------------------------------------------------------
def evaluation_payload(selection_id: str, **overrides: Any) -> Dict[str, Any]:
    """Body for POST /evaluations; "the only input is the `selection_id`"."""
    payload: Dict[str, Any] = {"selection_id": selection_id}
    payload.update(overrides)
    return payload


#: A complete cover of the canonical scorecard that scores 82.00 renormalised.
PASSING_ITEM_SCORES: Dict[str, Any] = {
    "DISCLOSE": 5,
    "GREET": 4,
    "RESOLVE": 3,
    "SURVEY": 5,
}

#: The same cover with the automatic-fail behaviour scored zero.
AUTO_FAIL_ITEM_SCORES: Dict[str, Any] = {
    "DISCLOSE": 0,
    "GREET": 4,
    "RESOLVE": 3,
    "SURVEY": 5,
}

#: A cover marking the not-applicable-eligible behaviour "NA".
NA_ITEM_SCORES: Dict[str, Any] = {
    "DISCLOSE": 5,
    "GREET": 4,
    "RESOLVE": 3,
    "SURVEY": "NA",
}

#: Covers pinned at the scores the high-score floor of 85.00 sits between.
HIGH_ITEM_SCORES_93: Dict[str, Any] = {
    "DISCLOSE": 5,
    "GREET": 4,
    "RESOLVE": 5,
    "SURVEY": 4,
}
HIGH_ITEM_SCORES_89: Dict[str, Any] = {
    "DISCLOSE": 5,
    "GREET": 4,
    "RESOLVE": 4,
    "SURVEY": 5,
}
HIGH_ITEM_SCORES_90: Dict[str, Any] = {
    "DISCLOSE": 5,
    "GREET": 5,
    "RESOLVE": 4,
    "SURVEY": 4,
}
HIGH_ITEM_SCORES_86: Dict[str, Any] = {
    "DISCLOSE": 5,
    "GREET": 5,
    "RESOLVE": 3,
    "SURVEY": 5,
}


def submit_payload(item_scores: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    """Body for POST /evaluations/{id}/submit."""
    payload: Dict[str, Any] = {"item_scores": dict(item_scores)}
    payload.update(overrides)
    return payload


def acknowledge_payload(agreement: str = "AGREE", **overrides: Any) -> Dict[str, Any]:
    """Body for POST /evaluations/{id}/acknowledge."""
    payload: Dict[str, Any] = {"agreement": agreement}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Disputes (PRD 3.6)
# --------------------------------------------------------------------------
def dispute_payload(
    evaluation_id: str,
    expected_evaluation_version: int,
    *,
    disputed_behavior_codes: Optional[List[str]] = None,
    rationale: str = "The resolution behaviour was scored without regard to the transfer.",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for POST /disputes."""
    payload: Dict[str, Any] = {
        "evaluation_id": evaluation_id,
        "disputed_behavior_codes": list(disputed_behavior_codes)
        if disputed_behavior_codes is not None
        else ["RESOLVE"],
        "rationale": rationale,
        "expected_evaluation_version": expected_evaluation_version,
    }
    payload.update(overrides)
    return payload


def resolve_payload(
    outcome: str,
    *,
    outcome_note: Optional[str] = None,
    adjusted_item_scores: Optional[Dict[str, Any]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for POST /disputes/{id}/resolve."""
    payload: Dict[str, Any] = {"outcome": outcome}
    if outcome_note is not None:
        payload["outcome_note"] = outcome_note
    if adjusted_item_scores is not None:
        payload["adjusted_item_scores"] = dict(adjusted_item_scores)
    payload.update(overrides)
    return payload


def respond_payload(
    additional_rationale: str = "The transfer note is attached to the ticket.",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for POST /disputes/{id}/respond."""
    payload: Dict[str, Any] = {"additional_rationale": additional_rationale}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Calibration (PRD 3.7)
# --------------------------------------------------------------------------
def calibration_session_payload(
    form_id: str,
    interaction_id: str,
    *,
    scheduled_start: str = "2026-08-06T09:00:00Z",
    scheduled_end: str = "2026-08-06T11:00:00Z",
    benchmark_item_scores: Optional[Dict[str, Any]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for POST /calibration-sessions."""
    payload: Dict[str, Any] = {
        "form_id": form_id,
        "interaction_id": interaction_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "benchmark_item_scores": dict(benchmark_item_scores)
        if benchmark_item_scores is not None
        else dict(PASSING_ITEM_SCORES),
    }
    payload.update(overrides)
    return payload


def calibration_submission_payload(
    session_id: str,
    item_scores: Dict[str, Any],
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for POST /calibration-submissions."""
    payload: Dict[str, Any] = {
        "session_id": session_id,
        "item_scores": dict(item_scores),
    }
    payload.update(overrides)
    return payload


def guidance_update(code: str, guidance_text: str) -> Dict[str, Any]:
    """One element of the optional `guidance_updates` array of a session close."""
    return {"code": code, "guidance_text": guidance_text}


def close_session_payload(
    guidance_updates: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for POST /calibration-sessions/{id}/close."""
    payload: Dict[str, Any] = {}
    if guidance_updates is not None:
        payload["guidance_updates"] = [dict(g) for g in guidance_updates]
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Coaching and recognition (PRD 3.8)
# --------------------------------------------------------------------------
def coaching_plan_payload(
    agent_id: str,
    source_evaluation_id: str,
    expected_agent_version: int,
    *,
    assigned_supervisor_id: str = "sup-operator-001",
    target_score: float = 85.00,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for POST /coaching-plans."""
    payload: Dict[str, Any] = {
        "agent_id": agent_id,
        "source_evaluation_id": source_evaluation_id,
        "assigned_supervisor_id": assigned_supervisor_id,
        "target_score": target_score,
        "expected_agent_version": expected_agent_version,
    }
    payload.update(overrides)
    return payload


def log_session_payload(
    session_at: str = "2026-08-06T09:00:00Z",
    *,
    session_note: str = "Reviewed the disclosure script line by line.",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for POST /coaching-plans/{id}/log-session."""
    payload: Dict[str, Any] = {
        "session_note": session_note,
        "session_at": session_at,
    }
    payload.update(overrides)
    return payload


def escalate_payload(
    escalation_note: str = "The plan ran past its due date without completion.",
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for POST /coaching-plans/{id}/escalate."""
    payload: Dict[str, Any] = {"escalation_note": escalation_note}
    payload.update(overrides)
    return payload


def recognition_payload(
    *, award_code: str = "QUARTERLY_STAR", points: int = 50, **overrides: Any
) -> Dict[str, Any]:
    """Body for POST /agents/{id}/recognition."""
    payload: Dict[str, Any] = {"award_code": award_code, "points": points}
    payload.update(overrides)
    return payload
