"""Request-payload builders.

Each builder produces only client-supplied fields; nothing computed, derived or
system-minted appears in a payload by default. Overrides are merged last so a
test can vary exactly one field.
"""

import itertools
from typing import Any, Dict, Optional

from . import constants as K

_member_counter = itertools.count(9000)
_title_counter = itertools.count(1)


def next_guild_member_id() -> str:
    """A guild member id that has not been used by any earlier call."""
    return f"GM-{next(_member_counter)}"


def build_guild_agreement(**overrides: Any) -> Dict[str, Any]:
    """The canonical rate card, with every optional field supplied."""
    payload = dict(K.BASE_AGREEMENT)
    payload.update(overrides)
    return payload


def build_minimal_guild_agreement(**overrides: Any) -> Dict[str, Any]:
    """The rate card with every optional field omitted."""
    payload = {k: K.BASE_AGREEMENT[k] for k in K.REQUIRED_ONLY_AGREEMENT_KEYS}
    payload.update(overrides)
    return payload


def build_writer(
    agreement_id: str,
    legal_name: str = "Wanda Cole",
    guild_member_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "legal_name": legal_name,
        "guild_member_id": guild_member_id or next_guild_member_id(),
        "agreement_id": agreement_id,
        "career_episodic_credits": 3,
        "diversity_program_participant": False,
        "is_showrunner_eligible": False,
    }
    payload.update(overrides)
    return payload


def build_minimal_writer(
    agreement_id: str,
    legal_name: str = "Ivy Nakamura",
    guild_member_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Only the required writer fields, so the defaults have to be applied."""
    payload: Dict[str, Any] = {
        "legal_name": legal_name,
        "guild_member_id": guild_member_id or next_guild_member_id(),
        "agreement_id": agreement_id,
    }
    payload.update(overrides)
    return payload


def build_availability_window(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "start_date": K.WINDOW_START_DATE,
        "end_date": K.WINDOW_END_DATE,
        "commitment_type": "EXCLUSIVE",
    }
    payload.update(overrides)
    return payload


def build_season(
    guild_agreement_id: str,
    showrunner_writer_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "guild_agreement_id": guild_agreement_id,
        "showrunner_writer_id": showrunner_writer_id,
        "title": f"Nightfall S{next(_title_counter)}",
        "episode_order": 8,
        "length_format": "ONE_HOUR",
        "production_start_date": K.SEASON_PRODUCTION_START,
        "staffing_window_start": K.STAFFING_WINDOW_START,
        "staffing_window_end": K.STAFFING_WINDOW_END,
        "ready_script_target": 1,
        "guarantee_application_mode": "FORWARD_COMMIT",
        "staffing_budget_weekly_cents": 5000000,
        "script_fee_budget_cents": 60000000,
    }
    payload.update(overrides)
    return payload


def build_minimal_season(
    guild_agreement_id: str,
    showrunner_writer_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """Season payload with the one optional field omitted."""
    payload = build_season(guild_agreement_id, showrunner_writer_id, **overrides)
    payload.pop("guarantee_application_mode", None)
    return payload


def build_room(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": "Main Room",
        "format": "IN_PERSON",
        "seat_capacity": 3,
        "duration_weeks_committed": 26,
        "start_date": K.ROOM_START_DATE,
        "end_date": K.ROOM_END_DATE,
        "diversity_seats_required": 0,
    }
    payload.update(overrides)
    return payload


def build_minimal_room(**overrides: Any) -> Dict[str, Any]:
    """Room payload with the one optional field omitted."""
    payload = build_room(**overrides)
    payload.pop("diversity_seats_required", None)
    return payload


def build_seat_offer(
    writer_id: str,
    expected_room_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "writer_id": writer_id,
        "level_at_hire": "STORY_EDITOR",
        "offered_weekly_compensation_cents": 600000,
        "exclusivity": "EXCLUSIVE",
        "start_date": K.ROOM_START_DATE,
        "end_date": K.ROOM_END_DATE,
        "episodic_guarantee_count": 1,
        "diversity_program_funded": False,
        "expected_room_version": expected_room_version,
    }
    payload.update(overrides)
    return payload


def build_minimal_seat_offer(
    writer_id: str,
    expected_room_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """Seat payload with both optional fields omitted."""
    payload = build_seat_offer(writer_id, expected_room_version, **overrides)
    payload.pop("episodic_guarantee_count", None)
    payload.pop("diversity_program_funded", None)
    return payload


def build_episode(episode_number: int = 1, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "episode_number": episode_number,
        "length_format": "ONE_HOUR",
        "production_unit": "UNIT_A",
        "production_start_date": K.SEASON_PRODUCTION_START,
        "shoot_days": 8,
    }
    payload.update(overrides)
    return payload


def build_minimal_episode(episode_number: int = 1, **overrides: Any) -> Dict[str, Any]:
    """Episode payload with the one optional field omitted."""
    payload = build_episode(episode_number, **overrides)
    payload.pop("shoot_days", None)
    return payload


def build_script_assignment(
    writer_id: str,
    expected_episode_version: int,
    assignment_type: str = "TELEPLAY",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "writer_id": writer_id,
        "assignment_type": assignment_type,
        "expected_episode_version": expected_episode_version,
    }
    payload.update(overrides)
    return payload


def build_reschedule(
    expected_season_version: int,
    new_production_start_date: str = K.RESCHEDULED_PRODUCTION_START,
) -> Dict[str, Any]:
    return {
        "new_production_start_date": new_production_start_date,
        "expected_season_version": expected_season_version,
    }


def build_reconfigure(
    expected_room_version: int,
    room_format: str = "REMOTE",
    duration_weeks_committed: int = 26,
) -> Dict[str, Any]:
    return {
        "format": room_format,
        "duration_weeks_committed": duration_weeks_committed,
        "expected_room_version": expected_room_version,
    }


def build_clearance_review(reviewed_draft_milestone_id: str) -> Dict[str, Any]:
    return {"reviewed_draft_milestone_id": reviewed_draft_milestone_id}


def build_clearance_item(
    item_type: str = "NAME",
    descriptor: str = "Character surname Kowalczyk",
    scene_reference: str = "Act 1 / Scene 1",
) -> Dict[str, Any]:
    return {
        "item_type": item_type,
        "descriptor": descriptor,
        "scene_reference": scene_reference,
    }


def build_item_decision(
    decision: str = "CLEARED", conditional_note: Optional[str] = None
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if conditional_note is not None:
        payload["conditional_note"] = conditional_note
    return payload


def build_waiver(waiver_memo: str = "Production legal accepts the residual risk.") -> Dict[str, Any]:
    return {"waiver_memo": waiver_memo}


def build_credit_submission(
    writer_id: str,
    claim_basis: str = "WRITTEN_BY",
    claimed_contribution_pct: int = 60,
) -> Dict[str, Any]:
    return {
        "writer_id": writer_id,
        "claim_basis": claim_basis,
        "claimed_contribution_pct": claimed_contribution_pct,
    }


def build_arbitration(*arbiter_writer_ids: str) -> Dict[str, Any]:
    return {"arbiter_writer_ids": list(arbiter_writer_ids)}


def build_ballot(vote_shares: Dict[str, int]) -> Dict[str, Any]:
    return {"vote_shares": dict(vote_shares)}


def build_notes(notes: str = "Tighten the second act and cut the cold open.") -> Dict[str, Any]:
    return {"notes": notes}


def build_void(reason: str = "Writer left the production.") -> Dict[str, Any]:
    return {"reason": reason}
