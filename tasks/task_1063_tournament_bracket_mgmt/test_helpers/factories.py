"""Payload factories — one per entity, input fields only.

Factories emit only required fields by default; optional fields are added via
**overrides so that "omit an optional field" tests remain expressible.
"""
from uuid import uuid4

from .constants import DEFAULT_CHECK_IN_DEADLINE


def unique_email() -> str:
    return f"player_{uuid4().hex[:12]}@example.com"


def create_venue_payload(name="Arena", address="1 Main St", open_minute=0, close_minute=1440, **overrides) -> dict:
    payload = {
        "name": name,
        "address": address,
        "open_minute": open_minute,
        "close_minute": close_minute,
    }
    payload.update(overrides)
    return payload


def create_station_payload(label="Table 1", **overrides) -> dict:
    payload = {"label": label}
    payload.update(overrides)
    return payload


def create_stream_channel_payload(name="Main Channel", platform="TWITCH", **overrides) -> dict:
    payload = {"name": name, "platform": platform}
    payload.update(overrides)
    return payload


def create_player_payload(display_name="Player", email=None, **overrides) -> dict:
    payload = {"display_name": display_name, "email": email or unique_email()}
    payload.update(overrides)
    return payload


def create_tournament_payload(
    venue_id,
    name="Cup",
    format="SINGLE_ELIM",
    max_participants=8,
    prize_pool_cents=0,
    check_in_deadline=DEFAULT_CHECK_IN_DEADLINE,
    **overrides,
) -> dict:
    payload = {
        "name": name,
        "venue_id": venue_id,
        "format": format,
        "max_participants": max_participants,
        "prize_pool_cents": prize_pool_cents,
        "check_in_deadline": check_in_deadline,
    }
    payload.update(overrides)
    return payload


def create_registration_payload(tournament_id, player_id, **overrides) -> dict:
    payload = {"tournament_id": tournament_id, "player_id": player_id}
    payload.update(overrides)
    return payload


def schedule_match_payload(station_id, scheduled_start, scheduled_end) -> dict:
    return {
        "station_id": station_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }


def report_match_payload(home_score, away_score) -> dict:
    return {"home_score": home_score, "away_score": away_score}


def confirm_match_payload(expected_match_version) -> dict:
    return {"expected_match_version": expected_match_version}


def complete_tournament_payload(expected_tournament_version) -> dict:
    return {"expected_tournament_version": expected_tournament_version}


def create_stream_assignment_payload(match_id, channel_id, start_at, end_at) -> dict:
    return {
        "match_id": match_id,
        "channel_id": channel_id,
        "start_at": start_at,
        "end_at": end_at,
    }


def create_dispute_payload(match_id, raised_by_registration_id, reason="disputed result") -> dict:
    return {
        "match_id": match_id,
        "raised_by_registration_id": raised_by_registration_id,
        "reason": reason,
    }


def resolve_dispute_payload(outcome, expected_match_version, resolution_note=None) -> dict:
    payload = {"outcome": outcome, "expected_match_version": expected_match_version}
    if resolution_note is not None:
        payload["resolution_note"] = resolution_note
    return payload
