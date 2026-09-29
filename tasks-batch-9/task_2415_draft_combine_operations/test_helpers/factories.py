"""Request payload builders.

Each builder returns a complete, valid payload for one endpoint and accepts
keyword overrides. Only client-supplied fields appear; server-computed fields
are never sent.
"""

from typing import Dict, List, Optional

from .constants import (
    COMBINE_WEEK_END_AT,
    COMBINE_WEEK_START_AT,
    DECLARATION_DEADLINE_AT,
    DRAFT_START_AT,
    SEASON_YEAR,
)

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------


def clock_payload(to_iso8601: str) -> Dict:
    return {"to_iso8601": to_iso8601}


# ---------------------------------------------------------------------------
# Draft cycle
# ---------------------------------------------------------------------------


def draft_cycle_payload(**overrides) -> Dict:
    payload = {
        "season_year": SEASON_YEAR,
        "declaration_deadline_at": DECLARATION_DEADLINE_AT,
        "combine_week_start_at": COMBINE_WEEK_START_AT,
        "combine_week_end_at": COMBINE_WEEK_END_AT,
        "draft_start_at": DRAFT_START_AT,
    }
    payload.update(overrides)
    return payload


def phase_payload(target_status: str) -> Dict:
    return {"target_status": target_status}


def lottery_payload(drawn_combination_sequence: List[int]) -> Dict:
    return {"drawn_combination_sequence": drawn_combination_sequence}


def invitation_selection_payload(target_count: int) -> Dict:
    return {"target_count": target_count}


# ---------------------------------------------------------------------------
# Club
# ---------------------------------------------------------------------------


