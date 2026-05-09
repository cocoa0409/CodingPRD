"""Payload factories — one factory per entity, input fields only.

Field names match the PRD verbatim (PRD §2.4, §3). All factories accept
**overrides so individual tests can pin the values they need to exercise
boundary or precondition behavior.
"""
from __future__ import annotations
import uuid
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Helpers for unique inputs
# ---------------------------------------------------------------------------
def unique_event_name(prefix: str = "Event") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def unique_athlete_external_id() -> str:
    return f"athlete-{uuid.uuid4().hex[:10]}"


def unique_referee_full_name(prefix: str = "Ref") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:6]}"


# ---------------------------------------------------------------------------
# Event payload (PRD §3.1)
# ---------------------------------------------------------------------------
def create_event_payload(
    *,
    name: Optional[str] = None,
    event_type: str = "ROUND_ROBIN",
    country_code: str = "ES",
    regulations_text: str = "Standard regulations.",
    registration_opens_at: str = "2030-01-01T00:00:00.000Z",
    registration_closes_at: str = "2030-01-15T00:00:00.000Z",
    starts_at: str = "2030-02-01T00:00:00.000Z",
    entry_fee_cents: int = 1000,
    settlement_currency: str = "USD",
    capacity_min: int = 2,
    capacity_max: int = 16,
    prize_pool_cents: int = 100_000,
    tax_withholding_pct: float = 0.0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name or unique_event_name(),
        "event_type": event_type,
        "country_code": country_code,
        "regulations_text": regulations_text,
        "registration_opens_at": registration_opens_at,
        "registration_closes_at": registration_closes_at,
        "starts_at": starts_at,
        "entry_fee_cents": entry_fee_cents,
        "settlement_currency": settlement_currency,
        "capacity_min": capacity_min,
        "capacity_max": capacity_max,
        "prize_pool_cents": prize_pool_cents,
        "tax_withholding_pct": tax_withholding_pct,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Participant payload (PRD §3.1)
# ---------------------------------------------------------------------------
def register_participant_payload(
    *,
    athlete_external_id: Optional[str] = None,
    display_name: Optional[str] = None,
    team_code: Optional[str] = None,
    country_code: str = "FR",
    world_ranking: Optional[int] = None,
    region: str = "UEFA",
    entry_fee_paid_cents: int = 1000,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "athlete_external_id": athlete_external_id or unique_athlete_external_id(),
        "display_name": display_name or f"Athlete-{uuid.uuid4().hex[:5]}",
        "team_code": team_code,
        "country_code": country_code,
        "world_ranking": world_ranking,
        "region": region,
        "entry_fee_paid_cents": entry_fee_paid_cents,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Referee payload (PRD §3.3)
# ---------------------------------------------------------------------------
def create_referee_payload(
    *,
    full_name: Optional[str] = None,
    country_code: str = "DE",
    team_affiliation: Optional[str] = None,
    qualifications: Optional[List[str]] = None,
    grade: str = "A",
    is_active: bool = True,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": full_name or unique_referee_full_name(),
        "country_code": country_code,
        "team_affiliation": team_affiliation,
        "qualifications": qualifications or ["SINGLE_ELIM", "ROUND_ROBIN", "SETS_MATCH"],
        "grade": grade,
        "is_active": is_active,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Referee assignment payload (PRD §3.3)
# ---------------------------------------------------------------------------
def create_referee_assignment_payload(
    *,
    referee_id: str,
    role: str = "HEAD",
    replaces_assignment_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "referee_id": referee_id,
        "role": role,
    }
    if replaces_assignment_id is not None:
        payload["replaces_assignment_id"] = replaces_assignment_id
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Result entry payload (PRD §3.4)
# ---------------------------------------------------------------------------
def submit_result_payload(
    *,
    submitted_by_assignment_id: str,
    home_score: int = 1,
    away_score: int = 0,
    home_sets_won: Optional[int] = None,
    away_sets_won: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "submitted_by_assignment_id": submitted_by_assignment_id,
        "home_score": home_score,
        "away_score": away_score,
    }
    if home_sets_won is not None:
        payload["home_sets_won"] = home_sets_won
    if away_sets_won is not None:
        payload["away_sets_won"] = away_sets_won
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Dispute payload (PRD §3.4)
# ---------------------------------------------------------------------------
def file_dispute_payload(
    *,
    filed_by_participant_id: str,
    reason_text: str = "Score appears miscounted.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "filed_by_participant_id": filed_by_participant_id,
        "reason_text": reason_text,
    }
    payload.update(overrides)
    return payload


def resolve_dispute_payload(
    *,
    uphold: bool,
    corrected_home_score: Optional[int] = None,
    corrected_away_score: Optional[int] = None,
    corrected_home_sets_won: Optional[int] = None,
    corrected_away_sets_won: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"uphold": uphold}
    if corrected_home_score is not None:
        payload["corrected_home_score"] = corrected_home_score
    if corrected_away_score is not None:
        payload["corrected_away_score"] = corrected_away_score
    if corrected_home_sets_won is not None:
        payload["corrected_home_sets_won"] = corrected_home_sets_won
    if corrected_away_sets_won is not None:
        payload["corrected_away_sets_won"] = corrected_away_sets_won
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Doping sample payloads (PRD §3.7)
# ---------------------------------------------------------------------------
def open_sample_payload(
    *,
    participant_id: str,
    collected_at: str = "2030-02-02T10:00:00.000Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "participant_id": participant_id,
        "collected_at": collected_at,
    }
    payload.update(overrides)
    return payload


def custody_payload(
    *,
    action: str,
    at: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action, "at": at}
    payload.update(overrides)
    return payload


def lab_result_payload(
    *,
    positive: bool,
    result_text: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"positive": positive}
    if result_text is not None:
        payload["result_text"] = result_text
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Appeal payloads (PRD §3.8)
# ---------------------------------------------------------------------------
def file_appeal_payload(
    *,
    sanction_id: str,
    ground_text: str = "Procedural error during sample handling.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "sanction_id": sanction_id,
        "ground_text": ground_text,
    }
    payload.update(overrides)
    return payload


def decide_appeal_payload(
    *,
    uphold: bool,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"uphold": uphold}
    payload.update(overrides)
    return payload


__all__ = [
    "unique_event_name",
    "unique_athlete_external_id",
    "unique_referee_full_name",
    "create_event_payload",
    "register_participant_payload",
    "create_referee_payload",
    "create_referee_assignment_payload",
    "submit_result_payload",
    "file_dispute_payload",
    "resolve_dispute_payload",
    "open_sample_payload",
    "custody_payload",
    "lab_result_payload",
    "file_appeal_payload",
    "decide_appeal_payload",
]
