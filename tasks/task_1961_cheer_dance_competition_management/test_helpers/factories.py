"""Payload factories — one per entity, input fields only.

System- and computed-sourced fields are never placed in request payloads by
these factories (the PRD's silent-ignore convention means they would be
dropped anyway).
"""
from .constants import ATHLETE_DOB, DIVISION_DEFAULTS, EVENT_DEFAULTS


def create_event_payload(**overrides) -> dict:
    defaults = dict(EVENT_DEFAULTS)
    defaults.update(overrides)
    return defaults


def create_division_payload(event_id, judge_ids, **overrides) -> dict:
    defaults = dict(DIVISION_DEFAULTS)
    defaults["event_id"] = event_id
    defaults["judge_ids"] = list(judge_ids)
    defaults.update(overrides)
    return defaults


def create_team_payload(event_id, division_id, coach_user_id, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "division_id": division_id,
        "name": "T1",
        "organization": "Gym1",
        "category": "CHEER",
        "level": 3,
        "coach_user_id": coach_user_id,
    }
    defaults.update(overrides)
    return defaults


def create_athlete_payload(**overrides) -> dict:
    defaults = {"full_name": "Ann", "date_of_birth": ATHLETE_DOB}
    defaults.update(overrides)
    return defaults


def create_roster_entry_payload(team_id, athlete_id, bib_number=1, **overrides) -> dict:
    defaults = {"team_id": team_id, "athlete_id": athlete_id, "bib_number": bib_number}
    defaults.update(overrides)
    return defaults


def create_judge_payload(**overrides) -> dict:
    defaults = {"full_name": "Judge", "certified_levels": [3]}
    defaults.update(overrides)
    return defaults


def mark_performed_payload(actual_duration_seconds=150, boundary_violations=0,
                           **overrides) -> dict:
    defaults = {
        "actual_duration_seconds": actual_duration_seconds,
        "boundary_violations": boundary_violations,
    }
    defaults.update(overrides)
    return defaults


def create_score_sheet_payload(building_difficulty=8.0, building_execution=8.0,
                               tumbling_difficulty=8.0, overall_impression=8.0,
                               **overrides) -> dict:
    defaults = {
        "building_difficulty": building_difficulty,
        "building_execution": building_execution,
        "tumbling_difficulty": tumbling_difficulty,
        "overall_impression": overall_impression,
    }
    defaults.update(overrides)
    return defaults


def create_deduction_payload(quantity=1, skill_tier=4, **overrides) -> dict:
    defaults = {"type": "SAFETY", "quantity": quantity, "skill_tier": skill_tier}
    defaults.update(overrides)
    return defaults


def create_appeal_payload(note="dispute", video_ref="vid-1", **overrides) -> dict:
    defaults = {"note": note, "video_ref": video_ref}
    defaults.update(overrides)
    return defaults


def create_music_submission_payload(track_count=2, license_provider="ACM",
                                    license_reference="LIC-1", **overrides) -> dict:
    defaults = {
        "track_count": track_count,
        "license_provider": license_provider,
        "license_reference": license_reference,
    }
    defaults.update(overrides)
    return defaults


def create_session_payload(event_id, capacity=100, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "name": "Sat AM",
        "starts_at": "2026-09-05T08:00:00Z",
        "ends_at": "2026-09-05T12:00:00Z",
        "capacity": capacity,
    }
    defaults.update(overrides)
    return defaults


def create_ticket_order_payload(session_id, quantity=2, **overrides) -> dict:
    defaults = {"session_id": session_id, "quantity": quantity}
    defaults.update(overrides)
    return defaults


def create_warm_up_assignment_payload(event_id, team_id, mat="M1",
                                      starts_at="2026-09-05T09:20:00Z",
                                      ends_at="2026-09-05T09:35:00Z",
                                      **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "team_id": team_id,
        "mat": mat,
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    defaults.update(overrides)
    return defaults
