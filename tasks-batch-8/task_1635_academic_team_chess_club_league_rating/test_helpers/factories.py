"""Payload factories — one per creatable entity, input fields only (PRD §3)."""
from .constants import TEST_DEFAULTS


def create_season_payload(**overrides) -> dict:
    defaults = {
        "name": "Season S",
        "start_date": TEST_DEFAULTS["SEASON_START"],
        "end_date": TEST_DEFAULTS["SEASON_END"],
        "dues_deadline": TEST_DEFAULTS["DUES_DEADLINE"],
        "regular_due_cents": TEST_DEFAULTS["REGULAR_DUE_CENTS"],
        "late_due_cents": TEST_DEFAULTS["LATE_DUE_CENTS"],
        "travel_base_cents": TEST_DEFAULTS["TRAVEL_BASE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_club_payload(season_id, **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "name": "Club",
        "school_name": "School HS",
        "region_code": "NE",
        "travel_tier": 1,
    }
    defaults.update(overrides)
    return defaults


def create_coach_payload(club_id, **overrides) -> dict:
    defaults = {
        "club_id": club_id,
        "full_name": "Coach",
        "email": "coach@example.com",
        "certification_level": "CLUB",
    }
    defaults.update(overrides)
    return defaults


def create_player_payload(club_id, **overrides) -> dict:
    defaults = {
        "club_id": club_id,
        "full_name": "Player",
        "grade_level": 9,
    }
    defaults.update(overrides)
    return defaults


def create_membership_payload(player_id, season_id) -> dict:
    return {"player_id": player_id, "season_id": season_id}


def create_meet_payload(season_id, host_club_id, away_club_id, **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "host_club_id": host_club_id,
        "away_club_id": away_club_id,
        "scheduled_date": TEST_DEFAULTS["MEET_DATE"],
        "rounds_count": 1,
        "boards_count": 1,
    }
    defaults.update(overrides)
    return defaults


def create_pairing_payload(round_number, board_number, white_player_id, black_player_id,
                           expected_meet_version) -> dict:
    return {
        "round_number": round_number,
        "board_number": board_number,
        "white_player_id": white_player_id,
        "black_player_id": black_player_id,
        "expected_meet_version": expected_meet_version,
    }


def create_tournament_payload(season_id, **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "name": "Tournament",
        "start_date": TEST_DEFAULTS["TOURNAMENT_START"],
        "end_date": TEST_DEFAULTS["TOURNAMENT_END"],
        "entry_fee_cents": 0,
        "capacity": 64,
    }
    defaults.update(overrides)
    return defaults


def create_section_payload(**overrides) -> dict:
    defaults = {
        "name": "Open",
        "min_rating": 0,
        "max_rating": 2900,
        "allow_provisional": True,
        "max_entries": 10,
    }
    defaults.update(overrides)
    return defaults


def create_ledger_adjustment_payload(amount_cents, expected_club_version, memo="adjustment") -> dict:
    return {
        "entry_type": "ADJUSTMENT",
        "amount_cents": amount_cents,
        "memo": memo,
        "expected_club_version": expected_club_version,
    }


def create_proctor_assignment_payload(coach_id, event_type, **overrides) -> dict:
    defaults = {"coach_id": coach_id, "event_type": event_type}
    defaults.update(overrides)
    return defaults


def create_dispute_payload(reason="result contested by club") -> dict:
    return {"reason": reason}
