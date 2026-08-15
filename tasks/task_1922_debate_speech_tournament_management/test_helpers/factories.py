"""Payload factories — one per creatable resource, input fields only (PRD §3)."""
from .constants import (
    REG_LOCKS_AT,
    REG_OPENS_AT,
    ROUND1_END,
    ROUND1_START,
)

DEFAULTS = {
    "TOURNAMENT_NAME": "Districts",
    "SCHOOL_NAME": "Alpha",
    "COMPETITOR_NAME": "Competitor One",
    "JUDGE_NAME": "Judge One",
    "ROOM_NAME": "Room 1",
    "HIRED_JUDGE_NAME": "Hired Judge",
}


def create_tournament_payload(name=None, registration_opens_at=REG_OPENS_AT,
                              registration_locks_at=REG_LOCKS_AT, **optional):
    """Required: name + the two window instants. Optional fields only when given."""
    payload = {
        "name": name or DEFAULTS["TOURNAMENT_NAME"],
        "registration_opens_at": registration_opens_at,
        "registration_locks_at": registration_locks_at,
    }
    for key in ("prelim_round_count", "entry_fee_cents", "tournament_staff_count",
                "late_fee_starts_at", "late_fee_surcharge_pct"):
        if optional.get(key) is not None:
            payload[key] = optional[key]
    return payload


def create_division_payload(tournament_id, event_type="DEBATE", event_code="CX",
                            division="VARSITY", per_school_entry_cap=None,
                            global_entry_cap=None):
    payload = {
        "tournament_id": tournament_id,
        "event_type": event_type,
        "event_code": event_code,
        "division": division,
    }
    if per_school_entry_cap is not None:
        payload["per_school_entry_cap"] = per_school_entry_cap
    if global_entry_cap is not None:
        payload["global_entry_cap"] = global_entry_cap
    return payload


def create_school_payload(tournament_id, name=None, credit_limit_cents=None):
    payload = {
        "tournament_id": tournament_id,
        "name": name or DEFAULTS["SCHOOL_NAME"],
    }
    if credit_limit_cents is not None:
        payload["credit_limit_cents"] = credit_limit_cents
    return payload


def create_entry_payload(school_id, division_id, competitor_name=None):
    return {
        "school_id": school_id,
        "division_id": division_id,
        "competitor_name": competitor_name or DEFAULTS["COMPETITOR_NAME"],
    }


def create_judge_payload(tournament_id, school_id, name=None):
    return {
        "tournament_id": tournament_id,
        "school_id": school_id,
        "name": name or DEFAULTS["JUDGE_NAME"],
    }


def create_judge_conflict_payload(judge_id, school_id, reason=None):
    payload = {"judge_id": judge_id, "school_id": school_id}
    if reason is not None:
        payload["reason"] = reason
    return payload


def create_room_payload(tournament_id, name=None, capacity=None):
    payload = {
        "tournament_id": tournament_id,
        "name": name or DEFAULTS["ROOM_NAME"],
    }
    if capacity is not None:
        payload["capacity"] = capacity
    return payload


def create_round_payload(division_id, round_number=1, kind="PRELIM",
                         starts_at=ROUND1_START, ends_at=ROUND1_END):
    return {
        "division_id": division_id,
        "round_number": round_number,
        "kind": kind,
        "starts_at": starts_at,
        "ends_at": ends_at,
    }


def create_debate_ballot_payload(pairing_id, winner_entry_id, speaker_points,
                                 allow_low_point_win=None):
    payload = {
        "pairing_id": pairing_id,
        "winner_entry_id": winner_entry_id,
        "speaker_points": speaker_points,
    }
    if allow_low_point_win is not None:
        payload["allow_low_point_win"] = allow_low_point_win
    return payload


def create_speech_ballot_payload(pairing_id, ranks):
    return {"pairing_id": pairing_id, "ranks": ranks}


def create_contract_payload(school_id, rounds_requested, expected_school_version):
    return {
        "school_id": school_id,
        "rounds_requested": rounds_requested,
        "expected_school_version": expected_school_version,
    }


def create_order_payload(tournament_id, kind="CATERING"):
    return {"tournament_id": tournament_id, "kind": kind}
