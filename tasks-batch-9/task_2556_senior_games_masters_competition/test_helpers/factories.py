"""Payload factories — one per resource, carrying only client-supplied fields."""
import itertools

from .constants import (
    EDITION_START_DATE,
    EDITION_END_DATE,
    EDITION_AGE_REFERENCE_DATE,
    EDITION_REGISTRATION_DEADLINE_UTC,
    DOB_AGE_60,
    BAND_60_64,
)

_counter = itertools.count(1)


def unique_suffix() -> int:
    """Monotonic counter for building unique sport codes and e-mail addresses."""
    return next(_counter)


def unique_sport_code(prefix: str = "SPT") -> str:
    """A two-to-eight uppercase-letter sport code that cannot collide."""
    n = unique_suffix()
    letters = ""
    while n > 0:
        letters = chr(ord("A") + (n - 1) % 26) + letters
        n = (n - 1) // 26
    return (prefix + letters)[:8]


def unique_email(local: str = "athlete") -> str:
    return f"{local}.{unique_suffix()}@example.com"


def games_edition_payload(**overrides) -> dict:
    payload = {
        "name": "Prairie Senior Games 2026",
        "host_city": "Springfield",
        "host_state_code": "IL",
        "competition_start_date": EDITION_START_DATE,
        "competition_end_date": EDITION_END_DATE,
        "age_reference_date": EDITION_AGE_REFERENCE_DATE,
        "registration_deadline_utc": EDITION_REGISTRATION_DEADLINE_UTC,
    }
    payload.update(overrides)
    return payload


def sport_payload(**overrides) -> dict:
    payload = {
        "sport_code": unique_sport_code("TRK"),
        "name": "Track and Field",
        "contact_class": "LOW",
        "mark_direction": "LOWER_IS_BETTER",
        "required_certification_level": 2,
        "min_age": 50,
    }
    payload.update(overrides)
    return payload


def sport_event_payload(sport_id: str, games_edition_id: str, **overrides) -> dict:
    payload = {
        "sport_id": sport_id,
        "games_edition_id": games_edition_id,
        "event_code": "T100M",
        "age_group_code": BAND_60_64,
        "gender_division": "MEN",
        "entry_fee_cents": 6000,
        "capacity": 8,
        "min_entries_to_stage": 1,
    }
    payload.update(overrides)
    return payload


def venue_payload(games_edition_id: str, **overrides) -> dict:
    payload = {
        "games_edition_id": games_edition_id,
        "name": "Lincoln Track Complex",
        "competition_area_count": 2,
        "spectator_capacity": 500,
        "emergency_protocol_code": "EP_ADVANCED",
        "has_onsite_medical_bay": True,
    }
    payload.update(overrides)
    return payload


def session_slot_payload(venue_id: str, sport_event_id: str, **overrides) -> dict:
    payload = {
        "venue_id": venue_id,
        "sport_event_id": sport_event_id,
        "start_utc": "2026-09-12T09:00:00Z",
        "end_utc": "2026-09-12T10:00:00Z",
        "teardown_buffer_minutes": 15,
        "required_official_count": 1,
    }
    payload.update(overrides)
    return payload


def athlete_payload(games_edition_id: str, **overrides) -> dict:
    payload = {
        "games_edition_id": games_edition_id,
        "full_name": "Ada Frost",
        "email": unique_email("ada.frost"),
        "date_of_birth": DOB_AGE_60,
        "residency_state_code": "IL",
    }
    payload.update(overrides)
    return payload


def qualifying_result_payload(athlete_id: str, sport_id: str, **overrides) -> dict:
    payload = {
        "athlete_id": athlete_id,
        "sport_id": sport_id,
        "event_code": "T100M",
        "mark_value": 14.8,
        "meet_date": "2026-05-16",
        "meet_level": "STATE",
        "sanctioned": True,
    }
    payload.update(overrides)
    return payload


def sport_entry_payload(athlete_id: str, sport_event_id: str, **overrides) -> dict:
    payload = {
        "athlete_id": athlete_id,
        "sport_event_id": sport_event_id,
        "qualification_source": "ORGANIZER_INVITE",
    }
    payload.update(overrides)
    return payload


def medical_screening_payload(athlete_id: str, screened_by_user_id: str, **overrides) -> dict:
    payload = {
        "athlete_id": athlete_id,
        "screened_by_user_id": screened_by_user_id,
        "systolic_bp": 128,
        "resting_hr": 70,
        "prior_cardiac_event": False,
    }
    payload.update(overrides)
    return payload


def personnel_payload(games_edition_id: str, **overrides) -> dict:
    payload = {
        "games_edition_id": games_edition_id,
        "full_name": "Owen Reyes",
        "personnel_type": "OFFICIAL",
        "certification_level": 3,
        "certified_sport_codes": [],
    }
    payload.update(overrides)
    return payload


def personnel_assignment_payload(personnel_id: str, session_slot_id: str, **overrides) -> dict:
    payload = {
        "personnel_id": personnel_id,
        "session_slot_id": session_slot_id,
        "role_at_event": "CHIEF_JUDGE",
    }
    payload.update(overrides)
    return payload


def competition_result_payload(
    sport_entry_id: str, session_slot_id: str, submitted_by_personnel_id: str, **overrides
) -> dict:
    payload = {
        "sport_entry_id": sport_entry_id,
        "session_slot_id": session_slot_id,
        "submitted_by_personnel_id": submitted_by_personnel_id,
        "mark_value": 15.2,
        "placement": 1,
    }
    payload.update(overrides)
    return payload


def age_group_record_payload(
    sport_event_id: str,
    competition_result_id: str,
    claimed_by_user_id: str,
    expected_sport_event_version: int,
    **overrides,
) -> dict:
    payload = {
        "sport_event_id": sport_event_id,
        "competition_result_id": competition_result_id,
        "claimed_by_user_id": claimed_by_user_id,
        "expected_sport_event_version": expected_sport_event_version,
    }
    payload.update(overrides)
    return payload


def accommodation_block_payload(games_edition_id: str, **overrides) -> dict:
    payload = {
        "games_edition_id": games_edition_id,
        "name": "Maple Hall",
        "bed_capacity": 4,
        "nightly_rate_cents": 12000,
        "accessible_units": 1,
    }
    payload.update(overrides)
    return payload


def village_stay_payload(
    athlete_id: str, accommodation_block_id: str, expected_block_version: int, **overrides
) -> dict:
    payload = {
        "athlete_id": athlete_id,
        "accommodation_block_id": accommodation_block_id,
        "check_in_date": "2026-09-10",
        "check_out_date": "2026-09-15",
        "expected_block_version": expected_block_version,
    }
    payload.update(overrides)
    return payload


def sponsorship_commitment_payload(games_edition_id: str, **overrides) -> dict:
    payload = {
        "games_edition_id": games_edition_id,
        "sponsor_name": "Cardinal Mutual",
        "sponsor_kind": "CORPORATE",
        "tier": "SILVER",
        "pledged_cents": 250100,
    }
    payload.update(overrides)
    return payload