def club_payload(draft_cycle_id: str, club_code: str = "ELM", **overrides) -> Dict:
    payload = {
        "draft_cycle_id": draft_cycle_id,
        "club_code": club_code,
        "market_name": "Elmwood",
        "prior_season_win_pct": 0.500,
        "strength_of_schedule": 0.470,
        "head_to_head_rank": 5,
        "rookie_pool_total_cents": 896721432,
        "lottery_combinations": 75,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Prospect
# ---------------------------------------------------------------------------


def prospect_payload(draft_cycle_id: str, **overrides) -> Dict:
    payload = {
        "draft_cycle_id": draft_cycle_id,
        "full_name": "Avery Lane",
        "position_group": "QB",
        "school_code": "NRT",
        "seasons_played": 4,
        "scouting_grade": 92.50,
        "position_group_scarcity_rank": 1,
    }
    payload.update(overrides)
    return payload


def declaration_payload(action: str = "DECLARE") -> Dict:
    return {"action": action}


def eligibility_determination_payload(action: str = "DECLARE_ELIGIBLE") -> Dict:
    return {"action": action}


def combine_invitation_payload(action: str) -> Dict:
    return {"action": action}


def consent_payload(
    action: str = "GRANT",
    scope: Optional[str] = "FULL",
    consent_expires_at: Optional[str] = "2027-03-15T12:00:00.000Z",
) -> Dict:
    payload: Dict = {"action": action}
    if scope is not None:
        payload["scope"] = scope
    if consent_expires_at is not None:
        payload["consent_expires_at"] = consent_expires_at
    return payload


# ---------------------------------------------------------------------------
# Eligibility waiver
# ---------------------------------------------------------------------------


def eligibility_waiver_payload(
    waiver_type: str = "LATE_DECLARATION", **overrides
) -> Dict:
    payload = {
        "waiver_type": waiver_type,
        "rationale": "Documented late paperwork from the registrar office.",
    }
    payload.update(overrides)
    return payload


def waiver_review_payload(action: str, **overrides) -> Dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Combine resources
# ---------------------------------------------------------------------------


def medical_station_payload(
    station_code: str = "ST-ORTHO-1", exam_type: str = "ORTHO", **overrides
) -> Dict:
    payload = {"station_code": station_code, "exam_type": exam_type}
    payload.update(overrides)
    return payload


def interview_room_payload(room_code: str = "IR-1", **overrides) -> Dict:
    payload = {"room_code": room_code}
    payload.update(overrides)
    return payload


def combine_booking_payload(
    prospect_id: str,
    booking_type: str,
    starts_at: str,
    ends_at: str,
    **overrides,
) -> Dict:
    payload = {
        "prospect_id": prospect_id,
        "booking_type": booking_type,
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    payload.update(overrides)
    return payload


def booking_status_payload(action: str) -> Dict:
    return {"action": action}


# ---------------------------------------------------------------------------
# Medical evaluation and shares
# ---------------------------------------------------------------------------


def medical_evaluation_payload(
    combine_booking_id: str, prospect_id: str, **overrides
) -> Dict:
    payload = {
        "combine_booking_id": combine_booking_id,
        "prospect_id": prospect_id,
        "findings_code": "ORTHO-CLEAR-01",
        "medical_grade": "PASS",
    }
    payload.update(overrides)
    return payload


def medical_record_share_payload(
    medical_evaluation_id: str,
    club_id: str,
    expected_medical_evaluation_version: int,
    scope: str = "FULL",
) -> Dict:
    return {
        "medical_evaluation_id": medical_evaluation_id,
        "club_id": club_id,
        "scope": scope,
        "expected_medical_evaluation_version": expected_medical_evaluation_version,
    }


def share_decision_payload(action: str, **overrides) -> Dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Selections and the clock
# ---------------------------------------------------------------------------


def selection_payload(prospect_id: str, **overrides) -> Dict:
    payload = {"prospect_id": prospect_id}
    payload.update(overrides)
    return payload


def clock_action_payload(action: str) -> Dict:
    return {"action": action}


# ---------------------------------------------------------------------------
# Pick trades
# ---------------------------------------------------------------------------


def pick_trade_payload(
    draft_cycle_id: str,
    proposing_club_id: str,
    receiving_club_id: str,
    offered_pick_ids: List[str],
    requested_pick_ids: List[str],
    **overrides,
) -> Dict:
    payload = {
        "draft_cycle_id": draft_cycle_id,
        "proposing_club_id": proposing_club_id,
        "receiving_club_id": receiving_club_id,
        "offered_pick_ids": offered_pick_ids,
        "requested_pick_ids": requested_pick_ids,
    }
    payload.update(overrides)
    return payload


def trade_counter_payload(
    offered_pick_ids: List[str], requested_pick_ids: List[str]
) -> Dict:
    return {
        "offered_pick_ids": offered_pick_ids,
        "requested_pick_ids": requested_pick_ids,
    }


def trade_termination_payload(action: str, **overrides) -> Dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


def conditional_resolution_payload(condition_satisfied: bool) -> Dict:
    return {"condition_satisfied": condition_satisfied}


# ---------------------------------------------------------------------------
# Compensatory claims
# ---------------------------------------------------------------------------


def compensatory_claim_payload(
    draft_cycle_id: str, club_id: str, **overrides
) -> Dict:
    payload = {
        "draft_cycle_id": draft_cycle_id,
        "club_id": club_id,
        "claim_type": "DEPARTURE",
        "player_name": "Dane Whitlock",
        "departed_apy_cents": 1450000000,
        "snap_pct": 0.72,
        "postseason_honor": "ALL_CONFERENCE",
    }
    payload.update(overrides)
    return payload


def claim_verify_payload(action: str) -> Dict:
    return {"action": action}


# ---------------------------------------------------------------------------
# Player contracts
# ---------------------------------------------------------------------------


def player_contract_payload(
    prospect_id: str,
    club_id: str,
    origin: str,
    expected_prospect_version: int,
    **overrides,
) -> Dict:
    payload = {
        "prospect_id": prospect_id,
        "club_id": club_id,
        "origin": origin,
        "expected_prospect_version": expected_prospect_version,
    }
    payload.update(overrides)
    return payload


def contract_status_payload(action: str) -> Dict:
    return {"action": action}
